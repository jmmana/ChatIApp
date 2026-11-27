import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type {
  CatalogEntry,
  CatalogField,
  ModelsResult,
  ProbeResult,
  Provider,
  ProviderInput,
} from "./api";
import { TestResultView } from "./TestResultView";

interface Props {
  /** Entrada del catálogo: de ella sale todo el formulario. */
  spec: CatalogEntry;
  /** Si viene, el formulario edita ese proveedor; si no, crea uno nuevo. */
  provider?: Provider;
  saving: boolean;
  error: string | null;
  testing: boolean;
  testResult: ProbeResult | null;
  onSubmit: (input: ProviderInput) => void;
  onTest: (input: ProviderInput) => void;
  /** Solo en edición: la lista en vivo se pide al proveedor guardado. */
  onLoadModels?: () => Promise<ModelsResult>;
  onCancel: () => void;
}

const selectClass =
  "flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm disabled:opacity-50";

function initialValue(field: CatalogField, provider?: Provider): string {
  const current = provider?.config[field.name];
  if (current === undefined || current === null) return provider ? "" : (field.default ?? "");
  return typeof current === "string" ? current : JSON.stringify(current, null, 2);
}

export function ProviderForm({
  spec,
  provider,
  saving,
  error,
  testing,
  testResult,
  onSubmit,
  onTest,
  onLoadModels,
  onCancel,
}: Props) {
  const editing = provider !== undefined;
  const plainFields = spec.fields.filter((f) => f.type !== "secret");
  const secretFields = spec.fields.filter((f) => f.type === "secret");

  const [name, setName] = useState(provider?.name ?? spec.label);
  const [model, setModel] = useState(provider?.model ?? spec.suggested_models[0] ?? "");
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(plainFields.map((f) => [f.name, initialValue(f, provider)])),
  );
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [replacing, setReplacing] = useState<Record<string, boolean>>({});
  const [isDefault, setIsDefault] = useState(provider?.is_default ?? false);
  const [liveModels, setLiveModels] = useState<ModelsResult | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [invalid, setInvalid] = useState<string | null>(null);

  const suggestions = [...new Set([...(liveModels?.models ?? []), ...spec.suggested_models])];

  /** Arma el cuerpo a partir de los campos del catálogo, o devuelve el motivo por el que no se puede. */
  function build(): ProviderInput | string {
    if (!name.trim()) return "Escribe un nombre para el proveedor.";
    if (!model.trim()) return "Escribe el modelo.";
    const config: Record<string, unknown> = {};
    for (const field of plainFields) {
      const raw = (values[field.name] ?? "").trim();
      if (!raw) {
        if (field.required && field.default === null)
          return `Completa el campo «${field.label}».`;
        continue;
      }
      if (field.type === "json") {
        try {
          config[field.name] = JSON.parse(raw);
        } catch {
          return `«${field.label}» no es un JSON válido.`;
        }
      } else {
        config[field.name] = raw;
      }
    }
    const sent: Record<string, string> = {};
    for (const field of secretFields) {
      const value = secrets[field.name]?.trim() ?? "";
      const stored = editing && field.name in provider.secrets;
      if (value) sent[field.name] = value;
      else if (field.required && field.default === null && !stored)
        return `Completa el campo «${field.label}».`;
    }
    return { name: name.trim(), model: model.trim(), config, secrets: sent, is_default: isDefault };
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const result = build();
    if (typeof result === "string") return setInvalid(result);
    setInvalid(null);
    onSubmit(result);
  }

  function handleTest() {
    const result = build();
    if (typeof result === "string") return setInvalid(result);
    setInvalid(null);
    onTest(result);
  }

  async function handleLoadModels() {
    if (!onLoadModels) return;
    setLoadingModels(true);
    try {
      setLiveModels(await onLoadModels());
    } catch (err) {
      setLiveModels({
        supported: true,
        models: [],
        error_kind: "provider_error",
        message: err instanceof Error ? err.message : null,
      });
    } finally {
      setLoadingModels(false);
    }
  }

  const message = invalid ?? error;

  return (
    <form onSubmit={handleSubmit} className="grid gap-4" noValidate>
      {spec.notes && <p className="text-sm text-muted-foreground">{spec.notes}</p>}

      <div className="grid gap-1.5">
        <label htmlFor="prov-name" className="text-sm font-medium">
          Nombre
        </label>
        <Input id="prov-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      {plainFields.map((field) => (
        <DynamicField
          key={field.name}
          field={field}
          value={values[field.name] ?? ""}
          onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))}
        />
      ))}

      {secretFields.map((field) => {
        const mask = provider?.secrets[field.name];
        return (
          <SecretField
            key={field.name}
            field={field}
            mask={mask}
            replacing={replacing[field.name] ?? false}
            value={secrets[field.name] ?? ""}
            onReplace={(on) => {
              setReplacing((current) => ({ ...current, [field.name]: on }));
              if (!on) setSecrets((current) => ({ ...current, [field.name]: "" }));
            }}
            onChange={(value) => setSecrets((current) => ({ ...current, [field.name]: value }))}
          />
        );
      })}

      <div className="grid gap-1.5">
        <label htmlFor="prov-model" className="text-sm font-medium">
          Modelo
        </label>
        <div className="flex gap-2">
          <Input
            id="prov-model"
            list="prov-model-options"
            value={model}
            autoComplete="off"
            onChange={(e) => setModel(e.target.value)}
            aria-describedby="prov-model-help"
          />
          {onLoadModels && (
            <Button
              type="button"
              variant="outline"
              disabled={loadingModels}
              onClick={handleLoadModels}
            >
              {loadingModels ? "Cargando…" : "Cargar modelos"}
            </Button>
          )}
        </div>
        <datalist id="prov-model-options">
          {suggestions.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
        <p id="prov-model-help" className="text-xs text-muted-foreground">
          Elige uno de la lista o escribe el nombre exacto del modelo.
          {liveModels?.supported && liveModels.models.length > 0 &&
            ` ${liveModels.models.length} modelos disponibles en el proveedor.`}
          {liveModels && !liveModels.supported &&
            " Este proveedor no permite listar sus modelos: escríbelo a mano."}
          {liveModels?.supported && liveModels.models.length === 0 &&
            ` No se pudo obtener la lista${liveModels.message ? `: ${liveModels.message}` : "."}`}
        </p>
      </div>

      <div className="flex items-start gap-3">
        <Switch id="prov-default" checked={isDefault} onCheckedChange={setIsDefault} />
        <div className="grid gap-0.5">
          <label htmlFor="prov-default" className="text-sm font-medium">
            Predeterminado
          </label>
          <p className="text-xs text-muted-foreground">
            Responde las tareas que no tengan otro proveedor asignado.
          </p>
        </div>
      </div>

      <div className="grid gap-2 rounded-lg border p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            {editing
              ? "Prueba la configuración guardada; si cambiaste algo, guarda primero."
              : "Prueba esta configuración sin guardarla."}
          </p>
          <Button type="button" variant="outline" size="sm" disabled={testing} onClick={handleTest}>
            {testing ? "Probando…" : "Probar conexión"}
          </Button>
        </div>
        {testResult && <TestResultView result={testResult} />}
      </div>

      {message && (
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      )}

      <div className="flex items-center justify-between gap-2">
        <a
          href={spec.docs_url}
          target="_blank"
          rel="noreferrer"
          className="text-sm text-muted-foreground underline"
        >
          Documentación
        </a>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancelar
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? "Guardando…" : "Guardar"}
          </Button>
        </div>
      </div>
    </form>
  );
}

