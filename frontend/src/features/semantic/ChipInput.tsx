import { X } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

interface ChipInputProps {
  label: string;
  values: (string | number)[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  describedBy?: string;
}

/** Lista de chips editable: Enter o coma agrega; Retroceso en vacío quita el último. */
export function ChipInput({ label, values, onChange, placeholder, describedBy }: ChipInputProps) {
  const [text, setText] = useState("");
  const current = values.map(String);

  function commit() {
    const value = text.trim();
    setText("");
    if (value && !current.includes(value)) onChange([...current, value]);
  }

  return (
    <div className="flex flex-wrap items-center gap-1 rounded-md border border-input bg-card px-2 py-1 text-sm">
      {current.map((value) => (
        <span
          key={value}
          className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-xs text-accent-foreground"
        >
          {value}
          <button
            type="button"
            aria-label={`Quitar ${value} de ${label}`}
            className="rounded-full hover:bg-background"
            onClick={() => onChange(current.filter((v) => v !== value))}
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
      <input
        aria-label={label}
        aria-describedby={describedBy}
        value={text}
        placeholder={current.length === 0 ? placeholder : undefined}
        className={cn("min-w-24 flex-1 bg-transparent py-0.5 outline-none")}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            commit();
          } else if (event.key === "Backspace" && text === "" && current.length > 0) {
            onChange(current.slice(0, -1));
          }
        }}
      />
    </div>
  );
}
