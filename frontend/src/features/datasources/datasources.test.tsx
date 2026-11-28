import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { setAccessToken } from "@/features/auth/api";
import type { Datasource } from "./api";
import { DatasourcesPage } from "./DatasourcesPage";

const ventas: Datasource = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Ventas",
  dialect: "postgres",
  url: "postgresql+psycopg://***:***@db:5432/ventas",
  execute: true,
  max_rows: 500,
  timeout_seconds: 20,
  privacy: "aggregates",
  managed_by: "ui",
  last_test_ok: null,
  last_test_at: null,
  last_test_error_kind: null,
};

const demo: Datasource = {
  ...ventas,
  id: "22222222-2222-2222-2222-222222222222",
  name: "Demo",
  dialect: "sqlite",
  url: "sqlite:///./demo/ventas.db",
  execute: false,
  privacy: "schema",
  managed_by: "config",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function mockApi(options: { admin?: boolean; test?: unknown; list?: Datasource[] } = {}) {
  const { admin = true, test, list = [ventas, demo] } = options;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/auth/me"))
      return json({ id: "1", email: "ana@example.com", is_admin: admin });
    if (url.endsWith("/auth/refresh"))
      return json({
        access_token: "jwt",
        expires_in: 900,
        user: { id: "1", email: "ana@example.com", is_admin: admin },
      });
    if (url.endsWith("/test")) return json(test);
    if (init?.method === "POST") return json({ ...ventas, id: "nuevo" }, 201);
    if (init?.method === "PATCH") return json(ventas);
    return json(list);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <DatasourcesPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function bodyOf(fetchMock: ReturnType<typeof mockApi>, method: string) {
  const call = writeCall(fetchMock, method);
  expect(call).toBeDefined();
  return JSON.parse(call![1]!.body as string) as Record<string, unknown>;
}

// Escrituras a /datasources (el refresco de sesión también es POST, pero a /auth).
function writeCall(fetchMock: ReturnType<typeof mockApi>, method: string) {
  return fetchMock.mock.calls.find(
    ([url, init]) => url.startsWith("/api/v1/datasources") && init?.method === method,
  );
}

beforeEach(() => {
  // jsdom no trae ResizeObserver y el Switch de Radix lo usa.
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

describe("lista de fuentes de datos", () => {
  it("muestra dialecto, modo, privacidad y la etiqueta de las gestionadas por configuración", async () => {
    mockApi();
    renderPage();

    const row = await screen.findByRole("listitem", { name: "Ventas" });
    expect(within(row).getByText("PostgreSQL")).toBeInTheDocument();
    expect(within(row).getByText("Ejecuta")).toBeInTheDocument();
    expect(within(row).getByText("Privacidad: Agregados")).toBeInTheDocument();
    expect(within(row).getByText(/sin probar/)).toBeInTheDocument();
    expect(within(row).queryByText("gestionada por configuración")).not.toBeInTheDocument();

    const managed = screen.getByRole("listitem", { name: "Demo" });
    expect(within(managed).getByText("Solo SQL")).toBeInTheDocument();
    expect(within(managed).getByText("gestionada por configuración")).toBeInTheDocument();
    // Solo lectura: no se puede editar.
    expect(within(managed).queryByRole("button", { name: /Editar/ })).not.toBeInTheDocument();
  });

  it("oculta las acciones de administración a quien no es administrador", async () => {
    mockApi({ admin: false });
    renderPage();

    await screen.findByRole("listitem", { name: "Ventas" });
    expect(screen.queryByRole("button", { name: "Nueva fuente" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Probar conexión/ })).not.toBeInTheDocument();
  });
});

describe("formulario", () => {
  it("crea una fuente con la ayuda de URL del dialecto elegido", async () => {
    const fetchMock = mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: /Nueva fuente/ }));
    await userEvent.type(screen.getByLabelText("Nombre"), "Mi base");
    await userEvent.selectOptions(screen.getByLabelText("Dialecto"), "mysql");
    expect(screen.getByText("mysql+pymysql://chatiapp_ro:***@host:3306/ventas")).toBeInTheDocument();

    const url = screen.getByLabelText("URL de conexión");
    expect(url).toHaveAttribute("type", "password");
    await userEvent.type(url, "mysql+pymysql://u:p@h/ventas");
    await userEvent.click(screen.getByRole("switch", { name: "Ejecutar consultas" }));
    await userEvent.selectOptions(screen.getByLabelText("Privacidad"), "samples");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await vi.waitFor(() => expect(bodyOf(fetchMock, "POST")).toBeDefined());
    expect(bodyOf(fetchMock, "POST")).toEqual({
      name: "Mi base",
      dialect: "mysql",
      url: "mysql+pymysql://u:p@h/ventas",
      execute: true,
      max_rows: 1000,
      timeout_seconds: 30,
      privacy: "samples",
    });
  });

  it("valida antes de enviar", async () => {
    const fetchMock = mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: /Nueva fuente/ }));
    await userEvent.type(screen.getByLabelText("Nombre"), "Mi base");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Escribe la URL de conexión.");
    expect(writeCall(fetchMock, "POST")).toBeUndefined();
  });

  it("al editar muestra la URL enmascarada y no la reenvía si no cambia", async () => {
    const fetchMock = mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Editar Ventas" }));
    const url = screen.getByLabelText("URL de conexión");
    expect(url).toHaveValue("");
    expect(url).toHaveAttribute("placeholder", ventas.url);

    await userEvent.clear(screen.getByLabelText("Máximo de filas"));
    await userEvent.type(screen.getByLabelText("Máximo de filas"), "800");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await vi.waitFor(() => expect(bodyOf(fetchMock, "PATCH")).toBeDefined());
    const body = bodyOf(fetchMock, "PATCH");
    expect(body).not.toHaveProperty("url");
    expect(body).toMatchObject({ name: "Ventas", max_rows: 800, privacy: "aggregates" });
  });
});

