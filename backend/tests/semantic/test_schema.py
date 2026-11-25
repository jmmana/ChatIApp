import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.semantic.schema import (
    SCHEMA_PATH,
    SemanticModelError,
    json_schema,
    parse_semantic_model,
)

ROOT = Path(__file__).parents[3]
EXAMPLE = ROOT / "examples" / "ventas" / "semantic-model.yaml"


def _example() -> dict[str, Any]:
    yaml = importlib.import_module("yaml")
    data: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text())
    return data


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    table: dict[str, Any] = next(t for t in data["tables"] if t["name"] == name)
    return table


def _column(data: dict[str, Any], table: str, name: str) -> dict[str, Any]:
    column: dict[str, Any] = next(c for c in _table(data, table)["columns"] if c["name"] == name)
    return column


def _errors(data: dict[str, Any]) -> list[str]:
    with pytest.raises(SemanticModelError) as info:
        parse_semantic_model(data)
    return [str(issue) for issue in info.value.issues]


def _assert_error(data: dict[str, Any], path: str, fragment: str) -> None:
    errors = _errors(data)
    assert any(e.startswith(f"{path}: ") and fragment in e for e in errors), errors


@pytest.fixture
def data() -> dict[str, Any]:
    return copy.deepcopy(_example())


def test_el_ejemplo_ventas_valida_sin_errores_ni_advertencias(data: dict[str, Any]) -> None:
    model = parse_semantic_model(data)

    assert model.name == "Ventas (demo)"
    assert len(model.tables) == 7
    assert [m.name for m in model.metrics][0] == "ventas_netas"
    assert model.warnings() == []


def test_campo_desconocido_se_rechaza_con_su_ruta(data: dict[str, Any]) -> None:
    data["metrics"][2]["dimesions"] = ["facturas.canal"]

    _assert_error(data, "metrics[2].dimesions", "Campo no permitido")


def test_campo_obligatorio_faltante(data: dict[str, Any]) -> None:
    del data["metrics"][1]["expression"]

    _assert_error(data, "metrics[1].expression", "Campo obligatorio")


def test_nombres_de_tablas_unicos(data: dict[str, Any]) -> None:
    data["tables"].append(copy.deepcopy(_table(data, "clientes")))

    _assert_error(data, "tables[7].name", "«clientes» está repetida")


def test_nombres_de_columnas_unicos(data: dict[str, Any]) -> None:
    _table(data, "clientes")["columns"].append({"name": "email"})

    _assert_error(data, "tables[4].columns[7].name", "«email» está repetida")


def test_nombres_de_metricas_unicos(data: dict[str, Any]) -> None:
    data["metrics"].append(copy.deepcopy(data["metrics"][0]))

    _assert_error(data, "metrics[6].name", "«ventas_netas» está repetida")


def test_nombres_de_roles_unicos(data: dict[str, Any]) -> None:
    data["security"]["roles"].append({"name": "mercadeo"})

    _assert_error(data, "security.roles[3].name", "«mercadeo» está repetido")


def test_relacion_con_tabla_inexistente(data: dict[str, Any]) -> None:
    data["relationships"][1]["to"] = "tiendas.id"

    _assert_error(data, "relationships[1].to", "La tabla «tiendas» no existe")


def test_relacion_con_columna_inexistente(data: dict[str, Any]) -> None:
    data["relationships"][0]["from"] = "facturas.cliente"

    _assert_error(data, "relationships[0].from", "La columna «cliente» no existe")


def test_llave_primaria_con_columna_inexistente(data: dict[str, Any]) -> None:
    _table(data, "facturas")["primary_key"] = ["codigo"]

    _assert_error(data, "tables[0].primary_key[0]", "La columna «codigo» no existe")


def test_time_column_de_tabla_inexistente(data: dict[str, Any]) -> None:
    _table(data, "facturas")["time_column"] = "emitida"

    _assert_error(data, "tables[0].time_column", "La columna «emitida» no existe")


def test_time_column_de_metrica_inexistente(data: dict[str, Any]) -> None:
    data["metrics"][0]["time_column"] = "emitida"

    _assert_error(data, "metrics[0].time_column", "La columna «emitida» no existe")


def test_time_column_de_metrica_en_otra_tabla_valida(data: dict[str, Any]) -> None:
    # unidades_vendidas usa facturas.fecha desde factura_detalle
    assert data["metrics"][4]["time_column"] == "facturas.fecha"
    parse_semantic_model(data)


