"""Errores del cliente."""

from typing import Any


class ChatIAppError(Exception):
    """La API respondió con un error HTTP (`{"error": {"code", "message", "details"}}`)."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def error_from_response(status_code: int, body: Any) -> ChatIAppError:
    """Arma el error a partir del cuerpo JSON (o de lo que haya) de una respuesta fallida."""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return ChatIAppError(
                status_code,
                str(error.get("code", "http_error")),
                str(error.get("message", "")),
                error.get("details") if isinstance(error.get("details"), dict) else None,
            )
        if "detail" in body:  # validación de FastAPI
            return ChatIAppError(
                status_code, "validation_error", "Petición inválida", {"detail": body["detail"]}
            )
    return ChatIAppError(status_code, "http_error", f"Respuesta inesperada ({status_code})")
