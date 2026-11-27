import { describe, expect, it, vi } from "vitest";
import { setAccessToken } from "@/features/auth/api";
import { SseHttpError, SseParser, streamTurn } from "../sse";
import type { TurnEvent } from "../types";

const STREAM =
  'event: turn.started\ndata: {"turn_id":"t1","conversation_id":"c1"}\n\n' +
  ": keep-alive\n\n" +
  'event: answer.delta\ndata: {"text":"Año ñ"}\n\n' +
  'event: turn.completed\ndata: {"usage":{"tokens_in":1,"tokens_out":2,"cost_usd":0},"elapsed_ms":5}\n\n';

function bodyFrom(chunks: Uint8Array[], onCancel?: () => void): ReadableStream<Uint8Array> {
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) controller.enqueue(chunks[i++]);
      else controller.close();
    },
    cancel() {
      onCancel?.();
    },
  });
}

async function collect(gen: AsyncGenerator<TurnEvent>): Promise<TurnEvent[]> {
  const out: TurnEvent[] = [];
  for await (const e of gen) out.push(e);
  return out;
}

describe("SseParser", () => {
  it("parsea eventos completos e ignora comentarios", () => {
    const events = new SseParser().push(STREAM);
    expect(events.map((e) => e.type)).toEqual(["turn.started", "answer.delta", "turn.completed"]);
  });

  it("reconstruye eventos partidos en fragmentos de 1 carácter", () => {
    const parser = new SseParser();
    const events: TurnEvent[] = [];
    for (const char of STREAM) events.push(...parser.push(char));
    expect(events).toHaveLength(3);
    expect(events[1]).toEqual({ type: "answer.delta", data: { text: "Año ñ" } });
  });

  it("soporta CRLF, incluso partido entre fragmentos", () => {
    const parser = new SseParser();
    const a = parser.push('event: reasoning\r\ndata: {"text":"x"}\r');
    const b = parser.push("\n\r\n");
    expect([...a, ...b]).toEqual([{ type: "reasoning", data: { text: "x" } }]);
  });

  it("une varias líneas data", () => {
    const events = new SseParser().push('event: reasoning\ndata: {"text":\ndata: "x"}\n\n');
    expect(events).toEqual([{ type: "reasoning", data: { text: "x" } }]);
  });

  it("ignora eventos desconocidos y JSON inválido", () => {
    const events = new SseParser().push(
      'event: otro\ndata: {}\n\nevent: reasoning\ndata: {mal\n\nevent: reasoning\ndata: {"text":"ok"}\n\n',
    );
    expect(events).toEqual([{ type: "reasoning", data: { text: "ok" } }]);
  });

  it("flush emite el último evento sin línea en blanco final", () => {
    const parser = new SseParser();
    expect(parser.push('event: reasoning\ndata: {"text":"x"}')).toEqual([]);
    expect(parser.flush()).toEqual([{ type: "reasoning", data: { text: "x" } }]);
  });
});

describe("streamTurn", () => {
  const request = { datasource_id: "ventas", message: "hola" };

  it("hace POST con cabeceras y emite eventos con UTF-8 partido entre fragmentos", async () => {
    setAccessToken("jwt-de-prueba");
    const bytes = new TextEncoder().encode(STREAM);
    const cut = STREAM.indexOf("ñ");
    const mid = new TextEncoder().encode(STREAM.slice(0, cut)).length + 1; // dentro de «ñ»
    const fetchImpl = vi.fn(async () => new Response(bodyFrom([bytes.slice(0, mid), bytes.slice(mid)])));

    const events = await collect(streamTurn(request, { fetchImpl: fetchImpl as typeof fetch }));

    expect(events.map((e) => e.type)).toEqual(["turn.started", "answer.delta", "turn.completed"]);
    expect(events[1]).toEqual({ type: "answer.delta", data: { text: "Año ñ" } });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/chat/stream");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      Authorization: "Bearer jwt-de-prueba",
    });
    expect(JSON.parse(init.body as string)).toEqual(request);
    setAccessToken(null);
  });

  it("lanza SseHttpError con el detalle si la respuesta no es 2xx", async () => {
    const fetchImpl = vi.fn(
      async () => new Response(JSON.stringify({ detail: "sin proveedor" }), { status: 422 }),
    );
    await expect(
      collect(streamTurn(request, { fetchImpl: fetchImpl as typeof fetch })),
    ).rejects.toMatchObject({ status: 422, message: "sin proveedor" });
    await expect(
      collect(streamTurn(request, { fetchImpl: fetchImpl as typeof fetch })),
    ).rejects.toBeInstanceOf(SseHttpError);
  });

  it("propaga los errores de red", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(
      collect(streamTurn(request, { fetchImpl: fetchImpl as unknown as typeof fetch })),
    ).rejects.toThrow("Failed to fetch");
  });

  it("cancela con AbortController: cancela el lector y pasa la señal a fetch", async () => {
    const abort = new AbortController();
    const cancelled = vi.fn();
    const enc = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode('event: reasoning\ndata: {"text":"x"}\n\n'));
      },
      cancel: cancelled,
    });
    const fetchImpl = vi.fn(async () => new Response(body));

    const gen = streamTurn(request, { signal: abort.signal, fetchImpl: fetchImpl as typeof fetch });
    const first = await gen.next();
    expect(first.value).toEqual({ type: "reasoning", data: { text: "x" } });
    abort.abort();
    const next = await gen.next();
    expect(next.done).toBe(true);
    expect(cancelled).toHaveBeenCalled();
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.signal).toBe(abort.signal);
  });
});
