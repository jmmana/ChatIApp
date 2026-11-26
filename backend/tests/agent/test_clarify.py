import importlib
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.clarify import (
    PERIOD_OPTIONS,
    Pending,
    apply_reply,
    dimension_question,
    metric_question,
    pending_clarification,
    period_question,
    should_assume_default,
    trailing_clarifications,
)
from app.agent.events import Event
from app.agent.orchestrator import Orchestrator
from app.agent.plan import Plan
from app.db.models import Base, Conversation, Datasource, Message
from app.db.session import make_engine
from app.demo.seed import generar
from app.engine.executor import QueryExecutor
from app.engine.guard import GuardCache
from app.engine.periods import PeriodConfig
from app.llm.gateway import Gateway, ProviderConfig
from app.semantic.schema import SemanticModel, parse_semantic_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)
CONFIG = PeriodConfig(timezone="America/Bogota", week_starts_on="monday", locale="es-CO")
PLAN = Plan(intent="metric", metric="ventas_netas", dimensions=["color"])


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


def _assistant(events: list[dict[str, Any]]) -> Message:
    return Message(conversation_id=None, role="assistant", content="", events=events)


def _ask_event(slot: str | None, options: list[str]) -> dict[str, Any]:
    data = {"question": "¿?", "options": options, "slot": slot}
    return {"type": "clarification", "data": data}


# --------------------------------------------------------------------------- preguntas


def test_pregunta_de_periodo_ofrece_las_seis_opciones(model: SemanticModel) -> None:
    metric = model.metrics[0]
    asked = period_question(metric, None)
    assert asked.slot == "period" and asked.options == PERIOD_OPTIONS and len(asked.options) == 6
    assert "ventas netas" in asked.question
    assert "No entendí el período «temporada alta»" in period_question(metric, "temporada alta").question


def test_pregunta_de_metrica_y_dimension(model: SemanticModel) -> None:
    metric_ask = metric_question(model.metrics[:2])
    assert metric_ask.slot == "metric" and metric_ask.options == [m.label for m in model.metrics[:2]]
    dim_ask = dimension_question("ventas_netas", "color", ["sucursales.ciudad"])
    assert dim_ask.slot == "dimension" and "sucursales.ciudad" in dim_ask.question


def test_tope_de_dos_aclaraciones_exige_periodo_por_defecto(model: SemanticModel) -> None:
    metric = model.metrics[0].model_copy(update={"default_period": None})
    assert not should_assume_default(5, metric)
    with_default = metric.model_copy(update={"default_period": "este mes"})
    assert not should_assume_default(1, with_default)
    assert should_assume_default(2, with_default)


# --------------------------------------------------------------------------- conversación


def test_cuenta_aclaraciones_seguidas_y_detecta_la_pendiente() -> None:
    ask = _assistant([_ask_event("period", ["Hoy"])])
    answer = _assistant([{"type": "answer", "data": {"text": "ok"}}])
    user = Message(conversation_id=None, role="user", content="x")
    assert trailing_clarifications([answer, user, ask, user, ask]) == 2
    assert trailing_clarifications([ask, user, answer, user]) == 0
    assert pending_clarification([user, ask, user]) == Pending("period", ["Hoy"])
    assert pending_clarification([ask, user, answer]) is None
    assert pending_clarification([]) is None


# --------------------------------------------------------------------------- respuesta


@pytest.mark.parametrize("reply", ["Este mes", "este mes", "el mes pasado", "Últimos 30 días"])
def test_respuesta_de_periodo_boton_o_escrita(model: SemanticModel, reply: str) -> None:
    plan = Plan(intent="metric", metric="ventas_netas")
    pending = Pending("period", PERIOD_OPTIONS)
    resumed = apply_reply(plan, pending, reply, model, CONFIG, NOW)
    assert resumed is not None and resumed.period_text == reply
    assert resumed.metric == "ventas_netas"


def test_periodo_no_reconocido_no_retoma(model: SemanticModel) -> None:
    plan = Plan(intent="metric", metric="ventas_netas")
    pending = Pending("period", PERIOD_OPTIONS)
    assert apply_reply(plan, pending, "la temporada alta", model, CONFIG, NOW) is None
    assert apply_reply(plan, pending, "  ", model, CONFIG, NOW) is None
    clarify = Plan.model_validate(
        {"intent": "clarify", "clarification": {"question": "¿?", "options": []}}
    )
    assert apply_reply(clarify, pending, "Este mes", model, CONFIG, NOW) is None


