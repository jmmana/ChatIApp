import { apiFetch } from "@/features/auth/api";

/** Error de la API con la forma `{"error": {"code", "message", "details"}}`. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

/** Llama a `/api/v1{path}` con la sesión; lanza `ApiError` si la respuesta no es 2xx. */
export async function apiRequest<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const { method = "GET", body } = options;
  // Un FormData lo serializa el navegador (con su `boundary`): no se fuerza Content-Type.
  const isForm = body instanceof FormData;
  const response = await apiFetch(`/api/v1${path}`, {
    method,
    headers: body === undefined || isForm ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string; details?: Record<string, unknown> };
    } | null;
    throw new ApiError(
      response.status,
      data?.error?.code ?? "unknown",
      data?.error?.message ?? "No se pudo completar la solicitud.",
      data?.error?.details ?? {},
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
