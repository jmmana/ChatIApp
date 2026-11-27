"""El constructor de SQL da el mismo resultado en cada motor que en SQLite."""

from dataclasses import dataclass
from datetime import date

import pytest

from app.engine.builder import build_sql
from app.engine.catalog import Catalog, PlanFilter
from app.engine.dialects import Granularity
from app.engine.periods import PeriodRange
from app.semantic.schema import SemanticModel
from tests.integration.helpers import Motor, assert_mismas_filas, ejecutar

METRICAS = [
    "ventas_netas",
    "ventas_sin_iva",
    "num_facturas",
    "ticket_promedio",
    "unidades_vendidas",
    "clientes_activos",
]
Q1 = PeriodRange(date(2025, 1, 1), date(2025, 4, 1), "T1 2025", "quarter", False)
ANIO_2025 = PeriodRange(date(2025, 1, 1), date(2026, 1, 1), "2025", "year", False)
MARZO = PeriodRange(date(2025, 3, 1), date(2025, 4, 1), "marzo de 2025", "month", False)
CAMBIO_DE_MES = PeriodRange(date(2026, 2, 15), date(2026, 3, 15), "15 feb a 14 mar", "range", False)


@dataclass(frozen=True)
class Pregunta:
    metrica: str
    periodo: PeriodRange
    dimensiones: tuple[str, ...] = ()
    filtros: tuple[PlanFilter, ...] = ()
    grano: Granularity | None = None
    limite: int | None = None


@pytest.fixture(scope="module")
def catalogo(modelo: SemanticModel) -> Catalog:
    return Catalog(modelo)


def _sql(motor: Motor, modelo: SemanticModel, catalogo: Catalog, p: Pregunta) -> str:
    plan = catalogo.verify(p.metrica, p.dimensiones, p.filtros, "gerencia_general")
    built = build_sql(
        modelo, plan, motor.dialect, period=p.periodo, time_grain=p.grano, limit=p.limite
    )
    return built.sql


def _comparar(
    motor: Motor, sqlite: Motor, modelo: SemanticModel, catalogo: Catalog, p: Pregunta
) -> list[list[object]]:
    real = ejecutar(motor, _sql(motor, modelo, catalogo, p))
    esperado = ejecutar(sqlite, _sql(sqlite, modelo, catalogo, p))
    assert real
    assert_mismas_filas(real, esperado)
    return real


@pytest.mark.parametrize("metrica", METRICAS)
def test_metrica_por_sucursal(
    motor: Motor, sqlite: Motor, modelo: SemanticModel, catalogo: Catalog, metrica: str
) -> None:
    _comparar(motor, sqlite, modelo, catalogo, Pregunta(metrica, Q1, ("sucursales.nombre",)))


@pytest.mark.parametrize("grano", ["day", "week", "month", "quarter", "year"])
def test_granos_de_tiempo(
    motor: Motor, sqlite: Motor, modelo: SemanticModel, catalogo: Catalog, grano: Granularity
) -> None:
    _comparar(motor, sqlite, modelo, catalogo, Pregunta("ventas_netas", ANIO_2025, grano=grano))


@pytest.mark.parametrize("periodo", [MARZO, CAMBIO_DE_MES], ids=["mes", "rango"])
def test_periodo_semiabierto(
    motor: Motor, sqlite: Motor, modelo: SemanticModel, catalogo: Catalog, periodo: PeriodRange
) -> None:
    filas = _comparar(motor, sqlite, modelo, catalogo, Pregunta("num_facturas", periodo))
    assert float(str(filas[0][0])) > 0


def test_dimensiones_y_filtros_por_relacion(
    motor: Motor, sqlite: Motor, modelo: SemanticModel, catalogo: Catalog
) -> None:
    pregunta = Pregunta(
        "unidades_vendidas",
        Q1,
        ("productos.categoria", "sucursales.nombre"),
        (PlanFilter("facturas.canal", "=", "ONLINE"),),
        "month",
    )
    _comparar(motor, sqlite, modelo, catalogo, pregunta)


def test_valor_con_comillas_no_rompe_la_consulta(
    motor: Motor, modelo: SemanticModel, catalogo: Catalog
) -> None:
    malicioso = PlanFilter("facturas.canal", "=", "x'; DROP TABLE facturas; --")
    pregunta = Pregunta("num_facturas", Q1, filtros=(malicioso,))
    assert ejecutar(motor, _sql(motor, modelo, catalogo, pregunta)) == [[0]]
    assert ejecutar(motor, "SELECT COUNT(*) FROM facturas")[0][0] == 50_000


def test_limite_por_motor(motor: Motor, modelo: SemanticModel, catalogo: Catalog) -> None:
    pregunta = Pregunta("ventas_netas", Q1, ("facturas.canal",), limite=2)
    assert len(ejecutar(motor, _sql(motor, modelo, catalogo, pregunta))) == 2
