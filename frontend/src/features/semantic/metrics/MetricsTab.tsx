import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { ChipInput } from "../ChipInput";
import { ColumnSelect } from "../ColumnSelect";
import { describedBy, hasErrorsUnder, type FieldErrors } from "../errors";
import { FieldError } from "../FieldError";
import { selectClass } from "../styles";
import { StringList } from "../StringList";
import type { MetricFormat, SemanticMetric, SemanticModel } from "../types";
import { PreviewPanel } from "./PreviewPanel";

const FORMATS: { value: MetricFormat; label: string }[] = [
  { value: "currency", label: "Moneda" },
  { value: "integer", label: "Entero" },
  { value: "number", label: "Número" },
  { value: "percent", label: "Porcentaje" },
];

interface Props {
  model: SemanticModel;
  errors: FieldErrors;
  datasourceId: string;
  dialect: string;
  onChange: (model: SemanticModel) => void;
}

function emptyMetric(): SemanticMetric {
  return {
    name: "",
    label: "",
    table: "",
    expression: "",
    time_column: "",
    requires_period: true,
    additive: true,
  };
}

function Field({
  label,
  hint,
  path,
  errors,
  children,
}: {
  label: string;
  hint?: string;
  path: string;
  errors: FieldErrors;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1 text-sm">
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      <FieldError errors={errors} path={path} />
    </div>
  );
}

