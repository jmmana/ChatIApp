"""El filtro por rol (ADR 0004) deja ver solo las sucursales del usuario, en cada motor."""

import contextlib

import pytest

from app.engine.executor import QueryExecutionError
from app.engine.guard import GuardCache, GuardResult, check_sql
from app.engine.rls import build_user_context
from app.semantic.schema import SemanticModel
from tests.integration.helpers import Motor, assert_mismas_filas, ejecutar, fuente

ROL = "gerente_sucursal"
SUCURSALES = [1, 2]
CONTEXTO = build_user_context({"sucursales": SUCURSALES})

CONSULTAS = {
    "agregado": "SELECT sucursal_id, COUNT(*) AS n FROM facturas GROUP BY sucursal_id ORDER BY 1",
    "join": (
        "SELECT s.id, s.nombre, SUM(f.total) AS total FROM facturas AS f "
        "JOIN sucursales AS s ON s.id = f.sucursal_id GROUP BY s.id, s.nombre ORDER BY s.id"
    ),
    "subconsulta": (
        "SELECT id, nombre FROM sucursales WHERE id IN "
        "(SELECT sucursal_id FROM facturas WHERE estado = 'PAGADA') ORDER BY id"
    ),
    "cte": (
        "WITH x AS (SELECT * FROM facturas) "
        "SELECT sucursal_id, COUNT(*) AS n FROM x GROUP BY sucursal_id ORDER BY sucursal_id"
    ),
    "union": (
        "SELECT sucursal_id FROM facturas UNION SELECT sucursal_id FROM ventas_diarias ORDER BY 1"
    ),
    "resumida diaria": (
        "SELECT sucursal_id, SUM(total_ventas) AS total FROM ventas_diarias "
        "GROUP BY sucursal_id ORDER BY sucursal_id"
    ),
    "resumida mensual": (
        "SELECT sucursal_id, SUM(unidades) AS u FROM ventas_mensuales "
        "GROUP BY sucursal_id ORDER BY sucursal_id"
    ),
    "intento de saltarse el filtro": (
        "SELECT DISTINCT sucursal_id FROM facturas WHERE sucursal_id NOT IN (1, 2)"
    ),
}
CON_SUCURSAL = [n for n in CONSULTAS if n != "intento de saltarse el filtro"]


def _revisar(sql: str, motor: Motor, modelo: SemanticModel) -> GuardResult:
    return check_sql(sql, modelo, fuente(motor.dialect), 1, ROL, GuardCache(), CONTEXTO)


@pytest.mark.parametrize("nombre", CON_SUCURSAL)
def test_solo_las_sucursales_del_usuario_y_igual_que_en_sqlite(
    motor: Motor, sqlite: Motor, modelo: SemanticModel, nombre: str, request: pytest.FixtureRequest
) -> None:
    if motor.dialect == "tsql" and nombre == "union":
        # sqlguardllm envuelve el UNION con ORDER BY en una tabla derivada que SQL Server rechaza.
        # Estricta: cuando llegue la versión corregida, esta prueba pasa y obliga a quitar la marca.
        request.applymarker(
            pytest.mark.xfail(strict=True, reason="https://github.com/jmmana/sqlguardllm/issues/92")
        )
    sql = CONSULTAS[nombre]
    en_motor = _revisar(sql, motor, modelo)
    en_sqlite = _revisar(sql, sqlite, modelo)
    assert en_motor.allowed, en_motor.violations
    assert en_sqlite.allowed, en_sqlite.violations
    assert en_motor.sql is not None and en_sqlite.sql is not None

    filas = ejecutar(motor, en_motor.sql)
    assert filas
    assert {int(fila[0]) for fila in filas} == set(SUCURSALES)
    assert_mismas_filas(filas, ejecutar(sqlite, en_sqlite.sql))


def test_el_filtro_no_se_puede_saltar_desde_la_consulta(
    motor: Motor, modelo: SemanticModel
) -> None:
    resultado = _revisar(CONSULTAS["intento de saltarse el filtro"], motor, modelo)
    assert resultado.allowed, resultado.violations
    assert resultado.sql is not None
    assert ejecutar(motor, resultado.sql) == []


def test_sin_filtro_hay_mas_sucursales(motor: Motor) -> None:
    # Control: la restricción viene del filtro, no de que los datos solo tengan dos sucursales.
    filas = ejecutar(motor, "SELECT DISTINCT sucursal_id FROM facturas")
    assert len(filas) > len(SUCURSALES)


def test_la_consulta_reescrita_usa_una_tabla_derivada(motor: Motor, modelo: SemanticModel) -> None:
    resultado = _revisar("SELECT COUNT(*) FROM facturas AS f", motor, modelo)
    assert resultado.allowed, resultado.violations
    assert resultado.sql is not None
    reescrita = " ".join(resultado.sql.split())
    assert "(SELECT * FROM facturas WHERE sucursal_id IN (1, 2)) AS f" in reescrita


def test_valores_del_usuario_se_escapan_en_el_motor(motor: Motor, modelo: SemanticModel) -> None:
    malicioso = build_user_context({"sucursales": ["1); DROP TABLE facturas; --"]})
    fuente_ = fuente(motor.dialect)
    sql = "SELECT COUNT(*) FROM facturas"
    resultado = check_sql(sql, modelo, fuente_, 1, ROL, GuardCache(), malicioso)
    if resultado.allowed:
        # Una columna entera comparada con texto: según el motor da error o 0 filas, pero nunca
        # ejecuta la sentencia inyectada.
        assert resultado.sql is not None
        with contextlib.suppress(QueryExecutionError):
            ejecutar(motor, resultado.sql)
    assert ejecutar(motor, "SELECT COUNT(*) FROM facturas") == [[50_000]]
