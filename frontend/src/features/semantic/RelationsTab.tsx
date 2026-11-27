import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { describedBy, type FieldErrors } from "./errors";
import { FieldError } from "./FieldError";
import { selectClass } from "./styles";
import type { SemanticModel } from "./types";

interface Props {
  model: SemanticModel;
  errors: FieldErrors;
  onChange: (model: SemanticModel) => void;
}

function RefSelect({
  label,
  value,
  model,
  describedById,
  onChange,
}: {
  label: string;
  value: string;
  model: SemanticModel;
  describedById?: string;
  onChange: (value: string) => void;
}) {
  const tables = model.tables ?? [];
  const known = tables.some((t) =>
    (t.columns ?? []).some((c) => `${t.name}.${c.name}` === value),
  );
  return (
    <select
      aria-label={label}
      aria-describedby={describedById}
      className={selectClass}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">Elige tabla.columna…</option>
      {value !== "" && !known && <option value={value}>{value}</option>}
      {tables.map((table) => (
        <optgroup key={table.name} label={table.name}>
          {(table.columns ?? []).map((column) => (
            <option key={column.name} value={`${table.name}.${column.name}`}>
              {table.name}.{column.name}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

export function RelationsTab({ model, errors, onChange }: Props) {
  const relationships = model.relationships ?? [];

  function update(next: typeof relationships) {
    onChange({ ...model, relationships: next });
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Cada relación une una columna con otra (por ejemplo,{" "}
        <code>facturas.cliente_id</code> con <code>clientes.id</code>) para que
        ChatIApp sepa cómo cruzar las tablas.
      </p>
      {relationships.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Todavía no hay relaciones.
        </p>
      )}
      <ul aria-label="Relaciones" className="flex flex-col gap-3">
        {relationships.map((relation, i) => (
          <li
            key={i}
            className="grid items-start gap-2 md:grid-cols-[1fr_1fr_auto]"
          >
            <div className="flex flex-col gap-1">
              <RefSelect
                label={`Desde, relación ${i + 1}`}
                value={relation.from}
                model={model}
                describedById={describedBy(errors, `relationships[${i}].from`)}
                onChange={(from) =>
                  update(
                    relationships.map((r, j) => (j === i ? { ...r, from } : r)),
                  )
                }
              />
              <FieldError errors={errors} path={`relationships[${i}].from`} />
            </div>
            <div className="flex flex-col gap-1">
              <RefSelect
                label={`Hacia, relación ${i + 1}`}
                value={relation.to}
                model={model}
                describedById={describedBy(errors, `relationships[${i}].to`)}
                onChange={(to) =>
                  update(
                    relationships.map((r, j) => (j === i ? { ...r, to } : r)),
                  )
                }
              />
              <FieldError errors={errors} path={`relationships[${i}].to`} />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Quitar relación ${i + 1}`}
              onClick={() => update(relationships.filter((_, j) => j !== i))}
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
          onClick={() => update([...relationships, { from: "", to: "" }])}
        >
          <Plus aria-hidden /> Agregar relación
        </Button>
      </div>
    </div>
  );
}
