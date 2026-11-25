from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from alembic import command
from app.db.models import (
    Base,
    Conversation,
    Datasource,
    Message,
    SemanticModelVersion,
    User,
)
from app.db.session import get_session, make_engine

BACKEND = Path(__file__).parents[2]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_crea_y_lee_fuente_version_conversacion_y_mensaje(engine: Engine) -> None:
    with Session(engine) as session:
        user = User(email="ana@example.com", password_hash="hash", is_admin=True)
        fuente = Datasource(name="ventas", dialect="sqlite", url_encrypted=b"cifrada")
        session.add_all([user, fuente])
        session.flush()
        session.add(
            SemanticModelVersion(
                datasource_id=fuente.id,
                version=1,
                model={"tables": []},
                created_by=user.id,
            )
        )
        conversacion = Conversation(user_id=user.id, datasource_id=fuente.id, title="Ventas")
        conversacion.messages.append(Message(role="user", content="¿Cuánto vendimos?"))
        session.add(conversacion)
        session.commit()
        conversacion_id = conversacion.id

    with Session(engine) as session:
        leida = session.get(Conversation, conversacion_id)
        assert leida is not None
        assert leida.title == "Ventas"
        assert [m.content for m in leida.messages] == ["¿Cuánto vendimos?"]
        version = session.scalars(select(SemanticModelVersion)).one()
        assert version.version == 1
        assert version.model == {"tables": []}
        assert session.scalars(select(Datasource)).one().execute is False


def test_migraciones_coinciden_con_los_modelos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'migrada.db'}"
    monkeypatch.setenv("CHATIAPP_DATABASE_URL", url)
    config = _alembic_config()

    command.upgrade(config, "head")
    command.check(config)

    eng = make_engine(url)
    try:
        assert set(inspect(eng).get_table_names()) >= set(Base.metadata.tables)
    finally:
        eng.dispose()


def test_get_session_es_dependencia_de_fastapi(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.db.session.get_engine", lambda: engine)
    application = FastAPI()

    @application.get("/usuarios")
    def usuarios(session: Annotated[Session, Depends(get_session)]) -> int:
        return len(session.scalars(select(User)).all())

    assert TestClient(application).get("/usuarios").json() == 0
