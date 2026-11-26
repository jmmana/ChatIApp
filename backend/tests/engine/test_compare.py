import importlib
import sqlite3
from collections.abc import Iterator, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.demo.seed import generar
from app.engine.catalog import Catalog, PlanFilter, VerifiedPlan
from app.engine.compare import CompareError, Comparison, compare_previous
from app.engine.periods import PeriodConfig, PeriodRange, resolve_period
from app.semantic.schema import SemanticModel, parse_semantic_model

ROOT = Path(__file__).parents[3]
EXAMPLE = ROOT / "examples" / "ventas" / "semantic-model.yaml"
NOW = datetime(2026, 11, 25, 10, 0, tzinfo=ZoneInfo("America/Bogota"))
CFG = PeriodConfig(timezone="America/Bogota")


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
    generar(path, seed=42, hasta=date(2026, 11, 25))
    connection = sqlite3.connect(path)
    yield connection
    connection.close()


def _plan(catalog: Catalog, metric: str) -> VerifiedPlan:
    return catalog.verify(metric, role="gerencia_general")


def _period(expression: str) -> PeriodRange:
    period = resolve_period(expression, CFG, NOW)
    assert period is not None
    return period


def _compare(
    model: SemanticModel,
    catalog: Catalog,
    conn: sqlite3.Connection,
    metric: str,
    expression: str,
) -> Comparison:
    return compare_previous(
        model,
        _plan(catalog, metric),
        "sqlite",
        _period(expression),
        lambda sql: conn.execute(sql).fetchall(),
        now=NOW,
    )


def _facturas(conn: sqlite3.Connection, start: date, end: date) -> list[tuple[Any, ...]]:
    """Facturas PAGADAS en `[start, end)`, leídas sin pasar por el motor."""
    rows = conn.execute(
        "SELECT fecha, total, cliente_id FROM facturas WHERE estado = 'PAGADA'"
    ).fetchall()
    return [r for r in rows if start.isoformat() <= r[0] < end.isoformat()]


def _total(conn: sqlite3.Connection, start: date, end: date) -> int:
    return sum(r[1] for r in _facturas(conn, start, end))


def _constant(value: Any) -> Any:
    return lambda sql: [(value,)]


def _sequence(*values: Any) -> Any:
    remaining = list(values)
    return lambda sql: [(remaining.pop(0),)]


# ---------------------------------------------------------------------- períodos equivalentes


