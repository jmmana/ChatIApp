import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "./App";
import { appRoutes } from "./routes";

let isAdmin = true;

beforeEach(() => {
  isAdmin = true;
  // La cookie de refresco vigente: la app recupera la sesión al abrir.
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url: string) => {
        // El rol sale de /auth/me; el usuario de refresh no cuenta.
        const user = { id: "1", email: "ana@example.com", is_admin: isAdmin };
        let body: unknown = url.endsWith("/auth/me")
          ? user
          : {
              access_token: "jwt",
              expires_in: 900,
              user: { ...user, is_admin: !isAdmin },
            };
        if (url.includes("/datasources") || url.includes("/providers") || url.includes("/evals"))
          body = [];
        else if (url.includes("/audit")) body = { items: [], total: 0, page: 1, page_size: 25 };
        return new Response(JSON.stringify(body), { status: 200 });
      },
    ),
  );
});

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
  it("muestra la barra lateral con las ocho secciones", async () => {
    await renderAt("/chat");
    const nav = screen.getByRole("navigation", { name: "Principal" });
    for (const title of [
      "Chat",
      "Modelo semántico",
      "Proveedores de IA",
      "Fuentes de datos",
      "Integraciones",
      "Usuarios",
      "Auditoría",
      "Evaluación",
    ]) {
      expect(within(nav).getByRole("link", { name: title })).toBeInTheDocument();
    }
  });

  it("redirige la raíz al chat", async () => {
    await renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Chat" })).toBeInTheDocument();
  });

  it("cada ruta muestra un estado vacío con su título", async () => {
    await renderAt("/chat");
    const nav = screen.getByRole("navigation", { name: "Principal" });
    for (const route of appRoutes) {
      await userEvent.click(within(nav).getByRole("link", { name: route.title }));
      expect(screen.getByRole("heading", { level: 1, name: route.title })).toBeInTheDocument();
    }
  });

  it("oculta las pantallas de administración a quien no es administrador", async () => {
    isAdmin = false;
    await renderAt("/chat");
    const nav = screen.getByRole("navigation", { name: "Principal" });
    expect(within(nav).getByRole("link", { name: "Chat" })).toBeInTheDocument();
    for (const route of appRoutes.filter((r) => r.adminOnly)) {
      expect(within(nav).queryByRole("link", { name: route.title })).not.toBeInTheDocument();
    }
  });

  it("muestra «Necesitas permisos de administrador» si entra por URL", async () => {
    isAdmin = false;
    await renderAt("/integraciones");
    expect(await screen.findByText("Necesitas permisos de administrador")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Integraciones" })).not.toBeInTheDocument();
  });

  it("el administrador ve la pantalla de administración", async () => {
    await renderAt("/integraciones");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Integraciones" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Necesitas permisos de administrador")).not.toBeInTheDocument();
  });
});
