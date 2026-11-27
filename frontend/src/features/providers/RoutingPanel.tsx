import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { putRouting, type Provider } from "./api";
import { TASKS, initialRouting } from "./catalog";

const selectClass =
  "flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm disabled:opacity-50";

export function RoutingPanel({ providers }: { providers: Provider[] }) {
  const queryClient = useQueryClient();
  const editable = providers.filter((p) => p.managed_by !== "config");
  const initial = initialRouting(editable);
  const [tasks, setTasks] = useState(initial.tasks);
  const [fallback, setFallback] = useState(initial.fallback);

  const save = useMutation({
    mutationFn: () => putRouting({ tasks, fallback }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["providers"] }),
  });

  const nameOf = (id: string) => editable.find((p) => p.id === id)?.name ?? id;
  const available = editable.filter((p) => !fallback.includes(p.id));

  function move(index: number, delta: number) {
    setFallback((current) => {
      const next = [...current];
      [next[index], next[index + delta]] = [next[index + delta], next[index]];
      return next;
    });
  }

  if (editable.length === 0) return null;

  return (
    <section aria-labelledby="routing-title" className="grid gap-4 rounded-xl border bg-card p-4">
      <div className="grid gap-1">
        <h2 id="routing-title" className="font-medium">
          Tareas y respaldo
        </h2>
        <p className="text-sm text-muted-foreground">
          Elige qué proveedor atiende cada tarea y el orden de respaldo si uno falla. Sin
          asignación, responde el predeterminado.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {TASKS.map((task) => (
          <div key={task.value} className="grid gap-1.5">
            <label htmlFor={`task-${task.value}`} className="text-sm font-medium">
              {task.label}
            </label>
            <select
              id={`task-${task.value}`}
              className={selectClass}
              value={tasks[task.value] ?? ""}
              onChange={(e) =>
                setTasks((current) => {
                  const next = { ...current };
                  if (e.target.value) next[task.value] = e.target.value;
                  else delete next[task.value];
                  return next;
                })
              }
            >
              <option value="">Predeterminado</option>
              {editable.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">{task.help}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-2">
        <h3 className="text-sm font-medium">Cadena de respaldo</h3>
        {fallback.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin respaldo configurado.</p>
        ) : (
          <ol className="grid gap-2" aria-label="Cadena de respaldo">
            {fallback.map((id, index) => (
              <li key={id} className="flex items-center justify-between gap-2 rounded-md border p-2">
                <span className="text-sm">
                  {index + 1}. {nameOf(id)}
                </span>
                <span className="flex gap-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                    aria-label={`Subir ${nameOf(id)}`}
                  >
                    <ArrowUp aria-hidden />
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={index === fallback.length - 1}
                    onClick={() => move(index, 1)}
                    aria-label={`Bajar ${nameOf(id)}`}
                  >
                    <ArrowDown aria-hidden />
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setFallback((current) => current.filter((i) => i !== id))}
                    aria-label={`Quitar ${nameOf(id)} del respaldo`}
                  >
                    <X aria-hidden />
                  </Button>
                </span>
              </li>
            ))}
          </ol>
        )}
        {available.length > 0 && (
          <div className="grid gap-1.5">
            <label htmlFor="fallback-add" className="text-sm font-medium">
              Agregar al respaldo
            </label>
            <select
              id="fallback-add"
              className={selectClass}
              value=""
              onChange={(e) => e.target.value && setFallback((c) => [...c, e.target.value])}
            >
              <option value="">Elige un proveedor…</option>
              {available.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {save.isError && (
        <p role="alert" className="text-sm text-destructive">
          {save.error.message}
        </p>
      )}
      {save.isSuccess && (
        <p role="status" className="text-sm text-muted-foreground">
          Asignación guardada.
        </p>
      )}
      <div className="flex justify-end">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? "Guardando…" : "Guardar asignación"}
        </Button>
      </div>
    </section>
  );
}
