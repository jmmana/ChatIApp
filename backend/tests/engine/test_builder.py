import importlib
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.demo.seed import generar
from app.engine.builder import (
    BuilderError,
    NoJoinPathError,
    OrderTerm,
    PeriodRequiredError,
    build_sql,
)
from app.engine.catalog import Catalog, PlanFilter, VerifiedPlan
from app.engine.dialects import Dialect
from app.engine.periods import PeriodRange
from app.semantic.schema import SemanticModel, parse_semantic_model

ROOT = Path(__file__).parents[3]
EXAMPLE = ROOT / "examples" / "ventas" / "semantic-model.yaml"
SNAPSHOTS = Path(__file__).parent / "snapshots"
METRICS = [
    "ventas_netas",
    "ventas_sin_iva",
    "num_facturas",
    "ticket_promedio",
    "unidades_vendidas",
    "clientes_activos",
]
Q1 = PeriodRange(date(2025, 1, 1), date(2025, 4, 1), "T1 2025", "quarter", False)
MARZO = PeriodRange(date(2025, 3, 1), date(2025, 4, 1), "marzo de 2025", "month", False)


@pytest.fixture(scope="module")
def model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    return parse_semantic_model(yaml.safe_load(EXAMPLE.read_text()))


@pytest.fixture(scope="module")
def catalog(model: SemanticModel) -> Catalog:
    return Catalog(model)


def _plan(
    catalog: Catalog,
    metric: str,
    dimensions: list[str] | None = None,
    filters: list[PlanFilter] | None = None,
) -> VerifiedPlan:
    return catalog.verify(metric, dimensions or [], filters or [], role="gerencia_general")


def _sql(
    model: SemanticModel, plan: VerifiedPlan, dialect: Dialect = "sqlite", **kwargs: Any
) -> str:
    return build_sql(model, plan, dialect, **kwargs).sql


# ---------------------------------------------------------------------- snapshots


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
@pytest.mark.parametrize("metric", METRICS)
def test_snapshot_de_cada_metrica_de_la_demo(
    model: SemanticModel, catalog: Catalog, metric: str, dialect: Dialect
) -> None:
    plan = _plan(catalog, metric, ["sucursales.nombre"])

    built = build_sql(model, plan, dialect, period=Q1, time_grain="month")

    expected = (SNAPSHOTS / f"{metric}.{dialect}.sql").read_text().rstrip("\n")
    assert built.sql == expected


def test_mismo_plan_mismo_sql(model: SemanticModel, catalog: Catalog) -> None:
    plan = _plan(catalog, "unidades_vendidas", ["productos.categoria", "sucursales.nombre"])

    first = build_sql(model, plan, "postgres", period=Q1, time_grain="week")
    second = build_sql(model, plan, "postgres", period=Q1, time_grain="week")

    assert first == second


# ---------------------------------------------------------------------- filtros y período


def test_aplica_filtros_de_la_metrica_y_rango_semiabierto(
    model: SemanticModel, catalog: Catalog
) -> None:
    sql = _sql(model, _plan(catalog, "ventas_netas"), period=MARZO)

    assert sql == (
        "SELECT SUM(facturas.total) AS valor\n"
        "FROM facturas\n"
        "WHERE facturas.estado = 'PAGADA' AND facturas.fecha >= '2025-03-01' "
        "AND facturas.fecha < '2025-04-01'"
    )


def test_metrica_que_requiere_periodo(model: SemanticModel, catalog: Catalog) -> None:
    with pytest.raises(PeriodRequiredError):
        _sql(model, _plan(catalog, "ventas_netas"))


def test_time_column_en_otra_tabla_agrega_el_join(model: SemanticModel, catalog: Catalog) -> None:
    built = build_sql(model, _plan(catalog, "unidades_vendidas"), "sqlite", period=MARZO)

    assert built.tables == ("factura_detalle", "facturas")
    assert "LEFT JOIN facturas ON factura_detalle.factura_id = facturas.id" in built.sql
    assert "facturas.fecha >= '2025-03-01'" in built.sql