function FieldHelp({ field, id }: { field: CatalogField; id: string }) {
  const parts = [field.help, field.required ? null : "Opcional."].filter(Boolean);
  if (parts.length === 0) return null;
  return (
    <p id={id} className="text-xs text-muted-foreground">
      {parts.join(" ")}
    </p>
  );
}

/** Un campo no secreto: el control lo decide el `type` que declara el catálogo. */
function DynamicField({
  field,
  value,
  onChange,
}: {
  field: CatalogField;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = `prov-${field.name}`;
  const helpId = `${id}-help`;
  let control;
  if (field.type === "select") {
    control = (
      <select
        id={id}
        className={selectClass}
        value={value}
        aria-describedby={helpId}
        onChange={(e) => onChange(e.target.value)}
      >
        {!field.required || field.default === null ? <option value="">—</option> : null}
        {field.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  } else if (field.type === "json") {
    control = (
      <Textarea
        id={id}
        className="font-mono text-xs"
        rows={5}
        value={value}
        aria-describedby={helpId}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  } else {
    control = (
      <>
        <Input
          id={id}
          type={field.type === "url" ? "url" : "text"}
          list={field.options.length > 0 ? `${id}-options` : undefined}
          autoComplete="off"
          value={value}
          aria-describedby={helpId}
          onChange={(e) => onChange(e.target.value)}
        />
        {field.options.length > 0 && (
          <datalist id={`${id}-options`}>
            {field.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </datalist>
        )}
      </>
    );
  }
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {field.label}
      </label>
      {control}
      <FieldHelp field={field} id={helpId} />
    </div>
  );
}

/** Secreto: siempre campo de contraseña; al editar se ve la máscara y «Reemplazar». */
function SecretField({
  field,
  mask,
  replacing,
  value,
  onReplace,
  onChange,
}: {
  field: CatalogField;
  mask: string | undefined;
  replacing: boolean;
  value: string;
  onReplace: (on: boolean) => void;
  onChange: (value: string) => void;
}) {
  const id = `prov-${field.name}`;
  const helpId = `${id}-help`;
  const stored = mask !== undefined;
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {field.label}
      </label>
      {stored && !replacing ? (
        <div className="flex gap-2">
          <Input
            id={id}
            type="password"
            readOnly
            value={mask}
            aria-describedby={helpId}
            className="font-mono"
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => onReplace(true)}
            aria-label={`Reemplazar ${field.label}`}
          >
            Reemplazar
          </Button>
        </div>
      ) : (
        <div className="flex gap-2">
          <Input
            id={id}
            type="password"
            autoComplete="new-password"
            value={value}
            aria-describedby={helpId}
            onChange={(e) => onChange(e.target.value)}
          />
          {stored && (
            <Button type="button" variant="outline" onClick={() => onReplace(false)}>
              Conservar
            </Button>
          )}
        </div>
      )}
      <FieldHelp field={field} id={helpId} />
    </div>
  );
}
