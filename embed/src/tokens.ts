/** El anfitrión entrega el token: una cadena, o una promesa de ella. */
export type GetToken = () => string | Promise<string>;

/** Segundos de margen: se pide otro token antes de que el actual venza en pleno turno. */
const EXPIRY_MARGIN_SECONDS = 30;

interface Claims {
  exp?: number;
  ds?: string;
}

/** Lee las claims del JWT sin verificarlas (las verifica el servidor en cada petición). */
export function decodeClaims(token: string): Claims {
  try {
    const payload = token.split(".")[1] ?? "";
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes)) as Claims;
  } catch {
    return {};
  }
}

export class TokenError extends Error {}

export interface TokenSource {
  /** Token vigente; `forceRefresh` descarta el guardado (el servidor respondió 401). */
  get(forceRefresh: boolean): Promise<string>;
  /** Fuente de datos a la que está atado el token (claim `ds`). */
  datasourceId(): Promise<string>;
}

/**
 * Guarda el token hasta poco antes de que expire y vuelve a llamar a `getToken()` cuando hace
 * falta. Las llamadas simultáneas comparten una sola petición al anfitrión.
 */
export function createTokenSource(
  getToken: () => GetToken | undefined,
  now: () => number = Date.now,
): TokenSource {
  let cached: { token: string; expiresAt: number } | null = null;
  let pending: Promise<string> | null = null;

  async function fetchToken(): Promise<string> {
    const provider = getToken();
    if (!provider) throw new TokenError("getToken no está definido");
    let token: unknown;
    try {
      token = await provider();
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new TokenError(`getToken falló: ${reason}`);
    }
    if (typeof token !== "string" || token === "") {
      throw new TokenError("getToken no devolvió un token");
    }
    const { exp } = decodeClaims(token);
    cached = { token, expiresAt: exp ? exp * 1000 : Number.POSITIVE_INFINITY };
    return token;
  }

  async function get(forceRefresh: boolean): Promise<string> {
    if (!forceRefresh && cached && cached.expiresAt - EXPIRY_MARGIN_SECONDS * 1000 > now()) {
      return cached.token;
    }
    pending ??= fetchToken().finally(() => {
      pending = null;
    });
    return pending;
  }

  async function datasourceId(): Promise<string> {
    const { ds } = decodeClaims(await get(false));
    if (!ds) throw new TokenError("El token no trae fuente de datos");
    return ds;
  }

  return { get, datasourceId };
}
