import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { useState } from "react";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/features/auth/AuthProvider";
import { listProviders, putRouting, type Provider, type Task } from "@/features/providers/api";
import { TASKS, formatLatency, initialRouting, taskLabel } from "@/features/providers/catalog";
import { listRuns, startRun, type EvalRun, type ProviderReport } from "./api";

const selectClass =
  "flex h-9 rounded-md border border-input bg-card px-3 py-1 text-sm disabled:opacity-50";
const DEFAULT_MAX_CALLS = 1000;

const percent = (fraction: number) => `${(fraction * 100).toFixed(1).replace(".", ",")} %`;
const dollars = (value: number) => `$ ${value.toFixed(4).replace(".", ",")}`;

function UseForTask({ provider, report }: { provider: Provider | undefined; report: ProviderReport }) {
  const queryClient = useQueryClient();
  const [task, setTask] = useState<Task>(TASKS[0].value);
  const assign = useMutation({
    mutationFn: async () => {
      if (!provider) throw new Error("El proveedor ya no existe.");
      // El enrutamiento se guarda completo: se parte de lo vigente y solo cambia esta tarea.
      const current = initialRouting((await listProviders()).filter((p) => p.managed_by !== "config"));
      return putRouting({ ...current, tasks: { ...current.tasks, [task]: provider.id } });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["providers"] }),
  });
  const editable = provider !== undefined && provider.managed_by !== "config";

  return (
    <div className="grid gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={`Tarea para ${report.proveedor}`}
          className={selectClass}
          value={task}
          onChange={(e) => setTask(e.target.value as Task)}
          disabled={!editable}
        >
          {TASKS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          variant="outline"
          disabled={!editable || assign.isPending}
          onClick={() => assign.mutate()}
          aria-label={`Usar ${report.proveedor} para esta tarea`}
        >
          Usar para esta tarea
        </Button>
      </div>
      {!editable && (
        <p className="text-xs text-muted-foreground">
          Se define en chatiapp.yaml: no se puede reasignar desde aquí.
        </p>
      )}
      {assign.isError && (
        <p role="alert" className="text-xs text-destructive">
          {assign.error.message}
        </p>
      )}
      {assign.isSuccess && (
        <p role="status" className="text-xs text-muted-foreground">
          {report.proveedor} atiende ahora la tarea «{taskLabel(task)}».
        </p>
      )}
    </div>
  );
}

