import { apiRequest } from "@/lib/api";
import type { ColumnRole, SemanticColumn, SemanticModel, SemanticTable } from "../types";

export type SuggestField = "description" | "synonyms" | "role";

/** Propuesta de la IA: `path` es `tabla` o `tabla.columna`. */
export interface Suggestion {
  path: string;
  field: SuggestField;
  value: string | string[];
  confidence: number;
}

export function requestSuggestions(datasourceId: string): Promise<Suggestion[]> {
  return apiRequest<Suggestion[]>(`/datasources/${datasourceId}/semantic/suggest`, {
    method: "POST",
    body: {},
  });
}

export const FIELD_LABELS: Record<SuggestField, string> = {
  description: "Descripción",
  synonyms: "Sinónimos",
  role: "Rol",
};

export function suggestionKey(suggestion: Suggestion): string {
  return `${suggestion.path}:${suggestion.field}`;
}

export function formatValue(suggestion: Suggestion): string {
  return Array.isArray(suggestion.value) ? suggestion.value.join(", ") : suggestion.value;
}

function locate(model: SemanticModel, path: string): { table: number; column: number | null } | null {
  const tables = model.tables ?? [];
  for (let table = 0; table < tables.length; table++) {
    if (tables[table].name === path) return { table, column: null };
    const prefix = `${tables[table].name}.`;
    if (!path.startsWith(prefix)) continue;
    const column = (tables[table].columns ?? []).findIndex((c) => c.name === path.slice(prefix.length));
    if (column >= 0) return { table, column };
  }
  return null;
}

function isEmpty(target: SemanticTable | SemanticColumn, field: SuggestField): boolean {
  if (field === "synonyms") return (target.synonyms ?? []).length === 0;
  if (field === "description") return !target.description || target.description.trim() === "";
  return !("role" in target) || !target.role || target.role === "other";
}

/** `true` si el campo sigue vacío y la sugerencia aún se puede aplicar. */
export function canApply(model: SemanticModel, suggestion: Suggestion): boolean {
  const found = locate(model, suggestion.path);
  if (!found) return false;
  const table = (model.tables ?? [])[found.table];
  if (found.column === null) return suggestion.field !== "role" && isEmpty(table, suggestion.field);
  return isEmpty((table.columns ?? [])[found.column], suggestion.field);
}

/** Aplica las sugerencias sobre el borrador; nunca pisa un campo que ya tiene valor. */
export function applySuggestions(model: SemanticModel, suggestions: Suggestion[]): SemanticModel {
  let next = model;
  for (const suggestion of suggestions) {
    if (!canApply(next, suggestion)) continue;
    const found = locate(next, suggestion.path);
    if (!found) continue;
    const patch: Partial<SemanticColumn> =
      suggestion.field === "synonyms"
        ? { synonyms: [suggestion.value].flat() }
        : suggestion.field === "role"
          ? { role: suggestion.value as ColumnRole }
          : { description: String(suggestion.value) };
    next = {
      ...next,
      tables: (next.tables ?? []).map((table, ti) => {
        if (ti !== found.table) return table;
        if (found.column === null) return { ...table, ...patch };
        return {
          ...table,
          columns: (table.columns ?? []).map((c, ci) => (ci === found.column ? { ...c, ...patch } : c)),
        };
      }),
    };
  }
  return next;
}
