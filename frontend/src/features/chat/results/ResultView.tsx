import { BarChart3, Download, Table2, TrendingUp } from "lucide-react";
import { lazy, Suspense, useState } from "react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import type { ResultData, SqlData } from "../types";
import { downloadCsv } from "./csv";
import { DEFAULT_LOCALE } from "./format";
import { KpiCard } from "./KpiCard";
import { ResultTable } from "./ResultTable";
import { detectShape } from "./shape";
import type { ViewKind } from "./shape";

// La librería de gráficos pesa más que todo el resto: se descarga solo cuando hay un gráfico.
const ResultChart = lazy(() =>
  import("./ResultChart").then((module) => ({ default: module.ResultChart })),
);

interface ResultViewProps {
  result: ResultData;
  sql?: SqlData | null;
  /** Etiqueta de la métrica por nombre de columna, del modelo semántico. */
  metricLabels?: Record<string, string>;
  locale?: string;
  currency?: string | null;
}

const VIEW_LABEL: Record<ViewKind, { text: string; icon: ReactNode }> = {
  kpi: { text: "Tarjeta", icon: <TrendingUp aria-hidden className="size-4" /> },
  line: { text: "Línea", icon: <TrendingUp aria-hidden className="size-4" /> },
  bar: { text: "Barras", icon: <BarChart3 aria-hidden className="size-4" /> },
  table: { text: "Tabla", icon: <Table2 aria-hidden className="size-4" /> },
};

export function ResultView({
  result,
  sql,
  metricLabels = {},
  locale = DEFAULT_LOCALE,
  currency,
}: ResultViewProps) {
  const shape = detectShape(result);
  const [chosen, setChosen] = useState<ViewKind | null>(null);
  const view = chosen && shape.available.includes(chosen) ? chosen : shape.auto;
  const options = { locale, currency };

  if (result.rows.length === 0) {
    return <p className="text-sm text-muted-foreground">La consulta no devolvió filas.</p>;
  }

  const current = shape.comparison?.current ?? shape.measureIndexes[0] ?? 0;
  const metricName = result.columns[current];

  return (
    <section aria-label="Resultado" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {shape.available.length > 1 && (
          <div role="group" aria-label="Vista del resultado" className="flex gap-1">
            {shape.available.map((kind) => (
              <Button
                key={kind}
                size="sm"
                variant={kind === view ? "default" : "outline"}
                aria-pressed={kind === view}
                onClick={() => setChosen(kind)}
              >
                {VIEW_LABEL[kind].icon}
                {VIEW_LABEL[kind].text}
              </Button>
            ))}
          </div>
        )}
        <Button size="sm" variant="outline" className="ml-auto" onClick={() => downloadCsv(result)}>
          <Download aria-hidden className="size-4" />
          Exportar CSV
        </Button>
      </div>

      {view === "kpi" && (
        <KpiCard
          label={metricLabels[metricName] ?? metricName}
          period={sql?.period}
          value={result.rows[0][current]}
          previous={shape.comparison ? result.rows[0][shape.comparison.previous] : undefined}
          {...options}
        />
      )}
      {(view === "line" || view === "bar") && (
        <Suspense fallback={<div role="status" aria-label="Cargando gráfico" className="h-72" />}>
          <ResultChart result={result} shape={shape} kind={view} {...options} />
        </Suspense>
      )}
      {view === "table" && <ResultTable result={result} {...options} />}

      {result.truncated && (
        <p role="status" className="text-sm text-amber-700">
          Mostrando {new Intl.NumberFormat(locale).format(result.row_count)} de más filas; exporta o
          filtra para ver el resto
        </p>
      )}
    </section>
  );
}