def test_este_mes_al_dia_25_se_compara_con_octubre_al_dia_25(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    result = _compare(model, catalog, conn, "ventas_netas", "este mes")

    assert result.previous_period.start == date(2026, 10, 1)
    assert result.previous_period.end_exclusive == date(2026, 10, 26)
    current = _total(conn, date(2026, 11, 1), date(2026, 12, 1))
    previous = _total(conn, date(2026, 10, 1), date(2026, 10, 26))
    assert current > 0 and previous > 0
    assert result.value == pytest.approx(current)
    assert result.previous_value == pytest.approx(previous)
    assert result.difference == pytest.approx(current - previous)
    assert result.change_pct == pytest.approx((current - previous) / previous * 100)
    assert result.change_note is None


def test_ano_pasado_se_compara_con_el_ano_anterior_a_ese(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    result = _compare(model, catalog, conn, "ventas_netas", "año pasado")

    assert result.period.start == date(2025, 1, 1)
    assert result.previous_period.start == date(2024, 1, 1)
    assert result.previous_period.end_exclusive == date(2025, 1, 1)
    assert result.value == pytest.approx(_total(conn, date(2025, 1, 1), date(2026, 1, 1)))
    # La demo empieza en 2025: no hay datos anteriores y la variación no se inventa.
    assert result.previous_value is None
    assert result.change_pct is None
    assert result.change_note


def test_este_ano_al_dia_25_se_compara_con_el_ano_pasado_al_dia_25(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    result = _compare(model, catalog, conn, "num_facturas", "este año")

    assert result.previous_period.start == date(2025, 1, 1)
    assert result.previous_period.end_exclusive == date(2025, 11, 26)
    current = len(_facturas(conn, date(2026, 1, 1), date(2027, 1, 1)))
    previous = len(_facturas(conn, date(2025, 1, 1), date(2025, 11, 26)))
    assert result.value == current
    assert result.previous_value == previous
    assert result.change_pct == pytest.approx((current - previous) / previous * 100)


# ---------------------------------------------------------------------- tablas resumidas


def test_periodos_cerrados_y_alineados_usan_la_mensual(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    result = _compare(model, catalog, conn, "ventas_netas", "mes pasado")

    assert result.summary_table == "ventas_mensuales"
    assert "FROM ventas_mensuales" in result.sql
    assert "FROM ventas_mensuales" in result.previous_sql
    assert result.value == pytest.approx(_total(conn, date(2026, 10, 1), date(2026, 11, 1)))
    assert result.previous_value == pytest.approx(_total(conn, date(2026, 9, 1), date(2026, 10, 1)))


def test_periodo_en_curso_usa_la_diaria_porque_la_mensual_no_lo_incluye(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    result = _compare(model, catalog, conn, "ventas_netas", "este mes")

    assert result.summary_table == "ventas_diarias"
    assert "ventas_mensuales" in result.summary_reason


def test_rango_no_alineado_usa_la_diaria(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    result = _compare(model, catalog, conn, "ventas_netas", "del 3 al 17 de marzo de 2026")

    assert result.summary_table == "ventas_diarias"
    assert result.value == pytest.approx(_total(conn, date(2026, 3, 3), date(2026, 3, 18)))
    assert result.previous_value == pytest.approx(_total(conn, date(2026, 2, 16), date(2026, 3, 3)))


def test_si_un_solo_periodo_no_califica_no_se_usa_la_resumida(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    # El mes pasado califica para la mensual, pero su anterior (hasta el día 25) no.
    period = _period("mes pasado")
    short = PeriodRange(period.start, date(2026, 10, 26), "octubre al 25", "range", False)

    result = compare_previous(
        model,
        _plan(catalog, "ventas_netas"),
        "sqlite",
        short,
        lambda sql: conn.execute(sql).fetchall(),
        now=NOW,
    )

    assert result.summary_table == "ventas_diarias"


def test_metrica_no_aditiva_sin_resumida_usa_las_tablas_base(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    result = _compare(model, catalog, conn, "clientes_activos", "mes pasado")

    assert result.summary_table is None
    assert "FROM facturas" in result.sql
    current = {r[2] for r in _facturas(conn, date(2026, 10, 1), date(2026, 11, 1))}
    previous = {r[2] for r in _facturas(conn, date(2026, 9, 1), date(2026, 10, 1))}
    assert result.value == len(current)
    assert result.previous_value == len(previous)


def test_ticket_promedio_desde_la_resumida_no_es_promedio_de_promedios(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    result = _compare(model, catalog, conn, "ticket_promedio", "mes pasado")

    assert result.summary_table == "ventas_mensuales"
    rows = _facturas(conn, date(2026, 10, 1), date(2026, 11, 1))
    assert result.value == pytest.approx(sum(r[1] for r in rows) / len(rows))


def test_resumida_y_tablas_base_dan_el_mismo_resultado(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    via_summary = _compare(model, catalog, conn, "ventas_netas", "mes pasado")
    without = model.model_copy(update={"summary_tables": []})

    via_base = compare_previous(
        without,
        _plan(catalog, "ventas_netas"),
        "sqlite",
        _period("mes pasado"),
        lambda sql: conn.execute(sql).fetchall(),
        now=NOW,
    )

    assert via_base.summary_table is None
    assert via_base.value == pytest.approx(via_summary.value)
    assert via_base.previous_value == pytest.approx(via_summary.previous_value)


def test_con_filtros_se_usan_las_tablas_base(model: SemanticModel, catalog: Catalog) -> None:
    plan = catalog.verify(
        "ventas_netas", filters=[PlanFilter("facturas.canal", "=", "WEB")], role="gerencia_general"
    )

    result = compare_previous(
        model, plan, "sqlite", _period("mes pasado"), _constant(10), now=NOW
    )

    assert result.summary_table is None
    assert "facturas.canal = 'WEB'" in result.sql


# ---------------------------------------------------------------------- variación


def test_valor_anterior_cero_deja_la_variacion_en_null_y_la_explica(
    model: SemanticModel, catalog: Catalog
) -> None:
    result = compare_previous(
        model,
        _plan(catalog, "ventas_netas"),
        "sqlite",
        _period("mes pasado"),
        _sequence(500, 0),
        now=NOW,
    )

    assert result.value == 500
    assert result.previous_value == 0
    assert result.difference == 500
    assert result.change_pct is None
    assert result.change_note is not None and "cero" in result.change_note


def test_variacion_negativa(model: SemanticModel, catalog: Catalog) -> None:
    result = compare_previous(
        model,
        _plan(catalog, "ventas_netas"),
        "sqlite",
        _period("mes pasado"),
        _sequence(75, 100),
        now=NOW,
    )

    assert result.difference == -25
    assert result.change_pct == pytest.approx(-25.0)
    assert result.change_note is None


def test_sin_datos_en_el_periodo_actual(model: SemanticModel, catalog: Catalog) -> None:
    result = compare_previous(
        model,
        _plan(catalog, "ventas_netas"),
        "sqlite",
        _period("mes pasado"),
        _sequence(None, 100),
        now=NOW,
    )

    assert result.value is None
    assert result.difference is None
    assert result.change_pct is None
    assert result.change_note


# ---------------------------------------------------------------------- errores


def test_rechaza_planes_con_desglose(model: SemanticModel, catalog: Catalog) -> None:
    plan = catalog.verify("ventas_netas", ["sucursales.nombre"], role="gerencia_general")

    with pytest.raises(CompareError):
        compare_previous(model, plan, "sqlite", _period("mes pasado"), _constant(1), now=NOW)


def test_rechaza_consultas_que_no_devuelven_un_solo_valor(
    model: SemanticModel, catalog: Catalog
) -> None:
    def rows(sql: str) -> Sequence[Sequence[Any]]:
        return [(1,), (2,)]

    with pytest.raises(CompareError):
        compare_previous(
            model, _plan(catalog, "ventas_netas"), "sqlite", _period("mes pasado"), rows, now=NOW
        )
