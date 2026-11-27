import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { selectClass } from "../styles";
import type { SemanticModel } from "../types";
import {
  previewMetric,
  validateSql,
  type GuardResult,
  type PreviewResult,
  type ValidateSqlResult,
} from "./api";
import { attributesIn, parseAttributes } from "./rules";

const NO_ROLE = "";

type Mode = "metric" | "sql";

interface Props {
  datasourceId: string;
  model: SemanticModel;
  /** Hay cambios sin publicar: la vista previa usa la última versión publicada. */
  dirty: boolean;
}

function Guard({ guard }: { guard: GuardResult }) {
  return (
    <div className="flex flex-col gap-2">
      <p
        className={guard.allowed ? "text-sm font-medium" : "text-sm font-medium text-destructive"}
      >
        {guard.allowed ? "El guardián permite la consulta." : "El guardián rechaza la consulta."}
      </p>
      {guard.violations.length > 0 && (
        <ul aria-label="Violaciones" className="list-disc pl-5 text-sm text-destructive">
          {guard.violations.map((violation, i) => (
            <li key={`${violation.code}-${i}`}>{violation.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SqlBlock({ sql }: { sql: string | null }) {
  if (!sql) return null;
  return (
    <pre
      aria-label="SQL resultante"
      className="overflow-x-auto whitespace-pre-wrap rounded-md border bg-muted p-3 font-mono text-xs"
    >
      {sql}
    </pre>
  );
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "Publica el modelo para poder probarlo.";
    return error.message;
  }
  return error instanceof Error ? error.message : "No se pudo generar la vista previa.";
}

export function ViewAsPanel({ datasourceId, model, dirty }: Props) {
  const roles = model.security?.roles ?? [];
  const metrics = model.metrics ?? [];
  const [mode, setMode] = useState<Mode>("metric");
  const [role, setRole] = useState(model.security?.default_role ?? roles[0]?.name ?? NO_ROLE);
  const [attributesText, setAttributesText] = useState("");
  const [metric, setMetric] = useState(metrics[0]?.name ?? "");
  const [period, setPeriod] = useState("");
  const [sql, setSql] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const used = [
    ...new Set(
      roles
        .filter((item) => item.name === role)
        .flatMap((item) => (item.filters ?? []).flatMap((f) => attributesIn(f.condition))),
    ),
  ];

  const run = useMutation<PreviewResult | ValidateSqlResult, unknown, void>({
    mutationFn: async () => {
      const parsed = parseAttributes(attributesText);
      if (parsed.error) throw new Error(parsed.error);
      const view_as = { role: role === NO_ROLE ? null : role, attributes: parsed.attributes };
      if (mode === "metric") {
        return previewMetric(datasourceId, {
          metric,
          view_as,
          ...(period.trim() ? { period: period.trim() } : {}),
        });
      }
      return validateSql(datasourceId, { sql, view_as });
    },
    onMutate: () => setLocalError(null),
    onError: (error) => setLocalError(errorMessage(error)),
  });

  const canRun = mode === "metric" ? metric !== "" : sql.trim() !== "";
  const result = run.data;
  const guard = result ? ("guard" in result ? result.guard : result) : null;
  const finalSql = result?.sql ?? null;

  return (
    <section aria-label="Ver como" className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      <h2 className="text-lg font-semibold">Ver como</h2>
      <p className="text-sm text-muted-foreground">
        Elige un rol y atributos de usuario para ver el SQL con el filtro inyectado. Usa la última
        versión publicada del modelo.
      </p>
      {dirty && (
        <p role="status" className="text-sm text-muted-foreground">
          Tienes cambios sin publicar: no se reflejan aquí hasta que publiques.
        </p>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label htmlFor="ver-como-rol" className="text-sm font-medium">
            Rol
          </label>
          <select
            id="ver-como-rol"
            className={selectClass}
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            <option value={NO_ROLE}>(rol por defecto del modelo)</option>
            {roles.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="ver-como-atributos" className="text-sm font-medium">
            Atributos del usuario
          </label>
          <Textarea
            id="ver-como-atributos"
            rows={2}
            placeholder={"sucursales = [1, 2]"}
            value={attributesText}
            onChange={(event) => setAttributesText(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Uno por línea: <code>nombre = valor</code> (listas como <code>[1, 2]</code>).
            {used.length > 0 && ` El rol usa: ${used.join(", ")}.`}
          </p>
        </div>
      </div>

      <div role="radiogroup" aria-label="Qué probar" className="flex gap-4 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="ver-como-modo"
            checked={mode === "metric"}
            onChange={() => setMode("metric")}
          />
          Métrica
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="ver-como-modo"
            checked={mode === "sql"}
            onChange={() => setMode("sql")}
          />
          SQL
        </label>
      </div>

      {mode === "metric" ? (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="ver-como-metrica" className="text-sm font-medium">
              Métrica
            </label>
            <select
              id="ver-como-metrica"
              className={selectClass}
              value={metric}
              onChange={(event) => setMetric(event.target.value)}
            >
              {metrics.length === 0 && <option value="">(el modelo no tiene métricas)</option>}
              {metrics.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="ver-como-periodo" className="text-sm font-medium">
              Período
            </label>
            <Input
              id="ver-como-periodo"
              placeholder="este mes"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
            />
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          <label htmlFor="ver-como-sql" className="text-sm font-medium">
            SQL a probar
          </label>
          <Textarea
            id="ver-como-sql"
            rows={3}
            className="font-mono"
            placeholder="SELECT * FROM facturas"
            value={sql}
            onChange={(event) => setSql(event.target.value)}
          />
        </div>
      )}

      <div>
        <Button type="button" disabled={!canRun || run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? "Generando…" : "Ver SQL"}
        </Button>
      </div>

      {localError && (
        <p role="alert" className="rounded-md border border-destructive p-3 text-sm">
          {localError}
        </p>
      )}
      {result && guard && (
        <div aria-label="Resultado" className="flex flex-col gap-3">
          <SqlBlock sql={finalSql} />
          <Guard guard={guard} />
          {"filters_applied" in result && (
            <ul aria-label="Filtros aplicados" className="list-disc pl-5 text-sm">
              {result.filters_applied.map((filter, i) => (
                <li key={`${filter.source}-${i}`}>
                  <span className="text-muted-foreground">{filter.source}:</span>{" "}
                  <code>{filter.text}</code>
                </li>
              ))}
            </ul>
          )}
          {"summary_table" in result && (
            <p className="text-sm text-muted-foreground">
              {result.summary_table
                ? `Tabla resumida: ${result.summary_table}. `
                : "Tablas base. "}
              {result.reason}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