describe("último resultado guardado", () => {
  it("muestra la prueba correcta y su fecha al cargar, sin volver a probar", async () => {
    const fetchMock = mockApi({
      list: [{ ...ventas, last_test_ok: true, last_test_at: "2026-11-27T10:30:00Z" }],
    });
    renderPage();

    const row = await screen.findByRole("listitem", { name: "Ventas" });
    expect(within(row).getByText(/Última prueba: correcta · /)).toHaveTextContent("2026");
    expect(within(row).queryByText(/sin probar/)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith("/test"))).toBe(false);
  });

  it("muestra el tipo de error guardado, sin mensaje", async () => {
    mockApi({
      list: [
        {
          ...ventas,
          last_test_ok: false,
          last_test_at: "2026-11-27T10:30:00Z",
          last_test_error_kind: "auth",
        },
      ],
    });
    renderPage();

    const row = await screen.findByRole("listitem", { name: "Ventas" });
    expect(
      within(row).getByText(/Última prueba: con error \(Credenciales rechazadas\)/),
    ).toBeInTheDocument();
  });
});

describe("probar conexión", () => {
  it("muestra latencia y versión del servidor", async () => {
    const fetchMock = mockApi({
      test: { ok: true, latency_ms: 42, server_version: "16.2", error: null },
    });
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Probar conexión de Ventas" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Latencia: 42 ms");
    expect(status).toHaveTextContent("Versión del servidor: 16.2");
    expect(screen.getByText(/Última prueba: correcta/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/datasources/${ventas.id}/test`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("muestra el error clasificado con la acción sugerida", async () => {
    mockApi({
      test: {
        ok: false,
        latency_ms: null,
        server_version: null,
        error: { kind: "auth", message: "Usuario o contraseña rechazados por la base" },
      },
    });
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Probar conexión de Ventas" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Credenciales rechazadas");
    expect(alert).toHaveTextContent("Usuario o contraseña rechazados por la base");
    expect(alert).toHaveTextContent("Qué hacer: Revisa el usuario y la contraseña");
    expect(screen.getByText(/Última prueba: con error/)).toBeInTheDocument();
  });
});
