import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "./App";
import { appRoutes } from "./routes";

function mockSession(admin: boolean) {
  const session = {
    access_token: "jwt",
    expires_in: 900,
    user: { id: "1", email: "ana@example.com", is_admin: admin },
  };
  const fetchMock = vi.fn(async (url: string) => {
    const body = url.endsWith("/auth/me")
      ? session.user
      : url.includes("/datasources")
        ? []
        : session;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  await screen.findByRole("navigation", { name: "Principal" });
}

describe("Layout", () => {
  it("muestra las secciones administrativas en el menú de administrador", async () => {
    const fetchMock = mockSession(true);
    await renderAt("/chat");
    const nav = screen.getByRole("navigation", { name: "Principal" });
    for (const title of [
      "Chat",
      "Modelo semántico",
      "Proveedores de IA",
      "Fuentes de datos",
      "Integraciones",
      "Auditoría",
      "Evaluación",
    ]) {
      expect(within(nav).getByRole("link", { name: title })).toBeInTheDocument();
    }
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/auth/me"))).toHaveLength(1);
  });

  it("oculta las rutas administrativas del menú para quien no es administrador", async () => {
    mockSession(false);
    await renderAt("/chat");
    const nav = screen.getByRole("navigation", { name: "Principal" });
    expect(within(nav).getByRole("link", { name: "Chat" })).toBeInTheDocument();
    for (const route of appRoutes.filter(({ adminOnly }) => adminOnly)) {
      expect(within(nav).queryByRole("link", { name: route.title })).not.toBeInTheDocument();
    }
  });

  it("bloquea el acceso directo a una ruta administrativa para un no administrador", async () => {
    const fetchMock = mockSession(false);
    await renderAt("/integraciones");

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Necesitas permisos de administrador",
      }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url.includes("/api-keys"))).toBe(false);
  });

  it("redirige la raíz al chat", async () => {
    mockSession(true);
    await renderAt("/");
    expect(screen.getByRole("heading", { level: 1, name: "Chat" })).toBeInTheDocument();
  });

  it("cada ruta muestra un estado vacío con su título", async () => {
    mockSession(true);
    await renderAt("/chat");
    const nav = screen.getByRole("navigation", { name: "Principal" });
    for (const route of appRoutes) {
      await userEvent.click(within(nav).getByRole("link", { name: route.title }));
      expect(screen.getByRole("heading", { level: 1, name: route.title })).toBeInTheDocument();
    }
  });
});
