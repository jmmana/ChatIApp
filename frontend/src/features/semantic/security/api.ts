import { apiRequest } from "@/lib/api";

export interface ViewAs {
  role: string | null;
  attributes: Record<string, unknown>;
}

export interface GuardResult {
  allowed: boolean;
  sql: string | null;
  tables: string[];
  violations: { code: string; message: string }[];
}

export interface PreviewResult {
  sql: string;
  metric: string;
  role: string | null;
  summary_table: string | null;
  reason: string;
  filters_applied: { source: string; text: string }[];
  guard: GuardResult;
}

export interface ValidateSqlResult extends GuardResult {
  role: string | null;
}

/** SQL de una métrica con el rol de `view_as` (sin IA). Usa la última versión publicada. */
export function previewMetric(
  datasourceId: string,
  body: { metric: string; period?: string; view_as: ViewAs },
): Promise<PreviewResult> {
  return apiRequest<PreviewResult>(`/datasources/${datasourceId}/preview`, {
    method: "POST",
    body,
  });
}

export function validateSql(
  datasourceId: string,
  body: { sql: string; view_as: ViewAs },
): Promise<ValidateSqlResult> {
  return apiRequest<ValidateSqlResult>(`/datasources/${datasourceId}/validate-sql`, {
    method: "POST",
    body,
  });
}
