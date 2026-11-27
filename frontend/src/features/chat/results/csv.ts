import type { ResultData } from "../types";

function escapeCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = typeof value === "object" ? JSON.stringify(value) : String(value);
  // Evita que una hoja de cálculo interprete el texto como fórmula.
  if (typeof value === "string" && /^[=+\-@\t\r]/.test(text) && Number.isNaN(Number(text))) {
    text = `'${text}`;
  }
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** CSV (RFC 4180) con los valores crudos, sin formato de configuración regional. */
export function toCsv(result: Pick<ResultData, "columns" | "rows">): string {
  const lines = [result.columns, ...result.rows].map((row) => row.map(escapeCell).join(","));
  return lines.join("\r\n") + "\r\n";
}

export function downloadCsv(result: ResultData, filename = "resultado.csv"): void {
  const blob = new Blob(["﻿" + toCsv(result)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
