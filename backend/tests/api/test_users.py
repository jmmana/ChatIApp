import importlib
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.agent.orchestrator import Orchestrator
from app.api.datasources import get_request_cipher
from app.db.models import Base, Conversation, Datasource, Grant, SemanticModelVersion, User
from app.db.session import get_session, make_engine
from app.demo.seed import generar
from app.engine.executor import QueryExecutor
from app.engine.guard import GuardCache, guards
from app.llm.gateway import Gateway, ProviderConfig
from app.main import app
from app.security.auth import get_current_user
from app.security.crypto import make_cipher
from app.security.grants import GrantError, ViewAs
from app.semantic.schema import parse_semantic_model

ROOT = Path(__file__).parents[3]
EXAMPLE = ROOT / "examples" / "ventas" / "semantic-model.yaml"
CIPHER = make_cipher("clave-de-prueba")
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def admin(factory: sessionmaker[Session]) -> User:
    user = User(id=uuid.uuid4(), email="admin@b.co", password_hash="x", is_admin=True)
    with factory() as session:
        session.add(user)
        session.commit()
    return user


@pytest.fixture
def client(factory: sessionmaker[Session], admin: User) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    guards.clear()
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_request_cipher] = lambda: CIPHER
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def datasource_id(factory: sessionmaker[Session]) -> uuid.UUID:
    yaml = importlib.import_module("yaml")
    with factory() as session:
        datasource = Datasource(
            name="Ventas", dialect="sqlite", url_encrypted=b"no-se-usa", execute=True
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
        return datasource.id


def _create(client: TestClient, email: str = "ana@b.co", **extra: Any) -> dict[str, Any]:
    response = client.post(
        "/api/v1/users", json={"email": email, "password": "contraseña-larga", **extra}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _grant(datasource_id: uuid.UUID, role: str, attributes: dict[str, Any]) -> dict[str, Any]:
    entry = {"datasource_id": str(datasource_id), "role": role, "attributes": attributes}
    return {"grants": [entry]}


def test_crud_de_usuarios(client: TestClient) -> None:
    created = _create(client, "  Ana@B.co ")
    assert created["email"] == "ana@b.co"
    assert created["is_admin"] is False and created["grants"] == []
    assert "password" not in json.dumps(created)

    listed = client.get("/api/v1/users").json()
    assert {u["email"] for u in listed} == {"admin@b.co", "ana@b.co"}

    changed = client.patch(f"/api/v1/users/{created['id']}", json={"email": "ana2@b.co"})
    assert changed.status_code == 200 and changed.json()["email"] == "ana2@b.co"
    assert client.get(f"/api/v1/users/{created['id']}").json()["email"] == "ana2@b.co"

    assert client.delete(f"/api/v1/users/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/users/{created['id']}").status_code == 404


def test_correo_repetido_o_invalido(client: TestClient) -> None:
    _create(client)
    clave = "contraseña-larga"
    repetido = client.post("/api/v1/users", json={"email": "ANA@b.co", "password": clave})
    assert repetido.status_code == 409
    invalido = client.post("/api/v1/users", json={"email": "sin-arroba", "password": clave})
    assert invalido.status_code == 422
    corta = client.post("/api/v1/users", json={"email": "x@b.co", "password": "corta"})
    assert corta.status_code == 422


def test_no_se_elimina_a_si_mismo_ni_al_ultimo_administrador(
    client: TestClient, admin: User
) -> None:
    assert client.delete(f"/api/v1/users/{admin.id}").status_code == 409
    quitar = client.patch(f"/api/v1/users/{admin.id}", json={"is_admin": False})
    assert quitar.status_code == 409
    otro = _create(client, "otro@b.co", is_admin=True)
    assert client.patch(f"/api/v1/users/{otro['id']}", json={"is_admin": False}).status_code == 200


def test_usuario_no_administrador_no_administra_usuarios(client: TestClient) -> None:
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@b.co", is_admin=False
    )
    assert client.get("/api/v1/users").status_code == 403


def test_put_grants_guarda_rol_y_atributos(client: TestClient, datasource_id: uuid.UUID) -> None:
    user = _create(client)
    response = client.put(
        f"/api/v1/users/{user['id']}/grants",
        json=_grant(datasource_id, "gerente_sucursal", {"sucursales": [1, 2]}),
    )
    assert response.status_code == 200, response.text
    assert response.json()["grants"] == [
        {
            "datasource_id": str(datasource_id),
            "role": "gerente_sucursal",
            "attributes": {"sucursales": [1, 2]},
        }
    ]
    # Reemplaza: un PUT vacío quita los permisos.
    vacio = client.put(f"/api/v1/users/{user['id']}/grants", json={"grants": []})
    assert vacio.json()["grants"] == []


def test_put_grants_rechaza_rol_inexistente_y_atributos_faltantes(
    client: TestClient, datasource_id: uuid.UUID
) -> None:
    user = _create(client)
    url = f"/api/v1/users/{user['id']}/grants"
    rol = client.put(url, json=_grant(datasource_id, "inventado", {}))
    assert rol.status_code == 422 and rol.json()["error"]["code"] == "unknown_role"
    falta = client.put(url, json=_grant(datasource_id, "gerente_sucursal", {}))
    assert falta.status_code == 422 and falta.json()["error"]["code"] == "missing_attributes"
    vacia = client.put(url, json=_grant(datasource_id, "gerente_sucursal", {"sucursales": []}))
    assert vacia.status_code == 422
    # Un rol sin filtros no exige atributos.
    assert client.put(url, json=_grant(datasource_id, "gerencia_general", {})).status_code == 200


def test_put_grants_fuente_inexistente(client: TestClient) -> None:
    user = _create(client)
    response = client.put(
        f"/api/v1/users/{user['id']}/grants", json=_grant(uuid.uuid4(), "gerencia_general", {})
    )
    assert response.status_code == 404


def test_sin_grant_no_se_puede_consultar_la_fuente(
    client: TestClient, factory: sessionmaker[Session], datasource_id: uuid.UUID
) -> None:
    user = _create(client)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.UUID(user["id"]), email="ana@b.co", is_admin=False
    )
    response = client.post(
        f"/api/v1/datasources/{datasource_id}/preview",
        json={"metric": "ventas_netas", "period": "este mes"},
    )
    assert response.status_code == 403

    with factory() as session:
        datasource = session.get(Datasource, datasource_id)
        row = session.scalars(select(SemanticModelVersion)).one()
        assert datasource is not None
        with pytest.raises(GrantError) as caught:
            Orchestrator.for_user(
                session,
                Gateway(ProviderConfig("fake", "fake-1", {})),
                datasource,
                parse_semantic_model(row.model),
                1,
                "sqlite:///x.db",
                User(id=uuid.UUID(user["id"]), email="ana@b.co", is_admin=False),
            )
        assert caught.value.status_code == 403


