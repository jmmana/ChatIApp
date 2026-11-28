import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "@/app/App";
import { setAccessToken } from "@/features/auth/api";
import type { PreviewResult, SemanticModel } from "../types";

const DS = "11111111-1111-1111-1111-111111111111";
const session = {
  access_token: "jwt-en-memoria",
  expires_in: 900,
  user: { id: "u1", email: "ana@example.com", is_admin: true },
};

function model(): SemanticModel {
  return {
    version: 1,
    name: "Ventas (demo)",
    tables: [
      {
        name: "facturas",
        columns: [
          { name: "id", role: "id" },
          { name: "fecha", role: "time" },
          { name: "total", role: "measure" },
          { name: "canal", role: "dimension" },
        ],
      },
      {
        name: "ventas_mensuales",
        columns: [
          { name: "mes", role: "time" },
          { name: "total_ventas", role: "measure" },
        ],
      },
    ],
    metrics: [
      {
        name: "ventas_netas",
        label: "Ventas netas",
        table: "facturas",
        expression: "SUM(total)",
        time_column: "facturas.fecha",
        filters: ["estado = 'PAGADA'"],
        dimensions: ["facturas.canal"],
      },
    ],
    summary_tables: [
      {
        table: "ventas_mensuales",
        grain: "month",
        time_column: "mes",
        includes_current_period: false,
        metrics: { ventas_netas: "SUM(total_ventas)" },
      },
    ],
  };
}

