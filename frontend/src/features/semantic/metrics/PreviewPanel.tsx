import { useMutation } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { formatSql } from "../../chat/formatSql";
import { previewMetric } from "../api";
import { ColumnSelect } from "../ColumnSelect";
import { selectClass } from "../styles";
import type { PreviewFilter, SemanticModel } from "../types";

const OPERATORS = ["=", "!=", ">", ">=", "<", "<=", "in", "contains"];

const SOURCE_LABELS: Record<string, string> = {
  metric: "Métrica",
  request: "Pedido",
  period: "Período",
  role: "Rol",
};

interface FilterRow {
  field: string;
  op: string;
  value: string;
}

interface Props {
  datasourceId: string;
  dialect: string;
  model: SemanticModel;
  initialMetric: string;
}

function toFilter(row: FilterRow): PreviewFilter {
  if (row.op === "in") {
    return {
      field: row.field,
      op: row.op,
      value: row.value
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
    };
  }
  return { field: row.field, op: row.op, value: row.value };
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "No se pudo generar la vista previa.";
}

/** Panel «Probar»: SQL que armaría el motor, sin IA. Usa el modelo publicado, no el borrador. */
export function PreviewPanel({ datasourceId, dialect, model, initialMetric }: Props) {
  const metrics = model.metrics ?? [];
  const [chosen, setChosen] = useState<string | null>(null);
  const [period, setPeriod] = useState("");
  const [dimensions, setDimensions] = useState<string[]>([]);
  const [filters, setFilters] = useState<FilterRow[]>([]);

  const metricName = chosen ?? initialMetric;
  const metric = metrics.find((m) => m.name === metricName);
  const available = metric?.dimensions ?? [];

  const preview = useMutation({
    mutationFn: () =>
      previewMetric(datasourceId, {
        metric: metricName,
        period: period.trim() || undefined,
        dimensions: dimensions.filter((d) => available.includes(d)),
        filters: filters.filter((f) => f.field).map(toFilter),
      }),
  });
  const result = preview.data;

  return (
    <section aria-label="Probar" className="flex flex-col gap-4 rounded-lg border bg-card p-4">
      <header>
        <h2 className="text-lg font-semibold">Probar</h2>
        <p className="text-sm text-muted-foreground">
          Mira el SQL que generaría el motor, sin gastar tokens. Prueba con el modelo{" "}
          <strong>publicado</strong>: publica tus cambios para verlos aquí.
        </p>
      </header>

      <form
        className="grid gap-4 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (metricName) preview.mutate();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Métrica a probar</span>
          <select
            aria-label="Métrica a probar"
            className={selectClass}
            value={metricName}
            onChange={(event) => {
              setChosen(event.target.value);
              setDimensions([]);
            }}
          >
            <option value="">Elige una métrica…</option>
            {metrics.map((m) => (
              <option key={m.name} value={m.name}>
                {m.label || m.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Período</span>
          <Input
            aria-label="Período a probar"
            placeholder="este mes, mes pasado, 2025…"
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
          />
        </label>

        <fieldset className="md:col-span-2">
          <legend className="text-sm font-medium">Dimensiones</legend>
          {available.length === 0 ? (
            <p className="text-xs text-muted-foreground">La métrica no declara dimensiones.</p>
          ) : (
            <div className="flex flex-wrap gap-3 pt-1">
              {available.map((dimension) => (
                <label key={dimension} className="flex items-center gap-1 text-sm">
                  <input
                    type="checkbox"
                    checked={dimensions.includes(dimension)}
                    onChange={(event) =>
                      setDimensions(
                        event.target.checked
                          ? [...dimensions, dimension]
                          : dimensions.filter((d) => d !== dimension),
                      )
                    }
                  />
                  {dimension}
                </label>
              ))}
            </div>
          )}
        </fieldset>

        <div className="flex flex-col gap-2 md:col-span-2">
          <span className="text-sm font-medium">Filtros</span>
          <ul aria-label="Filtros de la prueba" className="flex flex-col gap-2">
            {filters.map((row, i) => (
              <li key={i} className="grid items-center gap-2 md:grid-cols-[1fr_8rem_1fr_auto]">
                <ColumnSelect
                  label={`Campo del filtro ${i + 1}`}
                  value={row.field}
                  model={model}
                  onChange={(field) =>
                    setFilters(filters.map((f, j) => (j === i ? { ...f, field } : f)))
                  }
                />
                <select
                  aria-label={`Operador del filtro ${i + 1}`}
                  className={selectClass}
                  value={row.op}
                  onChange={(event) =>
                    setFilters(filters.map((f, j) => (j === i ? { ...f, op: event.target.value } : f)))
                  }
                >
                  {OPERATORS.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
                <Input
                  aria-label={`Valor del filtro ${i + 1}`}
                  placeholder={row.op === "in" ? "a, b, c" : "valor"}
                  value={row.value}
                  onChange={(event) =>
                    setFilters(
                      filters.map((f, j) => (j === i ? { ...f, value: event.target.value } : f)),
                    )
                  }
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Quitar filtro ${i + 1}`}
                  onClick={() => setFilters(filters.filter((_, j) => j !== i))}
                >
                  <Trash2 aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
          <div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setFilters([...filters, { field: "", op: "=", value: "" }])}
            >
              <Plus aria-hidden /> Agregar filtro de prueba
            </Button>
          </div>
        </div>

        <div className="md:col-span-2">
          <Button type="submit" disabled={!metricName || preview.isPending}>
            {preview.isPending ? "Generando…" : "Ver SQL"}
          </Button>
        </div>
      </form>

      {preview.isError && (
        <p role="alert" className="rounded-md border border-destructive p-3 text-sm">
          {describeError(preview.error)}
        </p>
      )}

      {result && (
        <div aria-label="Resultado de la prueba" className="flex flex-col gap-3" role="region">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant="secondary">
              {result.summary_table
                ? `Tabla resumida: ${result.summary_table}`
                : "Tablas base"}
            </Badge>
            {result.role && <Badge variant="outline">Rol: {result.role}</Badge>}
            {result.period && <Badge variant="outline">Período: {result.period.label}</Badge>}
            <Badge variant={result.guard.allowed ? "outline" : "destructive"}>
              {result.guard.allowed ? "Guardián: permitido" : "Guardián: rechazado"}
            </Badge>
          </div>
          <p className="text-sm">
            <span className="font-medium">Motivo: </span>
            {result.reason}
          </p>
          <pre className="overflow-x-auto rounded-md border p-3 font-mono text-sm">
            <code>{formatSql(result.sql, dialect)}</code>
          </pre>
          {result.guard.violations.length > 0 && (
            <ul role="alert" className="text-sm text-destructive">
              {result.guard.violations.map((v) => (
                <li key={`${v.code}:${v.message}`}>{v.message}</li>
              ))}
            </ul>
          )}
          {result.filters_applied.length > 0 && (
            <div>
              <p className="text-sm font-medium">Filtros aplicados</p>
              <ul aria-label="Filtros aplicados" className="text-sm text-muted-foreground">
                {result.filters_applied.map((f) => (
                  <li key={`${f.source}:${f.text}`}>
                    <span className="font-medium">{SOURCE_LABELS[f.source] ?? f.source}:</span>{" "}
                    <code>{f.text}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
