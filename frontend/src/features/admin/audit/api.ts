import { apiFetch } from "@/features/auth/api";

export type AuditStatus = "ok" | "rejected" | "error";

export interface AuditEntry {
  id: string;
  created_at: string;
  status: AuditStatus;
  error_code: string | null;
  user_id: string | null;
  user_email: string | null;
  external_user_id: string | null;
  api_key_id: string | null;
  api_key_name: string | null;
  role: string | null;
  datasource_id: string | null;
  datasource: string | null;
  semantic_version: number | null;
  question: string | null;
  plan: Record<string, unknown> | null;
  origin: "catalog" | "llm";
  sql_candidate: string | null;
  sql_final: string | null;
  filters_applied: Record<string, string[]> | null;
  summary_table: string | null;
  row_count: number | null;
  provider_kind: string | null;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: string | number | null;
  elapsed_ms: number | null;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

export interface AuditFilters {
  user_id: string;
  external_user_id: string;
  datasource_id: string;
  api_key_id: string;
  status: "" | AuditStatus;
  date_from: string;
  date_to: string;
}

export const emptyFilters: AuditFilters = {
  user_id: "",
  external_user_id: "",
  datasource_id: "",
  api_key_id: "",
  status: "",
  date_from: "",
  date_to: "",
};

export const PAGE_SIZE = 25;

export class AuditApiError extends Error {}

function query(filters: AuditFilters, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams(extra);
  for (const [key, value] of Object.entries(filters)) {
    if (value.trim()) params.set(key, value.trim());
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

async function failure(response: Response): Promise<AuditApiError> {
  const body = (await response.json().catch(() => null)) as {
    error?: { message?: string };
  } | null;
  return new AuditApiError(body?.error?.message ?? "No se pudo consultar la auditoría.");
}

export async function listAudit(filters: AuditFilters, page: number): Promise<AuditPage> {
  const response = await apiFetch(
    `/api/v1/audit${query(filters, { page: String(page), page_size: String(PAGE_SIZE) })}`,
  );
  if (!response.ok) throw await failure(response);
  return (await response.json()) as AuditPage;
}

export async function exportAudit(filters: AuditFilters): Promise<Blob> {
  const response = await apiFetch(`/api/v1/audit/export${query(filters)}`);
  if (!response.ok) throw await failure(response);
  return response.blob();
}
