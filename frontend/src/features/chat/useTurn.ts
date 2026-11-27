import { useCallback, useEffect, useReducer, useRef } from "react";
import { streamTurn } from "./sse";
import { initialTurnState, turnReducer } from "./turnReducer";
import type { ChatRequest } from "./types";

/** Ejecuta un turno por SSE; `retry` repite la última petición tras un error recuperable. */
export function useTurn() {
  const [state, dispatch] = useReducer(turnReducer, initialTurnState);
  const controller = useRef<AbortController | null>(null);
  const lastRequest = useRef<ChatRequest | null>(null);

  const cancel = useCallback(() => controller.current?.abort(), []);

  const send = useCallback(async (request: ChatRequest) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    lastRequest.current = request;
    dispatch({ type: "client.start" });
    try {
      for await (const event of streamTurn(request, { signal: abort.signal })) {
        dispatch(event);
      }
    } catch (error) {
      if (abort.signal.aborted) return;
      const message = error instanceof Error ? error.message : "Error de red";
      dispatch({ type: "client.network_error", message });
    }
  }, []);

  const retry = useCallback(() => {
    if (lastRequest.current) void send(lastRequest.current);
  }, [send]);

  useEffect(() => () => controller.current?.abort(), []);

  return { state, send, cancel, retry };
}
