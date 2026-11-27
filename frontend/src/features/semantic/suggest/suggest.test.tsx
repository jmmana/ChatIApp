import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "@/app/App";
import { setAccessToken } from "@/features/auth/api";
import type { SemanticModel } from "../types";
import { applySuggestions, type Suggestion } from "./suggest";

const DS = "11111111-1111-1111-1111-111111111111";
const session = {
  access_token: "jwt-en-memoria",
  expires_in: 900,
  user: { id: "u1", email: "ana@example.com", is_admin: true },
};

function baseModel(): SemanticModel {
  return {
    version: 1,
    name: "Ventas (demo)",
    tables: [
      {
        name: "facturas",
        description: "Encabezado de cada factura.",
        columns: [
          { name: "total", description: "Valor cobrado", role: "measure" },
          { name: "canal", role: "other" },
        ],
      },
    ],
  };
}

const SUGGESTIONS: Suggestion[] = [
  { path: "facturas.canal", field: "description", value: "Canal de venta", confidence: 0.9 },
  { path: "facturas.canal", field: "role", value: "dimension", confidence: 0.6 },
  { path: "facturas", field: "synonyms", value: ["ventas", "comprobantes"], confidence: 0.8 },
];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function setup(suggest: () => Response) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/auth/refresh")) return json(session);
    if (url.endsWith("/datasources")) return json([{ id: DS, name: "Ventas", dialect: "sqlite" }]);
    if (url.endsWith("/semantic/suggest")) return suggest();
    if (url.endsWith("/semantic/versions")) return json([]);
    if (url.endsWith("/semantic") && init?.method === "GET") {
      return json({ version: 3, created_by: "u1", created_at: "2026-11-20", model: baseModel() });
    }
    return json({ error: { code: "not_found", message: "no" } }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MemoryRouter initialEntries={["/modelo-semantico"]}>
      <App />
    </MemoryRouter>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe("applySuggestions", () => {
  it("rellena lo vacío y nunca pisa lo existente", () => {
    const model = baseModel();
    const next = applySuggestions(model, [
      ...SUGGESTIONS,
      { path: "facturas.total", field: "description", value: "Otro", confidence: 1 },
    ]);

    expect(next.tables?.[0].synonyms).toEqual(["ventas", "comprobantes"]);
    expect(next.tables?.[0].columns?.[1]).toMatchObject({
      description: "Canal de venta",
      role: "dimension",
    });
    expect(next.tables?.[0].columns?.[0].description).toBe("Valor cobrado");
    expect(model.tables?.[0].synonyms).toBeUndefined();
  });
});

describe("Sugerir con IA", () => {
  it("acepta una sugerencia, descarta otra y acepta el resto", async () => {
    setup(() => json(SUGGESTIONS));
    await userEvent.click(await screen.findByRole("button", { name: "Sugerir con IA" }));

    expect(await screen.findByText("3 sugerencias")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Aceptar Descripción de facturas.canal" }));
    expect(screen.getByText("2 sugerencias")).toBeInTheDocument();
    expect(screen.getByText("v3 · cambios sin publicar")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Descartar Rol de facturas.canal" }));
    expect(screen.getByText("1 sugerencia")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Aceptar todas" }));
    expect(screen.getByText("No hay sugerencias pendientes.")).toBeInTheDocument();
  });

  it("descarta todas sin cambiar el modelo", async () => {
    setup(() => json(SUGGESTIONS));
    await userEvent.click(await screen.findByRole("button", { name: "Sugerir con IA" }));
    await userEvent.click(await screen.findByRole("button", { name: "Descartar todas" }));

    expect(screen.getByText("No hay sugerencias pendientes.")).toBeInTheDocument();
    expect(screen.getByText("v3 · guardado")).toBeInTheDocument();
  });

  it("muestra el error cuando la IA no responde", async () => {
    setup(() =>
      json({ error: { code: "ai_unavailable", message: "La IA no pudo generar sugerencias" } }, 502),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Sugerir con IA" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("La IA no pudo generar sugerencias");
  });
});
