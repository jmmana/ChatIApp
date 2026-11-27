import { toNumber } from "./shape";

export function sortRows(rows: unknown[][], index: number, dir: "asc" | "desc"): unknown[][] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = a[index];
    const y = b[index];
    const xNull = x === null || x === undefined;
    const yNull = y === null || y === undefined;
    if (xNull || yNull) return xNull === yNull ? 0 : xNull ? 1 : -1; // nulos siempre al final
    const nx = toNumber(x);
    const ny = toNumber(y);
    if (nx !== null && ny !== null) return sign * (nx - ny);
    return sign * String(x).localeCompare(String(y));
  });
}
