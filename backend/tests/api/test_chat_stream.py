import asyncio
import importlib
import json
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.agent.events import Event, Step, TurnStarted
from app.agent.orchestrator import Orchestrator
from app.api import chat
from app.api.datasources import get_request_cipher
from app.db.models import Base, Datasource, Message, Provider, SemanticModelVersion, User
from app.db.session import get_session, make_engine
from app.demo.seed import generar
from app.engine.guard import guards
from app.integrations.embed_sessions import Caller, get_caller
from app.main import app
from app.security.auth import get_current_user
from app.security.crypto import encrypt, make_cipher

ROOT = Path(__file__).parents[3]
EXAMPLE = ROOT / "examples" / "ventas" / "semantic-model.yaml"
CIPHER = make_cipher("clave-de-prueba")
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)
GENERAL = {"role": "gerencia_general"}

SIN_PERIODO = {"intent": "metric", "reasoning": "Falta el período.", "metric": "ventas_netas"}
ESTE_MES = {**SIN_PERIODO, "reasoning": "Ventas de este mes.", "period_text": "este mes"}


class Sse:
    """Respuesta `text/event-stream` ya leída: eventos y comentarios."""

    def __init__(self, text: str) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.comments: list[str] = []
        for block in text.split("\n\n"):
            if block.startswith(":"):
                self.comments.append(block)
            elif block.strip():
                name, data = block.split("\n", 1)
                payload = json.loads(data.removeprefix("data: "))
                self.events.append((name.removeprefix("event: "), payload))

    @property
    def types(self) -> list[str]:
        return [name for name, _ in self.events]

    def first(self, kind: str) -> dict[str, Any]:
        return next(data for name, data in self.events if name == kind)


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def user_id(factory: sessionmaker[Session]) -> uuid.UUID:
    with factory() as session:
        user = User(email="a@b.co", password_hash="x", is_admin=True)
        session.add(user)
        session.commit()
        return user.id


@pytest.fixture
def client(factory: sessionmaker[Session], user_id: uuid.UUID) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    guards.clear()
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_request_cipher] = lambda: CIPHER
    usuario = User(id=user_id, email="a@b.co", is_admin=True)
    app.dependency_overrides[get_current_user] = lambda: usuario
    app.dependency_overrides[get_caller] = lambda: Caller(user=usuario)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def datasource_id(factory: sessionmaker[Session], tmp_path: Path) -> str:
    path = tmp_path / "ventas.db"
    generar(path, seed=42, hasta=date(2026, 11, 25))
    yaml = importlib.import_module("yaml")
    with factory() as session:
        datasource = Datasource(
            name="Ventas",
            dialect="sqlite",
            url_encrypted=encrypt(f"sqlite:///{path}", CIPHER),
            execute=True,
            privacy="aggregates",
        )
        session.add(datasource)
        session.flush()
        session.add(
            SemanticModelVersion(
                datasource_id=datasource.id,
                version=1,
                model=yaml.safe_load(EXAMPLE.read_text()),
            )
        )
        session.commit()
        return str(datasource.id)


def _provider(factory: sessionmaker[Session], name: str, *responses: Any, default: bool) -> str:
    texts = [r if isinstance(r, str) else json.dumps(r) for r in responses]
    with factory() as session:
        provider = Provider(
            name=name,
            kind="fake",
            model="fake-1",
            config={"responses": texts},
            is_default=default,
        )
        session.add(provider)
        session.commit()
        return str(provider.id)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Orchestrator, "now", lambda self: NOW)


def _chat(client: TestClient, datasource_id: str, message: str, **extra: Any) -> Any:
    body = {"datasource_id": datasource_id, "message": message, "view_as": GENERAL, **extra}
    return client.post("/api/v1/chat/stream", json=body)


def test_cuanto_vendi_y_luego_este_mes_con_el_stream_completo(
    client: TestClient, factory: sessionmaker[Session], datasource_id: str
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)
    este_mes = _provider(factory, "responde", ESTE_MES, default=False)

    started = time.perf_counter()
    first = _chat(client, datasource_id, "¿Cuánto vendí?")
    elapsed = time.perf_counter() - started

    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert first.headers["cache-control"] == "no-cache"
    assert first.headers["x-accel-buffering"] == "no"
    turno1 = Sse(first.text)
    assert turno1.types[0] == "turn.started" and turno1.types[-1] == "turn.completed"
    assert "clarification" in turno1.types and "sql" not in turno1.types
    assert turno1.first("clarification")["slot"] == "period"
    assert elapsed < 0.5  # el turno entero, y por tanto el primer evento, con proveedor simulado
    conversation_id = turno1.first("turn.started")["conversation_id"]

    second = _chat(
        client,
        datasource_id,
        "Este mes",
        conversation_id=conversation_id,
        provider_override=este_mes,
    )

    turno2 = Sse(second.text)
    assert turno2.types[0] == "turn.started" and turno2.types[-1] == "turn.completed"
    assert turno2.first("turn.started")["conversation_id"] == conversation_id
    for kind in ("step", "reasoning", "sql", "result", "answer"):
        assert kind in turno2.types
    assert turno2.types.index("sql") < turno2.types.index("result") < turno2.types.index("answer")
    assert "error" not in turno2.types

    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 2
    assistant = detail["messages"][3]
    assert [e["type"] for e in assistant["events"]][0] == "turn.started"
    assert "result" in [e["type"] for e in assistant["events"]]


