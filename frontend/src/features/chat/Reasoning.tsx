import { AlertTriangle, Check, ChevronRight, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import type { StepData, StepStatus } from "./types";

interface ReasoningProps {
  steps: StepData[];
  reasoning: string | null;
  /** El turno sigue en curso: el bloque se mantiene abierto. */
  streaming: boolean;
}

const STATUS_LABEL: Record<StepStatus, string> = {
  running: "En curso",
  done: "Listo",
  warning: "Advertencia",
  error: "Error",
};

function StepIcon({ status }: { status: StepStatus }): ReactNode {
  // `motion-reduce:animate-none` respeta prefers-reduced-motion.
  const base = "size-4 shrink-0";
  switch (status) {
    case "running":
      return <Loader2 aria-hidden className={`${base} animate-spin motion-reduce:animate-none`} />;
    case "done":
      return <Check aria-hidden className={`${base} text-primary`} />;
    case "warning":
      return <AlertTriangle aria-hidden className={`${base} text-amber-600`} />;
    case "error":
      return <XCircle aria-hidden className={`${base} text-destructive`} />;
  }
}

/** Resumen de una línea para el bloque plegado. */
export function summarizeSteps(steps: StepData[]): string {
  const count = steps.length;
  const parts = [count === 1 ? "1 paso" : `${count} pasos`];
  const warnings = steps.filter((s) => s.status === "warning").length;
  const errors = steps.filter((s) => s.status === "error").length;
  if (warnings) parts.push(warnings === 1 ? "1 advertencia" : `${warnings} advertencias`);
  if (errors) parts.push(errors === 1 ? "1 error" : `${errors} errores`);
  return parts.join(" · ");
}

export function Reasoning({ steps, reasoning, streaming }: ReasoningProps) {
  // `null` = sin decisión de la persona: abierto mientras dura el turno, plegado al final.
  const [manual, setManual] = useState<boolean | null>(null);
  if (steps.length === 0 && !reasoning) return null;
  const open = manual ?? streaming;
  const summary = summarizeSteps(steps);

  return (
    <section aria-label="Razonamiento" className="rounded-lg border bg-card text-sm">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setManual(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted-foreground"
      >
        <ChevronRight
          aria-hidden
          className={`size-4 shrink-0 transition-transform motion-reduce:transition-none ${open ? "rotate-90" : ""}`}
        />
        <span>{streaming ? "Razonando…" : `Razonamiento: ${summary}`}</span>
      </button>
      <div aria-live="polite" className="px-3 pb-3">
        {open && (
          <>
            <ol className="flex flex-col gap-1.5">
              {steps.map((step) => (
                <li key={step.id} className="flex items-start gap-2">
                  <StepIcon status={step.status} />
                  <span>
                    {step.label}
                    <span className="sr-only"> ({STATUS_LABEL[step.status]})</span>
                    {step.detail && <span className="text-muted-foreground"> — {step.detail}</span>}
                  </span>
                </li>
              ))}
            </ol>
            {reasoning && (
              <p className="mt-2 whitespace-pre-wrap border-l-2 pl-3 text-muted-foreground">
                {reasoning}
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}
