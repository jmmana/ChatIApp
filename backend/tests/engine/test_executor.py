import asyncio
import sqlite3
import time
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.executor import (
    QueryExecutionError,
    QueryExecutor,
    QueryTimeoutError,
    serialize_value,
)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    path = tmp_path / "demo.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER, nombre TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"n{i}") for i in range(10)])
    conn.commit()
    conn.close()
    return f"sqlite:///{path}"


@pytest.fixture
def ex() -> Iterator[QueryExecutor]:
    executor = QueryExecutor()
    yield executor
    executor.dispose()


def test_ejecuta_y_devuelve_columnas_y_filas(ex: QueryExecutor, db_url: str) -> None:
    res = ex.execute_sync("a", db_url, "sqlite", "SELECT id, nombre FROM t ORDER BY id LIMIT 2")
    assert res.executed
    assert res.columns == ["id", "nombre"]
    assert res.rows == [[0, "n0"], [1, "n1"]]
    assert not res.truncated


def test_recorta_a_max_rows_e_informa_truncated(ex: QueryExecutor, db_url: str) -> None:
    res = ex.execute_sync("a", db_url, "sqlite", "SELECT id FROM t", max_rows=3)
    assert len(res.rows) == 3
    assert res.truncated


def test_exactamente_max_rows_no_es_truncado(ex: QueryExecutor, db_url: str) -> None:
    res = ex.execute_sync("a", db_url, "sqlite", "SELECT id FROM t", max_rows=10)
    assert len(res.rows) == 10
    assert not res.truncated


def test_execute_false_no_ejecuta(ex: QueryExecutor) -> None:
    res = ex.execute_sync("a", "sqlite:///no-existe/x.db", "sqlite", "SELECT 1", execute=False)
    assert not res.executed
    assert res.rows == []


def test_tiempo_maximo_con_consulta_lenta(ex: QueryExecutor, db_url: str) -> None:
    slow = (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 1000000000) "
        "SELECT COUNT(*) FROM c"
    )
    started = time.perf_counter()
    with pytest.raises(QueryTimeoutError):
        ex.execute_sync("a", db_url, "sqlite", slow, timeout_seconds=1)
    assert time.perf_counter() - started < 10


def test_error_de_sql_se_informa_sin_filtrar(ex: QueryExecutor, db_url: str) -> None:
    with pytest.raises(QueryExecutionError):
        ex.execute_sync("a", db_url, "sqlite", "SELECT * FROM no_existe")


def test_version_asincrona(ex: QueryExecutor, db_url: str) -> None:
    res = asyncio.run(ex.execute("a", db_url, "sqlite", "SELECT COUNT(*) FROM t"))
    assert res.rows == [[10]]


def test_serializa_tipos() -> None:
    warnings: list[str] = []
    assert serialize_value(Decimal("1234.5000"), "c", warnings) == "1234.5000"
    assert serialize_value(Decimal("1E+3"), "c", warnings) == "1000"
    assert serialize_value(date(2026, 1, 31), "c", warnings) == "2026-01-31"
    assert serialize_value(datetime(2026, 1, 31, 8, 30), "c", warnings) == "2026-01-31T08:30:00"
    assert serialize_value(b"\x00\x01", "foto", warnings) is None
    assert serialize_value(b"\x02", "foto", warnings) is None
    assert len(warnings) == 1
    assert "foto" in warnings[0]


def test_binarios_de_la_base_salen_como_null_con_advertencia(
    ex: QueryExecutor, db_url: str
) -> None:
    res = ex.execute_sync("a", db_url, "sqlite", "SELECT X'00FF' AS blob")
    assert res.rows == [[None]]
    assert res.warnings


# ---------------------------------------------------------------------- demo «Ventas»


@pytest.fixture(scope="module")
def demo_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    from app.demo.seed import generar

    path = tmp_path_factory.mktemp("demo") / "ventas.db"
    generar(path, seed=42, hasta=date(2026, 11, 25))
    return f"sqlite:///{path}"


def test_demo_con_porcentajes_en_el_sql(ex: QueryExecutor, demo_url: str) -> None:
    # `%` en strftime y LIKE no debe confundirse con un marcador de parámetro del driver.
    sql = (
        "SELECT strftime('%Y-%m-01', fecha) AS mes, COUNT(*) AS n FROM facturas "
        "WHERE canal LIKE '%' GROUP BY 1 ORDER BY 1"
    )
    result = ex.execute_sync("demo", demo_url, "sqlite", sql, max_rows=500)
    assert result.columns == ["mes", "n"]
    assert result.rows and all(str(row[0]).endswith("-01") for row in result.rows)


def test_demo_es_solo_lectura(ex: QueryExecutor, demo_url: str) -> None:
    with pytest.raises(QueryExecutionError):
        ex.execute_sync("demo", demo_url, "sqlite", "DROP TABLE facturas")
    result = ex.execute_sync("demo", demo_url, "sqlite", "SELECT COUNT(*) FROM facturas")
    assert result.rows[0][0] > 0
