import { useMutation } from "@tanstack/react-query";
import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { issuesFrom } from "../api";
import type { Datasource, SemanticModel } from "../types";
import { previewImport, previewIntrospection } from "./api";
import type { ImportPreview } from "./types";

const ACCEPT = ".sql,.csv,.xlsx,.yaml,.yml,.json";

interface Props {
  datasource: Datasource;
  /** Recibe el modelo fusionado; el editor lo carga como borrador sin publicarlo. */
  onApply: (model: SemanticModel) => void;
}

interface Source {
  label: string;
  preview: ImportPreview;
}

function describeError(error: unknown): string[] {
  if (error instanceof ApiError) {
    const lines = [error.message];
    if (error.status === 422) {
      for (const { path, message } of issuesFrom(error)) {
        lines.push(path ? `${path}: ${message}` : message);
      }
    }
    return lines;
  }
  return ["No se pudo leer el archivo."];
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(vacío)";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function Group({
  sign,
  title,
  count,
  children,
}: {
  sign: string;
  title: string;
  count: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  if (count === 0) return null;
  return (
    <li className="rounded-md border border-border bg-card">
      <button
        type="button"
        aria-expanded={open}
        className="flex w-full items-center gap-2 p-3 text-left text-sm font-medium"
        onClick={() => setOpen(!open)}
      >
        <span aria-hidden="true" className="w-4 font-mono">
          {sign}
        </span>
        <span>{`${count} ${title}`}</span>
      </button>
      {open && <ul className="flex flex-col gap-1 border-t border-border p-3 text-sm">{children}</ul>}
    </li>
  );
}

function Preview({
  source,
  onApply,
  onCancel,
}: {
  source: Source;
  onApply: () => void;
  onCancel: () => void;
}) {
  const { diff, warnings } = source.preview;
  const nothing =
    !diff.added.length &&
    !diff.changed.length &&
    !diff.missing.length &&
    !diff.suggestions.length &&
    !warnings.length;
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-base font-semibold">Vista previa · {source.label}</h2>
      {nothing && (
        <p className="text-sm text-muted-foreground">El archivo no cambia nada del modelo.</p>
      )}
      <ul className="flex flex-col gap-2">
        <Group sign="+" title="nuevas" count={diff.added.length}>
          {diff.added.map((item) => (
            <li key={`${item.kind}:${item.path}`}>
              {item.path} <span className="text-muted-foreground">({item.kind})</span>
            </li>
          ))}
        </Group>
        <Group sign="~" title="cambian" count={diff.changed.length}>
          {diff.changed.map((item) => (
            <li key={`${item.path}:${item.field}`}>
              {item.path} · {item.field}: {show(item.before)} → {show(item.after)}
            </li>
          ))}
        </Group>
        <Group
          sign="~"
          title="descripciones se completan (las tuyas se conservan)"
          count={diff.suggestions.length}
        >
          {diff.suggestions.map((item) => (
            <li key={`${item.path}:${item.field}`}>
              {item.path} · {item.field}: {show(item.suggested)}
            </li>
          ))}
        </Group>
        <Group sign="−" title="no encontradas (se marcan, no se borran)" count={diff.missing.length}>
          {diff.missing.map((item) => (
            <li key={`${item.kind}:${item.path}`}>
              {item.path} <span className="text-muted-foreground">({item.kind})</span>
            </li>
          ))}
        </Group>
        <Group sign="!" title="advertencias" count={warnings.length}>
          {warnings.map((item, index) => (
            <li key={`${item.path}:${index}`}>
              {item.path ? `${item.path}: ` : ""}
              {item.message}
            </li>
          ))}
        </Group>
      </ul>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancelar
        </Button>
        <Button type="button" onClick={onApply}>
          Aplicar
        </Button>
      </div>
    </div>
  );
}

export function ImportTab({ datasource, onApply }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [source, setSource] = useState<Source | null>(null);
  const [errors, setErrors] = useState<string[]>([]);

  const start = useMutation({
    mutationFn: async (request: { label: string; run: () => Promise<ImportPreview> }) => ({
      label: request.label,
      preview: await request.run(),
    }),
    onMutate: () => {
      setErrors([]);
      setSource(null);
    },
    onSuccess: setSource,
    onError: (error) => setErrors(describeError(error)),
  });

  function readFile(file: File | undefined) {
    if (!file) return;
    start.mutate({ label: file.name, run: () => previewImport(datasource.id, file) });
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    readFile(event.dataTransfer.files[0]);
  }

  return (
    <div className="flex flex-col gap-4">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-testid="zona-importar"
        className={`flex flex-col items-center gap-3 rounded-md border-2 border-dashed p-8 text-center text-sm ${
          dragging ? "border-primary bg-accent" : "border-border"
        }`}
      >
        <p>Arrastra un archivo .sql, .csv, .xlsx, .yaml o .json</p>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          aria-label="Archivo a importar"
          className="sr-only"
          onChange={(event) => {
            readFile(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        <div className="flex flex-wrap justify-center gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={start.isPending}
            onClick={() => input.current?.click()}
          >
            Elegir archivo
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={start.isPending}
            onClick={() =>
              start.mutate({
                label: "base conectada",
                run: () => previewIntrospection(datasource.id, datasource.name),
              })
            }
          >
            Leer desde la base conectada
          </Button>
        </div>
      </div>

      {start.isPending && <p className="text-sm text-muted-foreground">Leyendo…</p>}
      {errors.length > 0 && (
        <div role="alert" className="rounded-md border border-destructive p-3 text-sm">
          <ul className="flex flex-col gap-1">
            {errors.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {source && (
        <Preview
          source={source}
          onCancel={() => setSource(null)}
          onApply={() => {
            onApply(source.preview.model);
            setSource(null);
          }}
        />
      )}
    </div>
  );
}
