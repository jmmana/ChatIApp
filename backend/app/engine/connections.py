"""Conexión a las bases que consulta ChatIApp: enmascarado de URL y prueba de conexión.

No importa nada de ``app/llm``. La URL se descifra fuera de este módulo; aquí solo se usa.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, NoSuchModuleError, OperationalError

from app.engine.dialects import Dialect

ErrorKind = Literal["auth", "network", "driver_missing", "unknown"]

# Extra de ``pyproject.toml`` que instala el driver de cada dialecto (SQLite viene incluido).
DIALECT_EXTRA: dict[Dialect, str] = {
    "postgres": "postgres",
    "tsql": "sqlserver",
    "mysql": "mysql",
    "oracle": "oracle",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
}

# Parámetro del driver que limita la espera al conectar.
_CONNECT_TIMEOUT_ARG: dict[Dialect, str] = {
    "sqlite": "timeout",
    "postgres": "connect_timeout",
    "mysql": "connect_timeout",
}

_AUTH_PATTERN = re.compile(
    r"password|authentication|auth failed|login failed|access denied|permission denied"
    r"|invalid credentials|ORA-01017",
    re.IGNORECASE,
)
_MASK = "***"


class InvalidUrlError(ValueError):
    """La URL de conexión no se puede interpretar (el mensaje nunca incluye la URL)."""


@dataclass(frozen=True)
class ConnectionFailure:
    kind: ErrorKind
    message: str


@dataclass(frozen=True)
class ConnectionResult:
    ok: bool
    latency_ms: int | None = None
    server_version: str | None = None
    error: ConnectionFailure | None = None


def validate_url(url: str) -> None:
    """Lanza ``InvalidUrlError`` si ``url`` no tiene forma de URL de SQLAlchemy."""
    try:
        make_url(url)
    except (ArgumentError, ValueError) as exc:
        raise InvalidUrlError("La URL de conexión no es válida") from exc


def mask_url(url: str) -> str:
    """Oculta usuario y contraseña: ``postgresql://***:***@host/db``."""
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):
        return _MASK
    updates: dict[str, Any] = {}
    if parsed.username is not None:
        updates["username"] = _MASK
    if parsed.password is not None:
        updates["password"] = _MASK
    rendered = parsed.set(**updates).render_as_string(hide_password=False)
    # SQLAlchemy codifica el usuario y la clave: devolvemos la máscara legible.
    return rendered.replace(quote(_MASK, safe=""), _MASK)


def missing_driver_message(dialect: Dialect) -> str:
    extra = DIALECT_EXTRA.get(dialect)
    if extra is None:
        return f"Falta el driver del dialecto «{dialect}»"
    return f"Falta el driver de «{dialect}»: instálalo con `uv sync --extra {extra}`"


def classify_error(exc: BaseException, dialect: Dialect) -> ConnectionFailure:
    """Clasifica un fallo de conexión sin filtrar la URL ni credenciales."""
    if isinstance(exc, ModuleNotFoundError | NoSuchModuleError):
        return ConnectionFailure("driver_missing", missing_driver_message(dialect))
    if isinstance(exc, OperationalError):
        if _AUTH_PATTERN.search(str(exc.orig or exc)):
            return ConnectionFailure("auth", "Usuario o contraseña rechazados por la base")
        return ConnectionFailure("network", "No se pudo alcanzar la base de datos")
    if isinstance(exc, OSError):
        return ConnectionFailure("network", "No se pudo alcanzar la base de datos")
    return ConnectionFailure("unknown", f"Error al conectar ({type(exc).__name__})")


def connect_args(dialect: Dialect, timeout_seconds: int) -> dict[str, Any]:
    """Argumentos del driver que limitan la espera al conectar (vacío si no hay uno conocido)."""
    arg = _CONNECT_TIMEOUT_ARG.get(dialect)
    return {arg: timeout_seconds} if arg is not None else {}


def check_connection(url: str, dialect: Dialect, timeout_seconds: int = 10) -> ConnectionResult:
    """Abre una conexión, ejecuta ``SELECT 1`` y mide la latencia."""
    engine: Engine | None = None
    try:
        engine = create_engine(url, connect_args=connect_args(dialect, timeout_seconds))
        started = time.perf_counter()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            latency_ms = round((time.perf_counter() - started) * 1000)
            version_info = conn.dialect.server_version_info
        version = ".".join(str(part) for part in version_info) if version_info else "desconocida"
        return ConnectionResult(ok=True, latency_ms=latency_ms, server_version=version)
    except Exception as exc:  # cualquier fallo se clasifica y se informa
        return ConnectionResult(ok=False, error=classify_error(exc, dialect))
    finally:
        if engine is not None:
            engine.dispose()
