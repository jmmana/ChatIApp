import { apiFetch } from "@/features/auth/api";

export type Dialect = "sqlite" | "postgres" | "mysql" | "tsql" | "oracle" | "snowflake" | "bigquery";
export type Privacy = "schema" | "aggregates" | "samples";
export type ErrorKind = "auth" | "network" | "driver_missing" | "unknown";

export interface Datasource {
  id: string;
  name: string;
  dialect: Dialect;
  /** URL con usuario y contraseña ocultos. */
  url: string;
  execute: boolean;
  max_rows: number;
  timeout_seconds: number;
  privacy: Privacy;
  managed_by: "ui" | "config";
  last_test_ok: boolean | null;
  last_test_at: string | null;
  last_test_error_kind: ErrorKind | null;
}

export interface DatasourceInput {
  name: string;
  dialect: Dialect;
  /** En una edición solo se envía si la persona escribió una URL nueva. */
  url?: string;
  execute: boolean;
  max_rows: number;
  timeout_seconds: number;
  privacy: Privacy;
}

export interface TestResult {
  ok: boolean;
  latency_ms: number | null;
  server_version: string | null;
  error: { kind: ErrorKind; message: string } | null;
}

export class DatasourceApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/v1/datasources";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(`${BASE}${path}`, {
    ...init,
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new DatasourceApiError(
      response.status,
      body?.error?.message ?? "No se pudo completar la operación. Inténtalo de nuevo.",
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listDatasources(): Promise<Datasource[]> {
  return request<Datasource[]>("");
}

export function createDatasource(input: DatasourceInput): Promise<Datasource> {
  return request<Datasource>("", { method: "POST", body: JSON.stringify(input) });
}

export function updateDatasource(id: string, input: DatasourceInput): Promise<Datasource> {
  return request<Datasource>(`/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function deleteDatasource(id: string): Promise<void> {
  return request<void>(`/${id}`, { method: "DELETE" });
}

export function testDatasource(id: string): Promise<TestResult> {
  return request<TestResult>(`/${id}/test`, { method: "POST" });
}
