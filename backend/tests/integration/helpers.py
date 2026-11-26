"""Utilidades de las pruebas de integración multimotor (ver ``conftest.py``)."""

import importlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from app.db.models import Datasource
from app.demo.seed import cargar
from app.engine.dialects import Dialect
from app.engine.executor import QueryExecutor
from app.semantic.schema import SemanticModel, parse_semantic_model

EJEMPLO = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
# Misma fecha que el resto de las pruebas del motor: noviembre de 2026 es el mes en curso.
HASTA = date(2026, 11, 25)
SEMILLA = 42

# Variable de entorno con la URL de SQLAlchemy de cada motor.
VARIABLES: dict[Dialect, str] = {
    "postgres": "CHATIAPP_IT_POSTGRES_URL",
    "mysql": "CHATIAPP_IT_MYSQL_URL",
    "tsql": "CHATIAPP_IT_TSQL_URL",
}
# Base que se crea en SQL Server si no existe (el contenedor solo trae ``master``).
BASE_TSQL = "chatiapp_it"


@dataclass(frozen=True)
class Motor:
    dialect: Dialect
    url: str


def cargar_modelo() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    return parse_semantic_model(yaml.safe_load(EJEMPLO.read_text()))


def fuente(dialect: Dialect, max_rows: int = 10_000) -> Datasource:
    return Datasource(id=uuid.uuid4(), name="integracion", dialect=dialect, max_rows=max_rows)


def url_configurada(dialect: Dialect) -> str | None:
    return os.environ.get(VARIABLES[dialect]) or None


def preparar_url(dialect: Dialect, url: str) -> str:
    """En SQL Server crea la base de las pruebas y devuelve la URL que apunta a ella."""
    if dialect != "tsql":
        return url
    base = make_url(url)
    admin = create_engine(base.set(database="master"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"IF DB_ID('{BASE_TSQL}') IS NULL CREATE DATABASE {BASE_TSQL}"))
    finally:
        admin.dispose()
    return base.set(database=BASE_TSQL).render_as_string(hide_password=False)


def crear_motor(url: str, dialect: Dialect) -> Engine:
    if dialect == "tsql":
        return create_engine(url, fast_executemany=True)
    return create_engine(url)


def cargar_demo(motor: Motor) -> None:
    engine = crear_motor(motor.url, motor.dialect)
    try:
        cargar(engine, seed=SEMILLA, hasta=HASTA)
    finally:
        engine.dispose()


_EJECUTOR = QueryExecutor()
_NUMERO = re.compile(r"^-?\d+(\.\d+)?$")


def cerrar_pools() -> None:
    _EJECUTOR.dispose()


def ejecutar(motor: Motor, sql: str) -> list[list[Any]]:
    """Ejecuta con el ejecutor real de la app (solo lectura, serialización estable)."""
    resultado = _EJECUTOR.execute_sync(
        f"it-{motor.dialect}", motor.url, motor.dialect, sql, max_rows=100_000
    )
    assert not resultado.truncated
    return list(resultado.rows)


def _celda(valor: Any) -> Any:
    """Deja los valores comparables entre motores: números como float, fechas como AAAA-MM-DD."""
    if isinstance(valor, bool) or valor is None:
        return valor
    if isinstance(valor, int | float):
        return float(valor)
    if isinstance(valor, str):
        if _NUMERO.match(valor):
            return float(valor)
        if re.match(r"^\d{4}-\d{2}-\d{2}T", valor):
            return valor[:10]
    return valor


def normalizar(filas: list[list[Any]]) -> list[list[Any]]:
    return [[_celda(v) for v in fila] for fila in filas]


def _clave(fila: list[Any]) -> list[tuple[int, Any]]:
    return [
        (0, round(v, 2)) if isinstance(v, float) else (1, "" if v is None else str(v)) for v in fila
    ]


def assert_mismas_filas(
    real: list[list[Any]], esperado: list[list[Any]], *, mismo_orden: bool = False
) -> None:
    """Mismos valores; los números con tolerancia (decimal frente a flotante).

    El orden solo se compara con `mismo_orden=True`: cada motor ordena el texto con su propia
    collation (SQLite por bytes pone «Celulares» antes que «Cámaras»; PostgreSQL, MySQL y SQL
    Server, al revés), así que un ORDER BY sobre texto no da el mismo orden en todos.
    """
    real, esperado = normalizar(real), normalizar(esperado)
    if not mismo_orden:
        real, esperado = sorted(real, key=_clave), sorted(esperado, key=_clave)
    assert len(real) == len(esperado), f"{len(real)} filas frente a {len(esperado)}"
    for i, (a, b) in enumerate(zip(real, esperado, strict=True)):
        assert len(a) == len(b), f"fila {i}: {a} frente a {b}"
        for x, y in zip(a, b, strict=True):
            if isinstance(x, float) and isinstance(y, float):
                assert abs(x - y) <= max(0.01, 1e-6 * abs(y)), f"fila {i}: {a} frente a {b}"
            else:
                assert x == y, f"fila {i}: {a} frente a {b}"
