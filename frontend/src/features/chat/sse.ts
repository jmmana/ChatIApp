import { getAccessToken } from "@/features/auth/api";
import { TURN_EVENT_TYPES, type ChatRequest, type TurnEvent, type TurnEventType } from "./types";

export class SseHttpError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

const KNOWN_TYPES = new Set<string>(TURN_EVENT_TYPES);

/**
 * Parser incremental de `text/event-stream`: acepta fragmentos arbitrarios,
 * así que un evento puede llegar partido en mitad de una línea.
 */
export class SseParser {
  private line = "";
  private skipLf = false;
  private eventName = "";
  private dataLines: string[] = [];

  push(chunk: string): TurnEvent[] {
    const events: TurnEvent[] = [];
    for (const char of chunk) {
      if (this.skipLf) {
        this.skipLf = false;
        if (char === "\n") continue; // segundo byte de un CRLF partido entre fragmentos
      }
      if (char === "\r" || char === "\n") {
        this.skipLf = char === "\r";
        const event = this.processLine(this.line);
        this.line = "";
        if (event) events.push(event);
      } else {
        this.line += char;
      }
    }
    return events;
  }

  /** Procesa lo que quede al cerrar el stream. */
  flush(): TurnEvent[] {
    const events: TurnEvent[] = [];
    if (this.line) {
      const event = this.processLine(this.line);
      this.line = "";
      if (event) events.push(event);
    }
    const last = this.dispatch();
    if (last) events.push(last);
    return events;
  }

  private processLine(line: string): TurnEvent | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return null; // comentario (keep-alive)
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.eventName = value;
    else if (field === "data") this.dataLines.push(value);
    return null;
  }

  private dispatch(): TurnEvent | null {
    const name = this.eventName;
    const raw = this.dataLines.join("\n");
    this.eventName = "";
    this.dataLines = [];
    if (!KNOWN_TYPES.has(name) || raw === "") return null; // desconocido o vacío: se ignora
    try {
      return { type: name as TurnEventType, data: JSON.parse(raw) } as TurnEvent;
    } catch {
      return null;
    }
  }
}

export interface StreamTurnOptions {
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

/** POST a `/api/v1/chat/stream` y emite los eventos conforme llegan. */
export async function* streamTurn(
  request: ChatRequest,
  { signal, fetchImpl = fetch }: StreamTurnOptions = {},
): AsyncGenerator<TurnEvent, void, undefined> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetchImpl("/api/v1/chat/stream", {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    let message = `Error ${response.status}`;
    let code: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown; code?: unknown; message?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (typeof body.message === "string") message = body.message;
      if (typeof body.code === "string") code = body.code;
    } catch {
      // cuerpo sin JSON: se deja el mensaje genérico
    }
    throw new SseHttpError(response.status, message, code);
  }
  if (!response.body) throw new SseHttpError(response.status, "La respuesta no trae cuerpo");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  const onAbort = () => void reader.cancel().catch(() => undefined);
  signal?.addEventListener("abort", onAbort);
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      yield* parser.push(decoder.decode(value, { stream: true }));
    }
    yield* parser.push(decoder.decode());
    yield* parser.flush();
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
}
