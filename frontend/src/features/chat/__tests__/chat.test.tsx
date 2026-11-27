import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { ChatPage } from "../ChatPage";
import { buildSuggestions } from "../suggestions";

const semantic = {
  version: 1,
  model: {
    metrics: [
      { name: "ventas_netas", label: "Ventas netas" },
      { name: "ticket_promedio", label: "Ticket promedio", requires_period: false },
    ],
    security: { roles: [{ name: "gerencia_general" }] },
  },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

const encoder = new TextEncoder();

function sse(events: [string, unknown][], keepOpen: boolean) {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const [type, data] of events) {
        controller.enqueue(encoder.encode(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`));
      }
      if (!keepOpen) controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function stubApi(options: { keepOpen?: boolean; isAdmin?: boolean } = {}) {
  const { keepOpen = false, isAdmin = true } = options;
  const calls: { url: string; method: string; body?: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
      if (url.endsWith("/auth/refresh"))
        return json({
          access_token: "jwt",
          expires_in: 900,
          user: { id: "1", email: "ana@example.com", is_admin: isAdmin },
        });
      if (url.endsWith("/chat/stream"))
        return sse(
          [
            ["turn.started", { turn_id: "t1", conversation_id: "c1" }],
            ...(keepOpen
              ? []
              : ([
                  ["answer", { text: "Vendiste 10." }],
                  [
                    "turn.completed",
                    { usage: { tokens_in: 1, tokens_out: 1, cost_usd: 0 }, elapsed_ms: 5 },
                  ],
                ] as [string, unknown][])),
          ],
          keepOpen,
        );
      if (url.includes("/cancel")) return json({ turn_id: "t1", status: "cancelled" });
      if (url.endsWith("/semantic")) return json(semantic);
      if (url.endsWith("/metrics")) return json({ metrics: semantic.model.metrics });
      if (url.endsWith("/api/v1/datasources"))
        return json([{ id: "ds1", name: "Ventas", dialect: "sqlite" }]);
      if (url.endsWith("/api/v1/providers"))
        return json([{ id: "p1", name: "Simulado", kind: "fake", model: "fake-1" }]);
      return json({});
    }),
  );
  return calls;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ChatPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const chatBody = (calls: { url: string; body?: string }[]) =>
  JSON.parse(calls.find((c) => c.url.endsWith("/chat/stream"))?.body ?? "null");

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildSuggestions", () => {
  it("genera preguntas desde las métricas y cae a una genérica sin ellas", () => {
    expect(buildSuggestions(semantic.model.metrics)).toEqual([
      "Muéstrame ventas netas de este mes",
      "Muéstrame ticket promedio",
    ]);
    expect(buildSuggestions([])).toHaveLength(1);
  });
});

describe("ChatPage", () => {
  it("muestra el estado vacío con preguntas sugeridas y la barra superior", async () => {
    stubApi();
    renderPage();
    expect(
      await screen.findByRole("button", { name: "Muéstrame ventas netas de este mes" }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("combobox", { name: "Fuente de datos" })).toHaveValue("ds1");
    expect(screen.getByRole("combobox", { name: "Modelo de IA" })).toBeInTheDocument();
    expect(await screen.findByRole("combobox", { name: "Rol" })).toBeInTheDocument();
  });

  it("quien no es administrador recibe sugerencias sin leer el modelo completo", async () => {
    const calls = stubApi({ isAdmin: false });
    renderPage();
    expect(
      await screen.findByRole("button", { name: "Muéstrame ventas netas de este mes" }),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/metrics"))).toBe(true);
    expect(calls.some((c) => c.url.endsWith("/semantic"))).toBe(false);
    expect(screen.queryByRole("combobox", { name: "Rol" })).not.toBeInTheDocument();
  });

  it("una pregunta sugerida se envía como mensaje", async () => {
    const calls = stubApi();
    renderPage();
    await userEvent.click(
      await screen.findByRole("button", { name: "Muéstrame ticket promedio" }),
    );
    expect(await screen.findByText("Vendiste 10.")).toBeInTheDocument();
    expect(chatBody(calls)).toMatchObject({ datasource_id: "ds1", message: "Muéstrame ticket promedio" });
  });

  it("Enter envía y Shift+Enter hace salto de línea", async () => {
    const calls = stubApi();
    renderPage();
    await screen.findByRole("combobox", { name: "Fuente de datos" });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Fuente de datos" })).toHaveValue("ds1"));
    const box = screen.getByLabelText("Pregunta");
    await userEvent.type(box, "¿Cuánto vendí?{Shift>}{Enter}{/Shift}hoy");
    expect(box).toHaveValue("¿Cuánto vendí?\nhoy");
    expect(calls.some((c) => c.url.endsWith("/chat/stream"))).toBe(false);

    await userEvent.type(box, "{Enter}");
    expect(await screen.findByText("Vendiste 10.")).toBeInTheDocument();
    expect(chatBody(calls).message).toBe("¿Cuánto vendí?\nhoy");
    expect(box).toHaveValue("");
  });

  it("Esc cancela el turno en curso y vuelve a habilitar el compositor", async () => {
    const calls = stubApi({ keepOpen: true });
    renderPage();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Fuente de datos" })).toHaveValue("ds1"));
    const box = screen.getByLabelText("Pregunta");
    await userEvent.type(box, "hola{Enter}");
    await waitFor(() => expect(box).toBeDisabled());

    await userEvent.keyboard("{Escape}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Turno cancelado.");
    await waitFor(() => expect(box).toBeEnabled());
    expect(
      calls.some((c) => c.url.endsWith("/chat/t1/cancel") && c.method === "POST"),
    ).toBe(true);
  });
});
