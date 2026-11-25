"""Diferencias de dialecto que resuelve el motor.

Fuente: docs/BASES_DE_DATOS.md#diferencias-de-dialecto-que-resuelve-el-motor.
Las funciones reciben la expresión SQL de la columna (ya citada) y devuelven SQL listo
para incrustar en el constructor. No importan nada de ``app/llm``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Literal, get_args

Dialect = Literal["sqlite", "postgres", "mysql", "tsql", "oracle", "snowflake", "bigquery"]
Granularity = Literal["day", "week", "month", "quarter", "year"]
WeekStart = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
ColumnType = Literal["date", "timestamp"]

DIALECTS: tuple[Dialect, ...] = get_args(Dialect)
GRANULARITIES: tuple[Granularity, ...] = get_args(Granularity)
WEEK_STARTS: tuple[WeekStart, ...] = get_args(WeekStart)

# Nombre de cada dialecto en sqlglot (hoy coinciden con los nuestros).
SQLGLOT_DIALECT: dict[Dialect, str] = {d: d for d in DIALECTS}


def date_literal(dialect: Dialect, value: date, column_type: ColumnType = "date") -> str:
    """Literal de fecha para comparar contra una columna del tipo indicado."""
    iso = value.isoformat()
    if dialect in ("sqlite", "mysql"):
        return f"'{iso}'"
    if dialect == "tsql":
        return f"'{value:%Y%m%d}'"
    if dialect == "oracle":
        return f"TO_DATE('{iso}', 'YYYY-MM-DD')"
    if dialect == "bigquery" and column_type == "timestamp":
        return f"CAST('{iso}' AS TIMESTAMP)"
    return f"CAST('{iso}' AS DATE)"


# En los truncadores, ``sd`` son los días desde el lunes hasta el inicio de semana (lunes = 0).


def _trunc_sqlite(col: str, g: Granularity, sd: int) -> str:
    if g == "day":
        return f"DATE({col})"
    if g == "week":
        # %w cuenta el domingo como 0, así que el lunes es 1.
        back = f"(CAST(STRFTIME('%w', {col}) AS INTEGER) + {7 - (sd + 1) % 7}) % 7"
        return f"DATE({col}, '-' || ({back}) || ' days')"
    if g == "month":
        return f"STRFTIME('%Y-%m-01', {col})"
    if g == "quarter":
        month = f"CAST(STRFTIME('%m', {col}) AS INTEGER)"
        return f"DATE({col}, 'start of year', '+' || (({month} - 1) / 3 * 3) || ' months')"
    return f"STRFTIME('%Y-01-01', {col})"


def _trunc_postgres(col: str, g: Granularity, sd: int) -> str:
    if g == "week" and sd:
        # DATE_TRUNC('WEEK') arranca en lunes: se desplaza la columna y se devuelve el resultado.
        shifted = f"DATE_TRUNC('WEEK', {col} - INTERVAL '{sd} days')"
        return f"CAST({shifted} AS DATE) + INTERVAL '{sd} days'"
    return f"DATE_TRUNC('{g.upper()}', {col})"


def _trunc_snowflake(col: str, g: Granularity, sd: int) -> str:
    if g == "week":
        # DATE_TRUNC('WEEK') depende del parámetro de sesión WEEK_START; se calcula explícito.
        back = f"MOD(DAYOFWEEKISO({col}) - 1 - {sd} + 7, 7)"
        return f"DATEADD(DAY, -{back}, CAST({col} AS DATE))"
    return f"DATE_TRUNC('{g.upper()}', {col})"


def _trunc_mysql(col: str, g: Granularity, sd: int) -> str:
    if g == "day":
        return f"DATE({col})"
    if g == "week":
        return f"FROM_DAYS(TO_DAYS({col}) - MOD(WEEKDAY({col}) - {sd} + 7, 7))"
    if g == "month":
        return f"DATE_FORMAT({col}, '%Y-%m-01')"
    if g == "quarter":
        first_month = f"(QUARTER({col}) - 1) * 3 + 1"
        return f"STR_TO_DATE(CONCAT(YEAR({col}), '-', {first_month}, '-01'), '%Y-%m-%d')"
    return f"DATE_FORMAT({col}, '%Y-01-01')"


def _trunc_tsql(col: str, g: Granularity, sd: int) -> str:
    if g == "day":
        return f"CAST({col} AS DATE)"
    if g == "week":
        # 1900-01-01 fue lunes: no depende de SET DATEFIRST.
        days = f"DATEDIFF(DAY, '19000101', {col})"
        return f"DATEADD(DAY, -(({days} - {sd} + 7) % 7), CAST({col} AS DATE))"
    if g == "month":
        return f"DATEFROMPARTS(YEAR({col}), MONTH({col}), 1)"
    if g == "quarter":
        return f"DATEFROMPARTS(YEAR({col}), (DATEPART(QUARTER, {col}) - 1) * 3 + 1, 1)"
    return f"DATEFROMPARTS(YEAR({col}), 1, 1)"


def _trunc_oracle(col: str, g: Granularity, sd: int) -> str:
    if g == "day":
        return f"TRUNC({col})"
    if g == "week":
        # 1900-01-01 fue lunes: no depende de NLS_TERRITORY.
        days = f"TRUNC({col}) - TO_DATE('1900-01-01', 'YYYY-MM-DD')"
        return f"TRUNC({col}) - MOD({days} - {sd} + 7, 7)"
    unit = {"month": "MONTH", "quarter": "Q", "year": "YEAR"}[g]
    return f"TRUNC({col}, '{unit}')"


def _trunc_bigquery(col: str, g: Granularity, sd: int, column_type: ColumnType) -> str:
    unit = f"WEEK({WEEK_STARTS[sd].upper()})" if g == "week" else g.upper()
    func = "TIMESTAMP_TRUNC" if column_type == "timestamp" else "DATE_TRUNC"
    return f"{func}({col}, {unit})"


_TRUNCATORS: dict[Dialect, Callable[[str, Granularity, int], str]] = {
    "sqlite": _trunc_sqlite,
    "postgres": _trunc_postgres,
    "mysql": _trunc_mysql,
    "tsql": _trunc_tsql,
    "oracle": _trunc_oracle,
    "snowflake": _trunc_snowflake,
}


def date_trunc(
    dialect: Dialect,
    column: str,
    granularity: Granularity,
    week_starts_on: WeekStart = "monday",
    column_type: ColumnType = "date",
) -> str:
    """Expresión que trunca ``column`` al inicio del período (``week`` respeta el inicio)."""
    sd = WEEK_STARTS.index(week_starts_on)
    if dialect == "bigquery":
        return _trunc_bigquery(column, granularity, sd, column_type)
    return _TRUNCATORS[dialect](column, granularity, sd)
