import hashlib
import re
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.demo.seed import cargar, generar

HASTA = date(2026, 11, 25)
EJEMPLOS = Path(__file__).resolve().parents[3] / "examples" / "ventas"
TABLAS = [
    "sucursales",
    "productos",
    "clientes",
    "facturas",
    "factura_detalle",
    "ventas_diarias",
    "ventas_mensuales",
]


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    ruta = tmp_path_factory.mktemp("demo") / "ventas.db"
    generar(ruta, seed=42, hasta=HASTA)
    return ruta


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(db_path)
    yield c
    c.close()


def _checksum(ruta: Path) -> str:
    h = hashlib.sha256()
    c = sqlite3.connect(ruta)
    try:
        for tabla in TABLAS:
            for fila in c.execute(f"SELECT * FROM {tabla} ORDER BY rowid"):
                h.update(repr(fila).encode())
    finally:
        c.close()
    return h.hexdigest()


def test_volumen_y_cobertura(conn: sqlite3.Connection) -> None:
    def uno(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    assert uno("SELECT COUNT(*) FROM sucursales") == 6
    assert uno("SELECT COUNT(*) FROM productos") >= 200
    assert uno("SELECT COUNT(*) FROM clientes") == 2000
    assert uno("SELECT COUNT(*) FROM facturas") == 50_000
    assert {r[0] for r in conn.execute("SELECT nombre FROM sucursales")} == {
        "Bogotá Andino",
        "Bogotá Unicentro",
        "Bogotá Titán",
        "Medellín El Tesoro",
        "Cali Chipichape",
        "Barranquilla Buenavista",
    }
    assert {r[0] for r in conn.execute("SELECT DISTINCT estado FROM facturas")} == {
        "PAGADA",
        "PENDIENTE",
        "ANULADA",
    }
    assert {r[0] for r in conn.execute("SELECT DISTINCT canal FROM facturas")} == {
        "TIENDA",
        "ONLINE",
        "MAYORISTA",
    }
    minimo, maximo = conn.execute("SELECT MIN(fecha), MAX(fecha) FROM facturas").fetchone()
    assert minimo >= "2025-01-01"
    assert maximo <= HASTA.isoformat()


def test_integridad(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # total = subtotal + impuesto; subtotal = suma de las líneas - descuento
    malas = conn.execute(
        """
        SELECT COUNT(*) FROM facturas f
        JOIN (SELECT factura_id, SUM(total_linea) AS s FROM factura_detalle GROUP BY factura_id) d
          ON d.factura_id = f.id
        WHERE f.total <> f.subtotal + f.impuesto OR f.subtotal <> d.s - f.descuento
        """
    ).fetchone()[0]
    assert malas == 0
    sin_lineas = conn.execute(
        "SELECT COUNT(*) FROM facturas WHERE id NOT IN (SELECT factura_id FROM factura_detalle)"
    ).fetchone()[0]
    assert sin_lineas == 0


def test_ventas_diarias_coinciden_con_facturas_pagadas(conn: sqlite3.Connection) -> None:
    esperado = conn.execute(
        """
        SELECT f.fecha, f.sucursal_id, f.canal, SUM(f.total), COUNT(*),
               SUM((SELECT SUM(d.cantidad) FROM factura_detalle d WHERE d.factura_id = f.id))
        FROM facturas f WHERE f.estado = 'PAGADA'
        GROUP BY f.fecha, f.sucursal_id, f.canal ORDER BY 1, 2, 3
        """
    ).fetchall()
    real = conn.execute("SELECT * FROM ventas_diarias ORDER BY 1, 2, 3").fetchall()
    assert len(real) > 0
    assert real == esperado


def test_ventas_mensuales_coinciden_y_excluyen_mes_en_curso(conn: sqlite3.Connection) -> None:
    mes_en_curso = HASTA.replace(day=1).isoformat()
    esperado = conn.execute(
        """
        SELECT SUBSTR(f.fecha, 1, 7) || '-01', f.sucursal_id, SUM(f.total), COUNT(*),
               SUM((SELECT SUM(d.cantidad) FROM factura_detalle d WHERE d.factura_id = f.id))
        FROM facturas f
        WHERE f.estado = 'PAGADA' AND SUBSTR(f.fecha, 1, 7) || '-01' < ?
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
        (mes_en_curso,),
    ).fetchall()
    real = conn.execute("SELECT * FROM ventas_mensuales ORDER BY 1, 2").fetchall()
    assert len(real) > 0
    assert real == esperado
    assert all(fila[0] < mes_en_curso for fila in real)


def test_misma_semilla_mismos_datos(db_path: Path, tmp_path: Path) -> None:
    otra = tmp_path / "otra.db"
    generar(otra, seed=42, hasta=HASTA)
    assert _checksum(otra) == _checksum(db_path)


def test_otra_semilla_cambia_los_datos(db_path: Path, tmp_path: Path) -> None:
    otra = tmp_path / "otra.db"
    generar(otra, seed=7, hasta=HASTA)
    assert _checksum(otra) != _checksum(db_path)


def test_datos_personales_ficticios(conn: sqlite3.Connection) -> None:
    correos = [r[0] for r in conn.execute("SELECT email FROM clientes WHERE email IS NOT NULL")]
    assert correos
    assert all(c.endswith("@example.com") for c in correos)


def _modelo_semantico() -> dict[str, set[str]]:
    """Tablas y columnas del modelo semántico (lectura por líneas: sin dependencia de YAML)."""
    texto = (EJEMPLOS / "semantic-model.yaml").read_text(encoding="utf-8")
    seccion = texto.split("\ntables:\n", 1)[1].split("\nrelationships:", 1)[0]
    tablas: dict[str, set[str]] = {}
    actual = ""
    for linea in seccion.splitlines():
        if m := re.match(r"^  - name: (\w+)", linea):
            actual = m.group(1)
            tablas[actual] = set()
        elif m := re.match(r"^\s+- \{ name: (\w+),", linea):
            tablas[actual].add(m.group(1))
    return tablas


def _esquema_sql() -> dict[str, set[str]]:
    texto = (EJEMPLOS / "schema.sql").read_text(encoding="utf-8")
    tablas: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\);", texto, re.S):
        tablas[m.group(1)] = {
            c.group(1)
            for c in re.finditer(r"^    (\w+)\s", m.group(2), re.M)
            if c.group(1) != "PRIMARY"
        }
    return tablas


def _base_generada(conn: sqlite3.Connection) -> dict[str, set[str]]:
    nombres = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")} for t in nombres}


def test_cargar_con_sqlalchemy_deja_los_mismos_datos(
    db_path: Path, tmp_path: Path, conn: sqlite3.Connection
) -> None:
    # `cargar` es el camino de las pruebas multimotor: aquí se comprueba sobre SQLite.
    otra = tmp_path / "sqlalchemy.db"
    engine = create_engine(f"sqlite:///{otra}")
    try:
        cargar(engine, seed=42, hasta=HASTA)
    finally:
        engine.dispose()
    copia = sqlite3.connect(otra)
    try:
        for tabla in TABLAS:
            consulta = f"SELECT * FROM {tabla} ORDER BY 1, 2"
            assert copia.execute(consulta).fetchall() == conn.execute(consulta).fetchall(), tabla
        assert copia.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        copia.close()


def test_modelo_semantico_y_ddl_describen_la_base(conn: sqlite3.Connection) -> None:
    generada = _base_generada(conn)
    assert set(generada) == set(TABLAS)
    assert _modelo_semantico() == generada
    assert _esquema_sql() == generada
