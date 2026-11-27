import type { ModelIssue } from "./types";

/** Mensajes de validación por ruta de campo (`tables[0].columns[1].role`). */
export type FieldErrors = Record<string, string[]>;

export function groupIssues(issues: ModelIssue[]): FieldErrors {
  const grouped: FieldErrors = {};
  for (const { path, message } of issues) (grouped[path] ??= []).push(message);
  return grouped;
}

export function errorId(path: string): string {
  return `error-${path.replace(/[^A-Za-z0-9]+/g, "-")}`;
}

/** ¿Hay errores en `prefix` o debajo de él (`tables[0]` incluye `tables[0].columns[1].name`)? */
export function hasErrorsUnder(errors: FieldErrors, prefix: string): boolean {
  return Object.keys(errors).some(
    (path) =>
      path === prefix ||
      path.startsWith(`${prefix}.`) ||
      path.startsWith(`${prefix}[`),
  );
}

export function describedBy(
  errors: FieldErrors,
  path: string,
): string | undefined {
  return errors[path] ? errorId(path) : undefined;
}
