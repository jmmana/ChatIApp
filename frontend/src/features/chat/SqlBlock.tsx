import { Check, ChevronRight, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { SqlData } from "./types";

const DIALECT_LABELS: Record<string, string> = {
  sqlite: "SQLite",
  postgres: "PostgreSQL",
  postgresql: "PostgreSQL",
  mysql: "MySQL",
  mariadb: "MariaDB",
  mssql: "SQL Server",
  sqlserver: "SQL Server",
  tsql: "SQL Server",
};

const KEYWORDS = new Set(
  (
    "select from where group by order having limit offset join left right inner outer full cross " +
    "on as and or not in is null like between case when then else end union all distinct with " +
    "asc desc top over partition exists"
  ).split(" "),
);

const TOKEN =
  /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|(\b[A-Za-z_][A-Za-z0-9_]*\b)/g;

function highlight(sql: string) {
  const nodes: React.ReactNode[] = [];
  let last = 0;
  for (const match of sql.matchAll(TOKEN)) {
    const start = match.index;
    if (start > last) nodes.push(sql.slice(last, start));
    const [text, comment, string, number, word] = match;
    let className: string | null = null;
    if (comment) className = "text-muted-foreground italic";
    else if (string) className = "text-accent-foreground";
    else if (number) className = "text-foreground underline decoration-dotted";
    else if (word && KEYWORDS.has(word.toLowerCase())) className = "font-semibold text-primary";
    nodes.push(
      className ? (
        <span key={start} className={className}>
          {text}
        </span>
      ) : (
        text
      ),
    );
    last = start + text.length;
  }
  if (last < sql.length) nodes.push(sql.slice(last));
  return nodes;
}

interface SqlBlockProps {
  sql: SqlData;
  /** Mientras el turno está en curso el bloque va abierto; al terminar se pliega. */
  streaming?: boolean;
}

export function SqlBlock({ sql, streaming = false }: SqlBlockProps) {
  const [toggled, setToggled] = useState<boolean | null>(null);
  const [copied, setCopied] = useState(false);
  // El formateador pesa bastante: se descarga aparte y mientras tanto se muestra el SQL tal cual.
  const [formattedFor, setFormattedFor] = useState<{ source: string; text: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void import("./formatSql").then(({ formatSql }) => {
      if (!cancelled) {
        setFormattedFor({ source: sql.sql, text: formatSql(sql.sql, sql.dialect) });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [sql.sql, sql.dialect]);
  const formatted = formattedFor?.source === sql.sql ? formattedFor.text : sql.sql;
  const open = toggled ?? streaming;
  const dialect = DIALECT_LABELS[sql.dialect.toLowerCase()] ?? sql.dialect;

  async function copy() {
    try {
      await navigator.clipboard.writeText(formatted);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section aria-label="Consulta SQL" className="rounded-lg border bg-card">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setToggled(!open)}
          className="flex items-center gap-1 text-sm font-medium"
        >
          <ChevronRight className={open ? "size-4 rotate-90" : "size-4"} aria-hidden />
          SQL
        </button>
        <Badge variant="outline">{dialect}</Badge>
        <Badge variant="secondary">{sql.origin === "catalog" ? "Catálogo" : "IA"}</Badge>
        {sql.summary_table && <Badge variant="outline">Tabla resumida: {sql.summary_table}</Badge>}
        {sql.filters_applied.length > 0 && <Badge variant="accent">Filtro de rol</Badge>}
        <Badge variant="outline">Solo lectura</Badge>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => void copy()}>
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? "Copiado" : "Copiar"}
        </Button>
      </div>
      {open && (
        <pre className="overflow-x-auto border-t p-3 font-mono text-sm">
          <code>{highlight(formatted)}</code>
        </pre>
      )}
    </section>
  );
}
