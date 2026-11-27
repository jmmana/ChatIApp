import type {
  ClarificationData,
  ErrorData,
  ResultData,
  SqlData,
  StepData,
  TurnCompletedData,
  TurnEvent,
} from "./types";

export type TurnStatus = "idle" | "streaming" | "clarifying" | "completed" | "error";

export interface TurnState {
  status: TurnStatus;
  turnId: string | null;
  conversationId: string | null;
  steps: StepData[];
  reasoning: string | null;
  clarification: ClarificationData | null;
  sql: SqlData | null;
  result: ResultData | null;
  /** Texto en vivo (deltas) hasta que llega `answer`. */
  answer: string;
  answerFinal: boolean;
  error: ErrorData | null;
  completed: TurnCompletedData | null;
}

/** Acciones locales (no vienen del servidor). */
export type TurnAction =
  | TurnEvent
  | { type: "client.start" }
  | { type: "client.network_error"; message: string }
  | { type: "client.reset" };

export const initialTurnState: TurnState = {
  status: "idle",
  turnId: null,
  conversationId: null,
  steps: [],
  reasoning: null,
  clarification: null,
  sql: null,
  result: null,
  answer: "",
  answerFinal: false,
  error: null,
  completed: null,
};

export function turnReducer(state: TurnState, event: TurnAction): TurnState {
  switch (event.type) {
    case "client.start":
      return { ...initialTurnState, status: "streaming" };
    case "client.reset":
      return initialTurnState;
    case "client.network_error":
      return {
        ...state,
        status: "error",
        error: { code: "network_error", message: event.message, recoverable: true },
      };
    case "turn.started":
      return {
        ...initialTurnState,
        status: "streaming",
        turnId: event.data.turn_id,
        conversationId: event.data.conversation_id,
      };
    case "step": {
      const exists = state.steps.some((s) => s.id === event.data.id);
      const steps = exists
        ? state.steps.map((s) => (s.id === event.data.id ? { ...s, ...event.data } : s))
        : [...state.steps, event.data];
      return { ...state, steps };
    }
    case "reasoning":
      return { ...state, reasoning: event.data.text };
    case "clarification":
      return { ...state, clarification: event.data, status: "clarifying" };
    case "sql":
      return { ...state, sql: event.data };
    case "result":
      return { ...state, result: event.data };
    case "answer.delta":
      // Tras `answer` el texto ya es definitivo: un delta tardío no lo altera.
      return state.answerFinal ? state : { ...state, answer: state.answer + event.data.text };
    case "answer":
      return { ...state, answer: event.data.text, answerFinal: true };
    case "error":
      return { ...state, status: "error", error: event.data };
    case "turn.completed":
      return {
        ...state,
        status: state.status === "clarifying" ? "clarifying" : "completed",
        completed: event.data,
      };
  }
}
