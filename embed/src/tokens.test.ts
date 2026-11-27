import { describe, expect, it, vi } from "vitest";
import { createTokenSource, decodeClaims, TokenError } from "./tokens";

function jwt(claims: Record<string, unknown>): string {
  const body = btoa(JSON.stringify(claims)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `cabecera.${body}.firma`;
}

describe("decodeClaims", () => {
  it("lee exp y ds del token", () => {
    expect(decodeClaims(jwt({ exp: 10, ds: "abc" }))).toEqual({ exp: 10, ds: "abc" });
  });

  it("devuelve vacío si no es un JWT", () => {
    expect(decodeClaims("no-es-jwt")).toEqual({});
  });
});

describe("createTokenSource", () => {
  it("reutiliza el token mientras no expire", async () => {
    const getToken = vi.fn(async () => jwt({ exp: 2000, ds: "d1" }));
    const source = createTokenSource(() => getToken, () => 1_000_000);
    await source.get(false);
    await source.get(false);
    expect(getToken).toHaveBeenCalledTimes(1);
    expect(await source.datasourceId()).toBe("d1");
  });

  it("vuelve a llamar a getToken cuando el token está por expirar", async () => {
    let now = 1_000_000;
    const getToken = vi.fn(async () => jwt({ exp: Math.floor(now / 1000) + 60, ds: "d1" }));
    const source = createTokenSource(() => getToken, () => now);
    const first = await source.get(false);
    now += 45_000; // quedan 15 s: dentro del margen
    await source.get(false);
    expect(getToken).toHaveBeenCalledTimes(2);
    expect(first).toBeTruthy();
  });

  it("forceRefresh descarta el token guardado", async () => {
    const getToken = vi.fn(async () => jwt({ exp: 9_999_999_999, ds: "d1" }));
    const source = createTokenSource(() => getToken);
    await source.get(false);
    await source.get(true);
    expect(getToken).toHaveBeenCalledTimes(2);
  });

  it("las llamadas simultáneas comparten una sola petición al anfitrión", async () => {
    const getToken = vi.fn(async () => jwt({ exp: 9_999_999_999, ds: "d1" }));
    const source = createTokenSource(() => getToken);
    await Promise.all([source.get(false), source.get(false), source.datasourceId()]);
    expect(getToken).toHaveBeenCalledTimes(1);
  });

  it("falla con TokenError si getToken no existe, falla o devuelve algo vacío", async () => {
    await expect(createTokenSource(() => undefined).get(false)).rejects.toBeInstanceOf(TokenError);
    await expect(
      createTokenSource(() => () => Promise.reject(new Error("sin sesión"))).get(false),
    ).rejects.toThrow(/sin sesión/);
    await expect(createTokenSource(() => () => "").get(false)).rejects.toBeInstanceOf(TokenError);
  });

  it("exige la claim ds para conocer la fuente", async () => {
    const source = createTokenSource(() => () => jwt({ exp: 9_999_999_999 }));
    await expect(source.datasourceId()).rejects.toBeInstanceOf(TokenError);
  });
});
