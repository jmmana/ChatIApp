import { useCallback, useEffect, useReducer, useRef } from "react";
import { streamTurn } from "./sse";
import type { StreamTurnOptions } from "./sse";
import { initialTurnState, turnReducer } from "./turnReducer";
import type { ChatRequest } from "./types";

/** Ejecuta un turno por SSE; `retry` repite la última petición tras un error recuperable. */
export function useTurn(options: Pick<StreamTurnOptions, "baseUrl" | "authorize"> = {}) {
  const [state, dispatch] = useReducer(turnReducer, initialTurnState);
  const controller = useRef<AbortController | null>(null);
  const lastRequest = useRef<ChatRequest | null>(null);
  // Se leen al enviar: un `getToken` nuevo en cada render no reinicia nada.
  const streamOptions = useRef(options);
  useEffect(() => {
    streamOptions.current = options;
  });

  const cancel = useCallback(() => {
    const active = controller.current;
    if (!active || active.signal.aborted) return;
    active.abort();
    // Abortar corta el stream sin evento: el estado debe reflejar la cancelación.
    dispatch({
      type: "error",
      data: { code: "cancelled", message: "Turno cancelado.", recoverable: true },
    });
  }, []);

  const send = useCallback(async (request: ChatRequest) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    lastRequest.current = request;
    dispatch({ type: "client.start" });
    try {
      for await (const event of streamTurn(request, { ...streamOptions.current, signal: abort.signal })) {
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
