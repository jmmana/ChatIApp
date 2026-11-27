import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { setAccessToken } from "@/features/auth/api";
import type { Provider } from "@/features/providers/api";
import type { EvalRun } from "./api";
import { EvaluationPage } from "./EvaluationPage";

function provider(id: string, name: string, kind: string, tasks: Provider["tasks"] = []): Provider {
  return {
    id,
    name,
    kind,
    model: `${name}-modelo`,
    config: {},
    secrets: {},
    params: {},
    tasks,
    is_default: false,
    managed_by: "ui",
  };
}

const claude = provider("p1", "Claude", "anthropic", ["planner"]);
const simulado = provider("p2", "Simulado", "fake", ["sql"]);

const doneRun: EvalRun = {
  id: "r1",
  status: "done",
  created_at: "2026-11-27T10:00:00Z",
  providers: [
    { id: "p1", name: "Claude", kind: "anthropic", model: "Claude-modelo" },
    { id: "p2", name: "Simulado", kind: "fake", model: "Simulado-modelo" },
  ],
  cases_total: 20,
  cases_done: 20,
  error: null,
  report: {
    set: "ventas",
    generado: "2026-11-27T10:05:00+00:00",
    proveedores: [
      {
        proveedor: "Claude",
        kind: "anthropic",
        modelo: "Claude-modelo",
        total: 10,
        correctos: 9,
        exactitud: 0.9,
        latencia_ms: { p50: 800, p95: 2400 },
        tokens: { entrada: 100, salida: 50 },
        costo_usd: 0.1234,
        fallidos: [
          {
            id: "caso-fallido-1",
            tags: ["metrica"],
            motivo: "el resultado no coincide con el esperado",
            sql: "SELECT 1 AS obtenido",
            sql_esperado: "SELECT 2 AS esperado",
            filas: [],
            aclaracion: null,
          },
        ],
      },
      {
        proveedor: "Simulado",
        kind: "fake",
        modelo: "Simulado-modelo",
        total: 10,
        correctos: 3,
        exactitud: 0.3,
        latencia_ms: { p50: 10, p95: 20 },
        tokens: { entrada: 0, salida: 0 },
        costo_usd: 0,
        fallidos: [],
      },
    ],
  },
};

function json(body: unknown, status = 202) {
  return new Response(JSON.stringify(body), { status });
}

function mockApi(runs: EvalRun[]) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/auth/refresh"))
      return json(
        {
          access_token: "jwt",
          expires_in: 900,
          user: { id: "1", email: "ana@example.com", is_admin: true },
        },
        200,
      );
    if (url.endsWith("/evals/runs") && init?.method === "POST") return json(runs[0]);
    if (url.endsWith("/evals/runs")) return json(runs, 200);
    if (url.endsWith("/providers/routing")) return json([claude, simulado], 200);
    return json([claude, simulado], 200);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <EvaluationPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function bodyOf(fetchMock: ReturnType<typeof mockApi>, method: string, suffix: string) {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url).endsWith(suffix) && init?.method === method,
  );
  return call ? JSON.parse(String(call[1]?.body)) : undefined;
}

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe("pantalla de evaluación", () => {
  it("lanza una corrida con los proveedores elegidos", async () => {
    const fetchMock = mockApi([]);
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByLabelText(/Simulado/));
    await user.click(screen.getByRole("button", { name: "Lanzar evaluación" }));

    await vi.waitFor(() => expect(bodyOf(fetchMock, "POST", "/evals/runs")).toBeDefined());
    expect(bodyOf(fetchMock, "POST", "/evals/runs")).toEqual({ provider_ids: ["p2"] });
  });

  it("pide un tope de llamadas cuando se elige un proveedor real", async () => {
    const fetchMock = mockApi([]);
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByLabelText(/Claude/));
    expect(screen.getByLabelText("Tope de llamadas")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Lanzar evaluación" }));

    await vi.waitFor(() => expect(bodyOf(fetchMock, "POST", "/evals/runs")).toBeDefined());
    expect(bodyOf(fetchMock, "POST", "/evals/runs")).toEqual({
      provider_ids: ["p1"],
      max_calls: 1000,
    });
  });

  it("muestra el progreso de la corrida en curso", async () => {
    mockApi([{ ...doneRun, status: "running", cases_done: 7, report: null }]);
    renderPage();

    expect(await screen.findByText("Casos evaluados: 7 de 20")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Evaluando…" })).toBeDisabled();
  });

  it("muestra la tabla comparativa y el SQL esperado y obtenido de los casos fallidos", async () => {
    mockApi([doneRun]);
    renderPage();

    expect(await screen.findByRole("cell", { name: "90,0 % (9/10)" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "$ 0,1234" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /exactitud frente a costo/ })).toBeInTheDocument();
    expect(screen.getByText("SELECT 2 AS esperado")).toBeInTheDocument();
    expect(screen.getByText("SELECT 1 AS obtenido")).toBeInTheDocument();
  });

  it("«Usar para esta tarea» asigna el proveedor conservando el resto del enrutamiento", async () => {
    const fetchMock = mockApi([doneRun]);
    renderPage();
    const user = userEvent.setup();

    await screen.findByRole("cell", { name: "90,0 % (9/10)" });
    await user.selectOptions(screen.getByLabelText("Tarea para Claude"), "answer");
    await user.click(screen.getByRole("button", { name: "Usar Claude para esta tarea" }));

    await vi.waitFor(() => expect(bodyOf(fetchMock, "PUT", "/providers/routing")).toBeDefined());
    expect(bodyOf(fetchMock, "PUT", "/providers/routing")).toEqual({
      tasks: { planner: "p1", sql: "p2", answer: "p1" },
      fallback: [],
    });
  });
});
