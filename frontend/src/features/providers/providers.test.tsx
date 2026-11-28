import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { setAccessToken } from "@/features/auth/api";
import type { CatalogEntry, Provider } from "./api";
import { ProvidersPage } from "./ProvidersPage";

const anthropic: CatalogEntry = {
  kind: "anthropic",
  label: "Claude (Anthropic)",
  category: "api",
  fields: [
    { name: "api_key", label: "API key", type: "secret", required: true, default: null, help: null, options: [] },
  ],
  suggested_models: ["claude-sonnet-5-5"],
  docs_url: "https://docs.anthropic.com",
  notes: null,
};

const bedrock: CatalogEntry = {
  kind: "bedrock",
  label: "AWS Bedrock",
  category: "platform",
  fields: [
    { name: "aws_region", label: "Región de AWS", type: "text", required: true, default: "us-east-1", help: null, options: [] },
    { name: "aws_access_key_id", label: "Access key ID", type: "text", required: false, default: null, help: "Déjalo vacío para usar el rol IAM de la máquina.", options: [] },
    { name: "aws_secret_access_key", label: "Secret access key", type: "secret", required: false, default: null, help: null, options: [] },
  ],
  suggested_models: ["amazon.nova-pro-v1:0"],
  docs_url: "https://docs.aws.amazon.com/bedrock",
  notes: null,
};

const claude: Provider = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Claude",
  kind: "anthropic",
  model: "claude-sonnet-5-5",
  config: {},
  secrets: { api_key: "…1234" },
  params: { fallback: 0 },
  tasks: ["planner", "sql"],
  is_default: true,
  managed_by: "ui",
};

