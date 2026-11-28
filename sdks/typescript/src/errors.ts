/** La API respondió con un error HTTP (`{"error": {"code", "message", "details"}}`). */
export class ChatIAppError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(`${status} ${code}: ${message}`);
    this.name = "ChatIAppError";
  }
}

export async function errorFromResponse(response: Response): Promise<ChatIAppError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const record = (body ?? {}) as Record<string, unknown>;
  const error = record.error as Record<string, unknown> | undefined;
  if (error && typeof error === "object") {
    const details = error.details && typeof error.details === "object" ? error.details : {};
    return new ChatIAppError(
      response.status,
      String(error.code ?? "http_error"),
      String(error.message ?? ""),
      details as Record<string, unknown>,
    );
  }
  if ("detail" in record) {
    return new ChatIAppError(response.status, "validation_error", "Petición inválida", {
      detail: record.detail,
    });
  }
  return new ChatIAppError(response.status, "http_error", `Respuesta inesperada (${response.status})`);
}
