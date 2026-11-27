"""Las tablas resumidas responden igual que las tablas base, en cada motor."""

from dataclasses import dataclass
from datetime import date

import pytest

from app.engine.builder import build_sql
from app.engine.catalog import Catalog, VerifiedPlan
from app.engine.dialects import Granularity
from app.engine.periods import PeriodRange
from app.engine.summary import plan_for_summary, route_summary
from app.semantic.schema import SemanticModel
from tests.integration.helpers import Motor, assert_mismas_filas, ejecutar

ESTE_MES = PeriodRange(date(2026, 11, 1), date(2026, 12, 1), "noviembre de 2026", "month", True)
MES_PASADO = PeriodRange(date(2026, 10, 1), date(2026, 11, 1), "octubre de 2026", "month", False)
ANIO_2025 = PeriodRange(date(2025, 1, 1), date(2026, 1, 1), "2025", "year", False)
TRES_A_17_MARZO = PeriodRange(date(2026, 3, 3), date(2026, 3, 18), "3 al 17 mar", "range", False)


@dataclass(frozen=True)
class Caso:
    periodo: PeriodRange
    dimensiones: tuple[str, ...]
    grano: Granularity | None
    resumida: str


CASOS = {
    "este mes": Caso(ESTE_MES, (), None, "ventas_diarias"),
    "mes pasado": Caso(MES_PASADO, (), None, "ventas_mensuales"),
    "2025 por mes": Caso(ANIO_2025, (), "month", "ventas_mensuales"),
    "3 al 17 de marzo": Caso(TRES_A_17_MARZO, (), None, "ventas_diarias"),
    "octubre por canal": Caso(MES_PASADO, ("facturas.canal",), None, "ventas_diarias"),
    "octubre por sucursal": Caso(MES_PASADO, ("sucursales.nombre",), None, "ventas_mensuales"),
}


@pytest.mark.parametrize("nombre", list(CASOS))
def test_resumida_igual_a_las_tablas_base(
    motor: Motor, sqlite: Motor, modelo: SemanticModel, nombre: str
) -> None:
    caso = CASOS[nombre]
    plan = Catalog(modelo).verify("ventas_netas", caso.dimensiones, (), "gerencia_general")
    decision = route_summary(modelo, plan, period=caso.periodo, time_grain=caso.grano)
    assert decision.table == caso.resumida

    ruteado = plan_for_summary(modelo, plan, caso.resumida)

    def sql(donde: Motor, que: VerifiedPlan) -> str:
        return build_sql(modelo, que, donde.dialect, period=caso.periodo, time_grain=caso.grano).sql

    base = ejecutar(motor, sql(motor, plan))
    resumida = ejecutar(motor, sql(motor, ruteado))
    referencia = ejecutar(sqlite, sql(sqlite, plan))

    assert base
    assert_mismas_filas(resumida, base)
    assert_mismas_filas(base, referencia)
