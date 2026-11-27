import type { Category, ProbeErrorKind, Provider, Task } from "./api";

export const CATEGORIES: { value: Category; label: string }[] = [
  { value: "api", label: "API directa" },
  { value: "platform", label: "Plataformas" },
  { value: "chinese", label: "Modelos chinos" },
  { value: "local", label: "Local" },
];

export const TASKS: { value: Task; label: string; help: string }[] = [
  { value: "planner", label: "Planificador", help: "Entiende la pregunta y arma el plan." },
  { value: "sql", label: "SQL", help: "Redacta la consulta." },
  { value: "answer", label: "Respuesta", help: "Explica el resultado en lenguaje claro." },
  { value: "suggest", label: "Sugerencias", help: "Propone preguntas y descripciones." },
];

export function taskLabel(task: string): string {
  return TASKS.find((t) => t.value === task)?.label ?? task;
}

export const ERROR_HELP: Record<ProbeErrorKind, { title: string; action: string }> = {
  auth: {
    title: "Credenciales rechazadas",
    action: "Revisa la API key o las credenciales y que tengan permiso para usar el modelo.",
  },
  quota: {
    title: "Sin cuota o límite alcanzado",
    action: "Revisa el saldo y los límites de tu cuenta con el proveedor.",
  },
  model_not_found: {
    title: "Modelo no encontrado",
    action: "Revisa el nombre del modelo; puedes elegir uno de la lista sugerida.",
  },
  timeout: {
    title: "El proveedor tardó demasiado",
    action: "Inténtalo de nuevo; si persiste, revisa la región o el endpoint.",
  },
  network: {
    title: "No se pudo alcanzar el proveedor",
    action: "Revisa la URL base y que el servidor esté encendido y accesible.",
  },
  provider_error: {
    title: "El proveedor devolvió un error",
    action: "Revisa el mensaje y la configuración; consulta los registros del servidor.",
  },
};

export function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
}

/** Posición en la cadena de respaldo, o `null` si el proveedor no está en ella. */
export function fallbackIndex(provider: Provider): number | null {
  const value = provider.params.fallback;
  return typeof value === "number" ? value : null;
}
