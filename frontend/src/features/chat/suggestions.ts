import type { MetricInfo } from "./api";

const FALLBACK = ["¿Qué puedo preguntar sobre mis datos?"];

/** Preguntas de ejemplo a partir de las métricas del catálogo (máximo `limit`). */
export function buildSuggestions(metrics: MetricInfo[], limit = 4): string[] {
  if (metrics.length === 0) return FALLBACK;
  return metrics.slice(0, limit).map((metric) => {
    const label = metric.label.trim().toLocaleLowerCase("es");
    return metric.requires_period === false
      ? `Muéstrame ${label}`
      : `Muéstrame ${label} de este mes`;
  });
}
