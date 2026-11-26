"""SQL Server: el literal de fecha `'YYYYMMDD'` no depende del idioma de la sesión."""

from datetime import date

import pytest
from sqlalchemy import create_engine

from app.engine.builder import build_sql
from app.engine.catalog import Catalog
from app.engine.dialects import Dialect
from app.engine.periods import PeriodRange
from app.semantic.schema import SemanticModel
from tests.integration.helpers import Motor, assert_mismas_filas, ejecutar

MARZO = PeriodRange(date(2025, 3, 1), date(2025, 4, 1), "marzo de 2025", "month", False)
IDIOMAS = ["us_english", "british", "spanish"]


def _sql(modelo: SemanticModel, dialect: Dialect) -> str:
    plan = Catalog(modelo).verify("num_facturas", (), (), "gerencia_general")
    return build_sql(modelo, plan, dialect, period=MARZO).sql


def test_el_constructor_emite_literales_yyyymmdd(sqlserver: Motor, modelo: SemanticModel) -> None:
    sql = _sql(modelo, "tsql")
    assert "'20250301'" in sql
    assert "'20250401'" in sql
    assert "2025-03-01" not in sql


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_mismo_resultado_con_cualquier_idioma_de_sesion(
    sqlserver: Motor, sqlite: Motor, modelo: SemanticModel, idioma: str
) -> None:
    esperado = ejecutar(sqlite, _sql(modelo, "sqlite"))
    engine = create_engine(sqlserver.url)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(f"SET LANGUAGE {idioma}")
            real = [list(fila) for fila in conn.exec_driver_sql(_sql(modelo, "tsql"))]
            conn.rollback()
    finally:
        engine.dispose()
    assert real[0][0] > 0
    assert_mismas_filas(real, esperado)


def test_con_british_yyyymmdd_se_lee_bien_en_columnas_datetime(sqlserver: Motor) -> None:
    engine = create_engine(sqlserver.url)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SET LANGUAGE british")
            conn.exec_driver_sql("CREATE TABLE #t (f DATETIME NOT NULL)")
            conn.exec_driver_sql(
                "INSERT INTO #t VALUES ('20250228 23:59:59'), ('20250301'), "
                "('20250331 23:59:59'), ('20250401')"
            )
            cuenta = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM #t WHERE f >= '20250301' AND f < '20250401'"
            ).scalar_one()
            # La trampa que evita el formato: con `british` (día-mes-año), el ISO con guiones
            # se lee como año-día-mes en columnas `datetime`.
            mes = conn.exec_driver_sql(
                "SELECT MONTH(CAST('2025-03-04' AS DATETIME))"
            ).scalar_one()
            mes_compacto = conn.exec_driver_sql(
                "SELECT MONTH(CAST('20250304' AS DATETIME))"
            ).scalar_one()
            conn.rollback()
    finally:
        engine.dispose()
    assert cuenta == 2
    assert mes_compacto == 3
    assert mes == 4