function FailedCases({ report }: { report: ProviderReport }) {
  return (
    <details className="rounded-md border p-3">
      <summary className="cursor-pointer text-sm font-medium">
        {report.proveedor}: {report.fallidos.length} casos fallidos
      </summary>
      {report.fallidos.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">Ningún caso falló.</p>
      ) : (
        <ul className="mt-3 grid gap-3">
          {report.fallidos.map((f) => (
            <li key={f.id} className="grid gap-1.5 text-sm">
              <p>
                <span className="font-mono">{f.id}</span> — {f.motivo ?? "Sin motivo"}
              </p>
              <div className="grid gap-2 md:grid-cols-2">
                <div>
                  <p className="text-xs font-medium text-muted-foreground">SQL esperado</p>
                  <pre className="overflow-x-auto rounded-md bg-muted p-2 font-mono text-xs">
                    {f.sql_esperado ?? "—"}
                  </pre>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">SQL obtenido</p>
                  <pre className="overflow-x-auto rounded-md bg-muted p-2 font-mono text-xs">
                    {f.sql ?? "—"}
                  </pre>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function Results({ run, providers }: { run: EvalRun; providers: Provider[] }) {
  if (!run.report) return null;
  const rows = run.report.proveedores;
  const points = rows.map((r) => ({ name: r.proveedor, costo: r.costo_usd, exactitud: r.exactitud * 100 }));
  return (
    <section aria-labelledby="results-title" className="grid gap-4 rounded-xl border bg-card p-4">
      <h2 id="results-title" className="font-medium">
        Resultados · {run.report.set}
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Comparativa de modelos</caption>
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-2 pr-4 font-medium">Proveedor</th>
              <th className="py-2 pr-4 font-medium">Modelo</th>
              <th className="py-2 pr-4 font-medium">Exactitud</th>
              <th className="py-2 pr-4 font-medium">Latencia p50</th>
              <th className="py-2 pr-4 font-medium">Latencia p95</th>
              <th className="py-2 pr-4 font-medium">Costo</th>
              <th className="py-2 font-medium">Asignar</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.proveedor} className="border-b align-top last:border-0">
                <td className="py-2 pr-4 font-medium">{r.proveedor}</td>
                <td className="py-2 pr-4 font-mono text-xs">{r.modelo}</td>
                <td className="py-2 pr-4">
                  {percent(r.exactitud)} ({r.correctos}/{r.total})
                </td>
                <td className="py-2 pr-4">{formatLatency(r.latencia_ms.p50)}</td>
                <td className="py-2 pr-4">{formatLatency(r.latencia_ms.p95)}</td>
                <td className="py-2 pr-4">{dollars(r.costo_usd)}</td>
                <td className="py-2">
                  <UseForTask
                    report={r}
                    provider={providers.find(
                      (p) => p.id === run.providers.find((rp) => rp.name === r.proveedor)?.id,
                    )}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div
        role="img"
        aria-label={`Gráfico de exactitud frente a costo: ${points
          .map((p) => `${p.name} ${p.exactitud.toFixed(0)} % a ${dollars(p.costo)}`)
          .join("; ")}`}
        className="h-72 w-full"
      >
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="costo"
              name="Costo"
              tickFormatter={dollars}
              label={{ value: "Costo de la corrida (USD)", position: "bottom", fontSize: 12 }}
              tick={{ fontSize: 12 }}
            />
            <YAxis
              type="number"
              dataKey="exactitud"
              name="Exactitud"
              domain={[0, 100]}
              unit=" %"
              tick={{ fontSize: 12 }}
            />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} />
            <Scatter data={points} fill="#2563eb" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      <div className="grid gap-2">
        <h3 className="text-sm font-medium">Casos fallidos</h3>
        {rows.map((r) => (
          <FailedCases key={r.proveedor} report={r} />
        ))}
      </div>
    </section>
  );
}

export function EvaluationPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [maxCalls, setMaxCalls] = useState(String(DEFAULT_MAX_CALLS));

  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: listProviders });
  const providers = providersQuery.data ?? [];
  const hasReal = providers.some((p) => selected.includes(p.id) && p.kind !== "fake");
  const runsQuery = useQuery({
    queryKey: ["evals", "runs"],
    queryFn: listRuns,
    refetchInterval: (query) => (query.state.data?.some((r) => r.status === "running") ? 2000 : false),
  });
  const start = useMutation({
    mutationFn: () =>
      startRun({
        provider_ids: selected,
        ...(hasReal ? { max_calls: Number(maxCalls) } : {}),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["evals", "runs"] }),
  });

  const run = runsQuery.data?.[0];
  const running = run?.status === "running";

  if (!user?.is_admin) {
    return (
      <p className="text-sm text-muted-foreground">
        Solo los administradores pueden evaluar modelos.
      </p>
    );
  }

  return (
    <div className="grid gap-6">
      <header className="grid gap-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <FlaskConical aria-hidden className="size-5" /> Evaluación
        </h1>
        <p className="text-sm text-muted-foreground">
          Corre el set de preguntas de referencia con cada proveedor y compara exactitud, costo y
          latencia.
        </p>
      </header>

      <form
        className="grid gap-3 rounded-xl border bg-card p-4"
        onSubmit={(e) => {
          e.preventDefault();
          start.mutate();
        }}
      >
        <fieldset className="grid gap-2">
          <legend className="text-sm font-medium">Proveedores a evaluar</legend>
          {providers.length === 0 && (
            <p className="text-sm text-muted-foreground">Aún no hay proveedores configurados.</p>
          )}
          {providers.map((p) => (
            <label key={p.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={selected.includes(p.id)}
                onChange={(e) =>
                  setSelected((cur) => (e.target.checked ? [...cur, p.id] : cur.filter((i) => i !== p.id)))
                }
              />
              {p.name} <span className="font-mono text-xs text-muted-foreground">{p.model}</span>
            </label>
          ))}
        </fieldset>
        {hasReal && (
          <div className="grid max-w-xs gap-1.5">
            <label htmlFor="max-calls" className="text-sm font-medium">
              Tope de llamadas
            </label>
            <Input
              id="max-calls"
              type="number"
              min={1}
              value={maxCalls}
              onChange={(e) => setMaxCalls(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Los proveedores reales cobran por llamada: la corrida se detiene al llegar al tope.
            </p>
          </div>
        )}
        {start.isError && (
          <p role="alert" className="text-sm text-destructive">
            {start.error.message}
          </p>
        )}
        <div>
          <Button type="submit" disabled={selected.length === 0 || running || start.isPending}>
            {running ? "Evaluando…" : "Lanzar evaluación"}
          </Button>
        </div>
      </form>

      {run && run.status !== "done" && (
        <section aria-label="Progreso" className="grid gap-2 rounded-xl border bg-card p-4">
          {run.status === "running" ? (
            <>
              <p className="text-sm">
                Casos evaluados: {run.cases_done} de {run.cases_total}
              </p>
              <progress
                className="h-2 w-full"
                max={run.cases_total}
                value={run.cases_done}
                aria-label="Progreso de la evaluación"
              />
            </>
          ) : (
            <p role="alert" className="text-sm text-destructive">
              {run.error ?? "La evaluación falló."}
            </p>
          )}
        </section>
      )}

      {run?.status === "done" && <Results run={run} providers={providers} />}
    </div>
  );
}
