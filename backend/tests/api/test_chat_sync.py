import threading
import time
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.agent.events import ErrorData, Event, Step, TurnStarted
from app.agent.orchestrator import Orchestrator
from app.api import chat
from app.integrations.api_keys import Principal, get_principal
from app.main import app
from app.security.auth import get_current_user

from .test_chat_stream import (  # noqa: F401 (fixtures de pytest)
    ESTE_MES,
    GENERAL,
    SIN_PERIODO,
    _provider,
    client,
    datasource_id,
    factory,
    fixed_now,
    user_id,
)


@pytest.fixture(autouse=True)
def _principal(client: TestClient) -> Iterator[None]:  # noqa: F811
    """`POST /chat` pide un `Principal`: el usuario administrador que ya fija el fixture."""
    usuario = app.dependency_overrides[get_current_user]()
    app.dependency_overrides[get_principal] = lambda: Principal(
        "user", frozenset({"chat"}), user=usuario
    )
    yield


def _post(http: TestClient, ds_id: str, message: str, **extra: Any) -> Any:
    body = {"datasource_id": ds_id, "message": message, "view_as": GENERAL, **extra}
    return http.post("/api/v1/chat", json=body)


def test_cuanto_vendi_y_luego_este_mes(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)
    este_mes = _provider(factory, "responde", ESTE_MES, default=False)

    first = _post(client, datasource_id, "¿Cuánto vendí?")

    assert first.status_code == 200
    turno1 = first.json()
    assert turno1["status"] == "needs_clarification"
    assert turno1["clarification"]["slot"] == "period"
    assert turno1["clarification"]["options"]
    assert turno1["reasoning"]
    assert "sql" not in turno1
    conversation_id = turno1["conversation_id"]

    second = _post(
        client,
        datasource_id,
        "Este mes",
        conversation_id=conversation_id,
        provider_override=este_mes,
    )

    turno2 = second.json()
    assert turno2["status"] == "answered"
    assert turno2["conversation_id"] == conversation_id
    assert turno2["sql"]["sql"].upper().startswith("SELECT")
    assert {"dialect", "origin", "filters_applied"} <= set(turno2["sql"])
    assert set(turno2["period"]) == {"label", "start", "end_exclusive"}
    assert {"columns", "rows", "truncated"} <= set(turno2["result"])
    assert turno2["answer"]
    assert set(turno2["usage"]) == {"tokens_in", "tokens_out", "cost_usd"}


def test_la_fuente_inexistente_responde_404(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)

    response = _post(client, str(uuid.uuid4()), "hola")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "datasource_not_found"


def test_un_rechazo_del_guardian_se_informa_con_status_rejected(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)

    def run(self: Orchestrator, conversation: Any, message: str) -> Iterator[Event]:
        yield Event(ErrorData(code="sql_rejected", message="Solo lectura.", recoverable=False))

    monkeypatch.setattr(Orchestrator, "run", run)

    body = _post(client, datasource_id, "borra todo").json()

    assert body["status"] == "rejected"
    assert body["error"]["code"] == "sql_rejected"


def test_pasado_el_tiempo_maximo_responde_504_y_cancela_el_turno(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)
    monkeypatch.setattr(chat, "get_settings", lambda: SimpleNamespace(chat_timeout_seconds=0.2))
    stopped = threading.Event()

    def run(self: Orchestrator, conversation: Any, message: str) -> Iterator[Event]:
        try:
            yield Event(TurnStarted(turn_id=str(uuid.uuid4()), conversation_id="c"))
            while True:
                time.sleep(0.05)
                yield Event(Step(id="understand", label="Pensando", status="running"))
        finally:
            stopped.set()

    monkeypatch.setattr(Orchestrator, "run", run)

    response = _post(client, datasource_id, "¿Cuánto vendí?")

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "turn_timeout"
    assert stopped.wait(2), "el hilo del turno debe cortarse"