def test_gerente_con_sucursales_1_y_2_solo_ve_esas_sucursales(
    client: TestClient,
    factory: sessionmaker[Session],
    datasource_id: uuid.UUID,
    tmp_path: Path,
) -> None:
    generar(tmp_path / "ventas.db", seed=42, hasta=date(2026, 11, 25))
    url = f"sqlite:///{tmp_path / 'ventas.db'}"
    executor = QueryExecutor()
    gerente = _create(client, "gerente@b.co")
    put = client.put(
        f"/api/v1/users/{gerente['id']}/grants",
        json=_grant(datasource_id, "gerente_sucursal", {"sucursales": [1, 2]}),
    )
    assert put.status_code == 200, put.text
    plan = json.dumps(
        {
            "intent": "metric",
            "reasoning": "Ventas por sucursal.",
            "metric": "ventas_netas",
            "dimensions": ["sucursales.nombre"],
            "period_text": "este año",
        }
    )

    def ask(user: User, view_as: ViewAs | None = None) -> list[list[Any]]:
        with factory() as session:
            datasource = session.get(Datasource, datasource_id)
            row = session.scalars(select(SemanticModelVersion)).one()
            assert datasource is not None
            conversation = Conversation(datasource_id=datasource_id)
            session.add(conversation)
            session.commit()
            orchestrator = Orchestrator.for_user(
                session,
                Gateway(ProviderConfig("fake", "fake-1", {"responses": [plan]})),
                datasource,
                parse_semantic_model(row.model),
                1,
                url,
                user,
                view_as=view_as,
                query_executor=executor,
                guard_cache=GuardCache(),
                now=NOW,
            )
            events = list(orchestrator.run(conversation, "ventas por sucursal"))
            assert "error" not in [e.type for e in events], events
            results = [e.payload() for e in events if e.type == "result"]
            rows: list[list[Any]] = results[0]["rows"]
            return rows

    try:
        with factory() as session:
            persisted = session.get(User, uuid.UUID(gerente["id"]))
            assert persisted is not None
            assert session.scalars(select(Grant)).one().attributes == {"sucursales": [1, 2]}
            admin_user = session.scalars(select(User).where(User.is_admin.is_(True))).one()
        assert len(ask(persisted)) == 2

        # Un administrador sí puede ver como otro rol; el gerente no puede usar view_as.
        todas = ask(admin_user, ViewAs("gerencia_general", {}))
        assert len(todas) > 2
        with pytest.raises(GrantError) as caught:
            ask(persisted, ViewAs("gerencia_general", {}))
        assert caught.value.code == "view_as_forbidden"
    finally:
        executor.dispose()
