import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "@/app/App";
import { getAccessToken, setAccessToken } from "./api";

const session = {
  access_token: "jwt-en-memoria",
  expires_in: 900,
  user: { id: "1", email: "ana@example.com", is_admin: false },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
  localStorage.clear();
});

describe("autenticación", () => {
  it("sin sesión redirige al login", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ error: { message: "No hay sesión activa." } }, 401)),
    );

    renderAt("/chat");

    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
  });

  it("inicia sesión, guarda el token solo en memoria y entra a la app", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/refresh")) return json({}, 401);
      if (url.endsWith("/me")) return json(session.user);
      return json(session);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAt("/chat");

    await userEvent.type(await screen.findByLabelText("Correo electrónico"), "ana@example.com");
    await userEvent.type(screen.getByLabelText("Contraseña"), "clave");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Chat" })).toBeInTheDocument();
    expect(getAccessToken()).toBe("jwt-en-memoria");
    expect(localStorage.length).toBe(0);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("muestra el error cuando las credenciales son incorrectas", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ error: { message: "Correo o contraseña incorrectos." } }, 401)),
    );
    renderAt("/login");

    await userEvent.type(await screen.findByLabelText("Correo electrónico"), "ana@example.com");
    await userEvent.type(screen.getByLabelText("Contraseña"), "mala");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Correo o contraseña incorrectos.");
  });

  it("cerrar sesión vuelve al login y descarta el token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/logout")
          ? new Response(null, { status: 204 })
          : url.endsWith("/me")
            ? json(session.user)
            : json(session),
      ),
    );
    renderAt("/chat");

    await userEvent.click(await screen.findByRole("button", { name: /Cerrar sesión/ }));

    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
  });
});
