import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, Pencil, Plug, Star } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/AuthProvider";
import {
  getCatalog,
  listProviders,
  testSavedProvider,
  type CatalogEntry,
  type ProbeResult,
  type Provider,
} from "./api";
import { CATEGORIES, formatLatency, taskLabel } from "./catalog";
import { ProviderSheet } from "./ProviderSheet";
import { RoutingPanel } from "./RoutingPanel";
import { TestResultView } from "./TestResultView";

type Editing = { spec: CatalogEntry; provider?: Provider } | null;

function statusText(result: ProbeResult | undefined): string {
  if (!result) return "Sin probar";
  return result.ok ? `Conectado · ${formatLatency(result.latency_ms)}` : "Con error";
}

export function ProvidersPage() {
  const { user } = useAuth();
  const isAdmin = user?.is_admin ?? false;
  const [editing, setEditing] = useState<Editing>(null);
  // La API no guarda el resultado de la última prueba: se conserva mientras la página está abierta.
  const [results, setResults] = useState<Record<string, ProbeResult>>({});
  const [testingId, setTestingId] = useState<string | null>(null);

  const catalogQuery = useQuery({ queryKey: ["providers", "catalog"], queryFn: getCatalog });
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: listProviders });

  const test = useMutation({
    mutationFn: (id: string) => testSavedProvider(id),
    onMutate: (id) => setTestingId(id),
    onSuccess: (result, id) => setResults((current) => ({ ...current, [id]: result })),
    onError: (error, id) =>
      setResults((current) => ({
        ...current,
        [id]: { ok: false, latency_ms: 0, error_kind: "provider_error", message: error.message },
      })),
    onSettled: () => setTestingId(null),
  });

  const catalog = catalogQuery.data ?? [];
  const providers = providersQuery.data ?? [];
  const specOf = (kind: string) => catalog.find((c) => c.kind === kind);

  function edit(provider: Provider) {
    const spec = specOf(provider.kind);
    if (spec) setEditing({ spec, provider });
  }

  return (
    <section className="mx-auto grid max-w-5xl gap-6">
      <header className="grid gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Proveedores de IA</h1>
        <p className="text-muted-foreground">
          Configura los modelos que usa ChatIApp y pruébalos antes de guardar.
        </p>
      </header>

      {(providersQuery.isPending || catalogQuery.isPending) && (
        <p className="text-muted-foreground">Cargando proveedores…</p>
      )}
      {(providersQuery.isError || catalogQuery.isError) && (
        <p role="alert" className="text-destructive">
          No se pudieron cargar los proveedores de IA.
        </p>
      )}

      {providersQuery.isSuccess && (
        <section aria-labelledby="configured-title" className="grid gap-3">
          <h2 id="configured-title" className="text-sm font-medium text-muted-foreground">
            CONFIGURADOS
          </h2>
          {providers.length === 0 && (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed py-12 text-center">
              <Bot className="size-6 text-muted-foreground" aria-hidden />
              <p className="text-muted-foreground">Todavía no hay proveedores configurados.</p>
            </div>
          )}
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {providers.map((p) => {
              const result = results[p.id];
              return (
                <li
                  key={p.id}
                  aria-label={p.name}
                  className="grid content-start gap-3 rounded-xl border bg-card p-4 text-card-foreground"
                >
                  <div className="grid gap-1">
                    <h3 className="flex items-center gap-1.5 font-medium">
                      {p.is_default && (
                        <Star
                          className="size-4 fill-current text-amber-500"
                          role="img"
                          aria-label="Predeterminado"
                        />
                      )}
                      {p.name}
                    </h3>
                    <p className="break-all font-mono text-xs text-muted-foreground">{p.model}</p>
                    <p className="text-sm">
                      <span aria-hidden>● </span>
                      {statusText(result)}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {p.tasks.map((t) => (
                      <Badge key={t} variant="accent">
                        {taskLabel(t)}
                      </Badge>
                    ))}
                    {typeof p.params.fallback === "number" && (
                      <Badge variant="outline">Respaldo {p.params.fallback + 1}</Badge>
                    )}
                    {p.managed_by === "config" && (
                      <Badge variant="secondary">gestionado por configuración</Badge>
                    )}
                  </div>
                  {result && <TestResultView result={result} />}
                  {isAdmin && (
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={testingId === p.id}
                        onClick={() => test.mutate(p.id)}
                        aria-label={`Probar conexión de ${p.name}`}
                      >
                        <Plug aria-hidden /> {testingId === p.id ? "Probando…" : "Probar conexión"}
                      </Button>
                      {p.managed_by !== "config" && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => edit(p)}
                          aria-label={`Editar ${p.name}`}
                        >
                          <Pencil aria-hidden /> Editar
                        </Button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {isAdmin && providersQuery.isSuccess && <RoutingPanel providers={providers} />}

      {isAdmin && catalogQuery.isSuccess && (
        <section aria-labelledby="gallery-title" className="grid gap-3">
          <h2 id="gallery-title" className="text-sm font-medium text-muted-foreground">
            AGREGAR
          </h2>
          {CATEGORIES.map((category) => (
            <div key={category.value} role="group" aria-label={category.label} className="grid gap-2">
              <h3 className="text-sm font-medium">{category.label}</h3>
              <div className="flex flex-wrap gap-2">
                {catalog
                  .filter((c) => c.category === category.value)
                  .map((spec) => (
                    <Button
                      key={spec.kind}
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing({ spec })}
                    >
                      {spec.label}
                    </Button>
                  ))}
              </div>
            </div>
          ))}
        </section>
      )}

      {editing && (
        <ProviderSheet
          key={editing.provider?.id ?? editing.spec.kind}
          spec={editing.spec}
          provider={editing.provider}
          onTested={(id, result) => setResults((current) => ({ ...current, [id]: result }))}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  );
}
