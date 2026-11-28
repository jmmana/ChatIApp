import { Button } from "@/components/ui/button";
import { Clarification } from "./Clarification";
import { Reasoning } from "./Reasoning";
import { ResultView } from "./results/ResultView";
import { SqlBlock } from "./SqlBlock";
import type { TurnState } from "./turnReducer";

export interface ResultFormat {
  locale?: string;
  currency?: string;
  metricLabels: Record<string, string>;
}

interface ExchangeProps {
  question: string;
  turn: TurnState;
  onOption?: (option: string) => void;
  onRetry?: () => void;
  format: ResultFormat;
  live?: boolean;
  /** El chat embebido puede ocultar el detalle técnico (sigue en la auditoría). */
  showSql?: boolean;
  showReasoning?: boolean;
  thinkingLabel?: string;
}

/** Una pregunta con todo lo que el turno fue emitiendo: razonamiento, SQL, resultado y texto. */
export function Exchange({
  question,
  turn,
  onOption,
  onRetry,
  format,
  live = false,
  showSql = true,
  showReasoning = true,
  thinkingLabel = "Pensando…",
}: ExchangeProps) {
  const text = turn.answer || turn.clarification?.question || "";
  return (
    <article className="flex flex-col gap-3">
      <p className="self-end rounded-xl bg-accent px-3 py-2 text-accent-foreground">{question}</p>
      {showReasoning && (
        <Reasoning
          steps={turn.steps}
          reasoning={turn.reasoning}
          streaming={turn.status === "streaming"}
        />
      )}
      {turn.status === "streaming" && !text && turn.steps.length === 0 && (
        <p role="status" className="text-sm text-muted-foreground">
          {thinkingLabel}
        </p>
      )}
      {showSql && turn.sql && <SqlBlock sql={turn.sql} streaming={turn.status === "streaming"} />}
      {turn.result && <ResultView result={turn.result} sql={turn.sql} {...format} />}
      {text && <p className="whitespace-pre-wrap">{text}</p>}
      {live && turn.status === "clarifying" && turn.clarification && (
        <Clarification
          question={turn.clarification.question}
          options={turn.clarification.options}
          onSelect={(option) => onOption?.(option)}
        />
      )}
      {turn.status === "error" && turn.error && (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-destructive">
            {turn.error.message}
          </p>
          {live && turn.error.recoverable && onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              Reintentar
            </Button>
          )}
        </div>
      )}
    </article>
  );
}
