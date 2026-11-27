import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api import evals
from app.db.models import Base, EvalRun, Provider, User
from app.db.session import get_session, make_engine
from app.eval.golden import SetDorado, cargar
from app.main import create_app
from app.security.auth import get_current_user

CASOS_EN_LA_PRUEBA = 2


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _set_corto(monkeypatch: pytest.MonkeyPatch) -> None:
    def corto() -> SetDorado:
        conjunto = cargar()
        conjunto.casos = conjunto.casos[:CASOS_EN_LA_PRUEBA]
        return conjunto

    monkeypatch.setattr(evals, "cargar_set", corto)
    evals._CORRIDAS.clear()


def _app(engine: Engine, admin: bool = True) -> TestClient:
    application = create_app()

    def _session() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as session:
            yield session

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[evals.get_session_factory] = lambda: (
        lambda: Session(engine, expire_on_commit=False)
    )
    application.dependency_overrides[get_current_user] = lambda: User(
        email="a@b.co", is_admin=admin
    )
    return TestClient(application)


@pytest.fixture
def client(engine: Engine) -> TestClient:
    return _app(engine)


def _proveedor(engine: Engine, kind: str = "fake", name: str = "simulado") -> uuid.UUID:
    with Session(engine, expire_on_commit=False) as session:
        provider = Provider(name=name, kind=kind, model="modelo-de-prueba")
        session.add(provider)
        session.commit()
        return provider.id


def _esperar(client: TestClient, run_id: str) -> dict[str, Any]:
    for _ in range(300):
        body: dict[str, Any] = client.get(f"/api/v1/evals/runs/{run_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.1)
    raise AssertionError("la corrida no terminó")


def test_una_corrida_con_el_proveedor_simulado_avanza_y_guarda_el_informe(
    client: TestClient, engine: Engine
) -> None:
    provider_id = _proveedor(engine)
    response = client.post("/api/v1/evals/runs", json={"provider_ids": [str(provider_id)]})
    assert response.status_code == 202, response.text
    assert response.json()["cases_total"] == CASOS_EN_LA_PRUEBA

    final = _esperar(client, response.json()["id"])

    assert final["status"] == "done", final
    assert final["cases_done"] == CASOS_EN_LA_PRUEBA
    assert final["report"]["proveedores"][0]["proveedor"] == "simulado"
    assert [r["id"] for r in client.get("/api/v1/evals/runs").json()] == [final["id"]]
    with Session(engine) as session:
        assert len(session.scalars(select(EvalRun)).all()) == 1


def test_un_proveedor_inexistente_responde_404(client: TestClient) -> None:
    response = client.post("/api/v1/evals/runs", json={"provider_ids": [str(uuid.uuid4())]})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "provider_not_found"


def test_con_un_proveedor_real_exige_el_tope_de_llamadas(
    client: TestClient, engine: Engine
) -> None:
    provider_id = _proveedor(engine, kind="anthropic", name="claude")
    response = client.post("/api/v1/evals/runs", json={"provider_ids": [str(provider_id)]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "max_calls_required"
    assert evals._CORRIDAS == {}


def test_una_corrida_inexistente_responde_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/evals/runs/{uuid.uuid4()}").status_code == 404


def test_solo_los_administradores_pueden_evaluar(engine: Engine) -> None:
    client = _app(engine, admin=False)
    assert client.get("/api/v1/evals/runs").status_code == 403
