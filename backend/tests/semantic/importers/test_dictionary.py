import importlib
import io
import json
from pathlib import Path

import pytest

from app.semantic.importers.dictionary import (
    DictionaryError,
    import_dictionary,
    parse_dictionary_csv,
    parse_dictionary_xlsx,
)
from app.semantic.importers.model_file import import_model_file, parse_model_text
from app.semantic.schema import SemanticModelError

ROOT = Path(__file__).parents[4]
VENTAS = ROOT / "examples" / "ventas"


def test_ejemplo_ventas_importa_sin_errores() -> None:
    result = import_dictionary(VENTAS / "diccionario.csv")
    assert result.issues == []
    tables = {t.name: t for t in result.tables}
    assert set(tables) == {"sucursales", "productos", "clientes", "facturas", "factura_detalle"}
    assert tables["sucursales"].synonyms == ["tiendas", "puntos de venta", "sedes"]
    clientes = {c.name: c for c in tables["clientes"].columns}
    assert clientes["documento"].hidden is True
    assert clientes["segmento"].hidden is False
    nombre = next(c for c in tables["sucursales"].columns if c.name == "nombre")
    assert nombre.sample_values == ["Bogotá Andino", "Medellín El Tesoro", "Cali Chipichape"]
    assert nombre.role == "dimension"


def test_encabezados_en_ingles_con_mayusculas_y_tildes() -> None:
    text = (
        "Table,COLUMN,Descripción,Synonyms,Role,Hidden\n"
        "t,,Una tabla,a|b,,\n"
        "t,c,Col,x,MEASURE,1\n"
    )
    result = parse_dictionary_csv(text)
    assert result.issues == []
    (table,) = result.tables
    assert table.description == "Una tabla"
    assert table.synonyms == ["a", "b"]
    assert table.columns[0].role == "measure"
    assert table.columns[0].hidden is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [("si", True), ("SÍ", True), ("true", True), ("1", True), ("no", False), ("0", False)],
)
def test_oculta_acepta_variantes(value: str, expected: bool) -> None:
    result = parse_dictionary_csv(f"tabla,columna,oculta\nt,c,{value}\n")
    assert result.issues == []
    assert result.tables[0].columns[0].hidden is expected


def test_filas_invalidas_se_reportan_y_las_validas_se_importan() -> None:
    text = (
        "tabla,columna,rol,oculta\n"
        "t,a,measure,\n"
        ",b,,\n"
        "t,c,raro,\n"
        "t,d,,quizas\n"
        "t,a,,\n"
        "t,e,id,no\n"
    )
    result = parse_dictionary_csv(text)
    assert [i.row for i in result.issues] == [3, 4, 5, 6]
    assert [c.name for c in result.tables[0].columns] == ["a", "e"]


def test_sin_encabezado_tabla_falla() -> None:
    with pytest.raises(DictionaryError):
        parse_dictionary_csv("columna,tipo\na,int\n")


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    openpyxl = importlib.import_module("openpyxl")
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_xlsx_usa_hoja_diccionario() -> None:
    content = _xlsx(
        {
            "Notas": [["tabla", "columna"], ["otra", "x"]],
            "Diccionario": [["table", "column", "hidden"], ["t", "c", True], ["t", "d", 0]],
        }
    )
    result = parse_dictionary_xlsx(content)
    assert result.issues == []
    assert result.tables[0].name == "t"
    assert [(c.name, c.hidden) for c in result.tables[0].columns] == [("c", True), ("d", False)]


def test_xlsx_sin_hoja_conocida_usa_la_primera() -> None:
    content = _xlsx({"Datos": [["tabla", "columna"], ["t", "c"]], "Otra": [["x"]]})
    assert parse_dictionary_xlsx(content).tables[0].name == "t"


def test_extension_no_soportada() -> None:
    with pytest.raises(DictionaryError):
        import_dictionary(Path("diccionario.txt"))


def test_modelo_yaml_de_ejemplo_valida() -> None:
    assert import_model_file(VENTAS / "semantic-model.yaml").metrics


def test_modelo_json_valida_y_reporta_errores() -> None:
    model = import_model_file(VENTAS / "semantic-model.yaml")
    as_json = json.dumps(model.model_dump(by_alias=True, mode="json"))
    assert parse_model_text(as_json, "json").name == model.name
    with pytest.raises(SemanticModelError) as info:
        parse_model_text(json.dumps({"version": 1}), "json")
    assert any(i.path == "name" for i in info.value.issues)


def test_modelo_con_sintaxis_invalida() -> None:
    with pytest.raises(SemanticModelError):
        parse_model_text("{no json", "json")
    with pytest.raises(SemanticModelError):
        parse_model_text("a: [", "yaml")
    with pytest.raises(SemanticModelError):
        parse_model_text("- 1", "yaml")
