import { toNumber } from "./shape";

export interface FormatOptions {
  locale: string;
  currency?: string | null;
}

export const DEFAULT_LOCALE = "es-CO";

function safeLocale(locale: string): string {
  try {
    return Intl.getCanonicalLocales(locale)[0] ?? DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

/** Formatea una cifra con `Intl`; con moneda, en notación compacta si es muy grande. */
export function formatNumber(value: number, { locale, currency }: FormatOptions): string {
  const tag = safeLocale(locale);
  if (currency) {
    const big = Math.abs(value) >= 1e6;
    try {
      return new Intl.NumberFormat(tag, {
        style: "currency",
        currency,
        notation: big ? "compact" : "standard",
        maximumFractionDigits: big ? 1 : 2,
      }).format(value);
    } catch {
      // Moneda inválida: se muestra como número simple.
    }
  }
  return new Intl.NumberFormat(tag, { maximumFractionDigits: 2 }).format(value);
}

export function formatPercent(ratio: number, locale: string): string {
  return new Intl.NumberFormat(safeLocale(locale), {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(Math.abs(ratio));
}

/** Celda de tabla: cifras con `Intl`, el resto como texto. */
export function formatCell(value: unknown, options: FormatOptions): string {
  if (value === null || value === undefined) return "—";
  const n = toNumber(value);
  if (n !== null) return formatNumber(n, { locale: options.locale });
  return String(value);
}

export interface Variation {
  direction: "up" | "down" | "flat";
  ratio: number;
}

/** Variación relativa respecto al período anterior; `null` si no se puede calcular. */
export function variation(current: number, previous: number): Variation | null {
  if (previous === 0) return null;
  const ratio = (current - previous) / Math.abs(previous);
  return { direction: ratio > 0 ? "up" : ratio < 0 ? "down" : "flat", ratio };
}
