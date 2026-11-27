import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "@/app/App";
import { setAccessToken } from "@/features/auth/api";
import type { ManagedUser } from "./api";

const session = {
  access_token: "jwt",
  expires_in: 900,
  user: { id: "1", email: "admin@example.com", is_admin: true },
};

const ana: ManagedUser = { id: "u1", email: "ana@example.com", is_admin: false, grants: [] };

const ventas = {
  id: "d1",
  name: "Ventas",
  dialect: "sqlite",
  url: "sqlite:///x.db",
  execute: true,
  max_rows: 1000,
  timeout_seconds: 30,
  privacy: "schema",
  managed_by: "ui",
};

const semantic = {
  version: 1,
  model: {
    security: {
      roles: [
        { name: "gerencia_general" },
        {
          name: "gerente_sucursal",
          filters: [{ table: "facturas", condition: "sucursal_id IN ({user.sucursales})" }],
        },
      ],
    },
  },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function stubApi() {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      if (url.includes("/auth/")) return json(session);
      const body = init.body ? JSON.parse(init.body as string) : undefined;
      calls.push({ method, url, body });
      if (url.endsWith("/grants")) return json({ ...ana, grants: body.grants });
      if (url.endsWith("/semantic")) return json(semantic);
      if (url.endsWith("/datasources")) return json([ventas]);
      return json([ana]);
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe("usuarios", () => {
  it("lista los usuarios", async () => {
    stubApi();
    render(
      <MemoryRouter initialEntries={["/usuarios"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByText("ana@example.com")).toBeInTheDocument();
    expect(screen.getByText("Sin acceso a fuentes")).toBeInTheDocument();
  });

  it("asigna rol y atributos por fuente", async () => {
    const calls = stubApi();
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/usuarios"]}>
        <App />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "Permisos de ana@example.com" }));
    const select = await screen.findByLabelText(/Rol en Ventas/);
    await screen.findByRole("option", { name: "gerente_sucursal" });
    await user.selectOptions(select, "gerente_sucursal");
    await user.type(screen.getByLabelText(/Atributo «sucursales»/), "1, 2");
    await user.click(screen.getByRole("button", { name: "Guardar permisos" }));

    const put = calls.find((c) => c.method === "PUT");
    expect(put?.url).toBe("/api/v1/users/u1/grants");
    expect(put?.body).toEqual({
      grants: [{ datasource_id: "d1", role: "gerente_sucursal", attributes: { sucursales: [1, 2] } }],
    });
  });
});
