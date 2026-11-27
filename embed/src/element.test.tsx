import { act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { defineChatiappChat } from "./element";
import type { ChatiappChatElement } from "./element";

function jwt(claims: Record<string, unknown>): string {
  return `cabecera.${btoa(JSON.stringify(claims))}.firma`;
}

const encoder = new TextEncoder();

function sse(events: [string, unknown][]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const [type, data] of events) {
        controller.enqueue(encoder.encode(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`));
      }
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const answer = (text: string): Response =>
  sse([
    ["turn.started", { turn_id: "t1", conversation_id: "c1" }],
    ["answer", { text }],
    ["turn.completed", { usage: { tokens_in: 1, tokens_out: 1, cost_usd: 0 }, elapsed_ms: 5 }],
  ]);

function mount(attributes: Record<string, string> = {}): ChatiappChatElement {
  const element = document.createElement("chatiapp-chat") as ChatiappChatElement;
  element.setAttribute("base-url", "https://chatiapp.example.com");
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  act(() => {
    document.body.append(element);
  });
  return element;
}

const shadow = (element: ChatiappChatElement) => element.shadowRoot as ShadowRoot;

beforeAll(() => defineChatiappChat());
afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

describe("<chatiapp-chat>", () => {
  it("se pinta dentro del Shadow DOM y no deja nada en la página", () => {
    const element = mount();
    expect(shadow(element).querySelector("textarea")).not.toBeNull();
    expect(shadow(element).querySelector("style")).not.toBeNull();
    expect(document.body.querySelector("textarea")).toBeNull();
    expect(document.head.querySelector("style")).toBeNull();
  });

  it("usa lang y suggested-questions", () => {
    const element = mount({ lang: "en", "suggested-questions": '["Sales today?"]' });
    expect(shadow(element).textContent).toContain("What do you want to know?");
    expect(shadow(element).textContent).toContain("Sales today?");
  });

  it("pregunta con el token del anfitrión y emite chatiapp:answer", async () => {
    const calls: { url: string; auth: string | null; body: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        calls.push({
          url,
          auth: (init.headers as Record<string, string>).Authorization,
          body: init.body as string,
        });
        return answer("Vendiste 10.");
      }),
    );
    const element = mount();
    const token = jwt({ exp: 9_999_999_999, ds: "ds-1" });
    element.getToken = async () => token;
    const received: unknown[] = [];
    document.addEventListener("chatiapp:answer", (event) =>
      received.push((event as CustomEvent).detail),
    );

    const textarea = shadow(element).querySelector("textarea") as HTMLTextAreaElement;
    await userEvent.type(textarea, "ventas de hoy{Enter}");

    await waitFor(() => expect(received).toHaveLength(1));
    expect(received[0]).toMatchObject({ text: "Vendiste 10.", conversationId: "c1" });
    expect(calls[0].url).toBe("https://chatiapp.example.com/api/v1/chat/stream");
    expect(calls[0].auth).toBe(`Bearer ${token}`);
    expect(JSON.parse(calls[0].body)).toMatchObject({ datasource_id: "ds-1", message: "ventas de hoy" });
    expect(shadow(element).textContent).toContain("Vendiste 10.");
  });

  it("pide otro token si el servidor responde 401 y sigue la misma conversación", async () => {
    const bodies: Record<string, unknown>[] = [];
    let first = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        bodies.push(JSON.parse(init.body as string));
        if (bodies.length === 2 && first) {
          first = false;
          return new Response(JSON.stringify({ error: { code: "token_expired" } }), {
            status: 401,
          });
        }
        return answer("ok");
      }),
    );
    const element = mount();
    let n = 0;
    const getToken = vi.fn(async () => jwt({ exp: 9_999_999_999, ds: "ds-1", n: ++n }));
    element.getToken = getToken;

    const textarea = () => shadow(element).querySelector("textarea") as HTMLTextAreaElement;
    await userEvent.type(textarea(), "primera{Enter}");
    await waitFor(() => expect(shadow(element).textContent).toContain("ok"));
    expect(getToken).toHaveBeenCalledTimes(1);

    await userEvent.type(textarea(), "segunda{Enter}");
    await waitFor(() => expect(bodies).toHaveLength(3)); // 401 + reintento
    expect(getToken).toHaveBeenCalledTimes(2);
    expect(bodies[2]).toMatchObject({ conversation_id: "c1", message: "segunda" });
  });

  it("emite chatiapp:error si getToken falla", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const element = mount();
    element.getToken = async () => {
      throw new Error("sin sesión");
    };
    const errors: unknown[] = [];
    element.addEventListener("chatiapp:error", (event) =>
      errors.push((event as CustomEvent).detail),
    );
    const textarea = shadow(element).querySelector("textarea") as HTMLTextAreaElement;
    await userEvent.type(textarea, "hola{Enter}");
    await waitFor(() => expect(errors).toHaveLength(1));
    expect(errors[0]).toMatchObject({ code: "token_error" });
    expect(shadow(element).querySelector('[role="alert"]')).not.toBeNull();
  });

  it("emite chatiapp:clarification y puede ocultar SQL y razonamiento", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sse([
          ["turn.started", { turn_id: "t2", conversation_id: "c2" }],
          ["step", { id: "s1", label: "Paso interno", status: "done" }],
          [
            "sql",
            {
              sql: "select 1",
              dialect: "sqlite",
              origin: "llm",
              summary_table: null,
              filters_applied: [],
            },
          ],
          ["clarification", { question: "¿Qué periodo?", options: ["Hoy", "Ayer"], slot: "period" }],
          ["turn.completed", { usage: { tokens_in: 1, tokens_out: 1, cost_usd: 0 }, elapsed_ms: 5 }],
        ]),
      ),
    );
    const element = mount({ "show-sql": "false", "show-reasoning": "false" });
    element.getToken = async () => jwt({ exp: 9_999_999_999, ds: "ds-1" });
    const events: unknown[] = [];
    element.addEventListener("chatiapp:clarification", (event) =>
      events.push((event as CustomEvent).detail),
    );
    const textarea = shadow(element).querySelector("textarea") as HTMLTextAreaElement;
    await userEvent.type(textarea, "ventas{Enter}");
    await waitFor(() => expect(events).toHaveLength(1));
    expect(events[0]).toMatchObject({ question: "¿Qué periodo?", options: ["Hoy", "Ayer"] });
    expect(shadow(element).textContent).not.toContain("Paso interno");
    expect(shadow(element).querySelector('section[aria-label="Consulta SQL"]')).toBeNull();
  });
});
