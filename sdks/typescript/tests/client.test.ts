import { describe, expect, it } from "vitest";
import { ChatIApp, ChatIAppError, type EndUser, type StreamEvent } from "../src/index.js";

const BASE = "https://chatiapp.tuempresa.com";
const KEY = "clave-de-prueba-1234";
const USER: EndUser = { id: "u-123", role: "gerente_sucursal", attributes: { sucursales: [1, 2] } };

const CLARIFICATION = {
  conversation_id: "7d0c0000-0000-0000-0000-000000000001",
  status: "needs_clarification",
  reasoning: "Es la métrica ventas_netas. No mencionan período.",
  clarification: { question: "¿De qué período quieres ver las ventas?", options: ["Hoy"], slot: "period" },
};
const ANSWERED = {
  conversation_id: "7d0c0000-0000-0000-0000-000000000001",
  status: "answered",
  sql: { sql: "SELECT 1", dialect: "postgres", origin: "catalog" },
  answer: "Este mes llevas $482,3 M en ventas netas.",
};

const SSE =
  ": keep-alive\n\n" +
  'event: turn.started\ndata: {"turn_id": "t1", "conversation_id": "c1"}\n\n' +
  'event: answer.delta\ndata: {"text": "Este "}\n\n' +
  'event: answer.delta\ndata: {"text": "mes"}\n\n' +
  'event: futuro\ndata: {"x": 1}\n\n' +
  'event: turn.completed\ndata: {"usage": {"tokens_in": 1, "tokens_out": 2, "cost_usd": 0}}\n\n';

interface Call {
  url: string;
  headers: Headers;
  body: Record<string, unknown>;
}

function mock(responder: (call: Call) => Response): { fetch: typeof fetch; calls: Call[] } {
  const calls: Call[] = [];
  const fakeFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = {
      url: String(input),
      headers: new Headers(init?.headers),
      body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {},
    };
    calls.push(call);
    return responder(call);
  }) as typeof fetch;
  return { fetch: fakeFetch, calls };
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

function chunked(text: string, size: number): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      for (let i = 0; i < bytes.length; i += size) controller.enqueue(bytes.slice(i, i + size));
      controller.close();
    },
  });
}

describe("ChatIApp", () => {
  it("resuelve la aclaración y recuerda la fuente de la conversación", async () => {
    const { fetch, calls } = mock((c) => json("conversation_id" in c.body ? ANSWERED : CLARIFICATION));
    const client = new ChatIApp({ baseUrl: `${BASE}/`, apiKey: KEY, fetch });

    let turn = await client.chat({ message: "¿Cuánto vendí?", datasource: "ventas", user: USER });
    expect(turn.status).toBe("needs_clarification");
    turn = await client.chat({ message: "Este mes", conversationId: turn.conversation_id, user: USER });
    expect(turn.status).toBe("answered");

    expect(calls[0]?.url).toBe(`${BASE}/api/v1/chat`);
    expect(calls[0]?.headers.get("authorization")).toBe(`Bearer ${KEY}`);
    expect(calls[0]?.body).toEqual({ datasource_id: "ventas", message: "¿Cuánto vendí?", user: USER });
    expect(calls[1]?.body.datasource_id).toBe("ventas");
    expect(calls[1]?.body.conversation_id).toBe(CLARIFICATION.conversation_id);
  });

  it("falla antes de llamar si no hay fuente", async () => {
    const { fetch, calls } = mock(() => json({}));
    const client = new ChatIApp({ baseUrl: BASE, apiKey: KEY, fetch });
    await expect(client.chat({ message: "hola", user: USER })).rejects.toThrow(/datasource/);
    expect(calls).toHaveLength(0);
  });

  it("emite eventos tipados por streaming (ejemplo de la documentación)", async () => {
    const { fetch, calls } = mock(
      () => new Response(chunked(SSE, 7), { headers: { "content-type": "text/event-stream" } }),
    );
    const client = new ChatIApp({ baseUrl: BASE, apiKey: KEY, fetch });

    let text = "";
    const types: string[] = [];
    for await (const event of client.chatStream({
      datasource: "ventas",
      message: "¿Cuánto vendí este mes?",
      user: USER,
    })) {
      types.push(event.type);
      if (event.type === "answer.delta") text += event.data.text;
    }
    expect(text).toBe("Este mes");
    expect(types).toEqual(["turn.started", "answer.delta", "answer.delta", "turn.completed"]);
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/chat/stream`);
    expect(calls[0]?.headers.get("accept")).toBe("text/event-stream");
  });

  it("tolera CRLF y un evento final sin línea en blanco", async () => {
    const raw = 'event: error\r\ndata: {"code":"x","message":"m","recoverable":true}\r\n\r\nevent: answer\r\ndata: {"text":"hola"}';
    const { fetch } = mock(() => new Response(chunked(raw, 5)));
    const client = new ChatIApp({ baseUrl: BASE, apiKey: KEY, fetch });
    const events: StreamEvent[] = [];
    for await (const e of client.chatStream({ datasource: "ventas", message: "x", user: USER })) {
      events.push(e);
    }
    expect(events.map((e) => e.type)).toEqual(["error", "answer"]);
  });

  it("convierte los errores HTTP en ChatIAppError", async () => {
    const error = { code: "role_not_allowed", message: "Rol no permitido", details: {} };
    const { fetch } = mock(() => json({ error }, 403));
    const client = new ChatIApp({ baseUrl: BASE, apiKey: KEY, fetch });
    const failure = await client.chat({ message: "x", datasource: "ventas", user: USER }).catch((e) => e);
    expect(failure).toBeInstanceOf(ChatIAppError);
    expect(failure).toMatchObject({ status: 403, code: "role_not_allowed" });
    await expect(
      client.chatStream({ message: "x", datasource: "ventas", user: USER }).next(),
    ).rejects.toMatchObject({ code: "role_not_allowed" });
  });

  it("emite tokens de sesión para el chat embebido", async () => {
    const { fetch, calls } = mock(() => json({ token: "tok", expires_at: "2026-11-28T10:15:00Z" }));
    const client = new ChatIApp({ baseUrl: BASE, apiKey: KEY, fetch });
    const session = await client.createEmbedSession({
      datasource: "ventas",
      origin: "https://portal.tuempresa.com",
      user: USER,
      ttlSeconds: 600,
    });
    expect(session.token).toBe("tok");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/embed/sessions`);
    expect(calls[0]?.body).toEqual({
      datasource: "ventas",
      origin: "https://portal.tuempresa.com",
      user: USER,
      ttl_seconds: 600,
    });
  });

  it("cancela un turno", async () => {
    const { fetch, calls } = mock(() => json({ turn_id: "t1", status: "cancelled" }));
    const client = new ChatIApp({ baseUrl: BASE, apiKey: KEY, fetch });
    expect((await client.cancel("t1")).status).toBe("cancelled");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/chat/t1/cancel`);
  });
});
