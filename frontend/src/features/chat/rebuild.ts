import type { StoredMessage } from "./api";
import { initialTurnState, turnReducer } from "./turnReducer";
import type { TurnState } from "./turnReducer";
import { TURN_EVENT_TYPES } from "./types";
import type { TurnEvent } from "./types";

export interface Message {
  question: string;
  turn: TurnState;
}

function isTurnEvent(event: { type: string }): event is TurnEvent {
  return (TURN_EVENT_TYPES as readonly string[]).includes(event.type);
}

/** Reconstruye el estado de un turno reproduciendo sus eventos guardados. */
export function turnFromEvents(
  events: { type: string; data: unknown }[] | null | undefined,
  fallbackText: string,
): TurnState {
  let state = initialTurnState;
  for (const event of events ?? []) {
    if (isTurnEvent(event)) state = turnReducer(state, event);
  }
  if (!state.answer && !state.clarification && !state.error && fallbackText) {
    state = { ...state, answer: fallbackText, answerFinal: true };
  }
  if (state.status === "streaming" || state.status === "idle") {
    state = { ...state, status: "completed" };
  }
  return state;
}

/** Empareja cada pregunta con la respuesta del asistente que le sigue. */
export function messagesFromStored(messages: StoredMessage[]): Message[] {
  const result: Message[] = [];
  messages.forEach((message, index) => {
    if (message.role !== "user") return;
    const reply = messages[index + 1];
    const turn =
      reply?.role === "assistant"
        ? turnFromEvents(reply.events, reply.content)
        : turnFromEvents(null, "");
    result.push({ question: message.content, turn });
  });
  return result;
}