const nova: Provider = {
  ...claude,
  id: "22222222-2222-2222-2222-222222222222",
  name: "Nova",
  kind: "bedrock",
  model: "amazon.nova-pro-v1:0",
  config: { aws_region: "us-west-2" },
  secrets: {},
  params: {},
  tasks: ["answer"],
  is_default: false,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function mockApi(options: { admin?: boolean; test?: unknown } = {}) {
  const { admin = true, test = { ok: true, latency_ms: 840, error_kind: null, message: null } } =
    options;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/auth/me"))
      return json({ id: "1", email: "ana@example.com", is_admin: admin });
    if (url.endsWith("/auth/refresh"))
      return json({
        access_token: "jwt",
        expires_in: 900,
        user: { id: "1", email: "ana@example.com", is_admin: admin },
      });
    if (url.endsWith("/providers/catalog")) return json([anthropic, bedrock]);
    if (url.endsWith("/models"))
      return json({ supported: true, models: ["claude-live-1"], error_kind: null, message: null });
    if (url.endsWith("/test")) return json(test);
    if (url.endsWith("/routing")) return json([claude, nova]);
    if (init?.method === "POST") return json(claude, 201);
    if (init?.method === "PATCH") return json(claude);
    return json([claude, nova]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ProvidersPage />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function callTo(fetchMock: ReturnType<typeof mockApi>, method: string, suffix: string) {
  return fetchMock.mock.calls.find(
    ([url, init]) => url.startsWith("/api/v1/providers") && url.endsWith(suffix) && init?.method === method,
  );
}

function bodyTo(fetchMock: ReturnType<typeof mockApi>, method: string, suffix = "/providers") {
  const call = callTo(fetchMock, method, suffix);
  expect(call).toBeDefined();
  return JSON.parse(call![1]!.body as string) as Record<string, unknown>;
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

describe("hub de proveedores", () => {
  it("muestra las tarjetas configuradas y la galería por categoría", async () => {
    mockApi();
    renderPage();

    const card = await screen.findByRole("listitem", { name: "Claude" });
    expect(within(card).getByText("claude-sonnet-5-5")).toBeInTheDocument();
    expect(within(card).getByText("Sin probar")).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: "Predeterminado" })).toBeInTheDocument();
    expect(within(card).getByText("Planificador")).toBeInTheDocument();
    expect(within(card).getByText("SQL")).toBeInTheDocument();
    expect(within(card).getByText("Respaldo 1")).toBeInTheDocument();

    const platforms = await screen.findByRole("group", { name: "Plataformas" });
    expect(within(platforms).getByRole("button", { name: "AWS Bedrock" })).toBeInTheDocument();
    const direct = screen.getByRole("group", { name: "API directa" });
    expect(within(direct).getByRole("button", { name: "Claude (Anthropic)" })).toBeInTheDocument();
  });

  it("muestra latencia y estado tras probar la conexión de una tarjeta", async () => {
    mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Probar conexión de Claude" }));

    const card = screen.getByRole("listitem", { name: "Claude" });
    expect(await within(card).findByText("Conectado · 840 ms")).toBeInTheDocument();
  });

  it("oculta las acciones de administración a quien no es administrador", async () => {
    mockApi({ admin: false });
    renderPage();

    await screen.findByRole("listitem", { name: "Claude" });
    expect(screen.queryByRole("button", { name: "AWS Bedrock" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Probar conexión/ })).not.toBeInTheDocument();
  });
});

describe("formulario dinámico", () => {
  it("Anthropic: solo pide la API key, en un campo de contraseña", async () => {
    const fetchMock = mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Claude (Anthropic)" }));
    const key = await screen.findByLabelText("API key");
    expect(key).toHaveAttribute("type", "password");
    expect(screen.queryByLabelText("Región de AWS")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Modelo")).toHaveValue("claude-sonnet-5-5");

    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Completa el campo «API key».");
    expect(callTo(fetchMock, "POST", "/providers")).toBeUndefined();

    await userEvent.type(key, "clave-de-prueba-1234");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await vi.waitFor(() => expect(callTo(fetchMock, "POST", "/providers")).toBeDefined());
    expect(bodyTo(fetchMock, "POST")).toEqual({
      kind: "anthropic",
      name: "Claude (Anthropic)",
      model: "claude-sonnet-5-5",
      config: {},
      secrets: { api_key: "clave-de-prueba-1234" },
      is_default: false,
    });
  });

  it("Bedrock: genera región y credenciales opcionales, sin API key", async () => {
    const fetchMock = mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "AWS Bedrock" }));
    expect(await screen.findByLabelText("Región de AWS")).toHaveValue("us-east-1");
    expect(screen.getByLabelText("Access key ID")).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("Secret access key")).toHaveAttribute("type", "password");
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
    expect(screen.getByText(/Déjalo vacío para usar el rol IAM/)).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText("Región de AWS"));
    await userEvent.type(screen.getByLabelText("Región de AWS"), "eu-west-1");
    // Sin credenciales: se permite (rol IAM de la máquina).
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await vi.waitFor(() => expect(callTo(fetchMock, "POST", "/providers")).toBeDefined());
    expect(bodyTo(fetchMock, "POST")).toMatchObject({
      kind: "bedrock",
      model: "amazon.nova-pro-v1:0",
      config: { aws_region: "eu-west-1" },
      secrets: {},
    });
  });

  it("prueba la conexión antes de guardar con la configuración escrita", async () => {
    const fetchMock = mockApi({
      test: { ok: false, latency_ms: 120, error_kind: "auth", message: "401 de prueba" },
    });
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Claude (Anthropic)" }));
    await userEvent.type(await screen.findByLabelText("API key"), "clave-de-prueba-1234");
    await userEvent.click(screen.getByRole("button", { name: "Probar conexión" }));

    expect(await screen.findByText("Credenciales rechazadas")).toBeInTheDocument();
    expect(screen.getByText("401 de prueba")).toBeInTheDocument();
    expect(bodyTo(fetchMock, "POST", "/providers/test")).toEqual({
      kind: "anthropic",
      model: "claude-sonnet-5-5",
      config: {},
      secrets: { api_key: "clave-de-prueba-1234" },
    });
    expect(callTo(fetchMock, "POST", "/providers")).toBeUndefined();
  });

  it("al editar muestra la máscara, no la reenvía y permite reemplazarla", async () => {
    const fetchMock = mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Editar Claude" }));
    const key = await screen.findByLabelText("API key");
    expect(key).toHaveValue("…1234");
    expect(key).toHaveAttribute("type", "password");
    expect(key).toHaveAttribute("readonly");

    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await vi.waitFor(() => expect(callTo(fetchMock, "PATCH", claude.id)).toBeDefined());
    expect(bodyTo(fetchMock, "PATCH", claude.id)).toMatchObject({ secrets: {} });
  });

  it("al reemplazar envía el secreto nuevo y la lista de modelos en vivo alimenta el selector", async () => {
    const fetchMock = mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Editar Claude" }));
    await userEvent.click(await screen.findByRole("button", { name: "Reemplazar API key" }));
    await userEvent.type(screen.getByLabelText("API key"), "clave-de-prueba-9999");

    await userEvent.click(screen.getByRole("button", { name: "Cargar modelos" }));
    expect(await screen.findByText(/1 modelos disponibles/)).toBeInTheDocument();
    expect(document.querySelector('option[value="claude-live-1"]')).not.toBeNull();
    // Texto libre siempre.
    await userEvent.clear(screen.getByLabelText("Modelo"));
    await userEvent.type(screen.getByLabelText("Modelo"), "modelo-propio");

    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await vi.waitFor(() => expect(callTo(fetchMock, "PATCH", claude.id)).toBeDefined());
    expect(bodyTo(fetchMock, "PATCH", claude.id)).toMatchObject({
      model: "modelo-propio",
      secrets: { api_key: "clave-de-prueba-9999" },
    });
  });
});

describe("tareas y respaldo", () => {
  it("guarda la asignación de tareas y la cadena de respaldo", async () => {
    const fetchMock = mockApi();
    renderPage();

    await userEvent.selectOptions(await screen.findByLabelText("Sugerencias"), nova.id);
    await userEvent.selectOptions(screen.getByLabelText("Agregar al respaldo"), nova.id);
    await userEvent.click(screen.getByRole("button", { name: "Guardar asignación" }));

    await vi.waitFor(() => expect(callTo(fetchMock, "PUT", "/routing")).toBeDefined());
    expect(bodyTo(fetchMock, "PUT", "/routing")).toEqual({
      tasks: { planner: claude.id, sql: claude.id, answer: nova.id, suggest: nova.id },
      fallback: [claude.id, nova.id],
    });
  });
});
