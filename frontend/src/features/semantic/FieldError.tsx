import { errorId, type FieldErrors } from "./errors";

/** Mensajes de validación del servidor, junto al campo de la ruta `path`. */
export function FieldError({ errors, path }: { errors: FieldErrors; path: string }) {
  const messages = errors[path];
  if (!messages) return null;
  return (
    <p id={errorId(path)} className="text-xs text-destructive">
      {messages.join(" · ")}
    </p>
  );
}
