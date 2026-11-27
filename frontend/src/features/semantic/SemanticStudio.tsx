import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api";
import {
  getSemantic,
  issuesFrom,
  listDatasources,
  publishSemantic,
} from "./api";
import { ContextTab } from "./ContextTab";
import { groupIssues, type FieldErrors } from "./errors";
import { MetricsTab } from "./metrics/MetricsTab";
import { RelationsTab } from "./RelationsTab";
import { selectClass } from "./styles";
import { SummaryTab } from "./summary/SummaryTab";
import { TablesTab } from "./TablesTab";
import type { Datasource, SemanticModel, SemanticVersion } from "./types";
import { VersionHistory } from "./VersionHistory";

function emptyModel(datasource: Datasource): SemanticModel {
  return { version: 1, name: datasource.name, dialect: datasource.dialect };
}

function Editor({
  datasource,
  initial,
  onReload,
}: {
  datasource: Datasource;
  initial: SemanticVersion | null;
  onReload: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [baseline, setBaseline] = useState(
    () => initial?.model ?? emptyModel(datasource),
  );
  const [draft, setDraft] = useState(baseline);
  const [baseVersion, setBaseVersion] = useState(initial?.version ?? 0);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [conflict, setConflict] = useState<number | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);

  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  const errorCount = Object.values(errors).reduce(
    (sum, list) => sum + list.length,
    0,
  );

  const publish = useMutation({
    mutationFn: () => publishSemantic(datasource.id, baseVersion, draft),
    onMutate: () => {
      setErrors({});
      setConflict(null);
      setFailure(null);
    },
    onSuccess: (published) => {
      setBaseline(published.model);
      setDraft(published.model);
      setBaseVersion(published.version);
      void queryClient.invalidateQueries({
        queryKey: ["semantic-versions", datasource.id],
      });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) {
        setErrors(groupIssues(issuesFrom(error)));
      } else if (error instanceof ApiError && error.status === 409) {
        setConflict(Number(error.details.current_version ?? 0));
      } else {
        setFailure(
          error instanceof Error
            ? error.message
            : "No se pudo publicar el modelo.",
        );
      }
    },
  });

  async function reload() {
    setReloading(true);
    try {
      await onReload();
    } finally {
      setReloading(false);
    }
  }

  let status = "sin versión publicada";
  if (baseVersion > 0)
    status = `v${baseVersion} · ${dirty ? "cambios sin publicar" : "guardado"}`;
  else if (dirty) status = "cambios sin publicar";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p aria-live="polite" className="text-sm text-muted-foreground">
          {status}
        </p>
        <Button
          type="button"
          disabled={publish.isPending || (!dirty && baseVersion > 0)}
          onClick={() => publish.mutate()}
        >
          {publish.isPending ? "Publicando…" : "Publicar"}
        </Button>
      </div>

      {conflict !== null && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-md border border-destructive p-3 text-sm"
        >
          <span>
            Alguien publicó la versión {conflict} antes que tú. Recarga el
            modelo para ver los cambios; los tuyos sin publicar se descartarán.
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={reloading}
            onClick={reload}
          >
            Recargar
          </Button>
        </div>
      )}
      {errorCount > 0 && (
        <p
          role="alert"
          className="rounded-md border border-destructive p-3 text-sm"
        >
          El modelo no se publicó: corrige{" "}
          {errorCount === 1 ? "el error" : `los ${errorCount} errores`} marcados
          junto a cada campo.
        </p>
      )}
      {failure && (
        <p
          role="alert"
          className="rounded-md border border-destructive p-3 text-sm"
        >
          {failure}
        </p>
      )}

      <Tabs defaultValue="tablas">
        <TabsList>
          <TabsTrigger value="contexto">Contexto</TabsTrigger>
          <TabsTrigger value="tablas">Tablas</TabsTrigger>
          <TabsTrigger value="relaciones">Relaciones</TabsTrigger>
          <TabsTrigger value="metricas">Métricas</TabsTrigger>
          <TabsTrigger value="resumidas">Resumidas</TabsTrigger>
          <TabsTrigger value="historial">Historial</TabsTrigger>
        </TabsList>
        <TabsContent value="contexto" className="mt-4">
          <ContextTab model={draft} errors={errors} onChange={setDraft} />
        </TabsContent>
        <TabsContent value="tablas" className="mt-4">
          <TablesTab model={draft} errors={errors} onChange={setDraft} />
        </TabsContent>
        <TabsContent value="relaciones" className="mt-4">
          <RelationsTab model={draft} errors={errors} onChange={setDraft} />
        </TabsContent>
        <TabsContent value="metricas" className="mt-4">
          <MetricsTab
            model={draft}
            errors={errors}
            datasourceId={datasource.id}
            dialect={datasource.dialect}
            onChange={setDraft}
          />
        </TabsContent>
        <TabsContent value="resumidas" className="mt-4">
          <SummaryTab model={draft} errors={errors} onChange={setDraft} />
        </TabsContent>
        <TabsContent value="historial" className="mt-4">
          <VersionHistory datasourceId={datasource.id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Loaded({ datasource }: { datasource: Datasource }) {
  const queryClient = useQueryClient();
  const [generation, setGeneration] = useState(0);
  const semantic = useQuery({
    queryKey: ["semantic", datasource.id],
    queryFn: () => getSemantic(datasource.id),
    retry: false,
    refetchOnWindowFocus: false,
  });

  if (semantic.isPending)
    return <p className="text-sm text-muted-foreground">Cargando…</p>;
  if (semantic.isError) {
    const forbidden =
      semantic.error instanceof ApiError && semantic.error.status === 403;
    return (
      <p role="alert" className="text-sm text-destructive">
        {forbidden
          ? "Solo los administradores pueden ver y editar el modelo semántico."
          : "No se pudo cargar el modelo semántico."}
      </p>
    );
  }

  async function reload() {
    await queryClient.refetchQueries({ queryKey: ["semantic", datasource.id] });
    await queryClient.invalidateQueries({
      queryKey: ["semantic-versions", datasource.id],
    });
    setGeneration((value) => value + 1);
  }

  return (
    <Editor
      key={`${datasource.id}:${generation}`}
      datasource={datasource}
      initial={semantic.data}
      onReload={reload}
    />
  );
}

export function SemanticStudio() {
  const datasources = useQuery({
    queryKey: ["datasources"],
    queryFn: listDatasources,
  });
  const [chosen, setChosen] = useState<string | null>(null);
  const list = datasources.data ?? [];
  const datasource = list.find((item) => item.id === chosen) ?? list[0];

  return (
    <section className="mx-auto flex max-w-6xl flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">
          Modelo semántico
        </h1>
        {list.length > 1 && datasource && (
          <select
            aria-label="Fuente de datos"
            className={`${selectClass} w-auto`}
            value={datasource.id}
            onChange={(event) => setChosen(event.target.value)}
          >
            {list.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        )}
        {list.length === 1 && (
          <p className="text-sm text-muted-foreground">{list[0].name}</p>
        )}
      </header>
      {datasources.isPending && (
        <p className="text-sm text-muted-foreground">Cargando…</p>
      )}
      {datasources.isError && (
        <p role="alert" className="text-sm text-destructive">
          No se pudieron cargar las fuentes de datos.
        </p>
      )}
      {datasources.isSuccess && !datasource && (
        <p className="text-sm text-muted-foreground">
          Aún no hay fuentes de datos: conecta una para describir su modelo.
        </p>
      )}
      {datasource && <Loaded key={datasource.id} datasource={datasource} />}
    </section>
  );
}