def test_metrica_con_tabla_inexistente(data: dict[str, Any]) -> None:
    data["metrics"][0]["table"] = "ventas"

    _assert_error(data, "metrics[0].table", "La tabla «ventas» no existe")


def test_dimension_inexistente_incluye_indice(data: dict[str, Any]) -> None:
    data["metrics"][2]["dimensions"][0] = "sucursales.barrio"

    _assert_error(data, "metrics[2].dimensions[0]", "La columna «barrio» no existe")


def test_dimension_sin_forma_tabla_columna(data: dict[str, Any]) -> None:
    data["metrics"][2]["dimensions"][1] = "ciudad"

    _assert_error(data, "metrics[2].dimensions[1]", "debe tener la forma tabla.columna")


def test_tabla_de_filtro_de_rol_inexistente(data: dict[str, Any]) -> None:
    data["security"]["roles"][1]["filters"][0]["table"] = "pedidos"

    _assert_error(data, "security.roles[1].filters[0].table", "La tabla «pedidos» no existe")


def test_hidden_tables_con_tabla_inexistente(data: dict[str, Any]) -> None:
    data["security"]["roles"][2]["hidden_tables"] = ["personas"]

    _assert_error(data, "security.roles[2].hidden_tables[0]", "La tabla «personas» no existe")


def test_rol_por_defecto_inexistente(data: dict[str, Any]) -> None:
    data["security"]["default_role"] = "jefe"

    _assert_error(data, "security.default_role", "El rol «jefe» no existe")


def test_metrica_de_resumida_inexistente(data: dict[str, Any]) -> None:
    data["summary_tables"][0]["metrics"]["margen"] = "SUM(total_ventas)"

    _assert_error(
        data, "summary_tables[0].metrics[margen]", "La métrica «margen» no existe en metrics"
    )


def test_resumida_con_tabla_inexistente(data: dict[str, Any]) -> None:
    data["summary_tables"][1]["table"] = "ventas_anuales"

    _assert_error(data, "summary_tables[1].table", "La tabla «ventas_anuales» no existe")


def test_dimension_de_resumida_apunta_a_columna_inexistente(data: dict[str, Any]) -> None:
    data["summary_tables"][0]["dimensions"]["facturas.canal"] = "canal_venta"

    _assert_error(
        data, "summary_tables[0].dimensions[facturas.canal]", "La columna «canal_venta» no existe"
    )


def test_expression_se_parsea_con_sqlglot(data: dict[str, Any]) -> None:
    data["metrics"][0]["expression"] = "SUM(total"

    _assert_error(data, "metrics[0].expression", "SQL no válido")


def test_filtro_de_metrica_se_parsea_con_sqlglot(data: dict[str, Any]) -> None:
    data["metrics"][0]["filters"] = ["estado = 'PAGADA'", "estado = ("]

    _assert_error(data, "metrics[0].filters[1]", "SQL no válido")


def test_expresion_de_resumida_se_parsea_con_sqlglot(data: dict[str, Any]) -> None:
    data["summary_tables"][0]["metrics"]["ventas_netas"] = "SUM(total_ventas"

    _assert_error(data, "summary_tables[0].metrics[ventas_netas]", "SQL no válido")


def test_dialecto_desconocido(data: dict[str, Any]) -> None:
    data["dialect"] = "cobol"

    _assert_error(data, "dialect", "Dialecto SQL desconocido")


def test_time_column_debe_tener_rol_time(data: dict[str, Any]) -> None:
    data["metrics"][0]["time_column"] = "canal"

    _assert_error(data, "metrics[0].time_column", "debe tener rol time")


def test_time_column_de_tabla_debe_tener_rol_time(data: dict[str, Any]) -> None:
    _table(data, "facturas")["time_column"] = "total"

    _assert_error(data, "tables[0].time_column", "debe tener rol time")


def test_time_column_de_resumida_debe_tener_rol_time(data: dict[str, Any]) -> None:
    data["summary_tables"][0]["time_column"] = "canal"

    _assert_error(data, "summary_tables[0].time_column", "debe tener rol time")


@pytest.mark.parametrize(
    "condition",
    [
        "sucursal_id IN ({user.})",
        "sucursal_id IN ({user sucursales})",
        "sucursal_id IN ({usuario.sucursales})",
        "sucursal_id IN ({user.sucursales)",
        "sucursal_id IN ({{user.sucursales}})",
    ],
)
def test_condicion_de_rol_con_marcador_mal_formado(
    data: dict[str, Any], condition: str
) -> None:
    data["security"]["roles"][1]["filters"][0]["condition"] = condition

    _assert_error(data, "security.roles[1].filters[0].condition", "Marcador mal formado")


