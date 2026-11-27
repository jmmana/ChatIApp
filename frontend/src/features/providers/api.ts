import { apiFetch } from "@/features/auth/api";

export type Category = "api" | "platform" | "chinese" | "local";
export type FieldType = "text" | "secret" | "url" | "select" | "json";
export type Task = "planner" | "sql" | "answer" | "suggest";
export type ProbeErrorKind =
  | "auth"
  | "quota"
  | "model_not_found"
  | "timeout"
  | "network"
  | "provider_error";

export interface FieldOption {
  value: string;
  label: string;
}

export interface CatalogField {
  name: string;
  label: string;
  type: FieldType;
  required: boolean;
  default: string | null;
  help: string | null;
  options: FieldOption[];
}

export interface CatalogEntry {
  kind: string;
  label: string;
  category: Category;
  fields: CatalogField[];
  suggested_models: string[];
  docs_url: string;
  notes: string | null;
}

export interface Provider {
  id: string;
  name: string;
  kind: string;
  model: string;
  config: Record<string, unknown>;
  /** Solo máscaras (`…1234`): los secretos nunca vuelven completos. */
  secrets: Record<string, string>;
  params: Record<string, unknown>;
  tasks: Task[];
  is_default: boolean;
  managed_by: "ui" | "config";
}

export interface ProviderInput {
  name: string;
  model: string;
  config: Record<string, unknown>;
  /** En una edición solo van los secretos que la persona reemplazó. */
  secrets: Record<string, string>;
  is_default: boolean;
}

export interface UnsavedConfig {
  kind: string;
  model: string;
  config: Record<string, unknown>;
  secrets: Record<string, string>;
}

export interface ProbeResult {
  ok: boolean;
  latency_ms: number;
  error_kind: ProbeErrorKind | null;
  message: string | null;
}

export interface ModelsResult {
  supported: boolean;
  models: string[];
  error_kind: ProbeErrorKind | null;
  message: string | null;
}

export interface Routing {
  tasks: Partial<Record<Task, string>>;
  fallback: string[];
}

export class ProviderApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/v1/providers";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(`${BASE}${path}`, {
    ...init,
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new ProviderApiError(
      response.status,
      body?.error?.message ?? "No se pudo completar la operación. Inténtalo de nuevo.",
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getCatalog(): Promise<CatalogEntry[]> {
  return request<CatalogEntry[]>("/catalog");
}

export function listProviders(): Promise<Provider[]> {
  return request<Provider[]>("");
}

export function createProvider(kind: string, input: ProviderInput): Promise<Provider> {
  return request<Provider>("", { method: "POST", body: JSON.stringify({ kind, ...input }) });
}

export function updateProvider(id: string, input: ProviderInput): Promise<Provider> {
  return request<Provider>(`/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function testSavedProvider(id: string): Promise<ProbeResult> {
  return request<ProbeResult>(`/${id}/test`, { method: "POST" });
}

export function testUnsavedProvider(input: UnsavedConfig): Promise<ProbeResult> {
  return request<ProbeResult>("/test", { method: "POST", body: JSON.stringify(input) });
}

export function listModels(id: string): Promise<ModelsResult> {
  return request<ModelsResult>(`/${id}/models`);
}

export function putRouting(routing: Routing): Promise<Provider[]> {
  return request<Provider[]>("/routing", { method: "PUT", body: JSON.stringify(routing) });
}
