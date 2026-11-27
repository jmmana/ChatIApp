import { apiFetch } from "@/features/auth/api";

export interface MetricInfo {
  name: string;
  label: string;
  requires_period?: boolean;
}

export interface SemanticInfo {
  metrics: MetricInfo[];
  roles: string[];
}

interface SemanticOut {
  model?: {
    metrics?: MetricInfo[];
    security?: { roles?: { name: string }[] };
  } | null;
}

/**
 * Métricas y roles del modelo vigente. Leer el modelo exige administrador (403 para los demás) y
 * una fuente sin modelo responde 404: en ambos casos no hay nada que sugerir.
 */
export async function getSemanticInfo(datasourceId: string): Promise<SemanticInfo> {
  try {
    const response = await apiFetch(`/api/v1/datasources/${datasourceId}/semantic`);
    if (!response.ok) return { metrics: [], roles: [] };
    const data = (await response.json()) as SemanticOut;
    return {
      metrics: data.model?.metrics ?? [],
      roles: (data.model?.security?.roles ?? []).map((role) => role.name),
    };
  } catch {
    return { metrics: [], roles: [] };
  }
}

/** Pide al servidor que detenga el turno; si ya terminó (404) no hay nada que hacer. */
export async function cancelTurnOnServer(turnId: string): Promise<void> {
  await apiFetch(`/api/v1/chat/${turnId}/cancel`, { method: "POST" }).catch(() => undefined);
}
