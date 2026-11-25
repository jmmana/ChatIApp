import sqlite3
from datetime import date, timedelta

import pytest
import sqlglot

from app.engine.dialects import (
    DIALECTS,
    GRANULARITIES,
    SQLGLOT_DIALECT,
    WEEK_STARTS,
    ColumnType,
    Dialect,
    Granularity,
    WeekStart,
    date_literal,
    date_trunc,
)

D = date(2026, 11, 1)


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("sqlite", "'2026-11-01'"),
        ("postgres", "CAST('2026-11-01' AS DATE)"),
        ("mysql", "'2026-11-01'"),
        ("tsql", "'20261101'"),
        ("oracle", "TO_DATE('2026-11-01', 'YYYY-MM-DD')"),
        ("snowflake", "CAST('2026-11-01' AS DATE)"),
        ("bigquery", "CAST('2026-11-01' AS DATE)"),
    ],
)
def test_date_literal(dialect: Dialect, expected: str) -> None:
    assert date_literal(dialect, D) == expected


def test_bigquery_timestamp_literal() -> None:
    assert date_literal("bigquery", D, "timestamp") == "CAST('2026-11-01' AS TIMESTAMP)"


def _roundtrip(sql: str, dialect: Dialect) -> str:
    name = SQLGLOT_DIALECT[dialect]
    first = sqlglot.parse_one(sql, read=name).sql(dialect=name)
    # Estable: regenerar lo regenerado no cambia nada.
    assert sqlglot.parse_one(first, read=name).sql(dialect=name) == first
    return first


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("granularity", GRANULARITIES)
@pytest.mark.parametrize("week_starts_on", ["monday", "sunday", "saturday"])
@pytest.mark.parametrize("column_type", ["date", "timestamp"])
def test_trunc_parses_in_dialect(
    dialect: Dialect, granularity: Granularity, week_starts_on: WeekStart, column_type: ColumnType
) -> None:
    expr = date_trunc(dialect, "f.fecha", granularity, week_starts_on, column_type)
    assert _roundtrip(f"SELECT {expr} AS periodo FROM f", dialect)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("column_type", ["date", "timestamp"])
def test_literal_parses_in_dialect(dialect: Dialect, column_type: ColumnType) -> None:
    lit = date_literal(dialect, D, column_type)
    assert _roundtrip(f"SELECT 1 FROM f WHERE f.fecha >= {lit}", dialect)


def test_known_month_expressions() -> None:
    assert date_trunc("sqlite", "c", "month") == "STRFTIME('%Y-%m-01', c)"
    assert date_trunc("postgres", "c", "month") == "DATE_TRUNC('MONTH', c)"
    assert date_trunc("mysql", "c", "month") == "DATE_FORMAT(c, '%Y-%m-01')"
    assert date_trunc("tsql", "c", "month") == "DATEFROMPARTS(YEAR(c), MONTH(c), 1)"
    assert date_trunc("oracle", "c", "month") == "TRUNC(c, 'MONTH')"
    assert date_trunc("snowflake", "c", "month") == "DATE_TRUNC('MONTH', c)"
    assert date_trunc("bigquery", "c", "month") == "DATE_TRUNC(c, MONTH)"
    assert date_trunc("bigquery", "c", "week", "sunday") == "DATE_TRUNC(c, WEEK(SUNDAY))"


def _expected(d: date, granularity: Granularity, week_starts_on: WeekStart) -> str:
    if granularity == "day":
        return d.isoformat()
    if granularity == "week":
        back = (d.weekday() - WEEK_STARTS.index(week_starts_on)) % 7
        return (d - timedelta(days=back)).isoformat()
    if granularity == "month":
        return d.replace(day=1).isoformat()
    if granularity == "quarter":
        return d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1).isoformat()
    return d.replace(month=1, day=1).isoformat()


@pytest.mark.parametrize("week_starts_on", WEEK_STARTS)
@pytest.mark.parametrize("granularity", GRANULARITIES)
def test_sqlite_executes_period_starts(granularity: Granularity, week_starts_on: WeekStart) -> None:
    days = [date(2025, 12, 28) + timedelta(days=i) for i in range(0, 430, 3)]
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE facturas (id INTEGER PRIMARY KEY, fecha DATE NOT NULL)")
    con.executemany("INSERT INTO facturas (fecha) VALUES (?)", [(d.isoformat(),) for d in days])
    expr = date_trunc("sqlite", "fecha", granularity, week_starts_on)
    rows = con.execute(f"SELECT {expr} FROM facturas ORDER BY id").fetchall()
    assert [r[0] for r in rows] == [_expected(d, granularity, week_starts_on) for d in days]


def test_sqlite_iso_text_literal_compares_as_text() -> None:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE f (fecha DATE)")
    con.executemany("INSERT INTO f VALUES (?)", [("2026-10-31",), ("2026-11-01",)])
    lit = date_literal("sqlite", D)
    assert con.execute(f"SELECT COUNT(*) FROM f WHERE fecha >= {lit}").fetchone() == (1,)
