// Eventos del stream del turno: docs/FLUJO_CONVERSACIONAL.md#eventos-de-streaming

export type StepStatus = "running" | "done" | "warning" | "error";

export interface TurnStartedData {
  turn_id: string;
  conversation_id: string;
}

export interface StepData {
  id: string;
  label: string;
  status: StepStatus;
  detail?: string;
}

export interface ReasoningData {
  text: string;
}

export interface ClarificationData {
  question: string;
  options: string[];
  slot: string;
}

export interface SqlData {
  sql: string;
  dialect: string;
  origin: "catalog" | "llm";
  summary_table?: string | null;
  filters_applied: string[];
  period?: { label: string; start: string; end_exclusive: string } | null;
  /** Nombre de la métrica del plan; solo cuando el SQL sale del catálogo. */
  metric?: string | null;
}

export interface ResultData {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
}

export interface AnswerDeltaData {
  text: string;
}

export interface AnswerData {
  text: string;
}

export interface ErrorData {
  code: string;
  message: string;
  recoverable: boolean;
}

export interface Usage {
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

export interface TurnCompletedData {
  usage: Usage;
  elapsed_ms: number;
}

export type TurnEvent =
  | { type: "turn.started"; data: TurnStartedData }
  | { type: "step"; data: StepData }
  | { type: "reasoning"; data: ReasoningData }
  | { type: "clarification"; data: ClarificationData }
  | { type: "sql"; data: SqlData }
  | { type: "result"; data: ResultData }
  | { type: "answer.delta"; data: AnswerDeltaData }
  | { type: "answer"; data: AnswerData }
  | { type: "error"; data: ErrorData }
  | { type: "turn.completed"; data: TurnCompletedData };

export type TurnEventType = TurnEvent["type"];

export const TURN_EVENT_TYPES: readonly TurnEventType[] = [
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
];

export interface ChatRequest {
  conversation_id?: string | null;
  datasource_id: string;
  message: string;
  provider_override?: string | null;
  view_as?: { role: string; attributes?: Record<string, unknown> } | null;
}
