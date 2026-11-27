import csv
import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ApiKey, Base, Conversation, Datasource, Message, QueryRun, User
from app.db.session import get_session, make_engine
from app.main import app
from app.security.auth import get_current_user

KEY_ID = uuid.uuid4()


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def admin(factory: sessionmaker[Session]) -> User:
    with factory() as session:
        user = User(email="ana@example.com", password_hash="hash", is_admin=True)
        session.add(user)
        session.commit()
        return user


@pytest.fixture
def client(factory: sessionmaker[Session], admin: User) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_run(
    session: Session,
    datasource: Datasource,
    created_at: datetime,
    *,
    status: str = "ok",
    user_id: uuid.UUID | None = None,
    api_key_id: uuid.UUID | None = None,
    external_user_id: str | None = None,
    question: str = "¿Cuánto vendí?",
) -> QueryRun:
    conversation = Conversation(datasource_id=datasource.id)
    session.add(conversation)
    session.flush()
    message = Message(conversation_id=conversation.id, role="assistant", content="")
    session.add(message)
    session.flush()
    run = QueryRun(
        message_id=message.id,
        origin="catalog",
        status=status,
        created_at=created_at,
        user_id=user_id,
        api_key_id=api_key_id,
        external_user_id=external_user_id,
        datasource_id=datasource.id,
        role="gerencia_general",
        question=question,
        plan={"intent": "metric", "metric": "ventas_netas"},
        sql_candidate="SELECT 1",
        sql_final="SELECT 1 LIMIT 10",
        filters_applied={"role": []},
        row_count=3,
        semantic_version=2,
        provider_kind="fake",
        model="fake-1",
        tokens_in=10,
        tokens_out=5,
        cost_usd=Decimal("0.001"),
        elapsed_ms=12,
    )
    session.add(run)
    session.commit()
    return run


@pytest.fixture
def seeded(factory: sessionmaker[Session], admin: User) -> Datasource:
    with factory() as session:
        datasource = Datasource(name="ventas", dialect="sqlite", url_encrypted=b"x")
        key = ApiKey(id=KEY_ID, name="CRM", prefix="chia_abc", secret_hash="0" * 64)
        session.add_all([datasource, key])
        session.commit()
        _add_run(session, datasource, datetime(2026, 11, 1, 10, tzinfo=UTC), user_id=admin.id)
        _add_run(
            session,
            datasource,
            datetime(2026, 11, 10, 10, tzinfo=UTC),
            status="rejected",
            api_key_id=KEY_ID,
            external_user_id="cliente-9",
        )
        _add_run(
            session,
            datasource,
            datetime(2026, 11, 20, 23, 30, tzinfo=UTC),
            status="error",
            question='=HYPERLINK("http://x")',
        )
        return datasource


def test_lista_paginada_con_todos_los_campos(client: TestClient, seeded: Datasource) -> None:
    response = client.get("/api/v1/audit", params={"page_size": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3 and body["page"] == 1 and body["page_size"] == 2
    assert [i["status"] for i in body["items"]] == ["error", "rejected"]  # la más reciente primero
    item = body["items"][1]
    assert item["datasource"] == "ventas" and item["api_key_name"] == "CRM"
    assert item["external_user_id"] == "cliente-9" and item["semantic_version"] == 2
    assert item["sql_candidate"] == "SELECT 1" and item["row_count"] == 3
    assert item["model"] == "fake-1" and item["role"] == "gerencia_general"
    second = client.get("/api/v1/audit", params={"page_size": 2, "page": 2}).json()
    assert [i["status"] for i in second["items"]] == ["ok"]
    assert second["items"][0]["user_email"] == "ana@example.com"


def test_filtros_por_usuario_estado_key_y_fechas(
    client: TestClient, seeded: Datasource, admin: User
) -> None:
    def ids(**params: str) -> list[str]:
        items = client.get("/api/v1/audit", params=params).json()["items"]
        return [i["status"] for i in items]

    assert ids(user_id=str(admin.id)) == ["ok"]
    assert ids(status="rejected") == ["rejected"]
    assert ids(api_key_id=str(KEY_ID)) == ["rejected"]
    assert ids(external_user_id="cliente-9") == ["rejected"]
    assert ids(datasource_id=str(seeded.id)) == ["error", "rejected", "ok"]
    assert ids(date_from="2026-11-05", date_to="2026-11-20") == ["error", "rejected"]
    assert ids(date_to="2026-11-01") == ["ok"]
    assert ids(date_from="2026-12-01") == []


def test_estado_invalido_es_422(client: TestClient) -> None:
    assert client.get("/api/v1/audit", params={"status": "raro"}).status_code == 422


def test_exporta_csv_filtrado_y_neutraliza_formulas(client: TestClient, seeded: Datasource) -> None:
    response = client.get("/api/v1/audit/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text.removeprefix("﻿"))))
    assert len(rows) == 3
    assert rows[0]["question"].startswith("'=")  # no se ejecuta como fórmula en Excel
    assert rows[1]["api_key_name"] == "CRM" and rows[1]["external_user_id"] == "cliente-9"
    only = client.get("/api/v1/audit/export", params={"status": "ok"}).text
    assert len(list(csv.DictReader(io.StringIO(only.removeprefix("﻿"))))) == 1


def test_solo_administradores(client: TestClient) -> None:
    app.dependency_overrides[get_current_user] = lambda: User(email="u@b.co", is_admin=False)

    assert client.get("/api/v1/audit").status_code == 403
    assert client.get("/api/v1/audit/export").status_code == 403


def test_la_auditoria_no_tiene_columnas_de_filas_ni_de_secretos(
    factory: sessionmaker[Session],
) -> None:
    with factory() as session:
        columns = {c["name"] for c in inspect(session.get_bind()).get_columns("query_run")}

    assert not {"rows", "result", "secret", "api_key_secret", "secret_hash", "token"} & columns
    assert {"row_count", "api_key_id", "external_user_id", "semantic_version"} <= columns
