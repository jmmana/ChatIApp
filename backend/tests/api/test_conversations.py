import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, Conversation, Datasource, Message, User
from app.db.session import get_session, make_engine
from app.integrations.embed_sessions import Caller, get_caller
from app.main import app
from app.security.auth import get_current_user


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def ids(factory: sessionmaker[Session]) -> dict[str, uuid.UUID]:
    with factory() as session:
        mine = User(email="yo@b.co", password_hash="x")
        other = User(email="otro@b.co", password_hash="x")
        datasource = Datasource(name="Ventas", dialect="sqlite", url_encrypted=b"x")
        session.add_all([mine, other, datasource])
        session.flush()
        own = Conversation(user_id=mine.id, datasource_id=datasource.id, title="Mía")
        foreign = Conversation(user_id=other.id, datasource_id=datasource.id, title="Ajena")
        session.add_all([own, foreign])
        session.flush()
        session.add(Message(conversation_id=own.id, role="user", content="¿Cuánto vendí?"))
        session.add(
            Message(
                conversation_id=own.id,
                role="assistant",
                content="¿Período?",
                events=[{"type": "turn.started", "data": {}}],
            )
        )
        session.commit()
        return {"mine": mine.id, "own": own.id, "foreign": foreign.id}


@pytest.fixture
def client(factory: sessionmaker[Session], ids: dict[str, uuid.UUID]) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    usuario = User(id=ids["mine"], email="yo@b.co")
    app.dependency_overrides[get_current_user] = lambda: usuario
    app.dependency_overrides[get_caller] = lambda: Caller(user=usuario)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_lista_solo_las_conversaciones_del_usuario(client: TestClient) -> None:
    response = client.get("/api/v1/conversations")

    assert response.status_code == 200
    assert [c["title"] for c in response.json()] == ["Mía"]


def test_detalle_trae_los_mensajes_con_sus_eventos(
    client: TestClient, ids: dict[str, uuid.UUID]
) -> None:
    response = client.get(f"/api/v1/conversations/{ids['own']}")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["events"][0]["type"] == "turn.started"


def test_una_conversacion_ajena_responde_404(client: TestClient, ids: dict[str, uuid.UUID]) -> None:
    url = f"/api/v1/conversations/{ids['foreign']}"

    assert client.get(url).status_code == 404
    assert client.patch(url, json={"title": "x"}).status_code == 404
    assert client.delete(url).status_code == 404


def test_renombrar(client: TestClient, ids: dict[str, uuid.UUID]) -> None:
    response = client.patch(f"/api/v1/conversations/{ids['own']}", json={"title": "Ventas de mayo"})

    assert response.status_code == 200 and response.json()["title"] == "Ventas de mayo"
    vacio = client.patch(f"/api/v1/conversations/{ids['own']}", json={"title": ""})
    assert vacio.status_code == 422


def test_eliminar_borra_la_conversacion_y_sus_mensajes(
    client: TestClient, factory: sessionmaker[Session], ids: dict[str, uuid.UUID]
) -> None:
    response = client.delete(f"/api/v1/conversations/{ids['own']}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/conversations/{ids['own']}").status_code == 404
    with factory() as session:
        assert session.query(Message).count() == 0