const previewResult: PreviewResult = {
  sql: "SELECT SUM(total) AS ventas_netas FROM facturas WHERE estado = 'PAGADA'",
  metric: "ventas_netas",
  role: null,
  summary_table: "ventas_diarias",
  reason: "ventas_mensuales no incluye el mes en curso",
  period: {
    text: "este mes",
    label: "Noviembre 2026",
    start: "2026-11-01",
    end_exclusive: "2026-12-01",
  },
  filters_applied: [{ source: "metric", text: "estado = 'PAGADA'" }],
  guard: { allowed: true, sql: null, tables: ["facturas"], violations: [] },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

interface Calls {
  previews: Record<string, unknown>[];
  puts: { model: SemanticModel }[];
}

function setup(handlers: { preview?: () => Response; put?: () => Response } = {}) {
  const calls: Calls = { previews: [], puts: [] };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/auth/me")) return json(session.user);
    if (url.endsWith("/auth/refresh")) return json(session);
    if (url.endsWith("/datasources")) {
      return json([{ id: DS, name: "Ventas (demo)", dialect: "sqlite" }]);
    }
    if (url.endsWith("/semantic/versions")) return json([]);
    if (url.endsWith("/preview")) {
      calls.previews.push(JSON.parse(init?.body as string));
      return (handlers.preview ?? (() => json(previewResult)))();
    }
    if (url.endsWith("/semantic") && init?.method === "PUT") {
      calls.puts.push(JSON.parse(init.body as string));
      return (handlers.put ?? (() => json({})))();
    }
    if (url.endsWith("/semantic")) {
      return json({
        version: 3,
        model: model(),
        created_by: "u1",
        created_at: "2026-11-20T15:00:00Z",
      });
    }
    return json({ error: { code: "not_found", message: "no" } }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MemoryRouter initialEntries={["/modelo-semantico"]}>
      <App />
    </MemoryRouter>,
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

async function openTab(name: string) {
  await userEvent.click(await screen.findByRole("tab", { name }));
}

describe("pestaña Métricas", () => {
  it("lista la métrica y muestra todos sus campos en el editor", async () => {
    setup();
    await openTab("Métricas");

    const list = screen.getByRole("list", { name: "Métricas" });
    expect(within(list).getByText("Ventas netas")).toBeInTheDocument();
    expect(screen.getByLabelText("Nombre de la métrica")).toHaveValue("ventas_netas");
    expect(screen.getByLabelText("Tabla base")).toHaveValue("facturas");
    expect(screen.getByLabelText("Columna de tiempo")).toHaveValue("facturas.fecha");
    expect(screen.getByLabelText("Expresión de la métrica")).toHaveValue("SUM(total)");
    expect(screen.getByLabelText("Filtro de la métrica 1")).toHaveValue("estado = 'PAGADA'");
    expect(screen.getByLabelText("Dimensión 1")).toHaveValue("facturas.canal");
    expect(screen.getByLabelText("Requiere período")).toBeChecked();
    expect(screen.getByLabelText("Aditiva")).toBeChecked();
  });

  it("muestra el error de expresión junto al campo al publicar", async () => {
    setup({
      put: () =>
        json(
          {
            error: {
              code: "invalid_semantic_model",
              message: "El modelo semántico no es válido",
              details: {
                errors: [
                  {
                    path: "metrics[0].expression",
                    message: "SQL inválido: paréntesis sin cerrar",
                  },
                ],
              },
            },
          },
          422,
        ),
    });
    await openTab("Métricas");
    const expression = screen.getByLabelText("Expresión de la métrica");
    await userEvent.clear(expression);
    await userEvent.type(expression, "SUM(total");
    await userEvent.click(screen.getByRole("button", { name: "Publicar" }));

    expect(await screen.findByText("SQL inválido: paréntesis sin cerrar")).toBeInTheDocument();
    expect(expression).toHaveAccessibleDescription("SQL inválido: paréntesis sin cerrar");
  });
});

describe("pestaña Resumidas", () => {
  it("edita granularidad, período en curso y mapeos", async () => {
    const calls = setup({
      put: () =>
        json({
          version: 4,
          created_by: "u1",
          created_at: "2026-11-26T10:00:00Z",
          model: model(),
        }),
    });
    await openTab("Resumidas");

    expect(screen.getByLabelText("Tabla resumida")).toHaveValue("ventas_mensuales");
    expect(screen.getByLabelText("Granularidad")).toHaveValue("month");
    expect(screen.getByLabelText("Columna de tiempo de la resumida")).toHaveValue("mes");
    expect(screen.getByLabelText("Incluye el período en curso")).not.toBeChecked();
    expect(screen.getByLabelText("Expresión de la métrica 1")).toHaveValue("SUM(total_ventas)");

    await userEvent.selectOptions(screen.getByLabelText("Granularidad"), "day");
    await userEvent.click(screen.getByLabelText("Incluye el período en curso"));
    await userEvent.click(screen.getByRole("button", { name: "Agregar dimensión" }));
    await userEvent.selectOptions(screen.getByLabelText("Dimensión 1"), "facturas.canal");
    await userEvent.selectOptions(
      screen.getByLabelText("Columna de la resumida 1"),
      "total_ventas",
    );
    await userEvent.click(screen.getByRole("button", { name: "Publicar" }));

    const [put] = calls.puts;
    expect(put.model.summary_tables?.[0]).toEqual({
      table: "ventas_mensuales",
      grain: "day",
      time_column: "mes",
      includes_current_period: true,
      metrics: { ventas_netas: "SUM(total_ventas)" },
      dimensions: { "facturas.canal": "total_ventas" },
    });
  });

  it("muestra el error de una expresión de la resumida junto a su fila", async () => {
    setup({
      put: () =>
        json(
          {
            error: {
              code: "invalid_semantic_model",
              message: "no válido",
              details: {
                errors: [
                  {
                    path: "summary_tables[0].metrics[ventas_netas]",
                    message: "Expresión inválida",
                  },
                ],
              },
            },
          },
          422,
        ),
    });
    await openTab("Resumidas");
    await userEvent.type(screen.getByLabelText("Expresión de la métrica 1"), " ");
    await userEvent.click(screen.getByRole("button", { name: "Publicar" }));

    expect(await screen.findByText("Expresión inválida")).toBeInTheDocument();
    expect(screen.getByLabelText("Expresión de la métrica 1")).toHaveAccessibleDescription(
      "Expresión inválida",
    );
  });
});

describe("panel «Probar»", () => {
  it("envía métrica, período, dimensiones y filtros, y muestra SQL, tabla y motivo", async () => {
    const calls = setup();
    await openTab("Métricas");
    const panel = screen.getByRole("region", { name: "Probar" });

    await userEvent.type(within(panel).getByLabelText("Período a probar"), "este mes");
    await userEvent.click(within(panel).getByLabelText("facturas.canal"));
    await userEvent.click(within(panel).getByRole("button", { name: "Agregar filtro de prueba" }));
    await userEvent.selectOptions(
      within(panel).getByLabelText("Campo del filtro 1"),
      "facturas.canal",
    );
    await userEvent.type(within(panel).getByLabelText("Valor del filtro 1"), "web");
    await userEvent.click(within(panel).getByRole("button", { name: "Ver SQL" }));

    const result = await within(panel).findByRole("region", {
      name: "Resultado de la prueba",
    });
    expect(calls.previews).toEqual([
      {
        metric: "ventas_netas",
        period: "este mes",
        dimensions: ["facturas.canal"],
        filters: [{ field: "facturas.canal", op: "=", value: "web" }],
      },
    ]);
    expect(within(result).getByText("Tabla resumida: ventas_diarias")).toBeInTheDocument();
    expect(within(result).getByText(/no incluye el mes en curso/)).toBeInTheDocument();
    expect(within(result).getByText(/SELECT/)).toBeInTheDocument();
    expect(within(result).getByText("Período: Noviembre 2026")).toBeInTheDocument();
    expect(within(result).getByText("Guardián: permitido")).toBeInTheDocument();
  });

  it("indica tablas base cuando no hay resumida", async () => {
    setup({
      preview: () =>
        json({
          ...previewResult,
          summary_table: null,
          reason: "Ninguna resumida califica",
        }),
    });
    await openTab("Métricas");
    await userEvent.click(screen.getByRole("button", { name: "Ver SQL" }));

    expect(await screen.findByText("Tablas base")).toBeInTheDocument();
    expect(screen.getByText(/Ninguna resumida califica/)).toBeInTheDocument();
  });

  it("muestra el error del servidor cuando el período no se entiende", async () => {
    setup({
      preview: () =>
        json(
          {
            error: {
              code: "invalid_period",
              message: "No entiendo el período «xyz»",
            },
          },
          422,
        ),
    });
    await openTab("Métricas");
    await userEvent.type(screen.getByLabelText("Período a probar"), "xyz");
    await userEvent.click(screen.getByRole("button", { name: "Ver SQL" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No entiendo el período «xyz»");
  });
});