def test_join_de_dos_saltos_por_la_ruta_mas_corta(model: SemanticModel, catalog: Catalog) -> None:
    plan = _plan(catalog, "unidades_vendidas", ["productos.categoria", "sucursales.nombre"])

    built = build_sql(model, plan, "sqlite", period=MARZO)

    assert built.tables == ("factura_detalle", "facturas", "productos", "sucursales")
    assert built.sql.count("JOIN") == 3


def test_tablas_de_los_filtros_tambien_se_unen(model: SemanticModel, catalog: Catalog) -> None:
    plan = _plan(catalog, "ventas_netas", filters=[PlanFilter("clientes.segmento", "=", "EMPRESA")])

    built = build_sql(model, plan, "postgres", period=MARZO)

    assert built.tables == ("facturas", "clientes")
    assert "LEFT JOIN clientes ON facturas.cliente_id = clientes.id" in built.sql
    assert "clientes.segmento = 'EMPRESA'" in built.sql


def test_nunca_une_una_tabla_del_lado_muchos(model: SemanticModel, catalog: Catalog) -> None:
    plan = VerifiedPlan(
        catalog.find_metric("ventas_netas"),
        (),
        (PlanFilter("factura_detalle.cantidad", ">", 1),),
    )

    with pytest.raises(NoJoinPathError):
        _sql(model, plan, period=MARZO)


def test_valores_con_comillas_se_escapan(model: SemanticModel, catalog: Catalog) -> None:
    plan = _plan(
        catalog,
        "ventas_netas",
        filters=[PlanFilter("clientes.nombre", "=", "O'Brien'; DROP TABLE facturas; --")],
    )

    sql = _sql(model, plan, period=MARZO)

    assert "clientes.nombre = 'O''Brien''; DROP TABLE facturas; --'" in sql


def test_operadores_in_y_contains(model: SemanticModel, catalog: Catalog) -> None:
    plan = _plan(
        catalog,
        "ventas_netas",
        filters=[
            PlanFilter("facturas.canal", "in", ["TIENDA", "ONLINE"]),
            PlanFilter("sucursales.nombre", "contains", "100%_a"),
        ],
    )

    sql = _sql(model, plan, period=MARZO)

    assert "facturas.canal IN ('TIENDA', 'ONLINE')" in sql
    assert "LOWER(sucursales.nombre) LIKE '%100!%!_a%' ESCAPE '!'" in sql


def test_operador_invalido(model: SemanticModel, catalog: Catalog) -> None:
    plan = VerifiedPlan(
        catalog.find_metric("ventas_netas"), (), (PlanFilter("facturas.canal", "~", "x"),)
    )

    with pytest.raises(BuilderError):
        _sql(model, plan, period=MARZO)


# ---------------------------------------------------------------------- orden, límite y grano


def test_con_time_grain_agrupa_y_ordena_por_el_periodo(
    model: SemanticModel, catalog: Catalog
) -> None:
    sql = _sql(model, _plan(catalog, "num_facturas"), "postgres", period=Q1, time_grain="week")

    assert "SELECT DATE_TRUNC('WEEK', facturas.fecha) AS periodo, COUNT(*) AS valor" in sql
    assert "GROUP BY DATE_TRUNC('WEEK', facturas.fecha)" in sql
    assert sql.endswith("ORDER BY periodo ASC\nLIMIT 1000")


def test_sin_grano_las_dimensiones_se_ordenan_por_valor(
    model: SemanticModel, catalog: Catalog
) -> None:
    plan = _plan(catalog, "ventas_netas", ["facturas.canal"])

    sql = _sql(model, plan, period=MARZO, limit=5)

    assert sql.endswith("ORDER BY valor DESC, facturas.canal ASC\nLIMIT 5")


