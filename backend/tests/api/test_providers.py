import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.models import Base, Provider
from app.db.session import get_session, make_engine
from app.llm.catalog import CATALOG
from app.main import create_app
from app.security.auth import get_current_user
from app.security.crypto import decrypt, encrypt

# Valores que no tienen forma de clave real (el escáner de secretos los rechazaría).
SECRETO = "clave-de-prueba-1234567890"
SECRETO_NUEVO = "clave-nueva-0987654321"


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_SECRET_KEY", "llave-de-prueba-" + "x" * 32)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    application = create_app()

    def _session() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as session:
            yield session

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_current_user] = lambda: object()
    yield TestClient(application)


def _crear(client: TestClient, name: str = "claude", **extra: Any) -> dict[str, Any]:
    body = {
        "name": name,
        "kind": "anthropic",
        "model": "modelo-de-prueba",
        "secrets": {"api_key": SECRETO},
        **extra,
    }
    response = client.post("/api/v1/providers", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_catalogo_devuelve_todas_las_entradas(client: TestClient) -> None:
    response = client.get("/api/v1/providers/catalog")

    assert response.status_code == 200
    body = response.json()
    assert [item["kind"] for item in body] == [spec.kind for spec in CATALOG]
    first = body[0]
    assert {"kind", "label", "category", "litellm_prefix", "fields", "docs_url"} <= first.keys()
    assert {"name", "label", "type", "required", "default", "help"} <= first["fields"][0].keys()


def test_crear_cifra_y_enmascara_el_secreto(client: TestClient, engine: Engine) -> None:
    created = _crear(client)

    assert created["secrets"]["api_key"] != SECRETO
    assert created["secrets"]["api_key"].endswith(SECRETO[-4:])
    with Session(engine) as session:
        row = session.scalars(select(Provider)).one()
        assert row.secrets_encrypted is not None
        assert SECRETO.encode() not in row.secrets_encrypted
        assert json.loads(decrypt(row.secrets_encrypted)) == {"api_key": SECRETO}


def test_patch_sin_secreto_lo_conserva_y_con_secreto_lo_cambia(
    client: TestClient, engine: Engine
) -> None:
    created = _crear(client)
    url = f"/api/v1/providers/{created['id']}"

    response = client.patch(url, json={"model": "otro-modelo"})
    assert response.status_code == 200
    assert response.json()["model"] == "otro-modelo"
    assert response.json()["secrets"] == created["secrets"]

    response = client.patch(url, json={"secrets": {"api_key": SECRETO_NUEVO}})
    assert response.status_code == 200
    with Session(engine) as session:
        row = session.get(Provider, created["id"])
        assert row is not None and row.secrets_encrypted is not None
        assert json.loads(decrypt(row.secrets_encrypted)) == {"api_key": SECRETO_NUEVO}


def test_valida_contra_el_catalogo_del_kind(client: TestClient) -> None:
    base = {"name": "x", "model": "m"}

    desconocido = client.post("/api/v1/providers", json={**base, "kind": "no-existe"})
    assert desconocido.status_code == 422
    assert desconocido.json()["error"]["code"] == "unknown_kind"

    sin_secreto = client.post("/api/v1/providers", json={**base, "kind": "anthropic"})
    assert sin_secreto.status_code == 422
    assert "api_key" in sin_secreto.json()["error"]["details"]["fields"]

    sobrante = client.post(
        "/api/v1/providers",
        json={**base, "kind": "anthropic", "secrets": {"api_key": SECRETO}, "config": {"zzz": 1}},
    )
    assert sobrante.status_code == 422
    assert "zzz" in sobrante.json()["error"]["details"]["fields"]


def test_un_unico_proveedor_predeterminado(client: TestClient) -> None:
    primero = _crear(client, "uno", is_default=True)
    segundo = _crear(client, "dos", is_default=True)

    listado = {p["id"]: p for p in client.get("/api/v1/providers").json()}
    assert listado[primero["id"]]["is_default"] is False
    assert listado[segundo["id"]]["is_default"] is True

    client.patch(f"/api/v1/providers/{primero['id']}", json={"is_default": True})
    listado = {p["id"]: p for p in client.get("/api/v1/providers").json()}
    assert [p["is_default"] for p in listado.values()].count(True) == 1
    assert listado[primero["id"]]["is_default"] is True


def test_nombre_repetido_da_409(client: TestClient) -> None:
    _crear(client, "claude")
    response = client.post(
        "/api/v1/providers",
        json={
            "name": "claude",
            "kind": "anthropic",
            "model": "m",
            "secrets": {"api_key": SECRETO},
        },
    )
    assert response.status_code == 409


def test_proveedor_de_config_no_se_edita_ni_borra(client: TestClient, engine: Engine) -> None:
    with Session(engine) as session:
        provider = Provider(
            name="desde-config",
            kind="anthropic",
            model="m",
            secrets_encrypted=encrypt(json.dumps({"api_key": SECRETO})),
            managed_by="config",
        )
        session.add(provider)
        session.commit()
        provider_id = str(provider.id)
    url = f"/api/v1/providers/{provider_id}"

    assert client.patch(url, json={"model": "x"}).status_code == 409
    assert client.delete(url).status_code == 409
    routing = client.put("/api/v1/providers/routing", json={"tasks": {"sql": provider_id}})
    assert routing.status_code == 409


def test_borrar_y_404(client: TestClient) -> None:
    created = _crear(client)
    url = f"/api/v1/providers/{created['id']}"

    assert client.delete(url).status_code == 204
    assert client.get("/api/v1/providers").json() == []
    assert client.delete(url).status_code == 404
    assert client.patch(url, json={"model": "x"}).status_code == 404


def test_routing_asigna_tareas_y_respaldo(client: TestClient) -> None:
    a = _crear(client, "a")
    b = _crear(client, "b")

    response = client.put(
        "/api/v1/providers/routing",
        json={"tasks": {"planner": a["id"], "answer": b["id"]}, "fallback": [b["id"]]},
    )

    assert response.status_code == 200
    por_id = {p["id"]: p for p in response.json()}
    assert por_id[a["id"]]["tasks"] == ["planner"]
    assert por_id[b["id"]]["tasks"] == ["answer"]
    assert por_id[b["id"]]["params"] == {"fallback": 0}


def test_ningun_endpoint_devuelve_un_secreto_en_claro(client: TestClient) -> None:
    created = _crear(client, tasks=["sql"], is_default=True)
    url = f"/api/v1/providers/{created['id']}"
    respuestas = [
        client.get("/api/v1/providers/catalog"),
        client.get("/api/v1/providers"),
        client.patch(url, json={"secrets": {"api_key": SECRETO_NUEVO}}),
        client.patch(url, json={"model": "otro"}),
        client.put("/api/v1/providers/routing", json={"tasks": {"sql": created["id"]}}),
        # Errores de validación: tampoco deben repetir el valor recibido.
        client.post(
            "/api/v1/providers",
            json={"name": "z", "kind": "anthropic", "model": "m", "secrets": {"otro": SECRETO}},
        ),
        client.post(
            "/api/v1/providers",
            json={
                "name": "claude",
                "kind": "anthropic",
                "model": "m",
                "secrets": {"api_key": SECRETO},
            },
        ),
        client.delete(url),
    ]

    for response in respuestas:
        assert SECRETO not in response.text
        assert SECRETO_NUEVO not in response.text
    assert created["id"] in respuestas[1].text
