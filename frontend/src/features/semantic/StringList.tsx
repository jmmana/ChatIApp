import { Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  label: string;
  values: string[];
  addLabel: string;
  placeholder?: string;
  onChange: (values: string[]) => void;
  /** Mensajes de error junto a cada elemento. */
  renderError?: (index: number) => ReactNode;
}

/** Lista de textos libres, uno por fila (para condiciones SQL, que pueden llevar comas). */
export function StringList({ label, values, addLabel, placeholder, onChange, renderError }: Props) {
  return (
    <div className="flex flex-col gap-2">
      <ul aria-label={label} className="flex flex-col gap-2">
        {values.map((value, i) => (
          <li key={i} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Input
                aria-label={`${label} ${i + 1}`}
                value={value}
                placeholder={placeholder}
                className="font-mono"
                onChange={(event) =>
                  onChange(values.map((v, j) => (j === i ? event.target.value : v)))
                }
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Quitar ${label} ${i + 1}`}
                onClick={() => onChange(values.filter((_, j) => j !== i))}
              >
                <Trash2 aria-hidden />
              </Button>
            </div>
            {renderError?.(i)}
          </li>
        ))}
      </ul>
      <div>
        <Button type="button" variant="outline" size="sm" onClick={() => onChange([...values, ""])}>
          <Plus aria-hidden /> {addLabel}
        </Button>
      </div>
    </div>
  );
}
