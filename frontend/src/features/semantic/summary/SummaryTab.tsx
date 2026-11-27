import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { ColumnSelect } from "../ColumnSelect";
import { describedBy, hasErrorsUnder, type FieldErrors } from "../errors";
import { FieldError } from "../FieldError";
import { selectClass } from "../styles";
import type { Grain, SemanticModel, SummaryTable } from "../types";

const GRAINS: { value: Grain; label: string }[] = [
  { value: "day", label: "Día" },
  { value: "week", label: "Semana" },
  { value: "month", label: "Mes" },
  { value: "quarter", label: "Trimestre" },
  { value: "year", label: "Año" },
];

interface Props {
  model: SemanticModel;
  errors: FieldErrors;
  onChange: (model: SemanticModel) => void;
}

type Mapping = Record<string, string>;

/** Reemplaza la clave `from` por `to` conservando el orden de las filas. */
function renameKey(mapping: Mapping, from: string, to: string): Mapping {
  return Object.fromEntries(Object.entries(mapping).map(([k, v]) => [k === from ? to : k, v]));
}

function omitKey(mapping: Mapping, key: string): Mapping {
  return Object.fromEntries(Object.entries(mapping).filter(([k]) => k !== key));
}

export function SummaryTab({ model, errors, onChange }: Props) {
  const summaries = model.summary_tables ?? [];
  const tables = model.tables ?? [];
  const metrics = model.metrics ?? [];
  const [selected, setSelected] = useState(0);
  const index = Math.min(selected, summaries.length - 1);
  const summary = summaries[index] as SummaryTable | undefined;
  const at = `summary_tables[${index}]`;
  const mappedMetrics = summary?.metrics ?? {};
  const mappedDimensions = summary?.dimensions ?? {};

  function update(next: SummaryTable[]) {
    onChange({ ...model, summary_tables: next });
  }

  function patch(changes: Partial<SummaryTable>) {
    update(summaries.map((s, i) => (i === index ? { ...s, ...changes } : s)));
  }

  function add() {
    update([
      ...summaries,
      {
        table: "",
        grain: "month",
        time_column: "",
        includes_current_period: true,
      },
    ]);
    setSelected(summaries.length);
  }

  return (
    <div className="grid gap-6 md:grid-cols-[16rem_1fr]">
      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          Tablas precalculadas (diarias, mensuales…) que responden más rápido. El motor decide solo
          cuándo usarlas.
        </p>
        {summaries.length === 0 && (
          <p className="text-sm text-muted-foreground">Todavía no hay tablas resumidas.</p>
        )}
        <ul aria-label="Tablas resumidas" className="flex flex-col gap-1">
          {summaries.map((item, i) => (
            <li key={i}>
              <button
                type="button"
                aria-current={i === index}
                onClick={() => setSelected(i)}
                className={cn(
                  "w-full rounded-md border px-3 py-2 text-left text-sm",
                  i === index ? "border-primary bg-accent" : "bg-card",
                  hasErrorsUnder(errors, `summary_tables[${i}]`) && "border-destructive",
                )}
              >
                <span className="block font-medium">{item.table || "(sin tabla)"}</span>
                <span className="block text-xs text-muted-foreground">
                  {GRAINS.find((g) => g.value === item.grain)?.label ?? item.grain}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <Button type="button" variant="outline" onClick={add}>
          <Plus aria-hidden /> Agregar resumida
        </Button>
      </div>

      {summary && (
        <section
          aria-label={`Editor de la resumida ${summary.table}`}
          className="flex flex-col gap-4"
        >
          <div className="grid gap-4 md:grid-cols-3">
            <div className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Tabla resumida</span>
              <select
                aria-label="Tabla resumida"
                aria-describedby={describedBy(errors, `${at}.table`)}
                className={selectClass}
                value={summary.table}
                onChange={(event) => patch({ table: event.target.value, time_column: "" })}
              >
                <option value="">Elige una tabla…</option>
                {summary.table !== "" && !tables.some((t) => t.name === summary.table) && (
                  <option value={summary.table}>{summary.table}</option>
                )}
                {tables.map((table) => (
                  <option key={table.name} value={table.name}>
                    {table.name}
                  </option>
                ))}
              </select>
              <FieldError errors={errors} path={`${at}.table`} />
            </div>
            <div className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Granularidad</span>
              <select
                aria-label="Granularidad"
                aria-describedby={describedBy(errors, `${at}.grain`)}
                className={selectClass}
                value={summary.grain}
                onChange={(event) => patch({ grain: event.target.value as Grain })}
              >
                {GRAINS.map((grain) => (
                  <option key={grain.value} value={grain.value}>
                    {grain.label}
                  </option>
                ))}
              </select>
              <FieldError errors={errors} path={`${at}.grain`} />
            </div>
            <div className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Columna de tiempo</span>
              <ColumnSelect
                label="Columna de tiempo de la resumida"
                value={summary.time_column}
                model={model}
                onlyTable={summary.table}
                placeholder="Elige una columna…"
                describedById={describedBy(errors, `${at}.time_column`)}
                onChange={(time_column) => patch({ time_column })}
              />
              <FieldError errors={errors} path={`${at}.time_column`} />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <Switch
              aria-label="Incluye el período en curso"
              checked={summary.includes_current_period ?? true}
              onCheckedChange={(includes_current_period) => patch({ includes_current_period })}
            />
            Incluye el período en curso (apágalo si se carga al cierre)
          </label>

          <div>
            <h3 className="text-sm font-medium">Métricas</h3>
            <p className="mb-2 text-xs text-muted-foreground">
              Cada métrica del catálogo con su expresión sobre la resumida. Para métricas no
              aditivas, usa una expresión correcta (p. ej.{" "}
              <code>SUM(total_ventas) / SUM(num_facturas)</code>).
            </p>
            <ul aria-label="Métricas de la resumida" className="flex flex-col gap-2">
              {Object.entries(mappedMetrics).map(([name, expression], i) => {
                const path = `${at}.metrics[${name}]`;
                return (
                  <li key={i} className="flex flex-col gap-1">
                    <div className="grid items-center gap-2 md:grid-cols-[14rem_1fr_auto]">
                      <select
                        aria-label={`Métrica ${i + 1}`}
                        className={selectClass}
                        value={name}
                        onChange={(event) =>
                          patch({
                            metrics: renameKey(mappedMetrics, name, event.target.value),
                          })
                        }
                      >
                        <option value="">Elige una métrica…</option>
                        {name !== "" && !metrics.some((m) => m.name === name) && (
                          <option value={name}>{name}</option>
                        )}
                        {metrics.map((m) => (
                          <option key={m.name} value={m.name}>
                            {m.label || m.name}
                          </option>
                        ))}
                      </select>
                      <Input
                        aria-label={`Expresión de la métrica ${i + 1}`}
                        aria-describedby={describedBy(errors, path)}
                        className="font-mono"
                        placeholder="SUM(total_ventas)"
                        value={expression}
                        onChange={(event) =>
                          patch({
                            metrics: {
                              ...mappedMetrics,
                              [name]: event.target.value,
                            },
                          })
                        }
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Quitar métrica ${i + 1}`}
                        onClick={() => patch({ metrics: omitKey(mappedMetrics, name) })}
                      >
                        <Trash2 aria-hidden />
                      </Button>
                    </div>
                    <FieldError errors={errors} path={path} />
                  </li>
                );
              })}
            </ul>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-2"
              disabled={"" in mappedMetrics}
              onClick={() => patch({ metrics: { ...mappedMetrics, "": "" } })}
            >
              <Plus aria-hidden /> Agregar métrica
            </Button>
          </div>

          <div>
            <h3 className="text-sm font-medium">Dimensiones</h3>
            <p className="mb-2 text-xs text-muted-foreground">
              Dimensión de la métrica y la columna de la resumida que la cubre. Las alcanzables por
              relación no hace falta mapearlas.
            </p>
            <ul aria-label="Dimensiones de la resumida" className="flex flex-col gap-2">
              {Object.entries(mappedDimensions).map(([dimension, column], i) => {
                const path = `${at}.dimensions[${dimension}]`;
                return (
                  <li key={i} className="flex flex-col gap-1">
                    <div className="grid items-center gap-2 md:grid-cols-[1fr_1fr_auto]">
                      <ColumnSelect
                        label={`Dimensión ${i + 1}`}
                        value={dimension}
                        model={model}
                        describedById={describedBy(errors, path)}
                        onChange={(value) =>
                          patch({
                            dimensions: renameKey(mappedDimensions, dimension, value),
                          })
                        }
                      />
                      <ColumnSelect
                        label={`Columna de la resumida ${i + 1}`}
                        value={column}
                        model={model}
                        onlyTable={summary.table}
                        placeholder="Elige una columna…"
                        onChange={(value) =>
                          patch({
                            dimensions: {
                              ...mappedDimensions,
                              [dimension]: value,
                            },
                          })
                        }
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Quitar dimensión ${i + 1}`}
                        onClick={() =>
                          patch({
                            dimensions: omitKey(mappedDimensions, dimension),
                          })
                        }
                      >
                        <Trash2 aria-hidden />
                      </Button>
                    </div>
                    <FieldError errors={errors} path={path} />
                  </li>
                );
              })}
            </ul>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-2"
              disabled={"" in mappedDimensions}
              onClick={() => patch({ dimensions: { ...mappedDimensions, "": "" } })}
            >
              <Plus aria-hidden /> Agregar dimensión
            </Button>
          </div>

          <div>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                update(summaries.filter((_, i) => i !== index));
                setSelected(0);
              }}
            >
              <Trash2 aria-hidden /> Quitar resumida
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
