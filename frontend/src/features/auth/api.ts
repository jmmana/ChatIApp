export interface AuthUser {
  id: string;
  email: string;
  is_admin: boolean;
}

interface TokenResponse {
  access_token: string;
  expires_in: number;
  user: AuthUser;
}

export class AuthApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// El JWT vive solo en memoria: no se escribe en localStorage ni en cookies.
let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

async function post(path: string, body?: unknown): Promise<Response> {
  return fetch(`/api/v1/auth/${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
}

async function readSession(response: Response): Promise<AuthUser> {
  const data = (await response.json()) as TokenResponse;
  setAccessToken(data.access_token);
  return data.user;
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const response = await post("login", { email, password });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new AuthApiError(
      response.status,
      body?.error?.message ?? "No se pudo iniciar sesión. Inténtalo de nuevo.",
    );
  }
  return readSession(response);
}

/** Recupera la sesión con la cookie de refresco; devuelve null si no hay sesión. */
export async function refresh(): Promise<AuthUser | null> {
  const response = await post("refresh");
  if (!response.ok) {
    setAccessToken(null);
    return null;
  }
  return readSession(response);
}

export async function me(): Promise<AuthUser> {
  const response = await apiFetch("/api/v1/auth/me");
  if (!response.ok) throw new AuthApiError(response.status, "No se pudo obtener el usuario.");
  return (await response.json()) as AuthUser;
}

export async function logout(): Promise<void> {
  setAccessToken(null);
  await post("logout").catch(() => undefined);
}

/** fetch con el JWT en memoria; ante un 401 intenta refrescar una vez. */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const send = () =>
    fetch(input, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${accessToken ?? ""}` },
    });
  const response = await send();
  if (response.status !== 401) return response;
  return (await refresh()) ? send() : response;
}
