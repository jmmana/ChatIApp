import type { ConversationSummary } from "./api";

export type GroupLabel = "Hoy" | "Ayer" | "Últimos 7 días" | "Anteriores";

export interface ConversationGroup {
  label: GroupLabel;
  items: ConversationSummary[];
}

const DAY_MS = 24 * 60 * 60 * 1000;
const ORDER: GroupLabel[] = ["Hoy", "Ayer", "Últimos 7 días", "Anteriores"];

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Grupo de una fecha según días calendario locales respecto a `now`. */
export function groupLabel(createdAt: string, now: Date): GroupLabel {
  const created = new Date(createdAt);
  if (Number.isNaN(created.getTime())) return "Anteriores";
  const days = Math.round((startOfDay(now) - startOfDay(created)) / DAY_MS);
  if (days <= 0) return "Hoy";
  if (days === 1) return "Ayer";
  if (days <= 7) return "Últimos 7 días";
  return "Anteriores";
}

/** Agrupa conservando el orden recibido; los grupos vacíos se omiten. */
export function groupConversations(
  items: ConversationSummary[],
  now: Date = new Date(),
): ConversationGroup[] {
  const groups = new Map<GroupLabel, ConversationSummary[]>();
  for (const item of items) {
    const label = groupLabel(item.created_at, now);
    groups.set(label, [...(groups.get(label) ?? []), item]);
  }
  return ORDER.filter((label) => groups.has(label)).map((label) => ({
    label,
    items: groups.get(label) ?? [],
  }));
}
