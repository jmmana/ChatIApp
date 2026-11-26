import importlib
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.events import Event, Step
from app.agent.free_sql import RepairError, repair_sql, strip_sql
from app.agent.orchestrator import Orchestrator
from app.db.models import Base, Conversation, Datasource, QueryRun
from app.db.session import make_engine
from app.demo.seed import generar
from app.engine.executor import QueryExecutor
from app.engine.guard import GuardCache
from app.llm.gateway import Gateway, ProviderConfig
from app.semantic.schema import SemanticModel, parse_semantic_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)
GENERAL = "gerencia_general"


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


def _gateway(*responses: dict[str, Any] | str) -> Gateway:
    texts = [r if isinstance(r, str) else json.dumps(r) for r in responses]
    return Gateway(ProviderConfig("fake", "fake-1", {"responses": texts}))


def _turn(
    session: Session,
    model: SemanticModel,
    gateway: Gateway,
    url: str,
    query_executor: QueryExecutor,
    question: str,
) -> list[Event]:
    datasource = Datasource(
        name="demo", dialect="sqlite", url_encrypted=b"no-se-usa", execute=True, privacy="schema"
    )
    session.add(datasource)
    session.commit()
    conversation = Conversation(datasource_id=datasource.id)
    session.add(conversation)
    session.commit()
    orchestrator = Orchestrator(
        session,
        gateway,
        datasource,
        model,
        1,
        url,
        role=GENERAL,
        query_executor=query_executor,
        guard_cache=GuardCache(),
        now=NOW,
    )
    return list(orchestrator.run(conversation, question))


def _of(events: list[Event], kind: str) -> list[dict[str, Any]]:
    return [e.payload() for e in events if e.type == kind]


def _steps(events: list[Event]) -> list[tuple[str, str]]:
    return [(e.data.id, e.data.status) for e in events if isinstance(e.data, Step)]


def test_sql_valido_se_ejecuta_sin_reparar_y_marca_origen_llm(
    session: Session, model: SemanticModel, demo_url: str, query_executor: QueryExecutor
) -> None:
    plan = {
        "intent": "sql",
        "sql": "SELECT canal, COUNT(*) AS n FROM facturas GROUP BY canal",
    }
    gateway = _gateway(plan, "Hay facturas en varios canales.")

    events = _turn(session, model, gateway, demo_url, query_executor, "¿Facturas por canal?")

    assert not _of(events, "error")
    assert _of(events, "sql")[0]["origin"] == "llm"
    assert _of(events, "result")[0]["columns"] == ["canal", "n"]
    assert all(step_id != "repair" for step_id, _ in _steps(events))
    assert session.scalars(select(QueryRun)).one().origin == "llm"


def test_sql_de_escritura_se_rechaza_aunque_el_reintento_insista(
    session: Session, model: SemanticModel, demo_url: str, query_executor: QueryExecutor
) -> None:
    gateway = _gateway(
        {"intent": "sql", "sql": "UPDATE facturas SET total = 0"},
        "UPDATE facturas SET total = 0",
    )

    events = _turn(session, model, gateway, demo_url, query_executor, "Pon los totales en cero")

    error = _of(events, "error")[0]
    assert error["code"] == "sql_rejected" and error["message"]
    assert not _of(events, "sql") and not _of(events, "result")
    assert _steps(events).count(("repair", "running")) == 1
    assert session.scalars(select(QueryRun)).one().status == "rejected"


def test_columna_inexistente_se_repara_con_un_reintento(
    session: Session, model: SemanticModel, demo_url: str, query_executor: QueryExecutor
) -> None:
    gateway = _gateway(
        {"intent": "sql", "sql": "SELECT SUM(monto_total) AS t FROM facturas"},
        "```sql\nSELECT SUM(total) AS t FROM facturas\n```",
        "El total facturado es la suma de las facturas.",
    )

    events = _turn(session, model, gateway, demo_url, query_executor, "¿Cuánto he facturado?")

    assert not _of(events, "error")
    assert ("repair", "done") in _steps(events)
    sql = _of(events, "sql")[0]
    assert sql["origin"] == "llm" and "SUM(total)" in sql["sql"]
    assert _of(events, "result")[0]["columns"] == ["t"]


def test_repair_sql_envia_el_error_exacto_y_el_dialecto(model: SemanticModel) -> None:
    seen: list[list[dict[str, str]]] = []

    class Spy(Gateway):
        def complete(self, messages: list[dict[str, str]], **params: Any) -> Any:
            seen.append(messages)
            return super().complete(messages, **params)

    gateway = Spy(ProviderConfig("fake", "fake-1", {"responses": ["SELECT 1"]}))

    fixed, usage = repair_sql(
        gateway, model, "pregunta", "SELECT x", "Columna «x» no permitida", dialect="sqlite"
    )

    assert fixed == "SELECT 1" and usage.output_tokens > 0
    assert "Error exacto: Columna «x» no permitida" in seen[0][1]["content"]
    assert "sqlite" in seen[0][0]["content"]


def test_repair_sql_sin_texto_falla(model: SemanticModel) -> None:
    gateway = _gateway("```sql\n```")

    with pytest.raises(RepairError) as info:
        repair_sql(gateway, model, "pregunta", "SELECT x", "error", dialect="sqlite")

    assert info.value.kind == "invalid_plan"


def test_strip_sql_quita_bloques_de_codigo() -> None:
    assert strip_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert strip_sql("  SELECT 1  ") == "SELECT 1"
