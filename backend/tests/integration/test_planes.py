"""Planes de ejecución del filtro por rol (ADR 0004) en PostgreSQL y SQL Server.

El ADR afirma que el optimizador empuja el filtro hacia la tabla, así que la tabla derivada
cuesta lo mismo que escribir el `WHERE` a mano. Aquí se comprueba: el plan de la consulta con la
tabla derivada debe tener los mismos operadores que el de la consulta con el filtro directo. Si
`CHATIAPP_IT_PLANES_DIR` está definida, cada plan se guarda ahí (el CI los sube como artefacto).
"""

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from tests.integration.helpers import Motor

# (nombre, consulta con tabla derivada, consulta con el filtro escrito a mano)
CASOS = {
    "facturas": (
        "SELECT COUNT(*) FROM (SELECT * FROM facturas WHERE sucursal_id IN (1, 2)) AS f "
        "WHERE f.estado = 'PAGADA'",
        "SELECT COUNT(*) FROM facturas AS f WHERE f.sucursal_id IN (1, 2) AND f.estado = 'PAGADA'",
    ),
    "join": (
        "SELECT s.nombre, SUM(f.total) FROM "
        "(SELECT * FROM facturas WHERE sucursal_id IN (1, 2)) AS f "
        "JOIN sucursales AS s ON s.id = f.sucursal_id GROUP BY s.nombre",
        "SELECT s.nombre, SUM(f.total) FROM facturas AS f "
        "JOIN sucursales AS s ON s.id = f.sucursal_id WHERE f.sucursal_id IN (1, 2) "
        "GROUP BY s.nombre",
    ),
    "resumida": (
        "SELECT SUM(total_ventas) FROM "
        "(SELECT * FROM ventas_diarias WHERE sucursal_id IN (1, 2)) AS v",
        "SELECT SUM(total_ventas) FROM ventas_diarias AS v WHERE v.sucursal_id IN (1, 2)",
    ),
}


def _guardar(motor: Motor, nombre: str, variante: str, plan: str) -> None:
    carpeta = os.environ.get("CHATIAPP_IT_PLANES_DIR")
    if carpeta:
        destino = Path(carpeta)
        destino.mkdir(parents=True, exist_ok=True)
        (destino / f"{motor.dialect}-{nombre}-{variante}.txt").write_text(plan, encoding="utf-8")


def _plan_postgres(motor: Motor, sql: str) -> str:
    engine = create_engine(motor.url)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("ANALYZE")
            filas = conn.exec_driver_sql(f"EXPLAIN (COSTS OFF) {sql}").fetchall()
            conn.rollback()
    finally:
        engine.dispose()
    return "\n".join(str(fila[0]) for fila in filas)


def _plan_sqlserver(motor: Motor, sql: str) -> str:
    engine = create_engine(motor.url)
    try:
        with engine.connect() as conn:
            # SHOWPLAN no ejecuta la consulta: devuelve el plan como texto, una línea por fila.
            conn.exec_driver_sql("SET SHOWPLAN_TEXT ON")
            try:
                filas = conn.exec_driver_sql(sql).fetchall()
            finally:
                conn.exec_driver_sql("SET SHOWPLAN_TEXT OFF")
            conn.rollback()
    finally:
        engine.dispose()
    return "\n".join(str(fila[0]) for fila in filas)


def _plan(motor: Motor, sql: str) -> str:
    if motor.dialect == "postgres":
        return _plan_postgres(motor, sql)
    if motor.dialect == "tsql":
        return _plan_sqlserver(motor, sql)
    pytest.skip("Los planes se revisan solo en PostgreSQL y SQL Server")


def _operadores(motor: Motor, plan: str) -> list[str]:
    """Nombres de los operadores del plan, sin costos, identificadores ni objetos concretos."""
    if motor.dialect == "tsql":
        return [m.group(1).strip() for m in re.finditer(r"\|--([A-Za-z ]+?)(?:\(|$)", plan, re.M)]
    lineas = [re.sub(r"\s+on\s+.*$", "", ln.replace("->", "").strip()) for ln in plan.splitlines()]
    # Sin calificadores de tabla: el alias de la tabla derivada no tiene por qué coincidir con el
    # que se escribió a mano (`facturas.sucursal_id` frente a `f.sucursal_id`).
    return [re.sub(r"\b\w+\.(\w+)", r"\1", ln) for ln in lineas]


@pytest.mark.parametrize("nombre", list(CASOS))
def test_la_tabla_derivada_tiene_el_mismo_plan_que_el_filtro_directo(
    motor: Motor, nombre: str
) -> None:
    derivada, directa = CASOS[nombre]
    plan_derivada = _plan(motor, derivada)
    plan_directa = _plan(motor, directa)
    _guardar(motor, nombre, "derivada", plan_derivada)
    _guardar(motor, nombre, "directa", plan_directa)

    assert "sucursal_id" in plan_derivada, "el filtro desapareció del plan"
    assert _operadores(motor, plan_derivada) == _operadores(motor, plan_directa)