def test_orden_explicito_por_dimension(model: SemanticModel, catalog: Catalog) -> None:
    plan = _plan(catalog, "ventas_netas", ["facturas.canal", "sucursales.ciudad"])

    sql = _sql(model, plan, period=MARZO, order_by=[OrderTerm("sucursales.ciudad", True)])

    assert "ORDER BY sucursales.ciudad DESC, facturas.canal ASC" in sql


def test_alias_distinto_cuando_dos_dimensiones_comparten_columna(
    model: SemanticModel, catalog: Catalog
) -> None:
    plan = _plan(catalog, "ventas_netas", ["sucursales.ciudad", "clientes.segmento"])
    assert " AS ciudad," in _sql(model, plan, period=MARZO)

    data = importlib.import_module("yaml").safe_load(EXAMPLE.read_text())
    data["metrics"][0]["dimensions"].append("clientes.ciudad")
    other = parse_semantic_model(data)
    plan = _plan_for(other, "ventas_netas", ["sucursales.ciudad", "clientes.ciudad"])
    sql = _sql(other, plan, period=MARZO)
    assert "sucursales.ciudad AS sucursales_ciudad" in sql
    assert "clientes.ciudad AS clientes_ciudad" in sql


def _plan_for(model: SemanticModel, metric: str, dimensions: list[str]) -> VerifiedPlan:
    return Catalog(model).verify(metric, dimensions, role="gerencia_general")


def test_orden_invalido(model: SemanticModel, catalog: Catalog) -> None:
    plan = _plan(catalog, "ventas_netas", ["facturas.canal"])

    with pytest.raises(BuilderError):
        _sql(model, plan, period=MARZO, order_by=[OrderTerm("periodo")])
    with pytest.raises(BuilderError):
        _sql(model, plan, period=MARZO, order_by=[OrderTerm("clientes.segmento")])


def test_limite_por_dialecto(model: SemanticModel, catalog: Catalog) -> None:
    plan = _plan(catalog, "ventas_netas", ["facturas.canal"])

    assert _sql(model, plan, "tsql", period=MARZO, limit=3).startswith(
        "SELECT TOP 3 facturas.canal AS canal"
    )
    assert _sql(model, plan, "oracle", period=MARZO, limit=3).endswith("FETCH FIRST 3 ROWS ONLY")
    assert _sql(model, plan, "mysql", period=MARZO, limit=3).endswith("LIMIT 3")
    with pytest.raises(BuilderError):
        _sql(model, plan, period=MARZO, limit=0)


def test_division_decimal_solo_en_sqlite(model: SemanticModel, catalog: Catalog) -> None:
    plan = _plan(catalog, "ticket_promedio")

    assert "CAST(SUM(facturas.total) AS REAL) / NULLIF(COUNT(*), 0)" in _sql(
        model, plan, period=MARZO
    )
    assert "SUM(facturas.total) / NULLIF(COUNT(*), 0)" in _sql(
        model, plan, "postgres", period=MARZO
    )


# ---------------------------------------------------------------------- ejecución en SQLite


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    path = tmp_path_factory.mktemp("demo") / "ventas.db"
    generar(path, seed=42, hasta=date(2026, 11, 25))
    connection = sqlite3.connect(path)
    yield connection
    connection.close()


def _run(conn: sqlite3.Connection, sql: str) -> list[tuple[Any, ...]]:
    return conn.execute(sql).fetchall()


def _facturas(conn: sqlite3.Connection, period: PeriodRange) -> list[tuple[Any, ...]]:
    """Facturas PAGADAS del período, leídas sin pasar por el constructor."""
    rows = conn.execute(
        "SELECT id, fecha, sucursal_id, total, subtotal, cliente_id FROM facturas "
        "WHERE estado = 'PAGADA'"
    ).fetchall()
    inicio, fin = period.start.isoformat(), period.end_exclusive.isoformat()
    return [r for r in rows if inicio <= r[1] < fin]


def _sucursales(conn: sqlite3.Connection) -> dict[int, str]:
    return dict(conn.execute("SELECT id, nombre FROM sucursales").fetchall())


