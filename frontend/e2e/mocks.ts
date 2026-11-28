import type { Page, Route } from "@playwright/test";

const DATASOURCE = { id: "ds1", name: "Ventas", dialect: "sqlite" };

const PROVIDER = {
  id: "p1",
  name: "Simulado",
  kind: "fake",
  model: "fake-1",
  config: {},
  secrets: {},
  params: {},
  tasks: ["planner", "sql", "answer", "suggest"],
  is_default: true,
  managed_by: "ui",
};

const CATALOG = [
  {
    kind: "fake",
    label: "Proveedor simulado",
    category: "local",
    fields: [],
    suggested_models: ["fake-1"],
    docs_url: "https://example.com/docs",
    notes: null,
  },
];

const SEMANTIC = {
  version: 1,
  created_by: "admin@example.com",
  created_at: "2025-01-15T10:00:00Z",
  model: {
    version: 1,
    name: "Ventas",
    business_context: "Ventas de una tienda.",
    settings: { timezone: "America/Bogota", currency: "COP", locale: "es-CO" },
    tables: [
      {
        name: "ventas",
        description: "Una fila por venta.",
        columns: [
          { name: "id", role: "id" },
          { name: "total", role: "measure" },
        ],
      },
    ],
    relationships: [],
  },
};

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function sse(events: [string, unknown][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

const TURN = { turn_id: "t1", conversation_id: "c1" };
const DONE = { usage: { tokens_in: 1, tokens_out: 1, cost_usd: 0 }, elapsed_ms: 10 };

/** Primer turno: pide el periodo; el segundo (tras elegir «Este mes») responde con un resultado. */
function chatStream(message: string): string {
  if (message === "Este mes") {
    return sse([
      ["turn.started", TURN],
      ["step", { id: "s1", label: "Consultando ventas", status: "done" }],
      [
        "sql",
        {
          sql: "SELECT SUM(total) AS ventas FROM ventas",
          dialect: "sqlite",
          origin: "catalog",
          filters_applied: [],
          period: "este mes",
        },
      ],
      [
        "result",
        { columns: ["ventas"], rows: [[1250000]], row_count: 1, truncated: false, elapsed_ms: 5 },
      ],
      ["answer", { text: "Este mes vendiste 1.250.000." }],
      ["turn.completed", DONE],
    ]);
  }
  return sse([
    ["turn.started", TURN],
    [
      "clarification",
      { question: "¿De qué periodo?", options: ["Este mes", "Mes pasado", "Este año"], slot: "period" },
    ],
    ["turn.completed", DONE],
  ]);
}

/** Simula toda la API bajo `/api/v1` con una sesión de administrador. */
export async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (path === "/auth/refresh" || path === "/auth/login") {
      return json(route, {
        access_token: "token-de-prueba",
        expires_in: 900,
        user: { id: "u1", email: "admin@example.com", is_admin: true },
      });
    }
    if (path === "/auth/me") {
      return json(route, { id: "u1", email: "admin@example.com", is_admin: true });
    }
    if (path === "/chat/stream") {
      const { message } = request.postDataJSON() as { message: string };
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: chatStream(message),
      });
    }
    if (path === "/datasources") return json(route, [DATASOURCE]);
    if (path === "/datasources/ds1/metrics") {
      return json(route, { metrics: [{ name: "ventas", label: "Ventas" }] });
    }
    if (path === "/datasources/ds1/semantic") return json(route, SEMANTIC);
    if (path === "/datasources/ds1/semantic/versions") {
      return json(route, [{ version: 1, created_by: "admin@example.com", created_at: SEMANTIC.created_at }]);
    }
    if (path === "/providers") return json(route, [PROVIDER]);
    if (path === "/providers/catalog") return json(route, CATALOG);
    if (path === "/conversations") return json(route, []);
    return json(route, { error: { code: "not_found", message: "No encontrado" } }, 404);
  });
}
