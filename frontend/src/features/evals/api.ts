import { apiFetch } from "@/features/auth/api";

export type RunStatus = "running" | "done" | "error";

export interface RunProvider {
  id: string;
  name: string;
  kind: string;
  model: string;
}

export interface FailedCase {
  id: string;
  tags: string[];
  motivo: string | null;
  sql: string | null;
  sql_esperado: string | null;
  filas: unknown[][];
  aclaracion: string | null;
}

/** Resumen de un proveedor en el informe (`backend/app/eval/report.py`). */
export interface ProviderReport {
  proveedor: string;
  kind: string;
  modelo: string;
  total: number;
  correctos: number;
  /** Fracción de 0 a 1. */
  exactitud: number;
  latencia_ms: { p50: number; p95: number };
  tokens: { entrada: number; salida: number };
  costo_usd: number;
  fallidos: FailedCase[];
}

export interface EvalReport {
  set: string;
  generado: string;
  proveedores: ProviderReport[];
}

export interface EvalRun {
  id: string;
  status: RunStatus;
  created_at: string;
  providers: RunProvider[];
  cases_total: number;
  cases_done: number;
  error: string | null;
  report: EvalReport | null;
}

export interface StartRunInput {
  provider_ids: string[];
  /** Obligatorio si algún proveedor es real (no `fake`). */
  max_calls?: number;
}

export class EvalApiError extends Error {
  constructor(
    public status: number,
    public code: string | null,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(`/api/v1/evals${path}`, {
    ...init,
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string; details?: Record<string, unknown> };
    } | null;
    throw new EvalApiError(
      response.status,
      body?.error?.code ?? null,
      body?.error?.message ?? "No se pudo completar la operación. Inténtalo de nuevo.",
      body?.error?.details,
    );
  }
  return (await response.json()) as T;
}

export function listRuns(): Promise<EvalRun[]> {
  return request<EvalRun[]>("/runs");
}

export function startRun(input: StartRunInput): Promise<EvalRun> {
  return request<EvalRun>("/runs", { method: "POST", body: JSON.stringify(input) });
}
