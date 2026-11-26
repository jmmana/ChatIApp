import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.datasources import get_request_cipher
from app.db.models import Base, Datasource, User
from app.db.session import get_session, make_engine
from app.demo.seed import generar
from app.engine.connections import classify_error, mask_url
from app.main import app
from app.security.auth import get_current_user
from app.security.crypto import decrypt, make_cipher

CIPHER = make_cipher("clave-de-prueba")
SECRET_URL = "postgresql+psycopg://admin:s3cr3to@db.interna:5432/ventas"


@pytest.fixture(scope="module")
def demo_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("demo") / "ventas.db"
    generar(path, seed=42, hasta=date(2025, 3, 31))
    return f"sqlite:///{path}"


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_request_cipher] = lambda: CIPHER
    app.dependency_overrides[get_current_user] = lambda: User(email="a@b.co", is_admin=True)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create(client: TestClient, **overrides: object) -> dict[str, object]:
    body = {"name": "Ventas", "dialect": "sqlite", "url": "sqlite:///x.db", **overrides}
    response = client.post("/api/v1/datasources", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()
    return created


def test_crea_con_valores_por_defecto(client: TestClient) -> None:
    created = _create(client)

    assert created["execute"] is False
    assert created["max_rows"] == 1000
    assert created["timeout_seconds"] == 30
    assert created["privacy"] == "schema"
    assert created["managed_by"] == "ui"


def test_url_se_guarda_cifrada_y_se_devuelve_enmascarada(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    created = _create(client, dialect="postgres", url=SECRET_URL)

    assert created["url"] == "postgresql+psycopg://***:***@db.interna:5432/ventas"
    listed = client.get("/api/v1/datasources")
    assert "s3cr3to" not in listed.text
    assert "admin" not in listed.text
    with factory() as session:
        stored = session.scalars(select(Datasource)).one()
        assert b"s3cr3to" not in stored.url_encrypted
        assert decrypt(stored.url_encrypted, CIPHER) == SECRET_URL


def test_lista_ordenada_por_nombre(client: TestClient) -> None:
    _create(client, name="B")
    _create(client, name="A")

    assert [d["name"] for d in client.get("/api/v1/datasources").json()] == ["A", "B"]


def test_nombre_repetido_es_409(client: TestClient) -> None:
    _create(client)

    response = client.post(
        "/api/v1/datasources", json={"name": "Ventas", "dialect": "sqlite", "url": "sqlite://"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "name_taken"


def test_url_invalida_es_422_sin_filtrar_la_url(client: TestClient) -> None:
    response = client.post(
        "/api/v1/datasources",
        json={"name": "X", "dialect": "sqlite", "url": "no-es-una-url:secreto"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_url"
    assert "secreto" not in response.text


def test_dialecto_y_limites_se_validan(client: TestClient) -> None:
    base = {"name": "X", "url": "sqlite://"}

    assert client.post("/api/v1/datasources", json={**base, "dialect": "db2"}).status_code == 422
    bad_rows = {**base, "dialect": "sqlite", "max_rows": 0}
    assert client.post("/api/v1/datasources", json=bad_rows).status_code == 422
    bad_privacy = {**base, "dialect": "sqlite", "privacy": "todo"}
    assert client.post("/api/v1/datasources", json=bad_privacy).status_code == 422


def test_patch_no_cambia_la_url_si_no_se_envia(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    created = _create(client, dialect="postgres", url=SECRET_URL)

    response = client.patch(
        f"/api/v1/datasources/{created['id']}", json={"max_rows": 50, "execute": True}
    )

    assert response.status_code == 200
    assert response.json()["max_rows"] == 50
    assert response.json()["execute"] is True
    with factory() as session:
        stored = session.scalars(select(Datasource)).one()
        assert decrypt(stored.url_encrypted, CIPHER) == SECRET_URL


def test_patch_reemplaza_la_url_si_se_envia(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    created = _create(client)

    response = client.patch(
        f"/api/v1/datasources/{created['id']}", json={"url": "mysql+pymysql://u:p@h/d"}
    )

    assert response.json()["url"] == "mysql+pymysql://***:***@h/d"
    with factory() as session:
        stored = session.scalars(select(Datasource)).one()
        assert decrypt(stored.url_encrypted, CIPHER) == "mysql+pymysql://u:p@h/d"


def test_patch_con_nombre_ocupado_es_409(client: TestClient) -> None:
    _create(client, name="A")
    other = _create(client, name="B")

    response = client.patch(f"/api/v1/datasources/{other['id']}", json={"name": "A"})

    assert response.status_code == 409


def test_delete_elimina(client: TestClient) -> None:
    created = _create(client)

    assert client.delete(f"/api/v1/datasources/{created['id']}").status_code == 204
    assert client.get("/api/v1/datasources").json() == []


def test_id_inexistente_es_404(client: TestClient) -> None:
    missing = uuid.uuid4()

    assert client.patch(f"/api/v1/datasources/{missing}", json={}).status_code == 404
    assert client.delete(f"/api/v1/datasources/{missing}").status_code == 404
    assert client.post(f"/api/v1/datasources/{missing}/test").status_code == 404


def test_fuente_de_config_no_se_edita_ni_se_borra(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    created = _create(client)
    with factory() as session:
        stored = session.get(Datasource, uuid.UUID(str(created["id"])))
        assert stored is not None
        stored.managed_by = "config"
        session.commit()
    path = f"/api/v1/datasources/{created['id']}"

    patched = client.patch(path, json={"max_rows": 5})
    deleted = client.delete(path)

    assert patched.status_code == 409
    assert patched.json()["error"]["code"] == "managed_by_config"
    assert deleted.status_code == 409
    assert len(client.get("/api/v1/datasources").json()) == 1


def test_prueba_de_conexion_con_la_demo_sqlite(client: TestClient, demo_url: str) -> None:
    created = _create(client, url=demo_url)

    response = client.post(f"/api/v1/datasources/{created['id']}/test")

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["latency_ms"] >= 0
    assert body["server_version"][0].isdigit()
    assert body["error"] is None


def test_prueba_sin_driver_indica_el_extra(client: TestClient) -> None:
    created = _create(client, dialect="tsql", url="mssql+controlador_inexistente://u:p@h/db")

    body = client.post(f"/api/v1/datasources/{created['id']}/test").json()

    assert body["ok"] is False
    assert body["error"]["kind"] == "driver_missing"
    assert "uv sync --extra sqlserver" in body["error"]["message"]


def test_prueba_con_base_inalcanzable_es_network(client: TestClient, tmp_path: Path) -> None:
    created = _create(client, url=f"sqlite:///{tmp_path / 'no' / 'existe' / 'x.db'}")

    body = client.post(f"/api/v1/datasources/{created['id']}/test").json()

    assert body["ok"] is False
    assert body["error"]["kind"] == "network"
    assert str(tmp_path) not in body["error"]["message"]


def test_prueba_con_llave_equivocada_es_unknown(client: TestClient) -> None:
    created = _create(client)
    app.dependency_overrides[get_request_cipher] = lambda: make_cipher("otra-llave")

    body = client.post(f"/api/v1/datasources/{created['id']}/test").json()

    assert body["ok"] is False
    assert body["error"]["kind"] == "unknown"
    listed = client.get("/api/v1/datasources").json()
    assert listed[0]["url"] == "***"


def test_clasificacion_de_errores() -> None:
    auth = OperationalError("SELECT 1", {}, Exception('password authentication failed for "u"'))
    network = OperationalError("SELECT 1", {}, Exception("connection refused"))

    assert classify_error(auth, "postgres").kind == "auth"
    assert classify_error(network, "postgres").kind == "network"
    assert classify_error(TimeoutError(), "postgres").kind == "network"
    assert classify_error(ValueError("x"), "postgres").kind == "unknown"
    assert classify_error(ModuleNotFoundError("psycopg"), "postgres").kind == "driver_missing"


def test_mask_url_casos() -> None:
    assert mask_url("sqlite:///./demo/ventas.db") == "sqlite:///./demo/ventas.db"
    assert mask_url("postgresql://solo_usuario@h/db") == "postgresql://***@h/db"
    assert mask_url("basura") == "***"


def test_usuario_sin_admin_solo_puede_listar(client: TestClient) -> None:
    creada = _create(client)
    app.dependency_overrides[get_current_user] = lambda: User(email="u@b.co", is_admin=False)

    assert client.get("/api/v1/datasources").status_code == 200
    assert client.post("/api/v1/datasources", json={}).status_code == 403
    assert client.patch(f"/api/v1/datasources/{creada['id']}", json={}).status_code == 403
    assert client.post(f"/api/v1/datasources/{creada['id']}/test").status_code == 403
    assert client.delete(f"/api/v1/datasources/{creada['id']}").status_code == 403
    introspect_url = f"/api/v1/datasources/{creada['id']}/semantic/introspect"
    assert client.post(introspect_url, json={}).status_code == 403


def test_introspect_devuelve_vista_previa_sin_guardar(client: TestClient, demo_url: str) -> None:
    created = _create(client, url=demo_url)

    response = client.post(f"/api/v1/datasources/{created['id']}/semantic/introspect", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["tables"]) == 7
    assert {"from": "facturas.cliente_id", "to": "clientes.id"} in body["relationships"]


def test_introspect_con_patron_y_muestras(client: TestClient, demo_url: str) -> None:
    created = _create(client, url=demo_url, privacy="samples")

    response = client.post(
        f"/api/v1/datasources/{created['id']}/semantic/introspect",
        json={"table_pattern": "facturas", "sample_values": True},
    )

    assert response.status_code == 200, response.text
    columns = {c["name"]: c for c in response.json()["tables"][0]["columns"]}
    assert columns["canal"]["sample_values"] == ["MAYORISTA", "ONLINE", "TIENDA"]


def test_introspect_fuente_inexistente_es_404(client: TestClient) -> None:
    response = client.post(f"/api/v1/datasources/{uuid.uuid4()}/semantic/introspect", json={})

    assert response.status_code == 404


def test_introspect_error_de_conexion_no_filtra_la_url(client: TestClient) -> None:
    created = _create(client, url="sqlite:////no/existe/secreto/x.db")

    response = client.post(f"/api/v1/datasources/{created['id']}/semantic/introspect", json={})

    assert response.status_code == 502
    assert "secreto" not in response.text