def test_el_primer_evento_llega_en_menos_de_500_ms_aunque_el_turno_siga(
    client: TestClient,
    factory: sessionmaker[Session],
    datasource_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)

    def lento(self: Orchestrator, conversation: Any, question: str) -> Iterator[Event]:
        yield Event(TurnStarted(turn_id=str(uuid.uuid4()), conversation_id=str(conversation.id)))
        time.sleep(1.0)  # el resto del turno tarda: solo se mide hasta el primer evento
        yield Event(Step(id="understand", label="Entendiendo", status="done"))

    monkeypatch.setattr(Orchestrator, "run", lento)
    body = json.dumps(
        {"datasource_id": datasource_id, "message": "hola", "view_as": GENERAL}
    ).encode()

    # `TestClient` acumula la respuesta entera: se llama a la app ASGI y se cronometra el primer
    # fragmento del cuerpo, que es lo que vería un cliente en streaming.
    async def primer_fragmento() -> tuple[float, bytes]:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/chat/stream",
            "raw_path": b"/api/v1/chat/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        sent = False
        arrived: asyncio.Future[tuple[float, bytes]] = asyncio.get_running_loop().create_future()
        started = time.perf_counter()

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(3600)  # sin desconexión mientras dura el turno
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                if not arrived.done():
                    arrived.set_result((time.perf_counter() - started, message["body"]))

        task = asyncio.create_task(app(scope, receive, send))
        try:
            return await asyncio.wait_for(arrived, timeout=5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    elapsed, first = asyncio.run(primer_fragmento())

    assert first.decode().startswith("event: turn.started")
    assert elapsed < 0.5


def test_fuente_inexistente_responde_404_sin_abrir_el_stream(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)

    response = _chat(client, str(uuid.uuid4()), "hola")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "datasource_not_found"


def test_sin_proveedor_responde_422(client: TestClient, datasource_id: str) -> None:
    response = _chat(client, datasource_id, "hola")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_provider"


def test_manda_un_comentario_keep_alive_mientras_espera(
    client: TestClient,
    factory: sessionmaker[Session],
    datasource_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)

    def lento(self: Orchestrator, conversation: Any, question: str) -> Iterator[Event]:
        yield Event(TurnStarted(turn_id=str(uuid.uuid4()), conversation_id=str(conversation.id)))
        time.sleep(0.25)
        yield Event(Step(id="understand", label="Entendiendo", status="done"))

    monkeypatch.setattr(chat, "KEEPALIVE_SECONDS", 0.05)
    monkeypatch.setattr(Orchestrator, "run", lento)

    sse = Sse(_chat(client, datasource_id, "hola").text)

    assert sse.comments and sse.comments[0] == ": keep-alive"
    assert sse.types == ["turn.started", "step"]


def test_cancelar_detiene_el_turno_y_emite_error_cancelled(
    client: TestClient,
    factory: sessionmaker[Session],
    datasource_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)
    turn_id = str(uuid.uuid4())

    def lento(self: Orchestrator, conversation: Any, question: str) -> Iterator[Event]:
        yield Event(TurnStarted(turn_id=turn_id, conversation_id=str(conversation.id)))
        for _ in range(100):
            time.sleep(0.05)
            yield Event(Step(id="understand", label="Entendiendo", status="running"))

    monkeypatch.setattr(Orchestrator, "run", lento)
    status: dict[str, int] = {}

    def cancelar() -> None:
        other = TestClient(app)
        for _ in range(100):
            response = other.post(f"/api/v1/chat/{turn_id}/cancel")
            if response.status_code == 200:
                status["code"] = 200
                return
            time.sleep(0.02)

    thread = threading.Thread(target=cancelar)
    thread.start()
    started = time.perf_counter()
    sse = Sse(_chat(client, datasource_id, "hola").text)
    thread.join()

    assert status == {"code": 200}
    assert time.perf_counter() - started < 3  # sin cancelar tardaría más de 5 s
    assert sse.types[-1] == "error" and sse.events[-1][1]["code"] == "cancelled"
    assert "turn.completed" not in sse.types
    assert client.post(f"/api/v1/chat/{turn_id}/cancel").status_code == 404


def test_cancelar_un_turno_inexistente_responde_404(client: TestClient) -> None:
    response = client.post(f"/api/v1/chat/{uuid.uuid4()}/cancel")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "turn_not_found"


def test_el_mensaje_guardado_queda_con_sus_eventos(
    client: TestClient, factory: sessionmaker[Session], datasource_id: str
) -> None:
    _provider(factory, "aclara", SIN_PERIODO, default=True)

    sse = Sse(_chat(client, datasource_id, "¿Cuánto vendí?").text)

    with factory() as session:
        message = session.get(Message, uuid.UUID(sse.first("turn.started")["turn_id"]))
        assert message is not None and message.events is not None
        assert [e["type"] for e in message.events] == sse.types
