import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "@/app/App";
import { setAccessToken } from "@/features/auth/api";
import type { SemanticModel } from "../types";
import { attributesIn, conditionProblem, parseAttributes, summaryWarnings } from "./rules";

const DS = "11111111-1111-1111-1111-111111111111";
const session = {
  access_token: "jwt-en-memoria",
  expires_in: 900,
  user: { id: "u1", email: "ana@example.com", is_admin: true },
};

/** Recorte de la demo `examples/ventas`: facturas con su resumida, y un rol por sucursal. */
function demoModel(): SemanticModel {
  return {
    version: 1,
    name: "Ventas (demo)",
    tables: [
      { name: "clientes", columns: [{ name: "id", role: "id" }] },
      { name: "facturas", columns: [{ name: "sucursal_id", role: "dimension" }] },
      { name: "ventas_diarias", columns: [{ name: "sucursal_id", role: "dimension" }] },
    ],
    metrics: [
      {
        name: "ventas_netas",
        label: "Ventas netas",
        table: "facturas",
        expression: "SUM(total)",
        time_column: "fecha",
      },
    ],
    summary_tables: [
      {
        table: "ventas_diarias",
        grain: "day",
        time_column: "fecha",
        metrics: { ventas_netas: "SUM(total)" },
      },
    ],
    security: {
      default_role: "gerente_sucursal",
      roles: [
        {
          name: "gerente_sucursal",
          filters: [{ table: "facturas", condition: "sucursal_id IN ({user.sucursales})" }],
        },
        { name: "mercadeo", hidden_tables: ["clientes"] },
      ],
    },
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

interface Calls {
  previews: Record<string, unknown>[];
  validations: Record<string, unknown>[];
}

function setup(model: SemanticModel = demoModel()) {
  const calls: Calls = { previews: [], validations: [] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/me")) return json(session.user);
      if (url.endsWith("/auth/refresh")) return json(session);
      if (url.endsWith("/datasources")) {
        return json([{ id: DS, name: "Ventas (demo)", dialect: "sqlite" }]);
      }
      if (url.endsWith("/preview")) {
        const body = JSON.parse(init?.body as string);
        calls.previews.push(body);
        if (!body.view_as.attributes.sucursales) {
          return json(
            { error: { code: "missing_attributes", message: "Falta el atributo «sucursales»" } },
            422,
          );
        }
        return json({
          sql: "SELECT SUM(total) FROM (SELECT * FROM facturas WHERE sucursal_id IN (1, 2)) AS facturas",
          metric: "ventas_netas",
          role: body.view_as.role,
          summary_table: null,
          reason: "Se usan las tablas base.",
          filters_applied: [{ source: "role", text: "sucursal_id IN (1, 2)" }],
          guard: { allowed: true, sql: null, tables: ["facturas"], violations: [] },
        });
      }
      if (url.endsWith("/validate-sql")) {
        calls.validations.push(JSON.parse(init?.body as string));
        return json({
          allowed: false,
          sql: null,
          tables: ["clientes"],
          violations: [{ code: "table_hidden", message: "La tabla «clientes» no está disponible" }],
          role: "mercadeo",
        });
      }
      if (url.endsWith("/semantic/versions")) return json([]);
      if (url.endsWith("/semantic")) {
        return json({ version: 3, model, created_by: "u1", created_at: "2026-11-20T15:00:00Z" });
      }
      return json({ error: { code: "not_found", message: "no" } }, 404);
    }),
  );
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

describe("reglas de seguridad", () => {
  it("valida condiciones y extrae atributos", () => {
    expect(conditionProblem("sucursal_id IN ({user.sucursales})")).toBeNull();
    expect(conditionProblem("  ")).toMatch(/vacía/);
    expect(conditionProblem("a = {user.}")).toMatch(/Marcador/);
    expect(conditionProblem("(a = 1")).toMatch(/paréntesis/);
    expect(conditionProblem("a = 'x")).toMatch(/comilla/);
    expect(attributesIn("a = {user.x} AND b = {user.x} OR c = {user.y}")).toEqual(["x", "y"]);
  });

  it("interpreta atributos como JSON o texto", () => {
    expect(parseAttributes('sucursales = [1, 2]\nregion = norte\nn = 5\nz = "a"')).toEqual({
      attributes: { sucursales: [1, 2], region: "norte", n: 5, z: "a" },
      error: null,
    });
    expect(parseAttributes("sin igual").error).toMatch(/Línea 1/);
  });

  it("avisa de resumidas sin filtro y no avisa si el rol las cubre", () => {
    const model = demoModel();
    expect(summaryWarnings(model)).toEqual([
      { role: "gerente_sucursal", table: "facturas", summary: "ventas_diarias" },
    ]);
    model.security!.roles![0].filters!.push({
      table: "ventas_diarias",
      condition: "sucursal_id IN ({user.sucursales})",
    });
    expect(summaryWarnings(model)).toEqual([]);
  });
});

describe("pestaña Seguridad", () => {
  it("muestra roles, filtros, tablas ocultas, rol por defecto y la advertencia", async () => {
    setup();
    await userEvent.click(await screen.findByRole("tab", { name: "Seguridad" }));

    expect(screen.getByLabelText("Rol por defecto")).toHaveValue("gerente_sucursal");
    expect(within(screen.getByRole("list", { name: "Roles" })).getAllByRole("button")).toHaveLength(2);
    expect(screen.getByLabelText("Condición del filtro 1")).toHaveValue(
      "sucursal_id IN ({user.sucursales})",
    );
    expect(screen.getByRole("alert", { name: "Advertencias de seguridad" })).toHaveTextContent(
      "«ventas_diarias» no tiene filtro",
    );

    await userEvent.click(screen.getByRole("button", { name: /mercadeo/ }));
    expect(screen.getByRole("switch", { name: "Ocultar tabla clientes" })).toBeChecked();
  });

  it("agrega un filtro para la resumida y la advertencia desaparece", async () => {
    setup();
    await userEvent.click(await screen.findByRole("tab", { name: "Seguridad" }));

    await userEvent.click(screen.getByRole("button", { name: "Agregar filtro" }));
    await userEvent.selectOptions(screen.getByLabelText("Tabla del filtro 2"), "ventas_diarias");
    await userEvent.type(screen.getByLabelText("Condición del filtro 2"), "(sucursal_id = 1");
    expect(screen.getByText("Hay un paréntesis sin cerrar.")).toBeInTheDocument();
    expect(screen.getByLabelText("Condición del filtro 2")).toBeInvalid();
    await userEvent.type(screen.getByLabelText("Condición del filtro 2"), ")");

    expect(screen.queryByRole("alert", { name: "Advertencias de seguridad" })).not.toBeInTheDocument();
    expect(screen.getByText("v3 · cambios sin publicar")).toBeInTheDocument();
  });

  it("crea un rol y lo hace el rol por defecto", async () => {
    setup();
    await userEvent.click(await screen.findByRole("tab", { name: "Seguridad" }));

    await userEvent.type(screen.getByLabelText("Nombre del rol nuevo"), "auditor");
    await userEvent.click(screen.getByRole("button", { name: "Rol" }));
    await userEvent.selectOptions(screen.getByLabelText("Rol por defecto"), "auditor");

    expect(screen.getByRole("region", { name: "Rol auditor" })).toBeInTheDocument();
    expect(screen.getByLabelText("Rol por defecto")).toHaveValue("auditor");
  });
});

describe("panel «Ver como»", () => {
  it("muestra el SQL con el filtro inyectado para una métrica", async () => {
    const calls = setup();
    await userEvent.click(await screen.findByRole("tab", { name: "Seguridad" }));
    const panel = screen.getByRole("region", { name: "Ver como" });

    await userEvent.type(within(panel).getByLabelText("Atributos del usuario"), "sucursales = [[1, 2]");
    await userEvent.type(within(panel).getByLabelText("Período"), "este mes");
    await userEvent.click(within(panel).getByRole("button", { name: "Ver SQL" }));

    expect(await within(panel).findByLabelText("SQL resultante")).toHaveTextContent(
      "sucursal_id IN (1, 2)",
    );
    expect(calls.previews[0]).toEqual({
      metric: "ventas_netas",
      period: "este mes",
      view_as: { role: "gerente_sucursal", attributes: { sucursales: [1, 2] } },
    });
    expect(within(panel).getByText("El guardián permite la consulta.")).toBeInTheDocument();
    expect(within(panel).getByRole("list", { name: "Filtros aplicados" })).toHaveTextContent(
      "role: sucursal_id IN (1, 2)",
    );
  });

  it("falla cerrado: muestra el error si faltan atributos", async () => {
    setup();
    await userEvent.click(await screen.findByRole("tab", { name: "Seguridad" }));
    const panel = screen.getByRole("region", { name: "Ver como" });

    await userEvent.click(within(panel).getByRole("button", { name: "Ver SQL" }));

    expect(await within(panel).findByRole("alert")).toHaveTextContent("Falta el atributo");
  });

  it("valida un SQL y muestra las violaciones del guardián", async () => {
    const calls = setup();
    await userEvent.click(await screen.findByRole("tab", { name: "Seguridad" }));
    const panel = screen.getByRole("region", { name: "Ver como" });

    await userEvent.selectOptions(within(panel).getByLabelText("Rol"), "mercadeo");
    await userEvent.click(within(panel).getByLabelText("SQL"));
    await userEvent.type(within(panel).getByLabelText("SQL a probar"), "SELECT * FROM clientes");
    await userEvent.click(within(panel).getByRole("button", { name: "Ver SQL" }));

    expect(await within(panel).findByText("El guardián rechaza la consulta.")).toBeInTheDocument();
    expect(within(panel).getByRole("list", { name: "Violaciones" })).toHaveTextContent(
      "«clientes» no está disponible",
    );
    expect(calls.validations[0]).toEqual({
      sql: "SELECT * FROM clientes",
      view_as: { role: "mercadeo", attributes: {} },
    });
  });
});
