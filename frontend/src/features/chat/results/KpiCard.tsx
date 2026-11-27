import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import { formatNumber, formatPercent, variation } from "./format";
import type { FormatOptions } from "./format";
import { toNumber } from "./shape";

interface KpiCardProps extends FormatOptions {
  label: string;
  period?: string | null;
  value: unknown;
  previous?: unknown;
}

const TREND = {
  up: { Icon: ArrowUpRight, word: "Subió", color: "text-green-700" },
  down: { Icon: ArrowDownRight, word: "Bajó", color: "text-red-700" },
  flat: { Icon: ArrowRight, word: "Sin cambio", color: "text-muted-foreground" },
} as const;

export function KpiCard({ label, period, value, previous, locale, currency }: KpiCardProps) {
  const current = toNumber(value);
  const before = toNumber(previous);
  const change = current !== null && before !== null ? variation(current, before) : null;
  const trend = change ? TREND[change.direction] : null;
  return (
    <Card className="flex flex-col gap-1 p-4" aria-label={`Indicador: ${label}`}>
      <p className="text-sm text-muted-foreground">
        {label}
        {period ? ` · ${period}` : ""}
      </p>
      <p className="text-3xl font-semibold tabular-nums">
        {current !== null ? formatNumber(current, { locale, currency }) : String(value ?? "—")}
      </p>
      {change && trend && (
        <p className={`flex items-center gap-1 text-sm ${trend.color}`}>
          <trend.Icon aria-hidden className="size-4" />
          <span>
            {trend.word}
            {change.direction === "flat" ? "" : ` ${formatPercent(change.ratio, locale)}`} vs.
            período anterior
          </span>
        </p>
      )}
    </Card>
  );
}
