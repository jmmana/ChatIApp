import importlib
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.agent.clarify import ALL_OPTION, Pending, apply_reply
from app.agent.entities import (
    EntityQuestion,
    like_pattern,
    resolve_filters,
    search_sql,
)
from app.agent.events import Event
from app.agent.orchestrator import Orchestrator
from app.agent.plan import Plan
from app.db.models import Base, Conversation, Datasource
from app.db.session import make_engine
from app.demo.seed import generar
from app.engine.catalog import PlanFilter
from app.engine.executor import QueryExecutor
from app.engine.guard import GuardCache, check_sql
from app.engine.periods import PeriodConfig
from app.llm.gateway import Gateway, ProviderConfig
from app.semantic.schema import SemanticModel, parse_semantic_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)
CONFIG = PeriodConfig(timezone="America/Bogota", week_starts_on="monday", locale="es-CO")
BOGOTA = ["Bogotá Andino", "Bogotá Titán", "Bogotá Unicentro"]


@pytest.fixture(scope="module")
def model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    return parse_semantic_model(yaml.safe_load(EXAMPLE.read_text()))


@pytest.fixture(scope="module")
def demo_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("demo") / "ventas.db"
    generar(path, seed=42, hasta=date(2026, 11, 25))
    return f"sqlite:///{path}"


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield s
    engine.dispose()


@pytest.fixture
def query_executor() -> Iterator[QueryExecutor]:
    ex = QueryExecutor()
    yield ex
    ex.dispose()


@pytest.fixture
def datasource(session: Session) -> Datasource:
    source = Datasource(
        name="demo",
        dialect="sqlite",
        url_encrypted=b"no-se-usa",
        execute=True,
        privacy="aggregates",
    )
    session.add(source)
    session.commit()
    return source


@pytest.fixture
def runner(
    model: SemanticModel, datasource: Datasource, demo_url: str, query_executor: QueryExecutor
) -> Any:
    """Corre la búsqueda como el orquestador: guardián primero, luego el ejecutor."""
    cache = GuardCache()
    seen: list[str] = []

    def run(sql: str) -> list[str]:
        guarded = check_sql(sql, model, datasource, 1, "gerencia_general", cache=cache)
        assert guarded.allowed and guarded.sql is not None, guarded.violations
        seen.append(guarded.sql)
        result = query_executor.execute_sync(str(datasource.id), demo_url, "sqlite", guarded.sql)
        return [str(row[0]) for row in result.rows]

    run.seen = seen  # type: ignore[attr-defined]
    return run


# --------------------------------------------------------------------------- búsqueda


def test_el_patron_ignora_tildes_y_mayusculas() -> None:
    assert like_pattern("BOGOTÁ") == like_pattern("bogota") == "%b_g_t_%"
    assert like_pattern("100%_x'y") == "%100__x''y%"
    assert like_pattern("Peña") == "%p___%"
    assert search_sql("sucursales.nombre", "Bogotá").endswith("LIMIT 20")


@pytest.mark.parametrize("term", ["Bogotá", "bogota", "BOGOTA", "bogotá"])
def test_bogota_ofrece_las_tres_tiendas(model: SemanticModel, runner: Any, term: str) -> None:
    filters = [PlanFilter("sucursales.nombre", "contains", term)]
    with pytest.raises(EntityQuestion) as caught:
        resolve_filters(model, filters, runner)
    asked = caught.value.question
    assert asked.options == [*BOGOTA, ALL_OPTION]
    assert asked.slot == "entity:sucursales.nombre"
    assert "3 valores" in asked.question
    assert all("LIMIT 20" in sql for sql in runner.seen)


def test_una_coincidencia_se_usa(model: SemanticModel, runner: Any) -> None:
    filters = [PlanFilter("sucursales.nombre", "contains", "unicentro")]
    resolved = resolve_filters(model, filters, runner)
    assert resolved == (PlanFilter("sucursales.nombre", "=", "Bogotá Unicentro"),)
    city = resolve_filters(model, [PlanFilter("sucursales.ciudad", "=", "medellin")], runner)
    assert city == (PlanFilter("sucursales.ciudad", "=", "Medellín"),)


def test_igualdad_con_valor_exacto_no_pregunta(model: SemanticModel, runner: Any) -> None:
    resolved = resolve_filters(model, [PlanFilter("sucursales.ciudad", "=", "bogota")], runner)
    assert resolved == (PlanFilter("sucursales.ciudad", "=", "Bogotá"),)


