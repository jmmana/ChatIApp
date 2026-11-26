import importlib
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.demo.seed import generar
from app.engine.builder import build_sql
from app.engine.catalog import Catalog, PlanFilter
from app.engine.dialects import Granularity
from app.engine.periods import PeriodRange
from app.engine.summary import SummaryDecision, plan_for_summary, route_summary
from app.semantic.schema import SemanticModel, parse_semantic_model

ROOT = Path(__file__).parents[3]
EXAMPLE = ROOT / "examples" / "ventas" / "semantic-model.yaml"

# La demo se genera «hoy» = 2026-11-25: noviembre de 2026 es el mes en curso.
HOY = date(2026, 11, 25)
ESTE_MES = PeriodRange(date(2026, 11, 1), date(2026, 12, 1), "noviembre de 2026", "month", True)
MES_PASADO = PeriodRange(date(2026, 10, 1), date(2026, 11, 1), "octubre de 2026", "month", False)
ANIO_2025 = PeriodRange(date(2025, 1, 1), date(2026, 1, 1), "2025", "year", False)
TRES_A_17_MARZO = PeriodRange(date(2026, 3, 3), date(2026, 3, 18), "3 al 17 mar", "range", False)
ESTE_ANIO = PeriodRange(date(2026, 1, 1), date(2027, 1, 1), "2026", "year", True)


@pytest.fixture(scope="module")
def model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    return parse_semantic_model(yaml.safe_load(EXAMPLE.read_text()))


@pytest.fixture(scope="module")
def catalog(model: SemanticModel) -> Catalog:
    return Catalog(model)


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    path = tmp_path_factory.mktemp("demo") / "ventas.db"
    generar(path, seed=42, hasta=HOY)
    connection = sqlite3.connect(path)
    yield connection
    connection.close()


@dataclass(frozen=True)
class Case:
    metric: str
    period: PeriodRange
    dimensions: tuple[str, ...]
    time_grain: Granularity | None
    expected: str | None  # tabla resumida elegida; None = tablas base


CASES = {
    "este mes": Case("ventas_netas", ESTE_MES, (), None, "ventas_diarias"),
    "mes pasado": Case("ventas_netas", MES_PASADO, (), None, "ventas_mensuales"),
    "2025 por mes": Case("ventas_netas", ANIO_2025, (), "month", "ventas_mensuales"),
    "3 al 17 de marzo": Case("ventas_netas", TRES_A_17_MARZO, (), None, "ventas_diarias"),
    "octubre por canal": Case(
        "ventas_netas", MES_PASADO, ("facturas.canal",), None, "ventas_diarias"
    ),
    "unidades por categoría": Case(
        "unidades_vendidas", MES_PASADO, ("productos.categoria",), None, None
    ),
    "clientes activos": Case("clientes_activos", ESTE_ANIO, (), None, None),
}


def _route(model: SemanticModel, catalog: Catalog, case: Case) -> SummaryDecision:
    plan = catalog.verify(case.metric, case.dimensions, role="gerencia_general")
    return route_summary(model, plan, period=case.period, time_grain=case.time_grain)


@pytest.mark.parametrize("name", list(CASES))
def test_preguntas_de_la_demo_eligen_la_tabla_indicada(
    model: SemanticModel, catalog: Catalog, name: str
) -> None:
    case = CASES[name]

    decision = _route(model, catalog, case)

    assert decision.table == case.expected
    assert decision.reason


@pytest.mark.parametrize("name", [n for n, c in CASES.items() if c.expected])
def test_resultado_enrutado_es_identico_al_de_las_tablas_base(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection, name: str
) -> None:
    case = CASES[name]
    plan = catalog.verify(case.metric, case.dimensions, role="gerencia_general")
    assert case.expected is not None
    kwargs: dict[str, Any] = {"period": case.period, "time_grain": case.time_grain}

    base = conn.execute(build_sql(model, plan, "sqlite", **kwargs).sql).fetchall()
    routed_plan = plan_for_summary(model, plan, case.expected)
    built = build_sql(model, routed_plan, "sqlite", **kwargs)
    routed = conn.execute(built.sql).fetchall()

    assert built.tables[0] == case.expected
    assert base
    assert len(routed) == len(base)
    for expected_row, row in zip(base, routed, strict=True):
        assert row[:-1] == expected_row[:-1]
        assert row[-1] == pytest.approx(expected_row[-1])