def test_respuesta_de_metrica(model: SemanticModel) -> None:
    plan = Plan(intent="metric", metric="facturar")
    options = ["Ventas netas", "Ventas sin IVA"]
    pending = Pending("metric", options)
    resumed = apply_reply(plan, pending, "Ventas sin IVA", model, CONFIG, NOW)
    assert resumed is not None and resumed.metric == "ventas_sin_iva"
    assert apply_reply(plan, pending, "ninguna de esas", model, CONFIG, NOW) is None


def test_respuesta_de_dimension(model: SemanticModel) -> None:
    pending = Pending("dimension", ["sucursales.ciudad", "facturas.canal"])
    resumed = apply_reply(PLAN, pending, "facturas.canal", model, CONFIG, NOW)
    assert resumed is not None and resumed.dimensions == ["facturas.canal"]
    typed = apply_reply(PLAN, pending, "mejor por sucursales.ciudad", model, CONFIG, NOW)
    assert typed is not None and typed.dimensions == ["sucursales.ciudad"]
    none = apply_reply(PLAN, pending, "ninguna", model, CONFIG, NOW)
    assert none is not None and none.dimensions == []
    assert apply_reply(PLAN, pending, "color", model, CONFIG, NOW) is None


# --------------------------------------------------------------------------- punta a punta


def _setup(session: Session, answers: list[str | dict[str, Any]]) -> tuple[Datasource, Gateway]:
    datasource = Datasource(
        name="demo", dialect="sqlite", url_encrypted=b"no-se-usa", execute=True, privacy="aggregates"
    )
    session.add(datasource)
    session.commit()
    texts = [a if isinstance(a, str) else json.dumps(a) for a in answers]
    return datasource, Gateway(ProviderConfig("fake", "fake-1", {"responses": texts}))


def _run(orchestrator: Orchestrator, conversation: Conversation, question: str) -> list[Event]:
    return list(orchestrator.run(conversation, question))


@pytest.mark.parametrize("reply", ["Este mes", "este mes por favor", "Mes pasado", "el mes pasado"])
def test_cuanto_vendi_pregunta_y_la_respuesta_retoma_el_plan(
    session: Session,
    model: SemanticModel,
    demo_url: str,
    query_executor: QueryExecutor,
    reply: str,
) -> None:
    plan = {"intent": "metric", "reasoning": "Falta el período.", "metric": "ventas_netas"}
    datasource, gateway = _setup(session, [plan, "Listo."])
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

    first = _run(orchestrator, conversation, "¿Cuánto vendí?")
    asked = [e.payload() for e in first if e.type == "clarification"][0]
    assert asked["slot"] == "period" and asked["options"] == PERIOD_OPTIONS

    second = _run(orchestrator, conversation, reply)
    types = [e.type for e in second]
    assert "clarification" not in types and "error" not in types
    assert "sql" in types and "result" in types and "answer" in types
    # Retomó el plan pendiente: la IA solo se usó para entender el primer turno y redactar.
    assert gateway._fake is not None and gateway._fake.calls == 2
    sql = [e.payload() for e in second if e.type == "sql"][0]
    month_start = "2026-11-01" if "este" in reply.lower() else "2026-10-01"
    assert sql["period"]["start"] == month_start
    messages = session.scalars(select(Message)).all()
    assert len(messages) == 4


def test_respuesta_ininteligible_vuelve_a_entender_con_el_plan_pendiente(
    session: Session, model: SemanticModel, demo_url: str, query_executor: QueryExecutor
) -> None:
    plan = {"intent": "metric", "metric": "ventas_netas"}
    resolved = {"intent": "metric", "metric": "ventas_netas", "period_text": "este año"}
    datasource, gateway = _setup(session, [plan, resolved, "Listo."])
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

    _run(orchestrator, conversation, "¿Cuánto vendí?")
    second = _run(orchestrator, conversation, "lo que va del ciclo")

    assert "result" in [e.type for e in second]
    assert gateway._fake is not None and gateway._fake.calls == 3
