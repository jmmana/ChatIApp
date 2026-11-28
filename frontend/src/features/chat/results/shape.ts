import type { ResultData } from "../types";

export type ViewKind = "kpi" | "line" | "bar" | "table";

export interface ResultShape {
  /** Vista elegida automáticamente. */
  auto: ViewKind;
  /** Vistas entre las que la persona puede alternar (la tabla siempre está). */
  available: ViewKind[];
  /** Índice de la columna de etiqueta (tiempo o categoría) del gráfico. */
  labelIndex: number;
  /** Índices de las columnas de medida. */
  measureIndexes: number[];
  /** Con comparación: índice de la columna actual y de la del período anterior. */
  comparison: { current: number; previous: number } | null;
  /** El eje del gráfico es una serie de tiempo (dos o más fechas distintas). */
  timeAxis: boolean;
  /** Columnas de tiempo con un único valor: se muestran como contexto, no como eje. */
  constants: { index: number; value: string }[];
}

/** Máximo de categorías para que un gráfico de barras siga siendo legible. */
export const MAX_BAR_CATEGORIES = 30;

const DATE_RE = /^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}.*)?$/;
const NUMBER_RE = /^-?\d+(\.\d+)?([eE][+-]?\d+)?$/;
const PREVIOUS_RE = /anterior|previo|previous|prior|prev\b/i;

/** Convierte números y cadenas numéricas (los decimales llegan como texto) en `number`. */
export function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && NUMBER_RE.test(value.trim())) return Number(value);
  return null;
}

function column(result: ResultData, index: number): unknown[] {
  return result.rows
    .map((row) => row[index])
    .filter((v) => v !== null && v !== undefined && v !== "");
}

export function isNumericColumn(result: ResultData, index: number): boolean {
  const values = column(result, index);
  return values.length > 0 && values.every((v) => toNumber(v) !== null);
}

export function isTimeColumn(result: ResultData, index: number): boolean {
  const values = column(result, index);
  return values.length > 0 && values.every((v) => typeof v === "string" && DATE_RE.test(v));
}

function distinctCount(result: ResultData, index: number): number {
  return new Set(column(result, index).map(String)).size;
}

export function detectShape(result: ResultData): ResultShape {
  const base: ResultShape = {
    auto: "table",
    available: ["table"],
    labelIndex: -1,
    measureIndexes: [],
    comparison: null,
    timeAxis: false,
    constants: [],
  };
  const count = result.columns.length;
  if (count === 0 || result.rows.length === 0) return base;

  const numeric = result.columns.map((_, i) => isNumericColumn(result, i));

  // Valor único, o valor + período anterior en una sola fila.
  if (result.rows.length === 1) {
    if (count === 1 && numeric[0]) {
      return { ...base, auto: "kpi", available: ["kpi", "table"], measureIndexes: [0] };
    }
    if (count === 2 && numeric[0] && numeric[1]) {
      const previous = result.columns.findIndex((name) => PREVIOUS_RE.test(name));
      if (previous !== -1) {
        const current = previous === 0 ? 1 : 0;
        return {
          ...base,
          auto: "kpi",
          available: ["kpi", "table"],
          measureIndexes: [current],
          comparison: { current, previous },
        };
      }
    }
    // Una medida y columnas de tiempo (p. ej. «periodo» y «valor» de un total mensual): sigue
    // siendo un valor único, y el tiempo pasa a ser el contexto de la tarjeta.
    const measures = numeric.flatMap((is, i) => (is ? [i] : []));
    const times = result.columns.flatMap((_, i) => (!numeric[i] && isTimeColumn(result, i) ? [i] : []));
    if (measures.length === 1 && times.length === count - 1) {
      return {
        ...base,
        auto: "kpi",
        available: ["kpi", "table"],
        measureIndexes: measures,
        constants: times.map((i) => ({ index: i, value: String(column(result, i)[0]) })),
      };
    }
    return base;
  }

  const measureIndexes = numeric.flatMap((is, i) => (is ? [i] : []));
  // Una columna de tiempo con un único valor es una constante, no un eje.
  const constants = result.columns.flatMap((_, i) =>
    !numeric[i] && isTimeColumn(result, i) && distinctCount(result, i) === 1
      ? [{ index: i, value: String(column(result, i)[0]) }]
      : [],
  );
  const isConstant = (i: number) => constants.some((c) => c.index === i);
  const labelIndex = numeric.findIndex((is, i) => !is && !isConstant(i));
  if (measureIndexes.length === 0 || labelIndex === -1) return base;

  if (isTimeColumn(result, labelIndex)) {
    return {
      ...base,
      constants,
      timeAxis: true,
      auto: "line",
      available: ["line", "bar", "table"],
      labelIndex,
      measureIndexes,
    };
  }
  const labels = column(result, labelIndex);
  if (labels.every((v) => typeof v === "string") && result.rows.length <= MAX_BAR_CATEGORIES) {
    return {
      ...base,
      constants,
      auto: "bar",
      available: ["bar", "line", "table"],
      labelIndex,
      measureIndexes,
    };
  }
  return base;
}

/** Vista automática según la forma del resultado. */
export function selectView(result: ResultData): ViewKind {
  return detectShape(result).auto;
}
