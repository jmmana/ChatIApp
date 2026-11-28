import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "@/app/App";
import { setAccessToken } from "@/features/auth/api";
import type { SemanticModel } from "./types";

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
    business_context: "Tienda de ropa.",
    settings: { timezone: "America/Bogota", week_starts_on: "monday" },
    tables: [
      {
        name: "clientes",
        description: "Clientes.",
        columns: [
          { name: "id", description: "Identificador", role: "id" },
          { name: "nombre", description: "Nombre", role: "dimension" },
        ],
      },
      {
        name: "facturas",
        description: "Encabezado de cada factura.",
        synonyms: ["ventas"],
        columns: [
          { name: "id", description: "Identificador", role: "id" },
          { name: "cliente_id", role: "other" },
          { name: "total", description: "Valor cobrado", role: "measure" },
          { name: "canal", role: "dimension" },
        ],
      },
    ],
    relationships: [{ from: "facturas.cliente_id", to: "clientes.id" }],
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

interface Calls {
  puts: { base_version: number; model: SemanticModel }[];
}

function setup(put: (calls: Calls) => Response, current = { version: 12, model: baseModel() }) {
  const calls: Calls = { puts: [] };
  let live = {
    ...current,
    created_by: "u1",
    created_at: "2026-11-20T15:00:00Z",
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/auth/me")) return json(session.user);
    if (url.endsWith("/auth/refresh")) return json(session);
    if (url.endsWith("/datasources")) {
      return json([{ id: DS, name: "Ventas (demo)", dialect: "sqlite" }]);
    }
    if (url.endsWith("/semantic/versions")) {
      return json([
        { version: 12, created_by: "u1", created_at: "2026-11-20T15:00:00Z" },
        {
          version: 11,
          created_by: "otro-usuario-id",
          created_at: "2026-11-18T10:00:00Z",
        },
      ]);
    }
    if (url.endsWith("/semantic") && init?.method === "PUT") {
      calls.puts.push(JSON.parse(init.body as string));
      const response = put(calls);
      if (response.ok) live = { ...live, ...(await response.clone().json()) };
      return response;
    }
    if (url.endsWith("/semantic")) return json(live);
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

describe("estudio del modelo", () => {
  it("lista las tablas con buscador y conteo de columnas sin descripción", async () => {
    setup(() => json({}));

    expect(await screen.findByRole("heading", { level: 2, name: "clientes" })).toBeInTheDocument();
    expect(screen.getByText("2 columnas sin descripción")).toBeInTheDocument();
    expect(screen.getByText("v12 · guardado")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Buscar tabla"), "fact");
    const list = screen.getByRole("list", { name: "Tablas" });
    expect(within(list).getAllByRole("button")).toHaveLength(1);
    await userEvent.click(within(list).getByRole("button", { name: /facturas/ }));
    expect(screen.getByRole("heading", { level: 2, name: "facturas" })).toBeInTheDocument();
  });

  it("edita una columna y publica con base_version", async () => {
    const calls = setup((c) =>
      json({
        version: 13,
        created_by: "u1",
        created_at: "2026-11-26T10:00:00Z",
        model: c.puts[0].model,
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /facturas/ }));

    await userEvent.type(screen.getByLabelText("Descripción de canal"), "Canal de venta");
    await userEvent.type(screen.getByLabelText("Sinónimos de canal"), "origen{Enter}");
    await userEvent.type(screen.getByLabelText("Valores de ejemplo de canal"), "web,tienda,");
    await userEvent.selectOptions(screen.getByLabelText("Rol de canal"), "dimension");
    await userEvent.click(screen.getByRole("switch", { name: "Oculta: canal" }));
    expect(screen.getByText("v12 · cambios sin publicar")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Publicar" }));

    expect(await screen.findByText("v13 · guardado")).toBeInTheDocument();
    expect(calls.puts).toHaveLength(1);
    expect(calls.puts[0].base_version).toBe(12);
    const canal = calls.puts[0].model.tables?.[1].columns?.[3];
    expect(canal).toMatchObject({
      name: "canal",
      description: "Canal de venta",
      synonyms: ["origen"],
      sample_values: ["web", "tienda"],
      role: "dimension",
      hidden: true,
    });
    expect(screen.getByRole("button", { name: "Publicar" })).toBeDisabled();
  });

  it("muestra los errores 422 junto a su campo", async () => {
    setup(() =>
      json(
        {
          error: {
            code: "invalid_semantic_model",
            message: "El modelo semántico no es válido",
            details: {
              errors: [
                {
                  path: "tables[1].columns[2].description",
                  message: "Descripción inválida",
                },
              ],
            },
          },
        },
        422,
      ),
    );
    await userEvent.click(await screen.findByRole("button", { name: /facturas/ }));
    await userEvent.type(screen.getByLabelText("Descripción de canal"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Publicar" }));

    const message = await screen.findByText("Descripción inválida");
    expect(message.id).not.toBe("");
    expect(screen.getByLabelText("Descripción de total")).toHaveAccessibleDescription(
      "Descripción inválida",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("el error");
  });

  it("ante un 409 ofrece recargar el modelo vigente", async () => {
    setup(() =>
      json(
        {
          error: {
            code: "version_conflict",
            message: "Alguien publicó antes",
            details: { current_version: 13 },
          },
        },
        409,
      ),
    );
    await userEvent.click(await screen.findByRole("button", { name: /facturas/ }));
    await userEvent.type(screen.getByLabelText("Descripción de canal"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Publicar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("versión 13");
    await userEvent.click(screen.getByRole("button", { name: "Recargar" }));

    expect(await screen.findByText("v12 · guardado")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Recargar" })).not.toBeInTheDocument();
  });

  it("agrega y quita relaciones con selectores tabla.columna", async () => {
    const calls = setup((c) =>
      json({
        version: 13,
        created_by: "u1",
        created_at: "2026-11-26T10:00:00Z",
        model: c.puts[0].model,
      }),
    );
    await userEvent.click(await screen.findByRole("tab", { name: "Relaciones" }));

    expect(screen.getByLabelText("Desde, relación 1")).toHaveValue("facturas.cliente_id");
    await userEvent.click(screen.getByRole("button", { name: "Agregar relación" }));
    await userEvent.selectOptions(screen.getByLabelText("Desde, relación 2"), "facturas.id");
    await userEvent.selectOptions(screen.getByLabelText("Hacia, relación 2"), "clientes.id");
    await userEvent.click(screen.getByRole("button", { name: "Quitar relación 1" }));
    await userEvent.click(screen.getByRole("button", { name: "Publicar" }));

    await screen.findByText("v13 · guardado");
    expect(calls.puts[0].model.relationships).toEqual([{ from: "facturas.id", to: "clientes.id" }]);
  });

  it("edita el contexto del negocio y la configuración regional", async () => {
    const calls = setup((c) =>
      json({
        version: 13,
        created_by: "u1",
        created_at: "2026-11-26T10:00:00Z",
        model: c.puts[0].model,
      }),
    );
    await userEvent.click(await screen.findByRole("tab", { name: "Contexto" }));

    const context = screen.getByLabelText("Contexto del negocio");
    await userEvent.clear(context);
    await userEvent.type(context, "Vendemos zapatos");
    await userEvent.type(screen.getByLabelText("Moneda"), "COP");
    await userEvent.type(screen.getByLabelText("Locale"), "es-CO");
    await userEvent.selectOptions(screen.getByLabelText("Inicio de semana"), "sunday");
    await userEvent.selectOptions(screen.getByLabelText("Inicio del año fiscal"), "4");
    await userEvent.click(screen.getByRole("button", { name: "Publicar" }));

    await screen.findByText("v13 · guardado");
    expect(calls.puts[0].model.business_context).toBe("Vendemos zapatos");
    expect(calls.puts[0].model.settings).toMatchObject({
      timezone: "America/Bogota",
      currency: "COP",
      locale: "es-CO",
      week_starts_on: "sunday",
      fiscal_year_start_month: 4,
    });
  });

  it("muestra el historial con fecha y autor", async () => {
    setup(() => json({}));
    await userEvent.click(await screen.findByRole("tab", { name: "Historial" }));

    const table = await screen.findByRole("table", {
      name: "Historial de versiones",
    });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("v12");
    expect(rows[1]).toHaveTextContent("ana@example.com");
    expect(rows[2]).toHaveTextContent("Usuario otro-usu");
  });

  it("se puede recorrer con el teclado", async () => {
    setup(() => json({}));
    await screen.findByRole("heading", { level: 2, name: "clientes" });

    const tab = screen.getByRole("tab", { name: "Tablas" });
    tab.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Relaciones" })).toHaveFocus();

    await userEvent.keyboard("{ArrowLeft}");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Publicar" })).not.toHaveFocus();
  });
});
