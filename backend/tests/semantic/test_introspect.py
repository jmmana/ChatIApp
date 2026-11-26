import time
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db.models import Datasource
from app.demo.seed import generar
from app.semantic.introspect import MAX_TABLES, TooManyTablesError, introspect
from app.semantic.schema import SemanticModel

DEMO_TABLES = {
    "sucursales",
    "productos",
    "clientes",
    "facturas",
    "factura_detalle",
    "ventas_diarias",
    "ventas_mensuales",
}


def _datasource(privacy: str = "schema", max_rows: int = 1000) -> Datasource:
    return Datasource(
        id=uuid.uuid4(),
        name="Demo",
        dialect="sqlite",
        url_encrypted=b"",
        execute=False,
        max_rows=max_rows,
        timeout_seconds=30,
        privacy=privacy,
        managed_by="ui",
    )


@pytest.fixture(scope="module")
def demo_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("demo") / "ventas.db"
    generar(path, seed=42, hasta=date(2025, 3, 31))
    return f"sqlite:///{path}"


def test_la_demo_produce_las_7_tablas(demo_url: str) -> None:
    result = introspect(demo_url, _datasource())

    assert {t.name for t in result.tables} == DEMO_TABLES
    assert result.schemas == ["main"]
    # La vista previa es un modelo válido.
    SemanticModel(version=1, name="demo", tables=result.tables, relationships=result.relationships)


def test_lee_columnas_tipos_y_llaves(demo_url: str) -> None:
    result = introspect(demo_url, _datasource())
    tables = {t.name: t for t in result.tables}

    facturas = tables["facturas"]
    assert facturas.primary_key == ["id"]
    columns = {c.name: c for c in facturas.columns}
    assert columns["numero"].type == "VARCHAR(20)"
    assert columns["canal"].sample_values == []
    assert tables["ventas_diarias"].primary_key == ["fecha", "sucursal_id", "canal"]
    pairs = {(r.from_, r.to) for r in result.relationships}
    assert ("facturas.cliente_id", "clientes.id") in pairs


def test_filtra_por_patron_de_tabla(demo_url: str) -> None:
    result = introspect(demo_url, _datasource(), table_pattern="VENTAS_*")

    assert {t.name for t in result.tables} == {"ventas_diarias", "ventas_mensuales"}


def test_filtra_por_esquema(demo_url: str) -> None:
    assert len(introspect(demo_url, _datasource(), schemas=["main"]).tables) == 7

    result = introspect(demo_url, _datasource(), schemas=["otro"])

    assert result.tables == []
    assert "otro" in result.warnings[0].message


def test_llave_foranea_fuera_del_filtro_es_advertencia(demo_url: str) -> None:
    result = introspect(demo_url, _datasource(), table_pattern="facturas")

    assert [t.name for t in result.tables] == ["facturas"]
    assert result.relationships == []
    assert result.warnings


def test_sin_privacidad_samples_no_hay_muestras(demo_url: str) -> None:
    result = introspect(demo_url, _datasource("aggregates"), sample_values=True)

    assert all(not c.sample_values for t in result.tables for c in t.columns)
    assert "samples" in result.warnings[0].message


def test_muestras_de_texto_de_baja_cardinalidad(demo_url: str) -> None:
    result = introspect(demo_url, _datasource("samples"), sample_values=True)
    facturas = {c.name: c for t in result.tables if t.name == "facturas" for c in t.columns}

    assert facturas["canal"].sample_values == ["MAYORISTA", "ONLINE", "TIENDA"]
    assert set(facturas["estado"].sample_values) <= {"PAGADA", "PENDIENTE", "ANULADA"}
    assert facturas["fecha"].sample_values == []  # no es texto
    assert facturas["numero"].sample_values == []  # alta cardinalidad
    assert all(len(c.sample_values) <= 20 for t in result.tables for c in t.columns)


def test_con_sample_values_falso_no_toma_muestras(demo_url: str) -> None:
    result = introspect(demo_url, _datasource("samples"), sample_values=False)

    assert all(not c.sample_values for t in result.tables for c in t.columns)


def test_limite_de_filas_bajo_omite_muestras(demo_url: str) -> None:
    result = introspect(demo_url, _datasource("samples", max_rows=10), sample_values=True)

    assert all(not c.sample_values for t in result.tables for c in t.columns)
    assert result.warnings


def test_mas_de_500_tablas_pide_filtrar(tmp_path: Path) -> None:
    path = tmp_path / "grande.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        for i in range(MAX_TABLES + 1):
            conn.execute(text(f"CREATE TABLE t{i:04d} (id INTEGER PRIMARY KEY, nombre TEXT)"))
    engine.dispose()
    url = f"sqlite:///{path}"

    with pytest.raises(TooManyTablesError) as error:
        introspect(url, _datasource())
    assert error.value.found == MAX_TABLES + 1

    started = time.monotonic()
    result = introspect(url, _datasource(), table_pattern="t00*")
    assert len(result.tables) == 100
    assert time.monotonic() - started < 30
