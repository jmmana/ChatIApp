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

export interface ConversationSummary {
  id: string;
  title: string;
  datasource_id: string;
  created_at: string;
}

export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  events?: { type: string; data: unknown }[] | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: StoredMessage[];
}

function expectOk(response: Response, message: string): Response {
  if (!response.ok) throw new Error(message);
  return response;
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const response = expectOk(
    await apiFetch("/api/v1/conversations"),
    "No se pudieron cargar las conversaciones.",
  );
  const data: unknown = await response.json();
  return Array.isArray(data) ? (data as ConversationSummary[]) : [];
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const response = expectOk(
    await apiFetch(`/api/v1/conversations/${id}`),
    "No se pudo abrir la conversación.",
  );
  return (await response.json()) as ConversationDetail;
}

export async function renameConversation(id: string, title: string): Promise<void> {
  expectOk(
    await apiFetch(`/api/v1/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
    "No se pudo renombrar la conversación.",
  );
}

export async function deleteConversation(id: string): Promise<void> {
  expectOk(
    await apiFetch(`/api/v1/conversations/${id}`, { method: "DELETE" }),
    "No se pudo eliminar la conversación.",
  );
}

/** Pide al servidor que detenga el turno; si ya terminó (404) no hay nada que hacer. */
export async function cancelTurnOnServer(turnId: string): Promise<void> {
  await apiFetch(`/api/v1/chat/${turnId}/cancel`, { method: "POST" }).catch(() => undefined);
}
