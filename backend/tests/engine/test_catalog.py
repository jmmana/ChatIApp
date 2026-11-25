import importlib
from pathlib import Path
from typing import Any

import pytest

from app.engine.catalog import (
    AmbiguousMetricError,
    Catalog,
    DimensionNotAllowedError,
    HiddenFieldError,
    InvalidFilterValueError,
    InvalidOperatorError,
    MetricNotAllowedError,
    PlanFilter,
    UnknownFilterFieldError,
    UnknownMetricError,
    normalize,
)
from app.semantic.schema import parse_semantic_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"


def _load() -> dict[str, Any]:
    yaml = importlib.import_module("yaml")
    data: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text())
    return data


@pytest.fixture
def catalog() -> Catalog:
    return Catalog(parse_semantic_model(_load()))


def test_normalize_quita_tildes_mayusculas_y_espacios() -> None:
    assert normalize("  ¿Cuánto   VENDÍ") == "¿cuanto vendi"


def test_encuentra_por_nombre_exacto(catalog: Catalog) -> None:
    assert catalog.find_metric("ventas_netas").name == "ventas_netas"


@pytest.mark.parametrize("text", ["cuánto vendí", "CUANTO VENDI", "Ingresos", "Ventas netas"])
def test_encuentra_por_sinonimo_o_etiqueta_sin_tildes_ni_mayusculas(
    catalog: Catalog, text: str
) -> None:
    assert catalog.find_metric(text).name == "ventas_netas"


def test_metrica_inexistente_lista_las_disponibles(catalog: Catalog) -> None:
    with pytest.raises(UnknownMetricError) as info:
        catalog.find_metric("margen")
    assert "ventas_netas" in info.value.available
    assert "ventas_netas" in info.value.message


def test_sinonimo_repetido_es_ambiguo() -> None:
    data = _load()
    data["metrics"][1]["synonyms"].append("ventas")
    catalog = Catalog(parse_semantic_model(data))

    with pytest.raises(AmbiguousMetricError) as info:
        catalog.find_metric("Ventas")
    assert info.value.candidates == ("ventas_netas", "ventas_sin_iva")


def test_plan_valido(catalog: Catalog) -> None:
    plan = catalog.verify(
        "ventas",
        ["sucursales.ciudad"],
        [PlanFilter("facturas.canal", "in", ["TIENDA", "ONLINE"])],
        role="gerencia_general",
    )
    assert plan.metric.name == "ventas_netas"
    assert plan.dimensions == ("sucursales.ciudad",)


def test_dimension_no_permitida_lista_las_permitidas(catalog: Catalog) -> None:
    with pytest.raises(DimensionNotAllowedError) as info:
        catalog.verify("ticket_promedio", ["clientes.segmento"], role="gerencia_general")
    assert info.value.allowed == (
        "sucursales.nombre",
        "sucursales.ciudad",
        "facturas.canal",
    )
    assert "sucursales.ciudad" in info.value.message


def test_dimension_de_tabla_oculta_para_el_rol(catalog: Catalog) -> None:
    with pytest.raises(HiddenFieldError):
        catalog.verify("ventas_netas", ["clientes.segmento"], role="mercadeo")


def test_dimension_no_permitida_no_ofrece_las_ocultas_del_rol(catalog: Catalog) -> None:
    with pytest.raises(DimensionNotAllowedError) as info:
        catalog.verify("ventas_netas", ["productos.marca"], role="mercadeo")
    assert "clientes.segmento" not in info.value.allowed


@pytest.mark.parametrize("op", ["=", "!=", ">", ">=", "<", "<=", "contains"])
def test_operadores_validos(catalog: Catalog, op: str) -> None:
    catalog.verify("ventas_netas", filters=[PlanFilter("facturas.canal", op, "TIENDA")])


def test_operador_invalido(catalog: Catalog) -> None:
    with pytest.raises(InvalidOperatorError):
        catalog.verify("ventas_netas", filters=[PlanFilter("facturas.canal", "like", "T%")])


def test_campo_de_filtro_inexistente(catalog: Catalog) -> None:
    with pytest.raises(UnknownFilterFieldError):
        catalog.verify("ventas_netas", filters=[PlanFilter("facturas.color", "=", "rojo")])


def test_campo_de_filtro_sin_relacion_con_la_metrica() -> None:
    data = _load()
    data["relationships"] = [
        r for r in data["relationships"] if not r["from"].startswith("ventas_diarias")
    ]
    catalog = Catalog(parse_semantic_model(data))

    with pytest.raises(UnknownFilterFieldError):
        catalog.verify("num_facturas", filters=[PlanFilter("ventas_diarias.canal", "=", "TIENDA")])


def test_columna_oculta_en_filtro(catalog: Catalog) -> None:
    with pytest.raises(HiddenFieldError):
        catalog.verify(
            "ventas_netas",
            filters=[PlanFilter("clientes.documento", "=", "123")],
            role="gerencia_general",
        )


def test_tabla_oculta_para_el_rol_en_filtro(catalog: Catalog) -> None:
    with pytest.raises(HiddenFieldError) as info:
        catalog.verify(
            "ventas_netas",
            filters=[PlanFilter("clientes.segmento", "=", "EMPRESA")],
            role="mercadeo",
        )
    assert info.value.role == "mercadeo"


def test_usa_el_rol_por_defecto_si_no_se_indica(catalog: Catalog) -> None:
    # gerente_sucursal no oculta tablas: el filtro por clientes.segmento es válido
    catalog.verify("ventas_netas", filters=[PlanFilter("clientes.segmento", "=", "EMPRESA")])


def test_metrica_sobre_tabla_oculta_para_el_rol() -> None:
    data = _load()
    data["security"]["roles"][2]["hidden_tables"] = ["facturas"]
    catalog = Catalog(parse_semantic_model(data))

    with pytest.raises(MetricNotAllowedError):
        catalog.verify("ventas_netas", role="mercadeo")


@pytest.mark.parametrize(
    ("op", "value"),
    [("in", "TIENDA"), ("in", []), ("=", ["TIENDA"]), ("=", None), ("contains", 5)],
)
def test_valor_de_filtro_invalido(catalog: Catalog, op: str, value: Any) -> None:
    with pytest.raises(InvalidFilterValueError):
        catalog.verify("ventas_netas", filters=[PlanFilter("facturas.canal", op, value)])
