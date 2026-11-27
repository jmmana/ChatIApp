import { apiFetch } from "@/features/auth/api";

export type AttributeValue = string | number | boolean | (string | number)[];

export interface Grant {
  datasource_id: string;
  role: string;
  attributes: Record<string, AttributeValue>;
}

export interface ManagedUser {
  id: string;
  email: string;
  is_admin: boolean;
  grants: Grant[];
}

export interface UserInput {
  email: string;
  password: string;
  is_admin: boolean;
}

/** Roles del modelo vigente de una fuente y los atributos que exigen sus filtros. */
export interface RoleInfo {
  name: string;
  attributes: string[];
}

export class UsersApiError extends Error {}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, {
    ...init,
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new UsersApiError(body?.error?.message ?? "No se pudo completar la operación.");
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function listUsers(): Promise<ManagedUser[]> {
  const data = await request<unknown>("/api/v1/users");
  return Array.isArray(data) ? (data as ManagedUser[]) : [];
}

export const createUser = (input: UserInput) =>
  request<ManagedUser>("/api/v1/users", { method: "POST", body: JSON.stringify(input) });

export const deleteUser = (id: string) => request<void>(`/api/v1/users/${id}`, { method: "DELETE" });

export const putGrants = (id: string, grants: Grant[]) =>
  request<ManagedUser>(`/api/v1/users/${id}/grants`, {
    method: "PUT",
    body: JSON.stringify({ grants }),
  });

interface SemanticModelOut {
  model?: {
    security?: { roles?: { name: string; filters?: { condition: string }[] }[] };
  };
}

const MARKER = /\{user\.([A-Za-z_]\w*)\}/g;

/** Roles del modelo vigente; vacío si la fuente aún no tiene modelo. */
export async function listRoles(datasourceId: string): Promise<RoleInfo[]> {
  try {
    const data = await request<SemanticModelOut>(`/api/v1/datasources/${datasourceId}/semantic`);
    return (data.model?.security?.roles ?? []).map((role) => ({
      name: role.name,
      attributes: [
        ...new Set(
          (role.filters ?? []).flatMap((f) => [...f.condition.matchAll(MARKER)].map((m) => m[1])),
        ),
      ],
    }));
  } catch {
    return [];
  }
}
