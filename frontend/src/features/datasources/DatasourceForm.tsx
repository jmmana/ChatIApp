import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import type { Datasource, DatasourceInput, Dialect, Privacy } from "./api";
import { DIALECTS, PRIVACY_LEVELS } from "./catalog";

interface Props {
  /** Si viene, el formulario edita esa fuente; si no, crea una nueva. */
  datasource?: Datasource;
  saving: boolean;
  error: string | null;
  onSubmit: (input: DatasourceInput) => void;
  onCancel: () => void;
}

const selectClass =
  "flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm disabled:opacity-50";

export function DatasourceForm({ datasource, saving, error, onSubmit, onCancel }: Props) {
  const editing = datasource !== undefined;
  const [name, setName] = useState(datasource?.name ?? "");
  const [dialect, setDialect] = useState<Dialect>(datasource?.dialect ?? "postgres");
  const [url, setUrl] = useState("");
  const [execute, setExecute] = useState(datasource?.execute ?? false);
  const [maxRows, setMaxRows] = useState(String(datasource?.max_rows ?? 1000));
  const [timeout, setTimeoutSeconds] = useState(String(datasource?.timeout_seconds ?? 30));
  const [privacy, setPrivacy] = useState<Privacy>(datasource?.privacy ?? "schema");
  const [invalid, setInvalid] = useState<string | null>(null);

  const dialectInfo = DIALECTS.find((d) => d.value === dialect) ?? DIALECTS[0];
  const privacyInfo = PRIVACY_LEVELS.find((p) => p.value === privacy) ?? PRIVACY_LEVELS[0];

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const rows = Number(maxRows);
    const seconds = Number(timeout);
    if (!name.trim()) return setInvalid("Escribe un nombre para la fuente.");
    if (!editing && !url.trim()) return setInvalid("Escribe la URL de conexión.");
    if (!Number.isInteger(rows) || rows < 1 || rows > 100_000)
      return setInvalid("El máximo de filas debe ser un entero entre 1 y 100000.");
    if (!Number.isInteger(seconds) || seconds < 1 || seconds > 600)
      return setInvalid("El tiempo límite debe ser un entero entre 1 y 600 segundos.");
    setInvalid(null);
    onSubmit({
      name: name.trim(),
      dialect,
      // En edición la URL solo se envía si se escribió una nueva.
      ...(url.trim() ? { url: url.trim() } : {}),
      execute,
      max_rows: rows,
      timeout_seconds: seconds,
      privacy,
    });
  }

  const message = invalid ?? error;

  return (
    <form onSubmit={handleSubmit} className="grid gap-4" noValidate>
      <div className="grid gap-1.5">
        <label htmlFor="ds-name" className="text-sm font-medium">
          Nombre
        </label>
        <Input id="ds-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      <div className="grid gap-1.5">
        <label htmlFor="ds-dialect" className="text-sm font-medium">
          Dialecto
        </label>
        <select
          id="ds-dialect"
          className={selectClass}
          value={dialect}
          onChange={(e) => setDialect(e.target.value as Dialect)}
        >
          {DIALECTS.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-1.5">
        <label htmlFor="ds-url" className="text-sm font-medium">
          URL de conexión
        </label>
        <Input
          id="ds-url"
          type="password"
          autoComplete="off"
          value={url}
          placeholder={editing ? datasource.url : dialectInfo.urlExample}
          onChange={(e) => setUrl(e.target.value)}
          aria-describedby="ds-url-help"
        />
        <p id="ds-url-help" className="text-xs text-muted-foreground">
          {editing && "Déjala vacía para conservar la actual. "}
          Ejemplo para {dialectInfo.label}:{" "}
          <code className="break-all font-mono">{dialectInfo.urlExample}</code>. Driver:{" "}
          {dialectInfo.driver}. Usa un usuario de solo lectura.
        </p>
      </div>

      <div className="flex items-start gap-3">
        <Switch id="ds-execute" checked={execute} onCheckedChange={setExecute} />
        <div className="grid gap-0.5">
          <label htmlFor="ds-execute" className="text-sm font-medium">
            Ejecutar consultas
          </label>
          <p className="text-xs text-muted-foreground">
            {execute
              ? "ChatIApp ejecuta el SQL en esta base y muestra los resultados."
              : "Solo genera el SQL: no se ejecuta nada en esta base."}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="grid gap-1.5">
          <label htmlFor="ds-max-rows" className="text-sm font-medium">
            Máximo de filas
          </label>
          <Input
            id="ds-max-rows"
            type="number"
            min={1}
            max={100000}
            value={maxRows}
            onChange={(e) => setMaxRows(e.target.value)}
          />
        </div>
        <div className="grid gap-1.5">
          <label htmlFor="ds-timeout" className="text-sm font-medium">
            Tiempo límite (segundos)
          </label>
          <Input
            id="ds-timeout"
            type="number"
            min={1}
            max={600}
            value={timeout}
            onChange={(e) => setTimeoutSeconds(e.target.value)}
          />
        </div>
      </div>

      <div className="grid gap-1.5">
        <label htmlFor="ds-privacy" className="text-sm font-medium">
          Privacidad
        </label>
        <select
          id="ds-privacy"
          className={selectClass}
          value={privacy}
          onChange={(e) => setPrivacy(e.target.value as Privacy)}
        >
          {PRIVACY_LEVELS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">{privacyInfo.help}</p>
      </div>

      {message && (
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancelar
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "Guardando…" : "Guardar"}
        </Button>
      </div>
    </form>
  );
}
