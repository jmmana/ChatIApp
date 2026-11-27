/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Vitest se ejecuta desde `frontend/`.
const css = readFileSync("src/index.css", "utf8");

type Tokens = Record<string, string>;

function tokensOf(block: string): Tokens {
  const tokens: Tokens = {};
  for (const [, name, value] of block.matchAll(/--([a-z-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    tokens[name] = value;
  }
  return tokens;
}

const darkStart = css.indexOf("@media (prefers-color-scheme: dark) {");
const light = tokensOf(css.slice(css.indexOf(":root"), darkStart));
const dark = { ...light, ...tokensOf(css.slice(darkStart, css.indexOf("@theme inline"))) };

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const channel = parseInt(hex.slice(i, i + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Pares texto/fondo que la interfaz usa de verdad (WCAG AA: 4,5:1 para texto normal). */
const PAIRS: [string, string][] = [
  ["foreground", "background"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["muted-foreground", "muted"],
  ["secondary-foreground", "secondary"],
  ["primary-foreground", "primary"],
  ["accent-foreground", "accent"],
  ["destructive-foreground", "destructive"],
  ["destructive", "background"],
  ["destructive", "card"],
];

describe.each([
  ["claro", light],
  ["oscuro", dark],
])("contraste AA en el tema %s", (_name, tokens) => {
  it.each(PAIRS)("%s sobre %s", (fg, bg) => {
    expect(tokens[fg], `falta el token ${fg}`).toBeDefined();
    expect(tokens[bg], `falta el token ${bg}`).toBeDefined();
    expect(contrast(tokens[fg], tokens[bg])).toBeGreaterThanOrEqual(4.5);
  });

  it("el anillo de foco tiene 3:1 sobre el fondo", () => {
    expect(contrast(tokens.ring, tokens.background)).toBeGreaterThanOrEqual(3);
  });
});
