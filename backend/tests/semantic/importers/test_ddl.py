from pathlib import Path

from app.semantic.importers.ddl import DdlImport, import_ddl
from app.semantic.schema import Table

ROOT = Path(__file__).parents[4]
FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "ddl"
VENTAS = ROOT / "examples" / "ventas" / "schema.sql"


def _table(result: DdlImport, name: str) -> Table:
    return next(t for t in result.tables if t.name == name)


def _relationships(result: DdlImport) -> set[tuple[str, str]]:
    return {(r.from_, r.to) for r in result.relationships}


def test_ventas_produce_7_tablas_6_relaciones_y_11_descripciones() -> None:
    result = import_ddl(VENTAS.read_text(), "postgres")

    assert result.warnings == []
    assert len(result.tables) == 7
    assert _relationships(result) == {
        ("facturas.cliente_id", "clientes.id"),
        ("facturas.sucursal_id", "sucursales.id"),
        ("factura_detalle.factura_id", "facturas.id"),
        ("factura_detalle.producto_id", "productos.id"),
        ("ventas_diarias.sucursal_id", "sucursales.id"),
        ("ventas_mensuales.sucursal_id", "sucursales.id"),
    }
    descriptions = [t.description for t in result.tables if t.description] + [
        c.description for t in result.tables for c in t.columns if c.description
    ]
    assert len(descriptions) == 11
    assert _table(result, "facturas").description == (
        "Encabezado de cada factura de venta. Una fila por factura."
    )
    estado = next(c for c in _table(result, "facturas").columns if c.name == "estado")
    assert estado.description == "PAGADA, PENDIENTE o ANULADA. Solo PAGADA cuenta como venta."


def test_ventas_lee_tipos_y_llaves_primarias() -> None:
    result = import_ddl(VENTAS.read_text(), "postgres")

    assert _table(result, "sucursales").primary_key == ["id"]
    assert _table(result, "ventas_diarias").primary_key == ["fecha", "sucursal_id", "canal"]
    columns = {c.name: c.type for c in _table(result, "facturas").columns}
    assert columns["subtotal"] == "decimal(14, 2)"
    assert columns["numero"] == "varchar(20)"


def test_postgres_con_esquema_restricciones_y_sentencias_ignoradas() -> None:
    result = import_ddl((FIXTURES / "postgres.sql").read_text(), "postgres")

    assert [t.name for t in result.tables] == [
        "ventas.clientes",
        "ventas.facturas",
        "ventas.detalle",
    ]
    assert _table(result, "ventas.facturas").primary_key == ["id"]
    assert _table(result, "ventas.detalle").primary_key == ["factura_id", "linea"]
    assert _relationships(result) == {
        ("ventas.facturas.cliente_id", "ventas.clientes.id"),
        ("ventas.detalle.factura_id", "ventas.facturas.id"),
    }
    assert _table(result, "ventas.facturas").description == "Encabezado de factura."
    total = next(c for c in _table(result, "ventas.facturas").columns if c.name == "total")
    assert total.description == "Valor final cobrado."
    # CREATE INDEX, SELECT e INSERT: se ignoran sin fallar
    assert len(result.warnings) == 3
    assert all(w.path.startswith("línea ") for w in result.warnings)


def test_mysql_lee_comentarios_en_linea_y_de_tabla() -> None:
    result = import_ddl((FIXTURES / "mysql.sql").read_text(), "mysql")

    assert [t.name for t in result.tables] == ["clientes", "tienda.pedidos", "tienda.pedido_lineas"]
    clientes = _table(result, "clientes")
    assert clientes.description == "Clientes de la tienda"
    assert clientes.primary_key == ["id"]
    assert [c.description for c in clientes.columns] == [
        "Identificador del cliente",
        "Nombre completo",
        None,
    ]
    assert _relationships(result) == {
        ("tienda.pedidos.cliente_id", "clientes.id"),
        ("tienda.pedido_lineas.pedido_id", "tienda.pedidos.id"),
    }
    assert result.warnings == []


def test_tsql_con_nombres_dbo_y_sentencias_ignoradas() -> None:
    result = import_ddl((FIXTURES / "tsql.sql").read_text(), "tsql")

    assert [t.name for t in result.tables] == ["dbo.sucursales", "dbo.facturas"]
    assert _table(result, "dbo.facturas").primary_key == ["id"]
    assert _relationships(result) == {("dbo.facturas.sucursal_id", "dbo.sucursales.id")}
    assert len(result.warnings) == 1


def test_oracle_comment_on_columna() -> None:
    result = import_ddl(
        "CREATE TABLE t (a NUMBER(10) PRIMARY KEY);\nCOMMENT ON COLUMN t.a IS 'Llave';",
        "oracle",
    )

    assert _table(result, "t").columns[0].description == "Llave"
    assert result.warnings == []


def test_sentencias_que_no_son_ddl_se_reportan_sin_fallar() -> None:
    result = import_ddl("SELECT 1; DROP TABLE x; CREATE TABLE a (id INT); esto no es sql ((;")

    assert [t.name for t in result.tables] == ["a"]
    assert len(result.warnings) >= 2


def test_llave_foranea_hacia_tabla_ausente_se_advierte() -> None:
    result = import_ddl("CREATE TABLE a (b_id INT REFERENCES b (id));")

    assert result.relationships == []
    assert len(result.warnings) == 1


def test_comment_sobre_objeto_desconocido_se_advierte() -> None:
    result = import_ddl("COMMENT ON TABLE nada IS 'x'; COMMENT ON COLUMN nada.c IS 'y';", "postgres")

    assert result.tables == []
    assert len(result.warnings) == 2
