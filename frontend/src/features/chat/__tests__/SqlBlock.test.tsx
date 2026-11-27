import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { formatSql, SqlBlock } from "../SqlBlock";
import type { SqlData } from "../types";

const base: SqlData = {
  sql: "select sum(total) from ventas where fecha >= '2026-11-01'",
  dialect: "sqlite",
  origin: "catalog",
  summary_table: null,
  filters_applied: [],
};

afterEach(() => vi.restoreAllMocks());

describe("SqlBlock", () => {
  const combos = [
    { origin: "catalog", summary_table: null, filters_applied: [] },
    { origin: "llm", summary_table: null, filters_applied: [] },
    { origin: "catalog", summary_table: "ventas_diarias", filters_applied: [] },
    { origin: "llm", summary_table: null, filters_applied: ["region = 'Norte'"] },
    { origin: "catalog", summary_table: "ventas_diarias", filters_applied: ["region = 'Norte'"] },
  ] as const;

  it.each(combos)("muestra las insignias para %o", (combo) => {
    render(<SqlBlock sql={{ ...base, ...combo, filters_applied: [...combo.filters_applied] }} />);
    expect(screen.getByText("SQLite")).toBeInTheDocument();
    expect(screen.getByText("Solo lectura")).toBeInTheDocument();
    expect(screen.getByText(combo.origin === "catalog" ? "Catálogo" : "IA")).toBeInTheDocument();
    const table = screen.queryByText(/Tabla resumida/);
    expect(!!table).toBe(combo.summary_table !== null);
    expect(!!screen.queryByText("Filtro de rol")).toBe(combo.filters_applied.length > 0);
  });

  it("va abierto en curso, formateado, y plegado al terminar", () => {
    const { rerender, container } = render(<SqlBlock sql={base} streaming />);
    expect(container.querySelector("code")?.textContent).toContain("SELECT");
    expect(container.querySelector("code")?.textContent).toContain("\n");
    rerender(<SqlBlock sql={base} streaming={false} />);
    expect(container.querySelector("code")).toBeNull();
  });

  it("se despliega a mano y copia con confirmación", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<SqlBlock sql={base} />);
    await user.click(screen.getByRole("button", { name: "SQL" }));
    expect(screen.getByRole("button", { name: "SQL" })).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: /Copiar/ }));
    expect(writeText).toHaveBeenCalledWith(formatSql(base.sql, "sqlite"));
    expect(await screen.findByText("Copiado")).toBeInTheDocument();
  });

  it("usa el dialecto de la fuente al formatear", () => {
    expect(formatSql("select top 1 [a] from t", "mssql")).toContain("[a]");
    expect(formatSql("select 1", "desconocido")).toContain("SELECT");
  });
});
