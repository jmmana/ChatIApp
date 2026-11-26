from pathlib import Path

import pytest

from app.semantic.importers.ddl import import_ddl
from app.semantic.merge import Imported, MergeResult, merge_import
from app.semantic.schema import Column, SemanticModel, Table

SCHEMA = Path(__file__).parents[3] / "examples" / "ventas" / "schema.sql"


def _from_schema() -> Imported:
    ddl = import_ddl(SCHEMA.read_text("utf-8"), "postgres")
    return Imported(ddl.tables, ddl.relationships, ddl.warnings)


def _table(model: SemanticModel, name: str) -> Table:
    return next(t for t in model.tables if t.name == name)


def _column(table: Table, name: str) -> Column:
    return next(c for c in table.columns if c.name == name)


@pytest.fixture
def base() -> MergeResult:
    return merge_import(None, _from_schema(), "Ventas")


def test_sin_modelo_previo_agrega_todo(base: MergeResult) -> None:
    assert base.model.name == "Ventas"
    assert {a.kind for a in base.diff.added} >= {"table", "column"}
    assert not base.diff.changed
    assert not base.diff.missing


def test_importar_dos_veces_el_mismo_archivo_no_da_diferencias(base: MergeResult) -> None:
    again = merge_import(base.model, _from_schema(), "Ventas")

    assert again.diff.is_empty
    assert again.model == base.model


def test_conserva_las_descripciones_escritas_a_mano(base: MergeResult) -> None:
    model = base.model.model_copy(deep=True)
    sucursales = _table(model, "sucursales")
    sucursales.description = "Tiendas físicas"
    _column(sucursales, "ciudad").description = "Ciudad donde queda la tienda"

    result = merge_import(model, _from_schema(), "Ventas")

    merged = _table(result.model, "sucursales")
    assert merged.description == "Tiendas físicas"
    assert _column(merged, "ciudad").description == "Ciudad donde queda la tienda"
    assert not [c for c in result.diff.changed if c.field == "description"]


def test_la_descripcion_de_la_fuente_distinta_queda_como_sugerencia() -> None:
    manual = SemanticModel(
        version=1,
        name="m",
        tables=[Table(name="t", columns=[Column(name="a", description="Mía")])],
    )
    source = Imported([Table(name="t", columns=[Column(name="a", description="De la fuente")])])

    result = merge_import(manual, source, "m")

    assert _column(result.model.tables[0], "a").description == "Mía"
    assert [(s.path, s.suggested) for s in result.diff.suggestions] == [("t.a", "De la fuente")]


def test_completa_descripciones_vacias_y_actualiza_tipos() -> None:
    existing = SemanticModel(
        version=1, name="m", tables=[Table(name="t", columns=[Column(name="a", type="int")])]
    )
    source = Imported(
        [Table(name="t", description="Una tabla", columns=[Column(name="a", type="bigint")])]
    )
    source.tables[0].columns[0].description = "Una columna"

    result = merge_import(existing, source, "m")

    table = result.model.tables[0]
    assert table.description == "Una tabla"
    assert table.columns[0].type == "bigint"
    assert table.columns[0].description == "Una columna"
    assert {(c.path, c.field) for c in result.diff.changed} == {
        ("t", "description"),
        ("t.a", "type"),
        ("t.a", "description"),
    }


def test_lo_que_ya_no_esta_se_marca_sin_borrar() -> None:
    existing = SemanticModel(
        version=1,
        name="m",
        tables=[
            Table(name="t", columns=[Column(name="a"), Column(name="vieja")]),
            Table(name="huérfana", columns=[Column(name="x")]),
        ],
    )
    source = Imported([Table(name="t", columns=[Column(name="a"), Column(name="nueva")])])

    result = merge_import(existing, source, "m")

    assert [(m.path, m.kind) for m in result.diff.missing] == [
        ("t.vieja", "column"),
        ("huérfana", "table"),
    ]
    assert [(a.path, a.kind) for a in result.diff.added] == [("t.nueva", "column")]
    assert {t.name for t in result.model.tables} == {"t", "huérfana"}
    assert {c.name for c in _table(result.model, "t").columns} == {"a", "vieja", "nueva"}


def test_no_modifica_el_modelo_original(base: MergeResult) -> None:
    before = base.model.model_copy(deep=True)
    source = Imported([Table(name="sucursales", columns=[Column(name="nueva")])])

    merge_import(base.model, source, "Ventas")

    assert base.model == before
