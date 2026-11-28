#!/usr/bin/env node
// Genera los modelos de los SDKs desde docs/openapi/v1.json (sin dependencias).
//
//   node sdks/scripts/generate.mjs           escribe los archivos generados
//   node sdks/scripts/generate.mjs --check   falla si están desactualizados (lo usa el CI)
//
// Salidas:
//   sdks/python/chatiapp/_generated.py        modelos Pydantic de components.schemas
//   sdks/typescript/src/generated/types.ts    interfaces de components.schemas
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const specPath = join(root, "docs", "openapi", "v1.json");
const spec = JSON.parse(readFileSync(specPath, "utf8"));
const schemas = spec.components?.schemas ?? {};
const names = Object.keys(schemas).sort();

const refName = (ref) => ref.slice(ref.lastIndexOf("/") + 1);
const isIdent = (s) => /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(s);
const comment = (text) => (text ?? "").replace(/\*\//g, "* /").replace(/\s+/g, " ").trim();

// ---------------------------------------------------------------- TypeScript

function tsType(s) {
  if (s.$ref) return refName(s.$ref);
  if (s.const !== undefined) return JSON.stringify(s.const);
  if (s.enum) return s.enum.map((v) => JSON.stringify(v)).join(" | ");
  const alt = s.anyOf ?? s.oneOf;
  if (alt) return [...new Set(alt.map(tsType))].join(" | ");
  if (Array.isArray(s.type)) return s.type.map((t) => tsType({ ...s, type: t })).join(" | ");
  switch (s.type) {
    case "null":
      return "null";
    case "string":
      return "string";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "array":
      return `Array<${s.items ? tsType(s.items) : "unknown"}>`;
    case "object":
      return tsObject(s);
    default:
      return s.properties ? tsObject(s) : "unknown";
  }
}

function tsObject(s) {
  if (s.properties) return `{ ${tsFields(s).join(" ")} }`;
  if (s.additionalProperties && typeof s.additionalProperties === "object") {
    return `Record<string, ${tsType(s.additionalProperties)}>`;
  }
  return "Record<string, unknown>";
}

function tsFields(s) {
  const required = new Set(s.required ?? []);
  return Object.entries(s.properties).map(([name, prop]) => {
    const key = isIdent(name) ? name : JSON.stringify(name);
    return `${key}${required.has(name) ? "" : "?"}: ${tsType(prop)};`;
  });
}

function generateTs() {
  const out = [
    "/* eslint-disable */",
    "// Generado por sdks/scripts/generate.mjs desde docs/openapi/v1.json. No lo edites.",
    "",
    `export const SPEC_VERSION = ${JSON.stringify(spec.info?.version ?? "")};`,
    "",
  ];
  for (const name of names) {
    const s = schemas[name];
    if (s.description) out.push(`/** ${comment(s.description)} */`);
    if (s.properties && !s.anyOf && !s.enum) {
      out.push(`export interface ${name} {`);
      for (const f of tsFields(s)) out.push(`  ${f}`);
      out.push("}", "");
    } else {
      out.push(`export type ${name} = ${tsType(s)};`, "");
    }
  }
  return out.join("\n");
}

// ---------------------------------------------------------------- Python

const PY_RESERVED = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue",
  "def", "del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import",
  "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while",
  "with", "yield", "copy", "json", "dict", "schema", "construct", "validate",
]);

function pyType(s) {
  if (s.$ref) return refName(s.$ref);
  if (s.const !== undefined) return `Literal[${JSON.stringify(s.const)}]`;
  if (s.enum) return `Literal[${s.enum.map((v) => JSON.stringify(v)).join(", ")}]`;
  const alt = s.anyOf ?? s.oneOf;
  if (alt) return [...new Set(alt.map(pyType))].join(" | ");
  if (Array.isArray(s.type)) {
    return [...new Set(s.type.map((t) => pyType({ ...s, type: t })))].join(" | ");
  }
  switch (s.type) {
    case "null":
      return "None";
    case "string":
      if (s.format === "date-time") return "_dt.datetime";
      if (s.format === "date") return "_dt.date";
      return "str";
    case "integer":
      return "int";
    case "number":
      return "float";
    case "boolean":
      return "bool";
    case "array":
      return `list[${s.items ? pyType(s.items) : "Any"}]`;
    case "object":
      return pyDict(s);
    default:
      return s.properties ? pyDict(s) : "Any";
  }
}