def test_resultado_enrutado_con_filtro_y_dimension_por_relacion(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    filters = [PlanFilter("facturas.canal", "=", "ONLINE")]
    plan = catalog.verify("ventas_netas", ["sucursales.nombre"], filters, "gerencia_general")

    decision = route_summary(model, plan, period=MES_PASADO)
    # ventas_mensuales no tiene canal: el filtro obliga a la diaria.
    assert decision.table == "ventas_diarias"

    base = conn.execute(build_sql(model, plan, "sqlite", period=MES_PASADO).sql).fetchall()
    routed_plan = plan_for_summary(model, plan, "ventas_diarias")
    routed = conn.execute(build_sql(model, routed_plan, "sqlite", period=MES_PASADO).sql).fetchall()

    assert [r[0] for r in routed] == [r[0] for r in base]
    assert [r[1] for r in routed] == pytest.approx([r[1] for r in base])


# ---------------------------------------------------------------------- motivos


def test_motivo_del_mes_en_curso(model: SemanticModel, catalog: Catalog) -> None:
    decision = _route(model, catalog, CASES["este mes"])

    assert ("ventas_mensuales", "no incluye el mes en curso (regla 5)") in decision.rejected
    assert "ventas_mensuales no incluye el mes en curso" in decision.reason
    assert decision.reason.startswith("Se usa ventas_diarias")


def test_motivo_de_rango_sin_alinear(model: SemanticModel, catalog: Catalog) -> None:
    decision = _route(model, catalog, CASES["3 al 17 de marzo"])

    [(table, why)] = decision.rejected
    assert table == "ventas_mensuales"
    assert "no está alineado" in why
    assert "regla 4" in why


def test_motivo_de_dimension_faltante(model: SemanticModel, catalog: Catalog) -> None:
    decision = _route(model, catalog, CASES["octubre por canal"])

    assert ("ventas_mensuales", "no tiene «facturas.canal» (regla 2)") in decision.rejected


def test_motivo_de_metrica_no_aditiva_sin_expresion(model: SemanticModel, catalog: Catalog) -> None:
    decision = _route(model, catalog, CASES["clientes activos"])

    assert decision.table is None
    assert decision.reason.startswith("Se usan las tablas base")
    assert decision.reason.count("regla 6") == 2


def test_motivo_de_metrica_aditiva_no_declarada(model: SemanticModel, catalog: Catalog) -> None:
    plan = catalog.verify("ventas_sin_iva", role="gerencia_general")

    decision = route_summary(model, plan, period=MES_PASADO)

    assert decision.table is None
    assert "no declara la métrica «ventas_sin_iva» (regla 1)" in decision.reason


# ---------------------------------------------------------------------- reglas sueltas


def test_gana_la_granularidad_mas_gruesa(model: SemanticModel, catalog: Catalog) -> None:
    plan = catalog.verify("ventas_netas", ["sucursales.nombre"], role="gerencia_general")

    decision = route_summary(model, plan, period=MES_PASADO, time_grain="month")

    assert decision.table == "ventas_mensuales"
    assert "más gruesa" in decision.reason
    assert "ventas_diarias" in decision.reason


def test_granularidad_pedida_mas_fina_que_la_resumida(
    model: SemanticModel, catalog: Catalog
) -> None:
    plan = catalog.verify("ventas_netas", role="gerencia_general")

    decision = route_summary(model, plan, period=MES_PASADO, time_grain="day")

    assert decision.table == "ventas_diarias"
    assert any("regla 3" in why for _, why in decision.rejected)


def test_semana_pedida_no_sale_de_una_mensual(model: SemanticModel, catalog: Catalog) -> None:
    plan = catalog.verify("ventas_netas", role="gerencia_general")

    decision = route_summary(model, plan, period=ANIO_2025, time_grain="week")

    assert decision.table == "ventas_diarias"


def test_sin_periodo_exige_que_la_resumida_incluya_el_periodo_en_curso(
    model: SemanticModel, catalog: Catalog
) -> None:
    plan = catalog.verify("ventas_netas", role="gerencia_general")

    decision = route_summary(model, plan)

    assert decision.table == "ventas_diarias"


def test_modelo_sin_resumidas_usa_las_base(model: SemanticModel, catalog: Catalog) -> None:
    plan = catalog.verify("ventas_netas", role="gerencia_general")
    sin_resumidas = model.model_copy(update={"summary_tables": []})

    decision = route_summary(sin_resumidas, plan, period=MES_PASADO)

    assert decision.table is None
    assert "no declara tablas resumidas" in decision.reason


def test_plan_para_resumida_de_una_tabla_desconocida(
    model: SemanticModel, catalog: Catalog
) -> None:
    plan = catalog.verify("ventas_netas", role="gerencia_general")

    with pytest.raises(ValueError, match="no es una tabla resumida"):
        plan_for_summary(model, plan, "facturas")


# ---------------------------------------------------------------------- regla 7: rol


def _sin_filtro_en(model: SemanticModel, table: str) -> SemanticModel:
    roles = []
    for role in model.security.roles:
        filters = [f for f in role.filters if f.table != table]
        roles.append(role.model_copy(update={"filters": filters}))
    security = model.security.model_copy(update={"roles": roles})
    return model.model_copy(update={"security": security})


def test_resumida_sin_filtro_del_rol_no_reemplaza_a_la_base(
    model: SemanticModel, catalog: Catalog
) -> None:
    sin_filtro = _sin_filtro_en(model, "ventas_mensuales")
    plan = catalog.verify("ventas_netas", role="gerente_sucursal")

    decision = route_summary(sin_filtro, plan, period=MES_PASADO, role="gerente_sucursal")

    assert decision.table != "ventas_mensuales"
    assert any("regla 7" in why for table, why in decision.rejected if table == "ventas_mensuales")


def test_rol_sin_filtros_si_puede_usar_la_resumida(model: SemanticModel, catalog: Catalog) -> None:
    sin_filtro = _sin_filtro_en(model, "ventas_mensuales")
    plan = catalog.verify("ventas_netas", role="gerencia_general")

    decision = route_summary(sin_filtro, plan, period=MES_PASADO, role="gerencia_general")

    assert decision.table == "ventas_mensuales"


def test_rol_desconocido_usa_las_tablas_base(model: SemanticModel, catalog: Catalog) -> None:
    plan = catalog.verify("ventas_netas", role="gerencia_general")

    decision = route_summary(model, plan, period=MES_PASADO, role="no-existe")

    assert decision.table is None


# ---------------------------------------------------------------------- conteos


def test_conteo_desde_resumida_da_cero_en_un_periodo_vacio(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    anio_2024 = PeriodRange(date(2024, 1, 1), date(2025, 1, 1), "2024", "year", False)
    plan = catalog.verify("num_facturas", role="gerencia_general")
    decision = route_summary(model, plan, period=anio_2024, role="gerencia_general")
    assert decision.table is not None

    routed = plan_for_summary(model, plan, decision.table)
    assert routed.metric.expression.startswith("COALESCE(")
    sql = build_sql(model, routed, "sqlite", period=anio_2024).sql
    base = build_sql(model, plan, "sqlite", period=anio_2024).sql
    assert conn.execute(sql).fetchall() == conn.execute(base).fetchall() == [(0,)]


def test_suma_desde_resumida_no_lleva_coalesce(model: SemanticModel, catalog: Catalog) -> None:
    plan = catalog.verify("ventas_netas", role="gerencia_general")
    routed = plan_for_summary(model, plan, "ventas_mensuales")
    assert not routed.metric.expression.startswith("COALESCE(")
