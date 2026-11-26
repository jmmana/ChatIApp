"""El generador de la demo carga los mismos datos en cada motor que en SQLite."""

import pytest

from app.demo.seed import TABLAS
from tests.integration.helpers import Motor, assert_mismas_filas, ejecutar

CONSULTAS = {
    "conteos": " UNION ALL ".join(f"SELECT '{t}' AS tabla, COUNT(*) AS n FROM {t}" for t in TABLAS)
    + " ORDER BY tabla",
    "totales": (
        "SELECT estado, canal, COUNT(*) AS n, SUM(subtotal) AS subtotal, SUM(descuento) AS dto, "
        "SUM(impuesto) AS iva, SUM(total) AS total FROM facturas GROUP BY estado, canal "
        "ORDER BY estado, canal"
    ),
    "rango de fechas": "SELECT MIN(fecha), MAX(fecha) FROM facturas",
    "detalle": "SELECT SUM(cantidad), SUM(total_linea) FROM factura_detalle",
    "clientes sin correo": "SELECT COUNT(*) FROM clientes WHERE email IS NULL",
    "resumidas": (
        "SELECT SUM(total_ventas), SUM(num_facturas), SUM(unidades), COUNT(*) FROM ventas_diarias"
    ),
    "resumidas por mes": (
        "SELECT MIN(mes), MAX(mes), SUM(total_ventas), COUNT(*) FROM ventas_mensuales"
    ),
}


@pytest.mark.parametrize("nombre", list(CONSULTAS))
def test_mismos_datos_que_sqlite(motor: Motor, sqlite: Motor, nombre: str) -> None:
    sql = CONSULTAS[nombre]
    assert_mismas_filas(ejecutar(motor, sql), ejecutar(sqlite, sql))


def test_volumen_de_la_demo(motor: Motor) -> None:
    filas = dict(ejecutar(motor, CONSULTAS["conteos"]))
    assert filas["sucursales"] == 6
    assert filas["clientes"] == 2000
    assert filas["facturas"] == 50_000
    assert filas["factura_detalle"] > 50_000


def test_integridad_referencial(motor: Motor) -> None:
    huerfanas = ejecutar(
        motor,
        "SELECT COUNT(*) FROM factura_detalle d "
        "LEFT JOIN facturas f ON f.id = d.factura_id WHERE f.id IS NULL",
    )
    assert huerfanas == [[0]]
