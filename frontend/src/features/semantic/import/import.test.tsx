/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "@/app/App";
import { setAccessToken } from "@/features/auth/api";
import type { SemanticModel } from "../types";
import type { ImportPreview } from "./types";

const diccionario = readFileSync(
  resolve(process.cwd(), "../examples/ventas/diccionario.csv"),
  "utf-8",
);

const DS = "11111111-1111-1111-1111-111111111111";
const session = {
  access_token: "jwt-en-memoria",
  expires_in: 900,
  user: { id: "u1", email: "ana@example.com", is_admin: true },
};

const current: SemanticModel = {
  version: 1,
  name: "Ventas (demo)",
  tables: [
    {
      name: "clientes",
      columns: [
        { name: "id", role: "id" },
        { name: "segmento", role: "other" },
      ],
    },
  ],
};

const merged: SemanticModel = {
  ...current,
  tables: [
    {
      name: "clientes",
      columns: [
        { name: "id", role: "id" },
        { name: "segmento", description: "Tipo de cliente", role: "dimension" },
      ],
    },
    { name: "sucursales", description: "Tiendas físicas de la cadena", columns: [] },
  ],
};

const preview: ImportPreview = {
  model: merged,
  diff: {
    added: [{ path: "sucursales", kind: "table" }],
    changed: [{ path: "clientes.segmento", field: "role", before: "other", after: "dimension" }],
    missing: [{ path: "clientes.telefono", kind: "column" }],
    suggestions: [],
  },
  warnings: [{ path: "fila 7", message: "Rol «xyz» no válido" }],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function setup(onImport: (file: File) => Response) {
  const uploads: File[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/auth/refresh")) return json(session);
    if (url.endsWith("/datasources")) {
      return json([{ id: DS, name: "Ventas (demo)", dialect: "sqlite" }]);
    }
    if (url.endsWith("/semantic/import")) {
      const file = (init?.body as FormData).get("file") as File;
      uploads.push(file);
      return onImport(file);
    }
    if (url.endsWith("/semantic")) {
      return json({ version: 3, created_by: "u1", created_at: "2026-11-20T15:00:00Z", model: current });
    }
    return json({ error: { code: "not_found", message: "no" } }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MemoryRouter initialEntries={["/modelo-semantico"]}>
      <App />
    </MemoryRouter>,
  );
  return { uploads, fetchMock };
}

async function openImport() {
  await userEvent.click(await screen.findByRole("tab", { name: "Importar" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe("importar estructura", () => {
  it("sube diccionario.csv, muestra la vista previa y aplica sin publicar", async () => {
    const { uploads } = setup(() => json(preview));
    await openImport();

    const file = new File([diccionario], "diccionario.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("Archivo a importar"), file);

    expect(await screen.findByText("Vista previa · diccionario.csv")).toBeInTheDocument();
    expect(uploads).toHaveLength(1);
    expect(uploads[0].name).toBe("diccionario.csv");
    expect(await uploads[0].text()).toBe(diccionario);

    const added = screen.getByRole("button", { name: /1 nuevas/ });
    expect(added).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/sucursales/)).not.toBeInTheDocument();
    await userEvent.click(added);
    expect(screen.getByText(/sucursales/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /1 cambian/ }));
    expect(screen.getByText(/clientes\.segmento · role: other → dimension/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /1 no encontradas/ }));
    expect(screen.getByText(/clientes\.telefono/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /1 advertencias/ }));
    expect(screen.getByText(/fila 7: Rol «xyz» no válido/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Aplicar" }));

    const list = await screen.findByRole("list", { name: "Tablas" });
    expect(within(list).getByRole("button", { name: /sucursales/ })).toBeInTheDocument();
    expect(screen.getByText("v3 · cambios sin publicar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publicar" })).toBeEnabled();
  });

  it("cancelar descarta la vista previa y deja el modelo intacto", async () => {
    setup(() => json(preview));
    await openImport();
    await userEvent.upload(
      screen.getByLabelText("Archivo a importar"),
      new File([diccionario], "diccionario.csv"),
    );

    await userEvent.click(await screen.findByRole("button", { name: "Cancelar" }));

    expect(screen.queryByText("Vista previa · diccionario.csv")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Tablas" }));
    const list = screen.getByRole("list", { name: "Tablas" });
    expect(within(list).queryByRole("button", { name: /sucursales/ })).not.toBeInTheDocument();
    expect(screen.getByText("v3 · guardado")).toBeInTheDocument();
  });

  it("muestra el error de archivo con el número de fila", async () => {
    setup(() =>
      json(
        {
          error: {
            code: "invalid_file",
            message: "fila 4: falta la columna «tabla»",
            details: {},
          },
        },
        422,
      ),
    );
    await openImport();

    await userEvent.upload(
      screen.getByLabelText("Archivo a importar"),
      new File(["tabla\n"], "malo.csv"),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("fila 4: falta la columna «tabla»");
  });

  it("lee la base conectada y la revisa con la misma vista previa", async () => {
    const { uploads, fetchMock } = setup(() => json(preview));
    const original = fetchMock.getMockImplementation();
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/semantic/introspect")) {
        return json({
          schemas: ["main"],
          tables: [{ name: "sucursales", columns: [{ name: "id", type: "integer" }] }],
          relationships: [],
          warnings: [{ path: "sucursales", message: "Sin clave primaria" }],
        });
      }
      return original!(url, init);
    });
    await openImport();

    await userEvent.click(screen.getByRole("button", { name: "Leer desde la base conectada" }));

    expect(await screen.findByText("Vista previa · base conectada")).toBeInTheDocument();
    expect(uploads[0].name).toBe("base-conectada.json");
    expect(JSON.parse(await uploads[0].text())).toMatchObject({
      version: 1,
      name: "Ventas (demo)",
      tables: [{ name: "sucursales" }],
    });
    expect(screen.getByRole("button", { name: /2 advertencias/ })).toBeInTheDocument();
  });
});
