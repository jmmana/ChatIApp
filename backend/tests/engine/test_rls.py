import importlib
import re
import sqlite3
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.db.models import Datasource
from app.demo.seed import generar
from app.engine.guard import GuardCache, build_policy, check_sql
from app.engine.rls import (
    ViewAsNotAllowedError,
    build_user_context,
    missing_context_message,
    role_row_filters,
)
from app.semantic.schema import Role, RoleFilter, SemanticModel, parse_semantic_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
ROLE = "gerente_sucursal"
CONTEXT = build_user_context({"sucursales": [1, 2]})


def _model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    data: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text())
    return parse_semantic_model(data)


def _source(dialect: str = "postgres", max_rows: int = 500) -> Datasource:
    return Datasource(id=uuid.uuid4(), name="demo", dialect=dialect, max_rows=max_rows)


def _norm(sql: str | None) -> str:
    assert sql is not None
    return re.sub(r"\s+", " ", sql).replace("( ", "(").replace(" )", ")")


def _check(sql: str, dialect: str = "postgres", context: Any = CONTEXT) -> Any:
    return check_sql(sql, _model(), _source(dialect), 1, ROLE, GuardCache(), context)


def test_filtros_del_rol_incluyen_tablas_resumidas() -> None:
    filters = role_row_filters(next(r for r in _model().security.roles if r.name == ROLE))
    assert filters == {
        "facturas": "sucursal_id IN ({user.sucursales})",
        "ventas_diarias": "sucursal_id IN ({user.sucursales})",
        "ventas_mensuales": "sucursal_id IN ({user.sucursales})",
    }


def test_filtros_repetidos_de_una_tabla_se_combinan_con_and() -> None:
    role = Role(
        name="r",
        filters=[
            RoleFilter(table="t", condition="a = 1"),
            RoleFilter(table="t", condition="b = 2"),
        ],
    )
    assert role_row_filters(role) == {"t": "(a = 1) AND (b = 2)"}
    assert role_row_filters(Role(name="vacio")) == {}


def test_la_politica_lleva_los_filtros_del_rol() -> None:
    policy = build_policy(_model(), _source(), ROLE)
    assert set(policy.row_filters) == {"facturas", "ventas_diarias", "ventas_mensuales"}
    assert not build_policy(_model(), _source(), "gerencia_general").row_filters


def test_contexto_usa_los_atributos_del_usuario() -> None:
    assert build_user_context({"sucursales": [1, 2]}) == {"user": {"sucursales": [1, 2]}}


def test_view_as_solo_para_administradores() -> None:
    admin = build_user_context({"sucursales": [9]}, view_as={"sucursales": [1]}, is_admin=True)
    assert admin == {"user": {"sucursales": [1]}}
    with pytest.raises(ViewAsNotAllowedError):
        build_user_context({"sucursales": [9]}, view_as={"sucursales": [1]})


def test_salida_join() -> None:
    sql = (
        "SELECT s.nombre, SUM(f.total) FROM facturas AS f "
        "JOIN sucursales AS s ON s.id = f.sucursal_id GROUP BY 1"
    )
    result = _check(sql)
    assert result.allowed, result.violations
    out = _norm(result.sql)
    assert "(SELECT * FROM facturas WHERE sucursal_id IN (1, 2)) AS f" in out
    assert "JOIN sucursales AS s" in out


def test_salida_subconsulta() -> None:
    sql = "SELECT * FROM sucursales AS c WHERE c.id IN (SELECT sucursal_id FROM facturas)"
    result = _check(sql)
    assert result.allowed, result.violations
    assert "(SELECT * FROM facturas WHERE sucursal_id IN (1, 2)) AS facturas" in _norm(result.sql)


def test_salida_cte() -> None:
    result = _check("WITH x AS (SELECT * FROM facturas) SELECT COUNT(*) FROM x")
    assert result.allowed, result.violations
    out = _norm(result.sql)
    assert "WITH x AS (SELECT * FROM (SELECT * FROM facturas WHERE sucursal_id IN (1, 2))" in out


def test_salida_sql_server_con_top() -> None:
    result = _check("SELECT SUM(total) FROM facturas WHERE fecha >= '20261101'", "tsql")
    assert result.allowed, result.violations
    out = _norm(result.sql)
    assert out.startswith("SELECT TOP 500 SUM(total)")
    assert "(SELECT * FROM facturas WHERE sucursal_id IN (1, 2)) AS facturas" in out


def test_los_valores_son_literales_escapados() -> None:
    context = build_user_context({"sucursales": ["1); DROP TABLE facturas; --"]})
    result = _check("SELECT COUNT(*) FROM facturas", context=context)
    assert result.allowed, result.violations
    assert "'1); DROP TABLE facturas; --'" in _norm(result.sql)


def test_atributo_faltante_es_problema_de_configuracion() -> None:
    result = _check("SELECT COUNT(*) FROM facturas", context=build_user_context({}))
    assert not result.allowed
    assert result.sql is None
    assert result.user_config_problem
    message = next(v.message for v in result.violations if v.code == "missing_context")
    assert "administrador" in message


def test_sin_contexto_tambien_se_rechaza() -> None:
    result = check_sql("SELECT COUNT(*) FROM facturas", _model(), _source(), 1, ROLE, GuardCache())
    assert result.user_config_problem
    assert result.sql is None


def test_rol_sin_filtros_no_necesita_contexto() -> None:
    result = check_sql(
        "SELECT COUNT(*) FROM facturas", _model(), _source(), 1, "gerencia_general", GuardCache()
    )
    assert result.allowed
    assert not result.user_config_problem


def test_mensaje_de_configuracion_incluye_el_detalle() -> None:
    assert "falta sucursales" in missing_context_message("falta sucursales")


def test_punta_a_punta_con_la_demo_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "ventas.db"
    generar(db, seed=42, hasta=date(2025, 3, 31))
    sql = "SELECT DISTINCT sucursal_id FROM facturas"
    with sqlite3.connect(db) as conn:
        todas = {row[0] for row in conn.execute(sql)}
        assert len(todas - {1, 2}) > 0  # sin filtro hay filas de otras sucursales

        result = _check(sql, "sqlite")
        assert result.allowed, result.violations
        assert result.sql is not None
        vistas = {row[0] for row in conn.execute(result.sql)}
        assert vistas
        assert vistas <= {1, 2}

        # También con tablas resumidas y con un intento de saltarse el filtro desde la consulta.
        for text in (
            "SELECT DISTINCT sucursal_id FROM ventas_diarias",
            "SELECT DISTINCT sucursal_id FROM facturas WHERE sucursal_id NOT IN (1, 2)",
        ):
            rewritten = _check(text, "sqlite").sql
            assert rewritten is not None
            assert {row[0] for row in conn.execute(rewritten)} <= {1, 2}