export function MetricsTab({ model, errors, datasourceId, dialect, onChange }: Props) {
  const metrics = model.metrics ?? [];
  const tables = model.tables ?? [];
  const [selected, setSelected] = useState(0);
  const index = Math.min(selected, metrics.length - 1);
  const metric = metrics[index] as SemanticMetric | undefined;
  const at = `metrics[${index}]`;

  function update(next: SemanticMetric[]) {
    onChange({ ...model, metrics: next });
  }

  function patch(changes: Partial<SemanticMetric>) {
    update(metrics.map((m, i) => (i === index ? { ...m, ...changes } : m)));
  }

  function add() {
    update([...metrics, emptyMetric()]);
    setSelected(metrics.length);
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-6 md:grid-cols-[16rem_1fr]">
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">
            Una métrica es la definición oficial de un número del negocio: el motor arma siempre el
            mismo SQL para ella.
          </p>
          {metrics.length === 0 && (
            <p className="text-sm text-muted-foreground">Todavía no hay métricas.</p>
          )}
          <ul aria-label="Métricas" className="flex flex-col gap-1">
            {metrics.map((item, i) => (
              <li key={i}>
                <button
                  type="button"
                  aria-current={i === index}
                  onClick={() => setSelected(i)}
                  className={cn(
                    "w-full rounded-md border px-3 py-2 text-left text-sm",
                    i === index ? "border-primary bg-accent" : "bg-card",
                    hasErrorsUnder(errors, `metrics[${i}]`) && "border-destructive",
                  )}
                >
                  <span className="block font-medium">{item.label || "(sin nombre)"}</span>
                  <span className="block text-xs text-muted-foreground">{item.name}</span>
                </button>
              </li>
            ))}
          </ul>
          <Button type="button" variant="outline" onClick={add}>
            <Plus aria-hidden /> Agregar métrica
          </Button>
        </div>

        {metric && (
          <section aria-label={`Editor de la métrica ${metric.label || metric.name}`}>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Nombre" hint="Identificador, p. ej. ventas_netas" path={`${at}.name`} errors={errors}>
                <Input
                  aria-label="Nombre de la métrica"
                  aria-describedby={describedBy(errors, `${at}.name`)}
                  value={metric.name}
                  onChange={(event) => patch({ name: event.target.value })}
                />
              </Field>
              <Field label="Etiqueta" hint="Nombre visible, p. ej. Ventas netas" path={`${at}.label`} errors={errors}>
                <Input
                  aria-label="Etiqueta de la métrica"
                  aria-describedby={describedBy(errors, `${at}.label`)}
                  value={metric.label}
                  onChange={(event) => patch({ label: event.target.value })}
                />
              </Field>
              <div className="md:col-span-2">
                <Field label="Descripción" hint="Qué mide y qué excluye" path={`${at}.description`} errors={errors}>
                  <Textarea
                    aria-label="Descripción de la métrica"
                    rows={2}
                    value={metric.description ?? ""}
                    onChange={(event) => patch({ description: event.target.value })}
                  />
                </Field>
              </div>
              <div className="md:col-span-2">
                <Field label="Sinónimos" hint="Cómo la pide la gente: «cuánto vendí»" path={`${at}.synonyms`} errors={errors}>
                  <ChipInput
                    label="Sinónimos de la métrica"
                    values={metric.synonyms ?? []}
                    onChange={(synonyms) => patch({ synonyms })}
                  />
                </Field>
              </div>
              <Field label="Tabla base" path={`${at}.table`} errors={errors}>
                <select
                  aria-label="Tabla base"
                  aria-describedby={describedBy(errors, `${at}.table`)}
                  className={selectClass}
                  value={metric.table}
                  onChange={(event) => patch({ table: event.target.value })}
                >
                  <option value="">Elige una tabla…</option>
                  {metric.table !== "" && !tables.some((t) => t.name === metric.table) && (
                    <option value={metric.table}>{metric.table}</option>
                  )}
                  {tables.map((table) => (
                    <option key={table.name} value={table.name}>
                      {table.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Columna de tiempo" hint="Puede estar en otra tabla" path={`${at}.time_column`} errors={errors}>
                <ColumnSelect
                  label="Columna de tiempo"
                  value={metric.time_column}
                  model={model}
                  describedById={describedBy(errors, `${at}.time_column`)}
                  onChange={(time_column) => patch({ time_column })}
                />
              </Field>
              <div className="md:col-span-2">
                <Field label="Expresión" hint="SQL agregado en el dialecto del modelo, p. ej. SUM(total)" path={`${at}.expression`} errors={errors}>
                  <Input
                    aria-label="Expresión de la métrica"
                    aria-describedby={describedBy(errors, `${at}.expression`)}
                    className="font-mono"
                    value={metric.expression}
                    onChange={(event) => patch({ expression: event.target.value })}
                  />
                </Field>
              </div>
              <div className="md:col-span-2">
                <span className="text-sm font-medium">Filtros fijos</span>
                <p className="mb-2 text-xs text-muted-foreground">
                  Condiciones que siempre aplican, p. ej. <code>estado = &apos;PAGADA&apos;</code>
                </p>
                <StringList
                  label="Filtro de la métrica"
                  addLabel="Agregar filtro"
                  values={metric.filters ?? []}
                  onChange={(filters) => patch({ filters })}
                  renderError={(i) => <FieldError errors={errors} path={`${at}.filters[${i}]`} />}
                />
              </div>
              <div className="md:col-span-2">
                <span className="text-sm font-medium">Dimensiones</span>
                <p className="mb-2 text-xs text-muted-foreground">
                  Por qué se puede desglosar la métrica.
                </p>
                <ul aria-label="Dimensiones de la métrica" className="flex flex-col gap-2">
                  {(metric.dimensions ?? []).map((dimension, i) => (
                    <li key={i} className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <ColumnSelect
                          label={`Dimensión ${i + 1}`}
                          value={dimension}
                          model={model}
                          describedById={describedBy(errors, `${at}.dimensions[${i}]`)}
                          onChange={(value) =>
                            patch({
                              dimensions: (metric.dimensions ?? []).map((d, j) =>
                                j === i ? value : d,
                              ),
                            })
                          }
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={`Quitar dimensión ${i + 1}`}
                          onClick={() =>
                            patch({ dimensions: (metric.dimensions ?? []).filter((_, j) => j !== i) })
                          }
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      </div>
                      <FieldError errors={errors} path={`${at}.dimensions[${i}]`} />
                    </li>
                  ))}
                </ul>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  onClick={() => patch({ dimensions: [...(metric.dimensions ?? []), ""] })}
                >
                  <Plus aria-hidden /> Agregar dimensión
                </Button>
              </div>
              <Field label="Formato" path={`${at}.format`} errors={errors}>
                <select
                  aria-label="Formato de la métrica"
                  className={selectClass}
                  value={metric.format ?? ""}
                  onChange={(event) =>
                    patch({ format: (event.target.value || null) as MetricFormat | null })
                  }
                >
                  <option value="">Sin formato</option>
                  {FORMATS.map((format) => (
                    <option key={format.value} value={format.value}>
                      {format.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Período por defecto" hint="Se asume tras 2 aclaraciones sin respuesta" path={`${at}.default_period`} errors={errors}>
                <Input
                  aria-label="Período por defecto"
                  placeholder="este mes"
                  value={metric.default_period ?? ""}
                  onChange={(event) => patch({ default_period: event.target.value || null })}
                />
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  aria-label="Requiere período"
                  checked={metric.requires_period ?? true}
                  onCheckedChange={(requires_period) => patch({ requires_period })}
                />
                Requiere período (si falta, se pregunta)
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  aria-label="Aditiva"
                  checked={metric.additive ?? true}
                  onCheckedChange={(additive) => patch({ additive })}
                />
                Aditiva (apágalo para promedios, razones y conteos distintos)
              </label>
            </div>
            <div className="mt-4">
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  update(metrics.filter((_, i) => i !== index));
                  setSelected(0);
                }}
              >
                <Trash2 aria-hidden /> Quitar métrica
              </Button>
            </div>
          </section>
        )}
      </div>

      <PreviewPanel
        datasourceId={datasourceId}
        dialect={dialect}
        model={model}
        initialMetric={metric?.name ?? ""}
      />
    </div>
  );
}
