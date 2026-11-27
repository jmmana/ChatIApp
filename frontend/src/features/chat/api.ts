import { apiFetch } from "@/features/auth/api";

export interface MetricInfo {
  name: string;
  label: string;
  description?: string | null;
  requires_period?: boolean;
  default_period?: string | null;
  dimensions?: string[];
}

/**
 * Métricas que el rol de la persona puede consultar (cualquier usuario con acceso a la fuente).
 * Sin acceso o sin modelo responde 404: no hay nada que sugerir.
 */
export async function getMetrics(datasourceId: string): Promise<MetricInfo[]> {
  try {
    const response = await apiFetch(`/api/v1/datasources/${datasourceId}/metrics`);
    if (!response.ok) return [];
    const data = (await response.json()) as { metrics?: MetricInfo[] };
    return data.metrics ?? [];
  } catch {
    return [];
  }
}

interface SemanticOut {
  model?: { security?: { roles?: { name: string }[] } } | null;
}

/** Roles del modelo vigente, para «ver como». Leer el modelo completo exige administrador. */
export async function getRoles(datasourceId: string): Promise<string[]> {
  try {
    const response = await apiFetch(`/api/v1/datasources/${datasourceId}/semantic`);
    if (!response.ok) return [];
    const data = (await response.json()) as SemanticOut;
    return (data.model?.security?.roles ?? []).map((role) => role.name);
  } catch {
    return [];
  }
}

/** Pide al servidor que detenga el turno; si ya terminó (404) no hay nada que hacer. */
export async function cancelTurnOnServer(turnId: string): Promise<void> {
  await apiFetch(`/api/v1/chat/${turnId}/cancel`, { method: "POST" }).catch(() => undefined);
}
