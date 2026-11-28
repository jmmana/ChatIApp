import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ResultData } from "../types";
import { formatNumber } from "./format";
import type { FormatOptions } from "./format";
import { toNumber } from "./shape";
import type { ResultShape } from "./shape";

const COLORS = ["#2563eb", "#d97706", "#059669", "#7c3aed", "#db2777", "#0891b2"];

interface ResultChartProps extends FormatOptions {
  result: ResultData;
  shape: ResultShape;
  kind: "line" | "bar";
}

const MAX_TICK_CHARS = 14;

function truncate(text: string): string {
  return text.length > MAX_TICK_CHARS ? `${text.slice(0, MAX_TICK_CHARS - 1)}…` : text;
}

/** Etiqueta del eje X truncada, con el texto completo en `<title>`. */
function LabelTick(props: { x?: number; y?: number; payload?: { value: string } }) {
  const { x = 0, y = 0, payload } = props;
  const full = String(payload?.value ?? "");
  return (
    <text x={x} y={y + 12} textAnchor="middle" fontSize={12} fill="currentColor">
      <title>{full}</title>
      {truncate(full)}
    </text>
  );
}

export function ResultChart({ result, shape, kind, locale, currency }: ResultChartProps) {
  const points = result.rows.map((row) => {
    const label = row[shape.labelIndex];
    const point: Record<string, string | number | null> = {
      label: label === null || label === undefined ? "—" : String(label),
    };
    for (const i of shape.measureIndexes) point[result.columns[i]] = toNumber(row[i]);
    return point;
  });
  // Con categorías, de mayor a menor por la primera medida (los nulos al final).
  const first = result.columns[shape.measureIndexes[0]];
  const sorted = shape.timeAxis
    ? points
    : [...points].sort((a, b) => {
        const x = a[first];
        const y = b[first];
        if (typeof x !== "number") return typeof y === "number" ? 1 : 0;
        if (typeof y !== "number") return -1;
        return y - x;
      });
  // El eje X no repite etiquetas: las repetidas llevan un sufijo (2), (3)…
  const seen = new Map<string, number>();
  const data = sorted.map((point) => {
    const label = String(point.label);
    const n = (seen.get(label) ?? 0) + 1;
    seen.set(label, n);
    return n === 1 ? point : { ...point, label: `${label} (${n})` };
  });
  const fmt = (value: unknown) => {
    const n = toNumber(value);
    return n === null ? "" : formatNumber(n, { locale, currency });
  };
  const measures = shape.measureIndexes.map((i) => result.columns[i]);
  const Chart = kind === "line" ? LineChart : BarChart;
  return (
    <div
      role="img"
      aria-label={`Gráfico de ${kind === "line" ? "líneas" : "barras"} de ${measures.join(", ")} por ${result.columns[shape.labelIndex]}`}
      className="h-72 w-full"
    >
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <Chart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" tick={<LabelTick />} interval={0} />
          <YAxis tickFormatter={fmt} tick={{ fontSize: 12 }} width={80} />
          <Tooltip formatter={(value) => fmt(value)} />
          {measures.length > 1 && <Legend />}
          {measures.map((name, n) =>
            kind === "line" ? (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={COLORS[n % COLORS.length]}
                dot={data.length < 40}
                isAnimationActive={false}
              />
            ) : (
              <Bar
                key={name}
                dataKey={name}
                fill={COLORS[n % COLORS.length]}
                isAnimationActive={false}
              />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}