function pyDict(s) {
  if (s.additionalProperties && typeof s.additionalProperties === "object") {
    return `dict[str, ${pyType(s.additionalProperties)}]`;
  }
  return "dict[str, Any]";
}

function pyValue(v) {
  if (v === null) return "None";
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(pyValue).join(", ")}]`;
  const items = Object.entries(v).map(([k, x]) => `${JSON.stringify(k)}: ${pyValue(x)}`);
  return `{${items.join(", ")}}`;
}

const isNullable = (s) =>
  (s.anyOf ?? s.oneOf ?? []).some((a) => a.type === "null") ||
  s.type === "null" ||
  (Array.isArray(s.type) && s.type.includes("null"));

function pyField(name, prop, required) {
  const unsafe = PY_RESERVED.has(name) || name.startsWith("_") || name.startsWith("model_");
  const attr = unsafe ? `${name.replace(/^_+/, "")}_` : name;
  let type = pyType(prop);
  const args = [];
  if (attr !== name) args.push(`alias=${JSON.stringify(name)}`);
  if (!required) {
    if (prop.default !== undefined && prop.default !== null) {
      const d = pyValue(prop.default);
      if (typeof prop.default === "object") args.push(`default_factory=lambda: ${d}`);
      else args.push(`default=${d}`);
    } else {
      if (!isNullable(prop)) type = `${type} | None`;
      args.push("default=None");
    }
  }
  if (args.length === 0) return `    ${attr}: ${type}`;
  if (args.length === 1 && args[0].startsWith("default=")) {
    return `    ${attr}: ${type} = ${args[0].slice("default=".length)}`;
  }
  return `    ${attr}: ${type} = Field(${args.join(", ")})`;
}

function generatePy() {
  // Los alias (`X = A | B`) se evalúan al importar: van después de lo que usan.
  const deps = (s) => {
    const found = new Set();
    JSON.stringify(s, (k, v) => {
      if (k === "$ref") found.add(refName(v));
      return v;
    });
    return [...found];
  };
  const order = [];
  const seen = new Set();
  const visit = (n) => {
    if (seen.has(n)) return;
    seen.add(n);
    for (const d of deps(schemas[n])) if (schemas[d]) visit(d);
    order.push(n);
  };
  names.forEach(visit);

  const out = [
    '"""Modelos generados por sdks/scripts/generate.mjs desde docs/openapi/v1.json. No lo edites."""',
    "",
    "# ruff: noqa",
    "# fmt: off",
    "from __future__ import annotations",
    "",
    "import datetime as _dt",
    "from typing import Any, Literal",
    "",
    "from pydantic import BaseModel, ConfigDict, Field",
    "",
    `SPEC_VERSION = ${JSON.stringify(spec.info?.version ?? "")}`,
    "",
  ];
  const classes = [];
  for (const name of order) {
    const s = schemas[name];
    if (s.properties && !s.anyOf && !s.enum) {
      classes.push(name);
      out.push("", `class ${name}(BaseModel):`);
      const doc = comment(s.description).replace(/\\/g, "\\\\").replace(/"""/g, "'''");
      if (doc) out.push(`    """${doc}"""`, "");
      out.push("    model_config = ConfigDict(populate_by_name=True)", "");
      const required = new Set(s.required ?? []);
      for (const [prop, ps] of Object.entries(s.properties)) {
        out.push(pyField(prop, ps, required.has(prop)));
      }
      out.push("");
    } else {
      out.push(`${name} = ${pyType(s)}`);
    }
  }
  out.push("", "", `for _model in (${classes.map((c) => `${c}, `).join("")}):`);
  out.push("    _model.model_rebuild()", "");
  out.push("__all__ = [", '    "SPEC_VERSION",', ...names.map((n) => `    "${n}",`), "]", "");
  return out.join("\n");
}

// ---------------------------------------------------------------- salida

const targets = [
  [join(root, "sdks", "python", "chatiapp", "_generated.py"), generatePy()],
  [join(root, "sdks", "typescript", "src", "generated", "types.ts"), generateTs()],
];

const check = process.argv.includes("--check");
let stale = false;
for (const [path, content] of targets) {
  const shown = path.slice(root.length + 1);
  if (check) {
    if (!existsSync(path) || readFileSync(path, "utf8") !== content) {
      console.error(`Desactualizado: ${shown}`);
      stale = true;
    }
  } else {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content);
    console.log(`Escrito ${shown}`);
  }
}
if (stale) {
  console.error("Ejecuta `node sdks/scripts/generate.mjs` y commitea el resultado.");
  process.exit(1);
}