def test_condicion_de_rol_con_sql_invalido(data: dict[str, Any]) -> None:
    data["security"]["roles"][1]["filters"][0]["condition"] = "sucursal_id IN ({user.x}"

    _assert_error(data, "security.roles[1].filters[0].condition", "no válida")


def test_metrica_no_puede_usar_columna_oculta_en_expresion(data: dict[str, Any]) -> None:
    _column(data, "facturas", "total")["hidden"] = True

    _assert_error(data, "metrics[0].expression", "columna oculta «facturas.total»")


def test_metrica_no_puede_usar_columna_oculta_en_filtro(data: dict[str, Any]) -> None:
    _column(data, "facturas", "estado")["hidden"] = True

    _assert_error(data, "metrics[0].filters[0]", "columna oculta «facturas.estado»")


def test_filtro_calificado_con_columna_oculta_de_otra_tabla(data: dict[str, Any]) -> None:
    data["metrics"][4]["filters"] = ["clientes.documento = '1'"]

    _assert_error(data, "metrics[4].filters[0]", "columna oculta «clientes.documento»")


def test_metrica_no_puede_usar_dimension_oculta(data: dict[str, Any]) -> None:
    data["metrics"][0]["dimensions"].append("clientes.email")

    _assert_error(data, "metrics[0].dimensions[5]", "columna oculta «clientes.email»")


def test_metrica_no_puede_usar_time_column_oculta(data: dict[str, Any]) -> None:
    _column(data, "facturas", "fecha")["hidden"] = True

    _assert_error(data, "metrics[0].time_column", "columna oculta «facturas.fecha»")


def test_resumida_no_puede_usar_columna_oculta(data: dict[str, Any]) -> None:
    _column(data, "ventas_diarias", "unidades")["hidden"] = True

    _assert_error(
        data, "summary_tables[0].metrics[unidades_vendidas]", "columna oculta «ventas_diarias."
    )


def test_dos_caminos_igual_de_cortos_no_validan(data: dict[str, Any]) -> None:
    # Segunda relación entre facturas y sucursales: el camino deja de ser único.
    _table(data, "facturas")["columns"].append({"name": "sucursal_destino_id", "role": "id"})
    data["relationships"].append({"from": "facturas.sucursal_destino_id", "to": "sucursales.id"})

    _assert_error(data, "metrics[0].dimensions[0]", "2 caminos igual de cortos")


def test_dimension_sin_relacion_con_la_tabla_de_la_metrica(data: dict[str, Any]) -> None:
    data["relationships"] = [r for r in data["relationships"] if r["to"] != "clientes.id"]

    _assert_error(data, "metrics[0].dimensions[4]", "No hay relaciones entre «facturas»")


def test_se_reportan_todos_los_errores_juntos(data: dict[str, Any]) -> None:
    data["metrics"][0]["table"] = "ventas"
    data["security"]["default_role"] = "jefe"

    assert len(_errors(data)) >= 2


def test_advertencia_si_tabla_filtrada_tiene_resumida_sin_filtro(data: dict[str, Any]) -> None:
    role = data["security"]["roles"][1]
    role["filters"] = [f for f in role["filters"] if f["table"] != "ventas_mensuales"]

    model = parse_semantic_model(data)

    assert [str(w) for w in model.warnings()] == [
        "security.roles[1].filters[0]: «facturas» está filtrada para el rol «gerente_sucursal», "
        "pero su tabla resumida «ventas_mensuales» no tiene filtro para ese rol"
    ]


def test_no_hay_advertencia_si_la_resumida_esta_oculta_para_el_rol(data: dict[str, Any]) -> None:
    role = data["security"]["roles"][1]
    role["filters"] = [f for f in role["filters"] if f["table"] != "ventas_mensuales"]
    role["hidden_tables"] = ["ventas_mensuales"]

    assert parse_semantic_model(data).warnings() == []


def test_json_schema_exportado_cubre_el_modelo() -> None:
    exported = json.loads(SCHEMA_PATH.read_text())
    generated = json_schema()

    assert exported["$schema"] == generated["$schema"]
    assert set(exported["properties"]) == set(generated["properties"])
    assert set(exported["$defs"]) == set(generated["$defs"])
    assert "from" in exported["$defs"]["Relationship"]["properties"]
