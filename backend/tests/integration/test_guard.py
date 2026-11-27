"""El guardián valida y reescribe en el dialecto de cada motor, y el SQL resultante se ejecuta."""

import pytest

from app.engine.guard import GuardCache, GuardResult, check_sql
from app.semantic.schema import SemanticModel
from tests.integration.helpers import Motor, assert_mismas_filas, ejecutar, fuente

ROL = "gerencia_general"

CONSULTAS = {
    "agregado": (
        "SELECT sucursal_id, COUNT(*) AS n, SUM(total) AS total FROM facturas "
        "WHERE estado = 'PAGADA' GROUP BY sucursal_id ORDER BY sucursal_id"
    ),
    "join": (
        "SELECT s.nombre, SUM(f.total) AS total FROM facturas AS f "
        "JOIN sucursales AS s ON s.id = f.sucursal_id GROUP BY s.nombre ORDER BY s.nombre"
    ),
    "subconsulta": (
        "SELECT nombre FROM sucursales WHERE id IN "
        "(SELECT sucursal_id FROM facturas WHERE canal = 'ONLINE') ORDER BY nombre"
    ),
    "cte": (
        "WITH x AS (SELECT sucursal_id, total FROM facturas WHERE estado = 'PAGADA') "
        "SELECT sucursal_id, SUM(total) AS total FROM x GROUP BY sucursal_id ORDER BY sucursal_id"
    ),
}

RECHAZADAS = {
    "borrar": "DROP TABLE facturas",
    "actualizar": "UPDATE facturas SET total = 0",
    "insertar": "INSERT INTO sucursales (id, nombre) VALUES (99, 'x')",
    "dos sentencias": "SELECT 1; DROP TABLE facturas",
    "columna oculta": "SELECT email FROM clientes",
    "columna oculta con *": "SELECT documento, nombre FROM clientes",
    "tabla fuera del modelo": "SELECT * FROM information_schema.tables",
}


def _revisar(sql: str, motor: Motor, modelo: SemanticModel, rol: str = ROL) -> GuardResult:
    return check_sql(sql, modelo, fuente(motor.dialect), 1, rol, GuardCache())


@pytest.mark.parametrize("nombre", list(CONSULTAS))
def test_sql_permitido_da_lo_mismo_que_en_sqlite(
    motor: Motor, sqlite: Motor, modelo: SemanticModel, nombre: str
) -> None:
    sql = CONSULTAS[nombre]
    en_motor = _revisar(sql, motor, modelo)
    en_sqlite = _revisar(sql, sqlite, modelo)
    assert en_motor.allowed, en_motor.violations
    assert en_sqlite.allowed, en_sqlite.violations
    assert en_motor.sql is not None and en_sqlite.sql is not None

    real = ejecutar(motor, en_motor.sql)
    assert real
    assert_mismas_filas(real, ejecutar(sqlite, en_sqlite.sql))


@pytest.mark.parametrize("nombre", list(RECHAZADAS))
def test_sql_peligroso_se_rechaza_sin_ejecutarse(
    motor: Motor, modelo: SemanticModel, nombre: str
) -> None:
    resultado = _revisar(RECHAZADAS[nombre], motor, modelo)
    assert not resultado.allowed
    assert resultado.sql is None
    assert ejecutar(motor, "SELECT COUNT(*) FROM facturas") == [[50_000]]


def test_el_limite_se_aplica_en_la_sintaxis_del_motor(motor: Motor, modelo: SemanticModel) -> None:
    fuente_chica = fuente(motor.dialect, max_rows=25)
    resultado = check_sql(
        "SELECT id FROM facturas ORDER BY id", modelo, fuente_chica, 1, ROL, GuardCache()
    )
    assert resultado.allowed, resultado.violations
    assert resultado.sql is not None
    esperado = "TOP 25" if motor.dialect == "tsql" else "LIMIT 25"
    assert esperado in resultado.sql.upper()
    assert len(ejecutar(motor, resultado.sql)) == 25


def test_tabla_oculta_para_el_rol(motor: Motor, modelo: SemanticModel) -> None:
    rol = next(r for r in modelo.security.roles if r.hidden_tables)
    tabla = rol.hidden_tables[0]
    resultado = _revisar(f"SELECT COUNT(*) FROM {tabla}", motor, modelo, rol.name)
    assert not resultado.allowed
