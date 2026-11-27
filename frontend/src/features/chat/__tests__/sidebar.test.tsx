import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import type { ConversationSummary } from "../api";
import { ChatPage } from "../ChatPage";
import { groupConversations } from "../grouping";
import { messagesFromStored } from "../rebuild";

// Miércoles 15 de enero de 2025, 10:00 hora local.
const NOW = new Date(2025, 0, 15, 10, 0, 0);

function conv(id: string, created: Date): ConversationSummary {
  return { id, title: `Conversación ${id}`, datasource_id: "ds1", created_at: created.toISOString() };
}

describe("groupConversations", () => {
  it("agrupa en Hoy, Ayer, Últimos 7 días y Anteriores, y omite los vacíos", () => {
    const items = [
      conv("a", new Date(2025, 0, 15, 0, 5)),
      conv("b", new Date(2025, 0, 14, 23, 59)),
      conv("c", new Date(2025, 0, 8, 12, 0)),
      conv("d", new Date(2025, 0, 7, 12, 0)),
      conv("e", new Date(2024, 11, 1)),
    ];
    const groups = groupConversations(items, NOW);
    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ["Hoy", ["a"]],
      ["Ayer", ["b"]],
      ["Últimos 7 días", ["c"]],
      ["Anteriores", ["d", "e"]],
    ]);
    expect(groupConversations([items[0]], NOW).map((g) => g.label)).toEqual(["Hoy"]);
    expect(groupConversations([], NOW)).toEqual([]);
  });

  it("conserva el orden recibido dentro de cada grupo", () => {
    const groups = groupConversations(
      [conv("x", new Date(2025, 0, 15, 9)), conv("y", new Date(2025, 0, 15, 8))],
      NOW,
    );
    expect(groups[0].items.map((i) => i.id)).toEqual(["x", "y"]);
  });
});

describe("messagesFromStored", () => {
  it("reconstruye razonamiento, SQL, resultado y respuesta desde los eventos", () => {
    const messages = messagesFromStored([
      { id: "1", role: "user", content: "¿Cuánto vendí?", created_at: "" },
      {
        id: "2",
        role: "assistant",
        content: "Vendiste 10.",
        created_at: "",
        events: [
          { type: "turn.started", data: { turn_id: "t1", conversation_id: "c1" } },
          { type: "reasoning", data: { text: "Uso ventas_netas." } },
          { type: "sql", data: { sql: "SELECT 1", dialect: "sqlite", origin: "llm", filters_applied: [] } },
          {
            type: "result",
            data: { columns: ["total"], rows: [[10]], row_count: 1, truncated: false, elapsed_ms: 3 },
          },
          { type: "answer", data: { text: "Vendiste 10." } },
        ],
      },
    ]);
    expect(messages).toHaveLength(1);
    expect(messages[0].question).toBe("¿Cuánto vendí?");
    expect(messages[0].turn).toMatchObject({
      status: "completed",
      reasoning: "Uso ventas_netas.",
      sql: { sql: "SELECT 1" },
      result: { rows: [[10]] },
      answer: "Vendiste 10.",
    });
  });

  it("usa el contenido cuando no hay eventos", () => {
    const [message] = messagesFromStored([
      { id: "1", role: "user", content: "hola", created_at: "" },
      { id: "2", role: "assistant", content: "Hola.", created_at: "", events: null },
    ]);
    expect(message.turn.answer).toBe("Hola.");
  });
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function stubApi() {
  const calls: { url: string; method: string; body?: string }[] = [];
  let list = [{ ...conv("c1", new Date()), title: "Ventas de hoy" }];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: init?.body as string | undefined });
      if (url.endsWith("/auth/refresh"))
        return json({
          access_token: "jwt",
          expires_in: 900,
          user: { id: "1", email: "ana@example.com", is_admin: false },
        });
      if (url.endsWith("/api/v1/conversations")) return json(list);
      if (url.endsWith("/api/v1/conversations/c1")) {
        if (method === "PATCH") {
          list = [{ ...list[0], title: JSON.parse(init?.body as string).title }];
          return json(list[0]);
        }
        if (method === "DELETE") {
          list = [];
          return new Response(null, { status: 204 });
        }
        return json({
          ...list[0],
          messages: [
            { id: "m1", role: "user", content: "¿Cuánto vendí?", created_at: "" },
            {
              id: "m2",
              role: "assistant",
              content: "Vendiste 10.",
              created_at: "",
              events: [{ type: "sql", data: { sql: "SELECT 1", dialect: "sqlite", origin: "llm", filters_applied: [] } }],
            },
          ],
        });
      }
      if (url.endsWith("/api/v1/datasources")) return json([{ id: "ds1", name: "Ventas", dialect: "sqlite" }]);
      if (url.endsWith("/api/v1/providers")) return json([]);
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Sidebar", () => {
  it("lista agrupada y abre una conversación reconstruyendo sus mensajes", async () => {
    stubApi();
    renderPage();
    const sidebar = await screen.findByRole("complementary", { name: "Conversaciones" });
    const group = await within(sidebar).findByRole("region", { name: "Hoy" });
    await userEvent.click(within(group).getByRole("button", { name: "Ventas de hoy" }));
    expect(await screen.findByText("¿Cuánto vendí?")).toBeInTheDocument();
    expect(screen.getByText("Vendiste 10.")).toBeInTheDocument();
    expect(screen.getByText("SELECT 1")).toBeInTheDocument();
  });

  it("Ctrl+K vuelve a una conversación nueva", async () => {
    stubApi();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Ventas de hoy" }));
    await screen.findByText("Vendiste 10.");
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(await screen.findByText("¿Qué quieres saber?")).toBeInTheDocument();
  });

  it("renombra desde un diálogo de la interfaz", async () => {
    const calls = stubApi();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Renombrar Ventas de hoy" }));
    const input = await screen.findByLabelText("Título");
    await userEvent.clear(input);
    await userEvent.type(input, "Ventas netas");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("button", { name: "Ventas netas" })).toBeInTheDocument();
    const patch = calls.find((c) => c.method === "PATCH");
    expect(JSON.parse(patch?.body ?? "null")).toEqual({ title: "Ventas netas" });
  });

  it("borra solo tras confirmar en el diálogo, sin window.confirm", async () => {
    const calls = stubApi();
    const confirm = vi.spyOn(window, "confirm");
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar Ventas de hoy" }));
    const dialog = await screen.findByRole("dialog");
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(await screen.findByText("Aún no hay conversaciones.")).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
  });
});
