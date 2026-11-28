import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "@/app/App";
import { setAccessToken } from "@/features/auth/api";
import type { AuditEntry } from "./api";

const session = {
  access_token: "jwt",
  expires_in: 900,
  user: { id: "1", email: "admin@example.com", is_admin: true },
};

const entry: AuditEntry = {
  id: "r1",
  created_at: "2026-11-20T10:00:00Z",
  status: "ok",
  error_code: null,
  user_id: null,
  user_email: null,
  external_user_id: "cliente-9",
  api_key_id: "k1",
  api_key_name: "CRM",
  role: "gerencia_general",
  datasource_id: "d1",
  datasource: "ventas",
  semantic_version: 3,
  question: "¿Cuánto vendí este mes?",
  plan: { intent: "metric", metric: "ventas_netas" },
  origin: "catalog",
  sql_candidate: "SELECT SUM(total) FROM facturas",
  sql_final: "SELECT SUM(total) FROM facturas LIMIT 1000",
  filters_applied: { role: ["facturas: sucursal_id IN (1, 2)"] },
  summary_table: null,
  row_count: 1,
  provider_kind: "fake",
  model: "fake-1",
  tokens_in: 120,
  tokens_out: 30,
  cost_usd: "0.0031",
  elapsed_ms: 85,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function stubApi() {
  const urls: string[] = [];
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(session.user);
    if (url.includes("/auth/")) return json(session);
    if (url.includes("/audit/export")) {
      urls.push(url);
      return new Response("fecha,estado\n", { status: 200 });
    }
    if (url.includes("/audit")) {
      urls.push(url);
      return json({ items: [entry], total: 1, page: 1, page_size: 25 });
    }
    if (url.includes("/datasources")) return json([{ id: "d1", name: "ventas" }]);
    return json([{ id: "k1", name: "CRM" }]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return urls;
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/auditoria"]}>
      <App />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe("auditoría", () => {
  it("lista los turnos con usuario final, key, fuente y resultado", async () => {
    stubApi();
    renderPage();

    const row = (await screen.findByText("¿Cuánto vendí este mes?")).closest("tr")!;
    expect(within(row).getByText("cliente-9 (vía CRM)")).toBeInTheDocument();
    expect(within(row).getByText("ventas")).toBeInTheDocument();
    expect(within(row).getByText("Correcto")).toBeInTheDocument();
    expect(within(row).getByText("US$ 0.0031")).toBeInTheDocument();
    expect(screen.getByText(/1 turno · página 1 de 1/)).toBeInTheDocument();
  });

  it("filtra por key y estado y manda los filtros al backend", async () => {
    const urls = stubApi();
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("¿Cuánto vendí este mes?");

    await user.selectOptions(await screen.findByLabelText("API key"), "k1");
    await user.selectOptions(screen.getByLabelText("Estado"), "rejected");
    await user.click(screen.getByRole("button", { name: "Filtrar" }));

    await screen.findByText("¿Cuánto vendí este mes?");
    const last = urls.filter((u) => !u.includes("/export")).at(-1)!;
    expect(last).toContain("api_key_id=k1");
    expect(last).toContain("status=rejected");
  });

  it("muestra el detalle del turno con el SQL candidato, el final y la versión del modelo", async () => {
    stubApi();
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Ver detalle/ }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("SELECT SUM(total) FROM facturas")).toBeInTheDocument();
    expect(
      within(dialog).getByText("SELECT SUM(total) FROM facturas LIMIT 1000"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Versión del modelo semántico")).toBeInTheDocument();
    expect(within(dialog).getByText("3")).toBeInTheDocument();
    expect(within(dialog).getByText(/facturas: sucursal_id IN \(1, 2\)/)).toBeInTheDocument();
  });

  it("exporta el CSV con los filtros vigentes", async () => {
    const urls = stubApi();
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("¿Cuánto vendí este mes?");

    await user.click(screen.getByRole("button", { name: /Exportar CSV/ }));

    await vi.waitFor(() => expect(urls.some((u) => u.includes("/audit/export"))).toBe(true));
  });
});
