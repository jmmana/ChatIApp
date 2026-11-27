import type { ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { describedBy, type FieldErrors } from "./errors";
import { FieldError } from "./FieldError";
import { selectClass } from "./styles";
import type { SemanticModel, SemanticSettings, Weekday } from "./types";

const WEEKDAYS: [Weekday, string][] = [
  ["monday", "Lunes"],
  ["tuesday", "Martes"],
  ["wednesday", "Miércoles"],
  ["thursday", "Jueves"],
  ["friday", "Viernes"],
  ["saturday", "Sábado"],
  ["sunday", "Domingo"],
];

const MONTHS = [
  "Enero",
  "Febrero",
  "Marzo",
  "Abril",
  "Mayo",
  "Junio",
  "Julio",
  "Agosto",
  "Septiembre",
  "Octubre",
  "Noviembre",
  "Diciembre",
];

interface Props {
  model: SemanticModel;
  errors: FieldErrors;
  onChange: (model: SemanticModel) => void;
}

export function ContextTab({ model, errors, onChange }: Props) {
  const settings = model.settings ?? {};

  function patch(change: Partial<SemanticSettings>) {
    onChange({ ...model, settings: { ...settings, ...change } });
  }

  function field(id: string, label: string, path: string, control: ReactNode) {
    return (
      <div className="flex flex-col gap-1">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        {control}
        <FieldError errors={errors} path={path} />
      </div>
    );
  }

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      {field(
        "contexto-negocio",
        "Contexto del negocio",
        "business_context",
        <Textarea
          id="contexto-negocio"
          rows={6}
          placeholder="Qué hace tu negocio, cómo se llaman las cosas y qué reglas importan al interpretar los datos."
          value={model.business_context ?? ""}
          aria-describedby={describedBy(errors, "business_context")}
          onChange={(event) =>
            onChange({ ...model, business_context: event.target.value })
          }
        />,
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {field(
          "ajuste-zona",
          "Zona horaria",
          "settings.timezone",
          <Input
            id="ajuste-zona"
            placeholder="America/Bogota"
            value={settings.timezone ?? "UTC"}
            aria-describedby={describedBy(errors, "settings.timezone")}
            onChange={(event) => patch({ timezone: event.target.value })}
          />,
        )}
        {field(
          "ajuste-moneda",
          "Moneda",
          "settings.currency",
          <Input
            id="ajuste-moneda"
            placeholder="COP"
            value={settings.currency ?? ""}
            aria-describedby={describedBy(errors, "settings.currency")}
            onChange={(event) =>
              patch({ currency: event.target.value || null })
            }
          />,
        )}
        {field(
          "ajuste-locale",
          "Locale",
          "settings.locale",
          <Input
            id="ajuste-locale"
            placeholder="es-CO"
            value={settings.locale ?? ""}
            aria-describedby={describedBy(errors, "settings.locale")}
            onChange={(event) => patch({ locale: event.target.value || null })}
          />,
        )}
        {field(
          "ajuste-semana",
          "Inicio de semana",
          "settings.week_starts_on",
          <select
            id="ajuste-semana"
            className={selectClass}
            value={settings.week_starts_on ?? "monday"}
            aria-describedby={describedBy(errors, "settings.week_starts_on")}
            onChange={(event) =>
              patch({ week_starts_on: event.target.value as Weekday })
            }
          >
            {WEEKDAYS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>,
        )}
        {field(
          "ajuste-fiscal",
          "Inicio del año fiscal",
          "settings.fiscal_year_start_month",
          <select
            id="ajuste-fiscal"
            className={selectClass}
            value={settings.fiscal_year_start_month ?? 1}
            aria-describedby={describedBy(
              errors,
              "settings.fiscal_year_start_month",
            )}
            onChange={(event) =>
              patch({ fiscal_year_start_month: Number(event.target.value) })
            }
          >
            {MONTHS.map((label, i) => (
              <option key={label} value={i + 1}>
                {label}
              </option>
            ))}
          </select>,
        )}
      </div>
    </div>
  );
}
