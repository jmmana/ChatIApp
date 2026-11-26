import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Pencil, Plus, Plug } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/features/auth/AuthProvider";
import {
  createDatasource,
  listDatasources,
  testDatasource,
  updateDatasource,
  type Datasource,
  type DatasourceInput,
  type TestResult,
} from "./api";
import { dialectLabel, privacyLabel } from "./catalog";
import { DatasourceForm } from "./DatasourceForm";
import { TestResultView } from "./TestResultView";

type Editing = { mode: "create" } | { mode: "edit"; datasource: Datasource } | null;

export function DatasourcesPage() {
  const { user } = useAuth();
  const isAdmin = user?.is_admin ?? false;
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Editing>(null);
  // La API no guarda el resultado de la última prueba: se conserva mientras la página está abierta.
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const [testingId, setTestingId] = useState<string | null>(null);

  const query = useQuery({ queryKey: ["datasources"], queryFn: listDatasources });

  const save = useMutation({
    mutationFn: (input: DatasourceInput) =>
      editing?.mode === "edit"
        ? updateDatasource(editing.datasource.id, input)
        : createDatasource(input),
    onSuccess: async () => {
      setEditing(null);
      await queryClient.invalidateQueries({ queryKey: ["datasources"] });
    },
  });

  const test = useMutation({
    mutationFn: (id: string) => testDatasource(id),
    onMutate: (id) => setTestingId(id),
    onSuccess: (result, id) => setResults((current) => ({ ...current, [id]: result })),
    onError: (error, id) =>
      setResults((current) => ({
        ...current,
        [id]: {
          ok: false,
          latency_ms: null,
          server_version: null,
          error: { kind: "unknown", message: error.message },
        },
      })),
    onSettled: () => setTestingId(null),
  });

  function openEditor(next: Editing) {
    save.reset();
    setEditing(next);
  }

  const datasources = query.data ?? [];

  return (
    <section className="mx-auto grid max-w-5xl gap-6">
      <header className="flex items-start justify-between gap-4">
        <div className="grid gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Fuentes de datos</h1>
          <p className="text-muted-foreground">
            Conecta las bases de datos que ChatIApp puede consultar.
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => openEditor({ mode: "create" })}>
            <Plus aria-hidden /> Nueva fuente
          </Button>
        )}
      </header>

      {query.isPending && <p className="text-muted-foreground">Cargando fuentes de datos…</p>}
      {query.isError && (
        <p role="alert" className="text-destructive">
          No se pudieron cargar las fuentes de datos.
        </p>
      )}
      {query.isSuccess && datasources.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed py-16 text-center">
          <Database className="size-6 text-muted-foreground" aria-hidden />
          <p className="text-muted-foreground">Todavía no hay fuentes de datos.</p>
        </div>
      )}

      <ul className="grid gap-3">
        {datasources.map((ds) => (
          <li
            key={ds.id}
            aria-label={ds.name}
            className="grid gap-3 rounded-xl border bg-card p-4 text-card-foreground"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="grid gap-1">
                <h2 className="font-medium">{ds.name}</h2>
                <p className="break-all font-mono text-xs text-muted-foreground">{ds.url}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{dialectLabel(ds.dialect)}</Badge>
                <Badge variant={ds.execute ? "accent" : "secondary"}>
                  {ds.execute ? "Ejecuta" : "Solo SQL"}
                </Badge>
                <Badge variant="outline">Privacidad: {privacyLabel(ds.privacy)}</Badge>
                {ds.managed_by === "config" && (
                  <Badge variant="secondary">gestionada por configuración</Badge>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">
                Última prueba:{" "}
                {results[ds.id] ? (results[ds.id].ok ? "correcta" : "con error") : "sin probar"}
              </p>
              {isAdmin && (
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={testingId === ds.id}
                    onClick={() => test.mutate(ds.id)}
                    aria-label={`Probar conexión de ${ds.name}`}
                  >
                    <Plug aria-hidden /> {testingId === ds.id ? "Probando…" : "Probar conexión"}
                  </Button>
                  {ds.managed_by !== "config" && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => openEditor({ mode: "edit", datasource: ds })}
                      aria-label={`Editar ${ds.name}`}
                    >
                      <Pencil aria-hidden /> Editar
                    </Button>
                  )}
                </div>
              )}
            </div>

            {results[ds.id] && <TestResultView result={results[ds.id]} />}
          </li>
        ))}
      </ul>

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editing?.mode === "edit" ? "Editar fuente de datos" : "Nueva fuente de datos"}
            </DialogTitle>
            <DialogDescription>
              La URL se guarda cifrada y nunca se vuelve a mostrar completa.
            </DialogDescription>
          </DialogHeader>
          {editing && (
            <DatasourceForm
              key={editing.mode === "edit" ? editing.datasource.id : "nueva"}
              datasource={editing.mode === "edit" ? editing.datasource : undefined}
              saving={save.isPending}
              error={save.error?.message ?? null}
              onSubmit={(input) => save.mutate(input)}
              onCancel={() => setEditing(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}
