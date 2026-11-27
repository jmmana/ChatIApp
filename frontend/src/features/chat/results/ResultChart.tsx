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

export function ResultChart({ result, shape, kind, locale, currency }: ResultChartProps) {
  const data = result.rows.map((row) => {
    const label = row[shape.labelIndex];
    const point: Record<string, string | number | null> = {
      label: label === null || label === undefined ? "—" : String(label),
    };
    for (const i of shape.measureIndexes) point[result.columns[i]] = toNumber(row[i]);
    return point;
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
          <XAxis dataKey="label" tick={{ fontSize: 12 }} />
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
