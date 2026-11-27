import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.agent.orchestrator import Orchestrator
from app.api.datasources import get_request_cipher
from app.db.models import Base, Datasource, Provider, SemanticModelVersion, User
from app.db.session import get_session, make_engine
from app.demo.bootstrap import DEMO_NAME, bootstrap_demo
from app.demo.seed import generar
from app.engine.guard import guards
from app.integrations.embed_sessions import Caller, get_caller
from app.main import app
from app.security.auth import get_current_user
from app.security.crypto import make_cipher

CIPHER = make_cipher("clave-de-prueba")
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)
ESTE_MES = {
    "intent": "metric",
    "reasoning": "Ventas de este mes.",
    "metric": "ventas_netas",
    "period_text": "este mes",
}


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def demo_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("CHATIAPP_DEMO", raising=False)
    path = tmp_path / "data" / "demo" / "ventas.db"
    path.parent.mkdir(parents=True)
    generar(path, seed=42, hasta=date(2026, 11, 25))
    return path


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    guards.clear()
    usuario = User(id=uuid.uuid4(), email="a@b.co", password_hash="no-se-usa", is_admin=True)
    with factory() as session:  # la conversación referencia al usuario con llave foránea
        session.add(usuario)
        session.commit()
        session.refresh(usuario)
        session.expunge(usuario)
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_request_cipher] = lambda: CIPHER
    app.dependency_overrides[get_current_user] = lambda: usuario
    app.dependency_overrides[get_caller] = lambda: Caller(user=usuario)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _arrancar(factory: sessionmaker[Session], demo_db: Path) -> bool:
    with factory() as session:
        return bootstrap_demo(session, CIPHER, demo_db)


def _conteos(factory: sessionmaker[Session]) -> tuple[int, int]:
    with factory() as session:
        fuentes = session.scalar(select(func.count()).select_from(Datasource))
        versiones = session.scalar(select(func.count()).select_from(SemanticModelVersion))
        return fuentes or 0, versiones or 0


def test_crea_la_fuente_con_el_modelo_version_1(
    client: TestClient, factory: sessionmaker[Session], demo_db: Path
) -> None:
    assert _arrancar(factory, demo_db) is True

    fuentes = client.get("/api/v1/datasources").json()
    assert [f["name"] for f in fuentes] == [DEMO_NAME]
    fuente = fuentes[0]
    assert fuente["dialect"] == "sqlite"
    assert fuente["execute"] is True
    assert fuente["privacy"] == "aggregates"
    assert (fuente["max_rows"], fuente["timeout_seconds"]) == (1000, 30)
    actual = client.get(f"/api/v1/datasources/{fuente['id']}/semantic").json()
    assert actual["version"] == 1


def test_correrlo_dos_veces_no_duplica_nada(factory: sessionmaker[Session], demo_db: Path) -> None:
    assert _arrancar(factory, demo_db) is True
    assert _arrancar(factory, demo_db) is False

    assert _conteos(factory) == (1, 1)


def test_no_hace_nada_si_hay_otras_fuentes(factory: sessionmaker[Session], demo_db: Path) -> None:
    with factory() as session:
        session.add(Datasource(name="Mía", dialect="sqlite", url_encrypted=b"x"))
        session.commit()

    assert _arrancar(factory, demo_db) is False

    assert _conteos(factory) == (1, 0)


@pytest.mark.parametrize("valor", ["0", "false", "OFF"])
def test_con_demo_desactivada_no_crea_nada(
    factory: sessionmaker[Session], demo_db: Path, monkeypatch: pytest.MonkeyPatch, valor: str
) -> None:
    monkeypatch.setenv("CHATIAPP_DEMO", valor)

    assert _arrancar(factory, demo_db) is False

    assert _conteos(factory) == (0, 0)


def test_sin_base_de_demo_no_crea_nada(factory: sessionmaker[Session], tmp_path: Path) -> None:
    assert _arrancar(factory, tmp_path / "no-existe.db") is False

    assert _conteos(factory) == (0, 0)


def test_la_conexion_de_la_fuente_responde_ok(
    client: TestClient, factory: sessionmaker[Session], demo_db: Path
) -> None:
    _arrancar(factory, demo_db)
    fuente_id = client.get("/api/v1/datasources").json()[0]["id"]

    respuesta = client.post(f"/api/v1/datasources/{fuente_id}/test")

    assert respuesta.status_code == 200
    assert respuesta.json()["ok"] is True


def test_pregunta_cuanto_vendi_este_mes_produce_sql_y_resultado(
    client: TestClient,
    factory: sessionmaker[Session],
    demo_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Orchestrator, "now", lambda self: NOW)
    _arrancar(factory, demo_db)
    fuente_id = client.get("/api/v1/datasources").json()[0]["id"]
    with factory() as session:
        session.add(
            Provider(
                name="simulado",
                kind="fake",
                model="fake-1",
                config={"responses": [json.dumps(ESTE_MES)]},
                is_default=True,
            )
        )
        session.commit()

    respuesta = client.post(
        "/api/v1/chat/stream",
        json={
            "datasource_id": fuente_id,
            "message": "¿Cuánto vendí este mes?",
            "view_as": {"role": "gerencia_general"},
        },
    )

    assert respuesta.status_code == 200
    eventos: dict[str, Any] = {}
    for bloque in respuesta.text.split("\n\n"):
        if bloque.startswith("event: "):
            nombre, datos = bloque.split("\n", 1)
            eventos.setdefault(nombre.removeprefix("event: "), json.loads(datos[len("data: ") :]))
    assert "error" not in eventos
    assert "ventas_diarias" in json.dumps(eventos["sql"])
    assert "result" in eventos
