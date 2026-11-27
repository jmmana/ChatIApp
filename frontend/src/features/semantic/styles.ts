import type { ColumnRole } from "./types";

export const ROLE_LABELS: Record<ColumnRole, string> = {
  time: "Tiempo",
  measure: "Medida",
  dimension: "Dimensión",
  id: "Identificador",
  other: "Otro",
};

export const selectClass =
  "h-9 w-full rounded-md border border-input bg-card px-2 text-sm disabled:opacity-50";
