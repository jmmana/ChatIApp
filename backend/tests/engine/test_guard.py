import importlib
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.db.models import Datasource
from app.engine.guard import GuardCache, UnknownRoleError, build_policy, check_sql
from app.semantic.schema import SemanticModel, parse_semantic_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"


def _model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    data: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text())
    return parse_semantic_model(data)


def _source(dialect: str = "postgres", max_rows: int = 500) -> Datasource:
    return Datasource(id=uuid.uuid4(), name="demo", dialect=dialect, max_rows=max_rows)


# Los 6 casos de docs/SEGURIDAD.md#el-guardián-sql: (dialecto, SQL, código esperado).
ATTACKS = [
    ("postgres", "DELETE FROM facturas", "write_operation"),
    ("postgres", "SELECT 1; DROP TABLE facturas", "multiple_statements"),
    ("tsql", "SELECT * INTO nueva FROM facturas", "write_operation"),
    (
        "postgres",
        "WITH d AS (DELETE FROM facturas RETURNING *) SELECT * FROM d",
        "write_operation",
    ),
    ("tsql", "EXEC xp_cmdshell 'dir'", "write_operation"),
    ("postgres", "SELECT pg_sleep(10)", "forbidden_function"),
]


@pytest.mark.parametrize(("dialect", "sql", "code"), ATTACKS)
def test_rechaza_los_casos_de_la_documentacion(dialect: str, sql: str, code: str) -> None:
    result = check_sql(sql, _model(), _source(dialect), 1, "gerencia_general", GuardCache())
    assert not result.allowed
    assert result.sql is None
    assert code in {v.code for v in result.violations}
    assert all(v.message for v in result.violations)


def test_consulta_valida_sale_con_limite_de_filas() -> None:
    sql = "SELECT sucursal_id, SUM(total) FROM facturas GROUP BY sucursal_id"
    result = check_sql(sql, _model(), _source(max_rows=500), 1, "gerencia_general", GuardCache())
    assert result.allowed
    assert result.violations == ()
    assert result.tables == ("facturas",)
    assert result.sql is not None
    assert "LIMIT 500" in result.sql.upper()


def test_columna_oculta_se_rechaza_tambien_con_select_estrella() -> None:
    cache = GuardCache()
    for sql in ("SELECT email FROM clientes", "SELECT * FROM clientes"):
        result = check_sql(sql, _model(), _source(), 1, "gerencia_general", cache)
        assert "hidden_column" in {v.code for v in result.violations}


def test_tabla_oculta_del_rol_se_rechaza() -> None:
    result = check_sql("SELECT id FROM clientes", _model(), _source(), 1, "mercadeo", GuardCache())
    assert not result.allowed


def test_politica_desde_el_modelo() -> None:
    policy = build_policy(_model(), _source(max_rows=250), "mercadeo")
    assert policy.max_rows == 250
    assert "clientes" not in policy.allowed_tables
    assert "facturas" in policy.allowed_tables
    full = build_policy(_model(), _source(), "gerencia_general")
    assert set(full.hidden_columns["clientes"]) == {"documento", "email"}


def test_rol_inexistente() -> None:
    with pytest.raises(UnknownRoleError):
        build_policy(_model(), _source(), "fantasma")


def test_cache_por_fuente_version_y_rol() -> None:
    cache = GuardCache()
    model, source = _model(), _source()
    first = cache.get(model, source, 1, "mercadeo")
    assert cache.get(model, source, 1, "mercadeo") is first
    assert cache.get(model, source, 1, "gerencia_general") is not first
    assert cache.get(model, _source(), 1, "mercadeo") is not first
    # Una versión nueva invalida las anteriores de la misma fuente.
    assert cache.get(model, source, 2, "mercadeo") is not first
    assert cache.get(model, source, 1, "mercadeo") is not first
