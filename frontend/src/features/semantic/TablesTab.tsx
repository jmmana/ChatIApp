import { Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { ChipInput } from "./ChipInput";
import { describedBy, hasErrorsUnder, type FieldErrors } from "./errors";
import { FieldError } from "./FieldError";
import type { ColumnRole, SemanticColumn, SemanticModel, SemanticTable } from "./types";

export const ROLE_LABELS: Record<ColumnRole, string> = {
  time: "Tiempo",
  measure: "Medida",
  dimension: "Dimensión",
  id: "Identificador",
  other: "Otro",
};

export const selectClass =
  "h-9 w-full rounded-md border border-input bg-card px-2 text-sm disabled:opacity-50";

function emptyValue(text: string | null | undefined): boolean {
  return !text || text.trim() === "";
}

function missingDescriptions(table: SemanticTable): number {
  return (table.columns ?? []).filter((column) => emptyValue(column.description)).length;
}

interface Props {
  model: SemanticModel;
  errors: FieldErrors;
  onChange: (model: SemanticModel) => void;
}

export function TablesTab({ model, errors, onChange }: Props) {
  const tables = model.tables ?? [];
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(0);
  const [newColumn, setNewColumn] = useState("");

  const needle = search.trim().toLowerCase();
  const visible = tables
    .map((table, index) => ({ table, index }))
    .filter(({ table }) => table.name.toLowerCase().includes(needle));
  const index = selected < tables.length ? selected : 0;
  const table = tables[index];
  const totalMissing = tables.reduce((sum, t) => sum + missingDescriptions(t), 0);

  function patchTable(patch: Partial<SemanticTable>) {
    onChange({ ...model, tables: tables.map((t, i) => (i === index ? { ...t, ...patch } : t)) });
  }

  function patchColumn(columnIndex: number, patch: Partial<SemanticColumn>) {
    patchTable({
      columns: (table.columns ?? []).map((c, i) => (i === columnIndex ? { ...c, ...patch } : c)),
    });
  }

  function addColumn() {
    const name = newColumn.trim();
    if (!name) return;
    patchTable({ columns: [...(table.columns ?? []), { name, role: "other" }] });
    setNewColumn("");
  }

  return (
    <div className="grid gap-6 md:grid-cols-[16rem_1fr]">
      <aside className="flex flex-col gap-3">
        <Input
          type="search"
          aria-label="Buscar tabla"
          placeholder="Buscar tabla…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <ul aria-label="Tablas" className="flex flex-col gap-1">
          {visible.map(({ table: item, index: itemIndex }) => {
            const missing = missingDescriptions(item);
            const active = itemIndex === index;
            return (
              <li key={item.name}>
                <button
                  type="button"
                  aria-current={active ? "true" : undefined}
                  onClick={() => setSelected(itemIndex)}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm",
                    active ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                    hasErrorsUnder(errors, `tables[${itemIndex}]`) && "ring-1 ring-destructive",
                  )}
                >
                  <span className="truncate font-medium">{item.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {(item.columns ?? []).length} col
                    {missing > 0 && ` · ${missing} sin descripción`}
                  </span>
                </button>
              </li>
            );
          })}
          {visible.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted-foreground">Ninguna tabla coincide.</li>
          )}
        </ul>
        <p className="text-sm text-muted-foreground">
          {totalMissing === 0
            ? "Todas las columnas tienen descripción."
            : `${totalMissing} ${totalMissing === 1 ? "columna sin descripción" : "columnas sin descripción"}`}
        </p>
      </aside>

      {table ? (
        <section aria-label={`Tabla ${table.name}`} className="flex min-w-0 flex-col gap-4">
          <h2 className="text-lg font-semibold">{table.name}</h2>
          <div className="flex flex-col gap-1">
            <label htmlFor="tabla-descripcion" className="text-sm font-medium">
              Descripción de la tabla
            </label>
            <Textarea
              id="tabla-descripcion"
              rows={2}
              value={table.description ?? ""}
              aria-describedby={describedBy(errors, `tables[${index}].description`)}
              onChange={(event) => patchTable({ description: event.target.value || null })}
            />
            <FieldError errors={errors} path={`tables[${index}].description`} />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium">Sinónimos de la tabla</span>
            <ChipInput
              label="Sinónimos de la tabla"
              values={table.synonyms ?? []}
              onChange={(synonyms) => patchTable({ synonyms })}
              placeholder="Agrega un sinónimo y presiona Enter"
              describedBy={describedBy(errors, `tables[${index}].synonyms`)}
            />
            <FieldError errors={errors} path={`tables[${index}].synonyms`} />
          </div>

          <ul aria-label="Columnas" className="flex flex-col gap-3">
            {(table.columns ?? []).map((column, columnIndex) => {
              const at = `tables[${index}].columns[${columnIndex}]`;
              return (
                <li key={column.name}>
                  <fieldset className="grid gap-3 rounded-lg border bg-card p-3 md:grid-cols-[1fr_10rem_6rem]">
                    <legend className="px-1 font-mono text-sm font-medium">{column.name}</legend>
                    <div className="flex flex-col gap-1">
                      <Input
                        aria-label={`Descripción de ${column.name}`}
                        placeholder="(vacío)"
                        value={column.description ?? ""}
                        aria-describedby={describedBy(errors, `${at}.description`)}
                        onChange={(event) =>
                          patchColumn(columnIndex, { description: event.target.value || null })
                        }
                      />
                      <FieldError errors={errors} path={`${at}.description`} />
                    </div>
                    <div className="flex flex-col gap-1">
                      <select
                        aria-label={`Rol de ${column.name}`}
                        className={selectClass}
                        value={column.role ?? "other"}
                        aria-describedby={describedBy(errors, `${at}.role`)}
                        onChange={(event) =>
                          patchColumn(columnIndex, { role: event.target.value as ColumnRole })
                        }
                      >
                        {Object.entries(ROLE_LABELS).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                      <FieldError errors={errors} path={`${at}.role`} />
                    </div>
                    <label className="flex items-center gap-2 text-sm">
                      <Switch
                        aria-label={`Oculta: ${column.name}`}
                        checked={column.hidden ?? false}
                        onCheckedChange={(hidden) => patchColumn(columnIndex, { hidden })}
                      />
                      Oculta
                    </label>
                    <div className="flex flex-col gap-1 md:col-span-1">
                      <ChipInput
                        label={`Sinónimos de ${column.name}`}
                        values={column.synonyms ?? []}
                        onChange={(synonyms) => patchColumn(columnIndex, { synonyms })}
                        placeholder="Sinónimos"
                        describedBy={describedBy(errors, `${at}.synonyms`)}
                      />
                      <FieldError errors={errors} path={`${at}.synonyms`} />
                    </div>
                    <div className="flex flex-col gap-1 md:col-span-2">
                      <ChipInput
                        label={`Valores de ejemplo de ${column.name}`}
                        values={column.sample_values ?? []}
                        onChange={(sample_values) => patchColumn(columnIndex, { sample_values })}
                        placeholder="Valores de ejemplo"
                        describedBy={describedBy(errors, `${at}.sample_values`)}
                      />
                      <FieldError errors={errors} path={`${at}.sample_values`} />
                    </div>
                    <FieldError errors={errors} path={`${at}.name`} />
                  </fieldset>
                </li>
              );
            })}
          </ul>

          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              addColumn();
            }}
          >
            <Input
              aria-label="Nombre de la columna nueva"
              placeholder="Nombre de la columna"
              value={newColumn}
              onChange={(event) => setNewColumn(event.target.value)}
            />
            <Button type="submit" variant="outline" disabled={newColumn.trim() === ""}>
              <Plus aria-hidden /> Columna
            </Button>
          </form>
        </section>
      ) : (
        <p className="text-sm text-muted-foreground">
          El modelo todavía no tiene tablas. Impórtalas desde la base conectada o desde un archivo.
        </p>
      )}
    </div>
  );
}
