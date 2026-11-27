import { selectClass } from "./styles";
import type { SemanticModel } from "./types";

interface Props {
  label: string;
  value: string;
  model: SemanticModel;
  /** Si se indica, solo ofrece las columnas de esa tabla (el valor es el nombre de columna). */
  onlyTable?: string;
  placeholder?: string;
  describedById?: string;
  onChange: (value: string) => void;
}

/** Selector de `tabla.columna` (o solo `columna` cuando se limita a una tabla). */
export function ColumnSelect({
  label,
  value,
  model,
  onlyTable,
  placeholder,
  describedById,
  onChange,
}: Props) {
  const tables = (model.tables ?? []).filter(
    (t) => onlyTable === undefined || t.name === onlyTable,
  );
  const optionValue = (table: string, column: string) =>
    onlyTable === undefined ? `${table}.${column}` : column;
  const known = tables.some((t) =>
    (t.columns ?? []).some((c) => optionValue(t.name, c.name) === value),
  );
  return (
    <select
      aria-label={label}
      aria-describedby={describedById}
      className={selectClass}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">{placeholder ?? "Elige tabla.columna…"}</option>
      {value !== "" && !known && <option value={value}>{value}</option>}
      {tables.map((table) => (
        <optgroup key={table.name} label={table.name}>
          {(table.columns ?? []).map((column) => (
            <option
              key={column.name}
              value={optionValue(table.name, column.name)}
            >
              {onlyTable === undefined
                ? `${table.name}.${column.name}`
                : column.name}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