def test_ninguna_coincidencia_muestra_valores_parecidos(model: SemanticModel, runner: Any) -> None:
    with pytest.raises(EntityQuestion) as caught:
        resolve_filters(model, [PlanFilter("sucursales.ciudad", "=", "Bogota DC")], runner)
    asked = caught.value.question
    assert "No encontré «Bogota DC»" in asked.question
    assert "Bogotá" in asked.options and ALL_OPTION not in asked.options

    with pytest.raises(EntityQuestion) as typo:
        resolve_filters(model, [PlanFilter("sucursales.ciudad", "=", "Medelin")], runner)
    assert "Medellín" in typo.value.question.options

    with pytest.raises(EntityQuestion) as nothing:
        resolve_filters(model, [PlanFilter("sucursales.ciudad", "=", "zzzzzz")], runner)
    assert nothing.value.question.options == []
    assert "No encontré «zzzzzz»" in nothing.value.question.question


def test_otros_filtros_pasan_sin_buscar(model: SemanticModel) -> None:
    def never(sql: str) -> list[str]:
        raise AssertionError(sql)

    filters = (
        PlanFilter("facturas.total", ">", 100),
        PlanFilter("sucursales.ciudad", "in", ["Cali"]),
    )
    assert resolve_filters(model, filters, never) == filters


# --------------------------------------------------------------------------- respuesta


def test_la_respuesta_reemplaza_el_filtro(model: SemanticModel) -> None:
    plan = Plan.model_validate(
        {
            "intent": "metric",
            "metric": "ventas_netas",
            "filters": [{"field": "sucursales.nombre", "op": "contains", "value": "Bogotá"}],
        }
    )
    pending = Pending("entity:sucursales.nombre", [*BOGOTA, ALL_OPTION])
    one = apply_reply(plan, pending, "Bogotá Titán", model, CONFIG, NOW)
    assert one is not None
    assert [(f.op, f.value) for f in one.filters] == [("=", "Bogotá Titán")]
    typed = apply_reply(plan, pending, "bogota unicentro", model, CONFIG, NOW)
    assert typed is not None and typed.filters[0].value == "Bogotá Unicentro"
    every = apply_reply(plan, pending, "todas", model, CONFIG, NOW)
    assert every is not None
    assert (every.filters[0].op, every.filters[0].value) == ("in", BOGOTA)
    assert apply_reply(plan, pending, "ninguna de esas", model, CONFIG, NOW) is None


# --------------------------------------------------------------------------- punta a punta


def _orchestrator(
    session: Session,
    model: SemanticModel,
    datasource: Datasource,
    demo_url: str,
    query_executor: QueryExecutor,
    answers: list[dict[str, Any] | str],
) -> tuple[Orchestrator, Conversation]:
    texts = [a if isinstance(a, str) else json.dumps(a) for a in answers]
    gateway = Gateway(ProviderConfig("fake", "fake-1", {"responses": texts}))
    conversation = Conversation(datasource_id=datasource.id)
    session.add(conversation)
    session.commit()
    orchestrator = Orchestrator(
        session,
        gateway,
        datasource,
        model,
        1,
        demo_url,
        role="gerencia_general",
        query_executor=query_executor,
        guard_cache=GuardCache(),
        now=NOW,
    )
    return orchestrator, conversation


def test_ventas_en_bogota_pregunta_y_la_respuesta_retoma(
    session: Session,
    model: SemanticModel,
    datasource: Datasource,
    demo_url: str,
    query_executor: QueryExecutor,
) -> None:
    plan = {
        "intent": "metric",
        "metric": "ventas_netas",
        "period_text": "este mes",
        "filters": [{"field": "sucursales.nombre", "op": "contains", "value": "Bogotá"}],
    }
    orchestrator, conversation = _orchestrator(
        session, model, datasource, demo_url, query_executor, [plan, "Listo."]
    )

    first: list[Event] = list(orchestrator.run(conversation, "ventas en Bogotá este mes"))
    asked = [e.payload() for e in first if e.type == "clarification"][0]
    assert asked["options"] == [*BOGOTA, ALL_OPTION]
    assert "sql" not in [e.type for e in first]

    second = list(orchestrator.run(conversation, "Todas"))
    types = [e.type for e in second]
    assert "error" not in types and "clarification" not in types and "result" in types
    sql = [e.payload() for e in second if e.type == "sql"][0]["sql"]
    assert all(name in sql for name in BOGOTA)
