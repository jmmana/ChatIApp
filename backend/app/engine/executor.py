"""Ejecutor de solo lectura: pool por fuente, tiempo máximo, tope de filas y serialización.

Fuente: docs/BASES_DE_DATOS.md#ejecución. Recibe SQL ya validado por el guardián y la URL ya
descifrada. No importa nada de ``app/llm``; la ejecución corre en un hilo aparte.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from app.engine.dialects import Dialect

JsonValue = str | int | float | bool | None


class QueryTimeoutError(Exception):
    """La consulta superó ``timeout_seconds`` y se canceló."""


class QueryExecutionError(Exception):
    """La base rechazó o falló la consulta (el mensaje nunca incluye la URL)."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[JsonValue]] = field(default_factory=list)
    truncated: bool = False
    executed: bool = True
    warnings: list[str] = field(default_factory=list)


def serialize_value(value: Any, column: str, warnings: list[str]) -> JsonValue:
    """Convierte un valor de la base a un tipo JSON estable."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        message = f"La columna «{column}» es binaria y se devolvió como null"
        if message not in warnings:
            warnings.append(message)
        return None
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return str(value)


class QueryExecutor:
    """Mantiene un pool de conexiones por fuente y ejecuta consultas de solo lectura."""

    def __init__(self) -> None:
        self._engines: dict[str, tuple[str, Engine]] = {}
        self._lock = threading.Lock()

    def _engine(self, source_id: str, url: str, dialect: Dialect) -> Engine:
        with self._lock:
            cached = self._engines.get(source_id)
            if cached is not None and cached[0] == url:
                return cached[1]
            if cached is not None:
                cached[1].dispose()
            kwargs: dict[str, Any] = {"pool_pre_ping": True}
            if dialect == "sqlite":
                kwargs["connect_args"] = {"check_same_thread": False}
            engine = create_engine(url, **kwargs)
            self._engines[source_id] = (url, engine)
            return engine

    def dispose(self, source_id: str | None = None) -> None:
        """Cierra el pool de una fuente (o de todas)."""
        with self._lock:
            ids = [source_id] if source_id is not None else list(self._engines)
            for key in ids:
                entry = self._engines.pop(key, None)
                if entry is not None:
                    entry[1].dispose()

    def execute_sync(
        self,
        source_id: str,
        url: str,
        dialect: Dialect,
        sql: str,
        *,
        execute: bool = True,
        max_rows: int = 1000,
        timeout_seconds: int = 30,
    ) -> QueryResult:
        if not execute:
            return QueryResult(executed=False)
        engine = self._engine(source_id, url, dialect)
        timed_out = threading.Event()
        timer: threading.Timer | None = None
        try:
            with engine.connect() as conn:
                timer = self._prepare(conn, dialect, timeout_seconds, timed_out)
                try:
                    result = conn.exec_driver_sql(sql)
                    columns = list(result.keys())
                    fetched = result.fetchmany(max_rows + 1)
                finally:
                    if timer is not None:
                        timer.cancel()
                    conn.rollback()
        except DBAPIError as exc:
            if timed_out.is_set() or _is_timeout(exc):
                raise QueryTimeoutError(
                    f"La consulta superó el tiempo máximo de {timeout_seconds} s"
                ) from exc
            detail = type(exc.orig).__name__
            raise QueryExecutionError(f"La base rechazó la consulta ({detail})") from exc
        truncated = len(fetched) > max_rows
        warnings: list[str] = []
        rows = [
            [serialize_value(v, columns[i], warnings) for i, v in enumerate(row)]
            for row in fetched[:max_rows]
        ]
        return QueryResult(columns=columns, rows=rows, truncated=truncated, warnings=warnings)

    async def execute(
        self,
        source_id: str,
        url: str,
        dialect: Dialect,
        sql: str,
        *,
        execute: bool = True,
        max_rows: int = 1000,
        timeout_seconds: int = 30,
    ) -> QueryResult:
        """Igual que ``execute_sync`` pero en un hilo, sin bloquear el event loop."""
        return await asyncio.to_thread(
            self.execute_sync,
            source_id,
            url,
            dialect,
            sql,
            execute=execute,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _prepare(
        conn: Connection, dialect: Dialect, timeout_seconds: int, timed_out: threading.Event
    ) -> threading.Timer | None:
        """Deja la transacción en solo lectura y fija el tiempo máximo según el motor."""
        if dialect == "postgres":
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_seconds) * 1000}")
        elif dialect == "mysql":
            conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET SESSION max_execution_time = {int(timeout_seconds) * 1000}")
        elif dialect == "sqlite":
            raw = conn.connection.driver_connection

            def interrupt() -> None:
                timed_out.set()
                raw.interrupt()  # type: ignore[union-attr]

            timer = threading.Timer(timeout_seconds, interrupt)
            timer.daemon = True
            timer.start()
            return timer
        return None


def _is_timeout(exc: DBAPIError) -> bool:
    text = str(exc.orig or exc).lower()
    markers = ("statement timeout", "max_execution_time", "maximum execution")
    return any(marker in text for marker in markers)


executor = QueryExecutor()
