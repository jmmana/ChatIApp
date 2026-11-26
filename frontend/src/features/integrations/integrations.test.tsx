import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "@/app/App";
import { setAccessToken } from "@/features/auth/api";
import type { ApiKey } from "./api";

const session = {
  access_token: "jwt",
  expires_in: 900,
  user: { id: "1", email: "admin@example.com", is_admin: true },
};

const portal: ApiKey = {
  id: "k1",
  name: "Portal de clientes",
  prefix: "chia_k7Hx2Lm9",
  scopes: ["chat", "embed"],
  datasources: ["ventas"],
  allowed_roles: ["gerente_sucursal"],
  allowed_origins: ["https://portal.example.com"],
  rate_limit_per_minute: 60,
  monthly_budget_usd: "50",
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
  created_at: "2026-01-01T00:00:00Z",
  usage: { turns: 12, tokens: 3400, cost_usd: 0.42 },
};

const secret = "clave-de-prueba-1234";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

/** Servidor simulado: guarda las keys en memoria y registra las llamadas. */
function stubApi() {
  const keys: ApiKey[] = [];
  const calls: { method: string; url: string; body?: unknown }[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    if (url.endsWith("/auth/me")) return json(session.user);
    if (url.endsWith("/auth/refresh")) return json(session);
    const body = init.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ method, url, body });
    if (method === "POST" && url.endsWith("/revoke")) {
      keys[0] = { ...keys[0], revoked_at: "2026-02-01T00:00:00Z" };
      return json(keys[0]);
    }
    if (method === "POST") {
      keys.push({ ...portal, ...body, usage: null });
      return json({ ...keys[0], secret }, 201);
    }
    if (method === "PATCH") {
      keys[0] = { ...keys[0], ...body };
      return json(keys[0]);
    }
    return json(keys);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { keys, calls };
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/integraciones"]}>
      <App />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe("integraciones", () => {
  it("lista las keys con prefijo, alcances, fuentes, roles, orígenes y consumo", async () => {
    const { keys } = stubApi();
    keys.push(portal);
    renderPage();

    const row = (await screen.findByText("Portal de clientes")).closest("tr")!;
    expect(within(row).getByText("chia_k7Hx2Lm9")).toBeInTheDocument();
    expect(within(row).getByText("chat, embed")).toBeInTheDocument();
    expect(within(row).getByText("ventas")).toBeInTheDocument();
    expect(within(row).getByText("gerente_sucursal")).toBeInTheDocument();
    expect(within(row).getByText("https://portal.example.com")).toBeInTheDocument();
    expect(within(row).getByText("Nunca")).toBeInTheDocument();
    expect(within(row).getByText(/12 turnos · 3400 tokens · US\$ 0\.42/)).toBeInTheDocument();
  });

  it("crea una key, muestra el secreto una vez, lo copia y luego la revoca", async () => {
    const { calls } = stubApi();
    const user = userEvent.setup(); // instala un portapapeles simulado
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Nueva API key/ }));
    await user.type(screen.getByLabelText("Nombre"), "Portal de clientes");
    await user.type(screen.getByLabelText(/Fuentes permitidas/), "ventas");
    await user.click(screen.getByRole("button", { name: "Crear key" }));

    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      name: "Portal de clientes",
      scopes: ["chat"],
      datasources: ["ventas"],
    });
    expect(await screen.findByText(secret)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("no la uses en el navegador");

    await user.click(screen.getByRole("button", { name: "Copiar secreto" }));
    expect(await screen.findByRole("button", { name: "Copiado" })).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe(secret);

    await user.click(screen.getByRole("button", { name: "Listo" }));
    expect(screen.queryByText(secret)).not.toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Revocar Portal de clientes" }));
    expect(calls.some((c) => c.url.endsWith("/revoke"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirmar revocación" }));

    expect(await screen.findByText("Revocada")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/k1/revoke"))).toBe(true);
  });

  it("edita los límites de una key", async () => {
    const { keys, calls } = stubApi();
    keys.push(portal);
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Editar Portal de clientes" }));
    const rate = screen.getByLabelText("Peticiones por minuto");
    await userEvent.clear(rate);
    await userEvent.type(rate, "10");
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    await screen.findByText("Portal de clientes");
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.url).toBe("/api/v1/api-keys/k1");
    expect(patch?.body).toMatchObject({ rate_limit_per_minute: 10, monthly_budget_usd: 50 });
  });

  it("muestra fragmentos con la URL de la instalación", async () => {
    stubApi();
    renderPage();

    expect(await screen.findByRole("button", { name: "Copiar backend" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copiar widget" })).toBeInTheDocument();
    expect(
      screen.getAllByText(new RegExp(`${window.location.origin}/embed/v1/chatiapp.js`)).length,
    ).toBeGreaterThan(0);
  });
});
