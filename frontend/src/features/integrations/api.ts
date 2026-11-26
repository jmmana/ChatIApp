import { apiFetch } from "@/features/auth/api";

export const SCOPES = ["chat", "embed", "sql:preview", "semantic:read", "semantic:write"] as const;
export type Scope = (typeof SCOPES)[number];

/** Consumo del mes en curso; el backend lo añadirá a la lista (docs/API.md#integraciones-m3). */
export interface ApiKeyUsage {
  turns: number;
  tokens: number;
  cost_usd: number;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: Scope[];
  datasources: string[];
  allowed_roles: string[];
  allowed_origins: string[];
  rate_limit_per_minute: number | null;
  monthly_budget_usd: string | number | null;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
  usage?: ApiKeyUsage | null;
}

export interface ApiKeyCreated extends ApiKey {
  secret: string;
}

export interface ApiKeyInput {
  name: string;
  scopes: Scope[];
  datasources: string[];
  allowed_roles: string[];
  allowed_origins: string[];
  rate_limit_per_minute: number | null;
  monthly_budget_usd: number | null;
  expires_at: string | null;
}

export class IntegrationsApiError extends Error {}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(`/api/v1/api-keys${path}`, {
    ...init,
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new IntegrationsApiError(body?.error?.message ?? "No se pudo completar la operación.");
  }
  return (await response.json()) as T;
}

export async function listApiKeys(): Promise<ApiKey[]> {
  const data = await request<unknown>("");
  return Array.isArray(data) ? (data as ApiKey[]) : [];
}

export const createApiKey = (input: ApiKeyInput) =>
  request<ApiKeyCreated>("", { method: "POST", body: JSON.stringify(input) });

export const updateApiKey = (id: string, input: ApiKeyInput) =>
  request<ApiKey>(`/${id}`, { method: "PATCH", body: JSON.stringify(input) });

export const revokeApiKey = (id: string) => request<ApiKey>(`/${id}/revoke`, { method: "POST" });
