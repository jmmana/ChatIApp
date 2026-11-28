// Eventos SSE tipados de POST /api/v1/chat/stream (docs/FLUJO_CONVERSACIONAL.md).

export type StepStatus = "running" | "done" | "warning" | "error";
export type Scalar = string | number | boolean | null;

export interface PeriodData {
  label: string;
  start: string;
  end_exclusive: string;
}

export interface SqlData {
  sql: string;
  dialect: string;
  origin: "catalog" | "llm";
  summary_table?: string;
  filters_applied?: string[];
  period?: PeriodData;
  metric?: string;
}

export interface ResultData {
  columns: string[];
  rows: Scalar[][];
  row_count?: number;
  truncated: boolean;
  elapsed_ms?: number;
}

export interface ClarificationData {
  question: string;
  options?: string[];
  slot?: string;
}

export interface ErrorData {
  code: string;
  message: string;
  recoverable: boolean;
}

export interface UsageData {
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

export type TurnStartedEvent = { type: "turn.started"; data: { turn_id: string; conversation_id: string } };
export type StepEvent = {
  type: "step";
  data: { id: string; label: string; status: StepStatus; detail?: string };
};
export type ReasoningEvent = { type: "reasoning"; data: { text: string } };
export type ClarificationEvent = { type: "clarification"; data: ClarificationData };
export type SqlEvent = { type: "sql"; data: SqlData };
export type ResultEvent = { type: "result"; data: ResultData };
export type AnswerDeltaEvent = { type: "answer.delta"; data: { text: string } };
export type AnswerEvent = { type: "answer"; data: { text: string } };
export type ErrorEvent = { type: "error"; data: ErrorData };
export type TurnCompletedEvent = {
  type: "turn.completed";
  data: { usage: UsageData; elapsed_ms?: number };
};

export type StreamEvent =
  | TurnStartedEvent
  | StepEvent
  | ReasoningEvent
  | ClarificationEvent
  | SqlEvent
  | ResultEvent
  | AnswerDeltaEvent
  | AnswerEvent
  | ErrorEvent
  | TurnCompletedEvent;

const KNOWN = new Set<string>([
  "turn.started",
  "step",
  "reasoning",
  "clarification",
  "sql",
  "result",
  "answer.delta",
  "answer",
  "error",
  "turn.completed",
]);

/** Interpreta un flujo `text/event-stream` y emite los eventos conocidos (ignora los demás). */
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n?/g, "\n");
      let end = buffer.indexOf("\n\n");
      while (end !== -1) {
        const event = toEvent(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (event) yield event;
        end = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    const last = toEvent(buffer); // el servidor cerró sin la línea en blanco final
    if (last) yield last;
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}

function toEvent(block: string): StreamEvent | null {
  let type: string | null = null;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") type = value;
    else if (field === "data") data.push(value);
  }
  if (type === null || !KNOWN.has(type) || data.length === 0) return null;
  try {
    return { type, data: JSON.parse(data.join("\n")) } as StreamEvent;
  } catch {
    return null;
  }
}