def _expected(conn: sqlite3.Connection, metric: str, period: PeriodRange) -> float:
    facturas = _facturas(conn, period)
    if metric == "ventas_netas":
        return sum(r[3] for r in facturas)
    if metric == "ventas_sin_iva":
        return sum(r[4] for r in facturas)
    if metric == "num_facturas":
        return len(facturas)
    if metric == "ticket_promedio":
        return sum(r[3] for r in facturas) / len(facturas)
    if metric == "clientes_activos":
        return len({r[5] for r in facturas})
    ids = {r[0] for r in facturas}
    detalle = conn.execute("SELECT factura_id, cantidad FROM factura_detalle").fetchall()
    return sum(cantidad for factura_id, cantidad in detalle if factura_id in ids)


@pytest.mark.parametrize("metric", METRICS)
def test_total_coincide_con_el_calculo_en_python(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection, metric: str
) -> None:
    sql = _sql(model, _plan(catalog, metric), period=MARZO)

    [(value,)] = _run(conn, sql)

    expected = _expected(conn, metric, MARZO)
    assert expected > 0
    assert value == pytest.approx(expected)


def test_ticket_promedio_es_decimal(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    [(value,)] = _run(conn, _sql(model, _plan(catalog, "ticket_promedio"), period=MARZO))

    facturas = _facturas(conn, MARZO)
    total = sum(r[3] for r in facturas)
    assert isinstance(value, float)
    assert value == pytest.approx(total / len(facturas))
    assert value != total // len(facturas)


def test_division_entera_en_sqlite_no_se_trunca(model: SemanticModel, catalog: Catalog) -> None:
    memory = sqlite3.connect(":memory:")
    memory.execute("CREATE TABLE facturas (id INTEGER, fecha DATE, total INTEGER, estado TEXT)")
    memory.executemany(
        "INSERT INTO facturas VALUES (?, '2025-03-10', ?, 'PAGADA')", [(1, 10), (2, 10), (3, 5)]
    )

    [(value,)] = memory.execute(_sql(model, _plan(catalog, "ticket_promedio"), period=MARZO))

    assert value == pytest.approx(25 / 3)
    memory.close()


def test_agrupado_por_sucursal_coincide_con_python(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    plan = _plan(catalog, "ventas_netas", ["sucursales.nombre"])
    rows = _run(conn, _sql(model, plan, period=Q1))

    nombres = _sucursales(conn)
    expected: dict[str, int] = defaultdict(int)
    for r in _facturas(conn, Q1):
        expected[nombres[r[2]]] += r[3]
    assert dict(rows) == pytest.approx(dict(expected))
    assert [r[0] for r in rows] == sorted(expected, key=lambda n: (-expected[n], n))


def test_unidades_por_mes_y_sucursal_coinciden_con_python(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    plan = _plan(catalog, "unidades_vendidas", ["sucursales.nombre"])
    rows = _run(conn, _sql(model, plan, period=Q1, time_grain="month"))

    nombres = _sucursales(conn)
    por_factura = {r[0]: (r[1][:7] + "-01", nombres[r[2]]) for r in _facturas(conn, Q1)}
    expected: dict[tuple[str, str], int] = defaultdict(int)
    for factura_id, cantidad in conn.execute("SELECT factura_id, cantidad FROM factura_detalle"):
        if factura_id in por_factura:
            expected[por_factura[factura_id]] += cantidad
    assert {(p, n): v for p, n, v in rows} == dict(expected)
    assert [(p, n) for p, n, _ in rows] == sorted(expected)


def test_valor_malicioso_no_rompe_la_consulta(
    model: SemanticModel, catalog: Catalog, conn: sqlite3.Connection
) -> None:
    plan = _plan(
        catalog,
        "ventas_netas",
        filters=[PlanFilter("clientes.nombre", "=", "x' OR '1'='1")],
    )

    assert _run(conn, _sql(model, plan, period=MARZO)) == [(None,)]
