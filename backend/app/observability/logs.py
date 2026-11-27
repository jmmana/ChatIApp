"""Logs JSON con el contexto del turno (`turn_id`, `conversation_id`, usuario y etapa).

El formateador solo emite campos conocidos: lo que no esté en `_EXTRA_FIELDS` se descarta, así una
fila o un secreto pasado en `extra=` nunca llega al log. El mensaje además pasa por `redact`, y de
las excepciones solo salen el tipo y la pila (sin el mensaje, que podría traer valores de la base).
"""

import json
import logging
import re
import sys
import traceback
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

_CONTEXT_FIELDS = ("turn_id", "conversation_id", "user", "stage")
_EXTRA_FIELDS = (
    "provider",
    "model",
    "code",
    "status",
    "duration_ms",
    "tokens_in",
    "tokens_out",
    "cost_usd",
)

_log_context: ContextVar[dict[str, str | None] | None] = ContextVar(
    "chatiapp_log_context", default=None
)

_REDACTED = "[redactado]"
_PLAIN_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[\w.~+/=-]+"),
    re.compile(r"\b(?:sk|pk|rk)-[\w-]{8,}"),
    re.compile(r"\b(?:AKIA|ghp_|gho_|xox[bap]-)[\w-]{8,}"),
)
_ASSIGNMENT = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password|passwd|authorization)[\"']?\s*[:=]\s*[\"']?)"
    r"[^\s,;\"'&]+"
)


def redact(text: str) -> str:
    """Tapa credenciales con forma conocida dentro de un texto."""
    for pattern in _PLAIN_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{_REDACTED}", text)


class LogScope:
    """Contexto de log de un turno. `stage` cambia mientras el turno avanza."""

    def __init__(self, conversation_id: str | None = None, user: str | None = None) -> None:
        self.fields: dict[str, str | None] = {
            "turn_id": None,
            "conversation_id": conversation_id,
            "user": user,
            "stage": None,
        }

    def update(self, **fields: str | None) -> None:
        self.fields.update(fields)

    def wrap[T](self, events: Iterator[T]) -> Iterator[T]:
        """Recorre `events` con este contexto activo solo mientras el generador avanza.

        Se activa en cada `next()` y se desactiva antes de ceder el control, de modo que el
        contexto no se filtra al consumidor ni depende del hilo que avance el generador.
        """
        try:
            while True:
                token = _log_context.set(self.fields)
                try:
                    item = next(events)
                except StopIteration:
                    return
                finally:
                    _log_context.reset(token)
                yield item
        finally:
            close = getattr(events, "close", None)
            if close is not None:
                token = _log_context.set(self.fields)
                try:
                    close()
                finally:
                    _log_context.reset(token)


class JsonFormatter(logging.Formatter):
    """Una línea JSON por registro."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        context = _log_context.get() or {}
        for name in _CONTEXT_FIELDS:
            if context.get(name) is not None:
                entry[name] = context[name]
        for name in _EXTRA_FIELDS:
            value = record.__dict__.get(name)
            if value is not None:
                entry[name] = redact(value) if isinstance(value, str) else value
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, _, tb = record.exc_info
            entry["exc_type"] = exc_type.__name__
            entry["stack"] = [
                f"{frame.filename}:{frame.lineno} {frame.name}"
                for frame in traceback.extract_tb(tb)
            ]
        return json.dumps(entry, ensure_ascii=False, default=str)


_HANDLER_MARK = "_chatiapp_handler"


def configure_logging(level: str = "INFO", fmt: Literal["json", "text"] = "json") -> None:
    """Deja un único manejador de la app en el logger raíz. Es idempotente."""
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARK, False):
            root.removeHandler(existing)
    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _HANDLER_MARK, True)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())
    # uvicorn trae manejadores propios con otro formato: sus registros pasan por el raíz.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
