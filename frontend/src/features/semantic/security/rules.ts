import type { SemanticModel } from "../types";

const MARKER = /\{user\.[A-Za-z_]\w*\}/g;

/** Atributos `{user.x}` que usa una condición, sin repetidos. */
export function attributesIn(condition: string): string[] {
  const names = (condition.match(MARKER) ?? []).map((marker) => marker.slice(6, -1));
  return [...new Set(names)];
}

/**
 * Validación local de una condición de rol (marcadores, paréntesis y comillas). El servidor la
 * parsea con sqlglot en el dialecto del modelo al publicar; aquí se atrapa lo evidente al escribir.
 */
export function conditionProblem(condition: string): string | null {
  if (condition.trim() === "") return "La condición no puede estar vacía.";
  const rest = condition.replace(MARKER, "NULL");
  if (/[{}]/.test(rest)) {
    return "Marcador mal formado: usa {user.nombre} con letras, números o guion bajo.";
  }
  let depth = 0;
  let quote: string | null = null;
  for (const char of rest) {
    if (quote) {
      if (char === quote) quote = null;
    } else if (char === "'" || char === '"') {
      quote = char;
    } else if (char === "(") {
      depth += 1;
    } else if (char === ")") {
      depth -= 1;
      if (depth < 0) return "Hay un paréntesis de cierre sin abrir.";
    }
  }
  if (quote) return "Hay una comilla sin cerrar.";
  if (depth > 0) return "Hay un paréntesis sin cerrar.";
  return null;
}

export interface SecurityWarning {
  role: string;
  table: string;
  summary: string;
}

/** Tablas filtradas en un rol cuyas resumidas no tienen filtro (ni están ocultas) para ese rol. */
export function summaryWarnings(model: SemanticModel): SecurityWarning[] {
  const baseOf = new Map((model.metrics ?? []).map((metric) => [metric.name, metric.table]));
  const found: SecurityWarning[] = [];
  for (const role of model.security?.roles ?? []) {
    const covered = new Set([
      ...(role.filters ?? []).map((filter) => filter.table),
      ...(role.hidden_tables ?? []),
    ]);
    const seen = new Set<string>();
    for (const rule of role.filters ?? []) {
      for (const summary of model.summary_tables ?? []) {
        const uses = Object.keys(summary.metrics ?? {}).some((m) => baseOf.get(m) === rule.table);
        const key = `${rule.table}|${summary.table}`;
        if (uses && !covered.has(summary.table) && !seen.has(key)) {
          seen.add(key);
          found.push({ role: role.name, table: rule.table, summary: summary.table });
        }
      }
    }
  }
  return found;
}

/** `nombre = valor` por línea; el valor es JSON (`[1, 2]`, `"norte"`, `5`) o texto sin comillas. */
export function parseAttributes(text: string): {
  attributes: Record<string, unknown>;
  error: string | null;
} {
  const attributes: Record<string, unknown> = {};
  for (const [i, raw] of text.split("\n").entries()) {
    const line = raw.trim();
    if (line === "") continue;
    const at = line.indexOf("=");
    const name = line.slice(0, at).trim();
    if (at < 0 || !/^[A-Za-z_]\w*$/.test(name)) {
      return { attributes, error: `Línea ${i + 1}: usa «nombre = valor».` };
    }
    const value = line.slice(at + 1).trim();
    try {
      attributes[name] = JSON.parse(value);
    } catch {
      attributes[name] = value;
    }
  }
  return { attributes, error: null };
}
