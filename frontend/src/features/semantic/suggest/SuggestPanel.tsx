import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import type { SemanticModel } from "../types";
import {
  applySuggestions,
  canApply,
  FIELD_LABELS,
  formatValue,
  requestSuggestions,
  suggestionKey,
  type Suggestion,
} from "./suggest";

interface Props {
  datasourceId: string;
  model: SemanticModel;
  onChange: (model: SemanticModel) => void;
}

/** «Sugerir con IA»: la IA propone lo que está vacío y el analista acepta o descarta. */
export function SuggestPanel({ datasourceId, model, onChange }: Props) {
  const [pending, setPending] = useState<Suggestion[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const request = useMutation({
    mutationFn: () => requestSuggestions(datasourceId),
    onMutate: () => setFailure(null),
    onSuccess: (list) => setPending(list),
    onError: (error) => {
      setPending(null);
      setFailure(
        error instanceof ApiError ? error.message : "No se pudieron obtener las sugerencias.",
      );
    },
  });

  function settle(accepted: Suggestion[], resolved: Suggestion[]) {
    if (accepted.length > 0) onChange(applySuggestions(model, accepted));
    const keys = new Set(resolved.map(suggestionKey));
    setPending((list) => (list ?? []).filter((item) => !keys.has(suggestionKey(item))));
  }

  const list = pending ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          disabled={request.isPending}
          onClick={() => request.mutate()}
        >
          <Sparkles aria-hidden />
          {request.isPending ? "Pensando…" : "Sugerir con IA"}
        </Button>
        <p className="text-sm text-muted-foreground">
          La IA solo propone para campos vacíos; tú decides qué aceptar.
        </p>
      </div>
      {failure && (
        <p role="alert" className="rounded-md border border-destructive p-3 text-sm">
          {failure}
        </p>
      )}
      {pending !== null && list.length === 0 && !failure && (
        <p role="status" className="text-sm text-muted-foreground">
          No hay sugerencias pendientes.
        </p>
      )}
      {list.length > 0 && (
        <section aria-label="Sugerencias de la IA" className="rounded-md border p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">
              {list.length === 1 ? "1 sugerencia" : `${list.length} sugerencias`}
            </h2>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => settle(list.filter((s) => canApply(model, s)), list)}
              >
                Aceptar todas
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => settle([], list)}>
                Descartar todas
              </Button>
            </div>
          </div>
          <ul className="flex flex-col divide-y">
            {list.map((item) => {
              const label = `${FIELD_LABELS[item.field]} de ${item.path}`;
              const applicable = canApply(model, item);
              return (
                <li key={suggestionKey(item)} className="flex flex-wrap items-center gap-3 py-2">
                  <div className="min-w-0 flex-1 text-sm">
                    <p className="font-medium">{label}</p>
                    <p>{formatValue(item)}</p>
                    <p className="text-xs text-muted-foreground">
                      Confianza {Math.round(item.confidence * 100)} %
                      {!applicable && " · el campo ya tiene valor"}
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    disabled={!applicable}
                    aria-label={`Aceptar ${label}`}
                    onClick={() => settle([item], [item])}
                  >
                    Aceptar
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label={`Descartar ${label}`}
                    onClick={() => settle([], [item])}
                  >
                    Descartar
                  </Button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
