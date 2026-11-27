import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ResultData } from "../../types";
import { toCsv } from "../csv";
import { formatNumber, variation } from "../format";
import { ResultView } from "../ResultView";
import { selectView } from "../shape";
import { sortRows } from "../sort";

function result(columns: string[], rows: unknown[][], truncated = false): ResultData {
  return { columns, rows, row_count: rows.length, truncated, elapsed_ms: 1 };
}

describe("selectView", () => {
  it("valor único (también como texto decimal) → tarjeta KPI", () => {
    expect(selectView(result(["ventas_netas"], [["482315000.00"]]))).toBe("kpi");
  });

  it("valor + período anterior en una fila → tarjeta KPI", () => {
    expect(selectView(result(["ventas", "ventas_anterior"], [[10, 8]]))).toBe("kpi");
  });

  it("tiempo + medida → línea", () => {
    const r = result(["mes", "ventas"], [["2026-01-01", 1], ["2026-02-01", 2]]);
    expect(selectView(r)).toBe("line");
  });

  it("categoría + medida → barras", () => {
    const r = result(["sucursal", "ventas"], [["Norte", 1], ["Sur", 2]]);
    expect(selectView(r)).toBe("bar");
  });

  it("sin medida, sin filas o con demasiadas categorías → tabla", () => {
    expect(selectView(result(["a", "b"], [["x", "y"], ["z", "w"]]))).toBe("table");
    expect(selectView(result(["a"], []))).toBe("table");
    const many = Array.from({ length: 31 }, (_, i) => [`c${i}`, i]);
    expect(selectView(result(["c", "v"], many))).toBe("table");
  });

  it("una fila con varias columnas sin comparación → tabla", () => {
    expect(selectView(result(["a", "b"], [[1, 2]]))).toBe("table");
  });
});

describe("utilidades", () => {
  it("formatNumber usa Intl con moneda", () => {
    expect(formatNumber(1234.5, { locale: "en-US", currency: "USD" })).toBe("$1,234.50");
  });

  it("variation calcula dirección y razón; null sin base", () => {
    expect(variation(110, 100)).toEqual({ direction: "up", ratio: 0.1 });
    expect(variation(50, 100)?.direction).toBe("down");
    expect(variation(5, 0)).toBeNull();
  });

  it("toCsv escapa comillas, comas y fórmulas", () => {
    const csv = toCsv({ columns: ["a", "b"], rows: [['x,"y"', "=SUM(A1)"], [1, null]] });
    expect(csv).toBe('a,b\r\n"x,""y""",\'=SUM(A1)\r\n1,\r\n');
  });

  it("sortRows ordena números como números y deja nulos al final", () => {
    const rows = [[10], [2], [null], [30]];
    expect(sortRows(rows, 0, "asc").map((r) => r[0])).toEqual([2, 10, 30, null]);
    expect(sortRows(rows, 0, "desc").map((r) => r[0])).toEqual([30, 10, 2, null]);
  });
});

describe("ResultView", () => {
  it("muestra la tarjeta con etiqueta, período y variación con flecha y texto", () => {
    render(
      <ResultView
        result={result(["ventas", "ventas_anterior"], [[110, 100]])}
        sql={{
          sql: "",
          dialect: "sqlite",
          origin: "catalog",
          filters_applied: [],
          period: "noviembre",
        }}
        metricLabels={{ ventas: "Ventas netas" }}
        locale="en-US"
      />,
    );
    expect(screen.getByText("Ventas netas · noviembre")).toBeInTheDocument();
    expect(screen.getByText("110")).toBeInTheDocument();
    expect(screen.getByText(/Subió 10%/)).toBeInTheDocument();
  });

  it("permite cambiar a tabla, ordenar y avisa del recorte", async () => {
    const user = userEvent.setup();
    render(
      <ResultView
        result={result(["sucursal", "ventas"], [["Norte", 5], ["Sur", 20]], true)}
        locale="en-US"
      />,
    );
    expect(screen.getByRole("img", { name: /barras/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tabla" }));
    const header = screen.getByRole("columnheader", { name: /ventas/ });
    expect(header).toHaveAttribute("aria-sort", "none");
    await user.click(screen.getByRole("button", { name: /ventas/ }));
    await user.click(screen.getByRole("button", { name: /ventas/ }));
    expect(header).toHaveAttribute("aria-sort", "descending");
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("Sur");
    expect(screen.getByText(/de más filas/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Exportar CSV/ })).toBeInTheDocument();
  });
});
