import importlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.datasources import get_request_cipher
from app.db.models import Base, Datasource, Grant, SemanticModelVersion, User
from app.db.session import get_session, make_engine
from app.main import app
from app.security.auth import get_current_user
from app.security.crypto import make_cipher

ROOT = Path(__file__).parents[3]
EXAMPLE = ROOT / "examples" / "ventas" / "semantic-model.yaml"
CIPHER = make_cipher("clave-de-prueba")
INTERNAL = ("expression", "table", "time_column", "filters", "sql", "hidden", "documento", "email")


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
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="a@b.co", is_admin=True
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def datasource_id(client: TestClient, factory: sessionmaker[Session]) -> str:
    response = client.post(
        "/api/v1/datasources",
        json={"name": "Ventas", "dialect": "sqlite", "url": "sqlite:///x.db"},
    )
    assert response.status_code == 201, response.text
    created = str(response.json()["id"])
    yaml = importlib.import_module("yaml")
    with factory() as session:
        session.add(
            SemanticModelVersion(
                datasource_id=uuid.UUID(created),
                version=1,
                model=yaml.safe_load(EXAMPLE.read_text()),
            )
        )
        session.commit()
    return created


def _login_as(
    factory: sessionmaker[Session], datasource_id: str, role: str | None, **attributes: Any
) -> None:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@b.co", password_hash="x")
    with factory() as session:
        session.add(user)
        if role is not None:
            session.add(
                Grant(
                    user_id=user.id,
                    datasource_id=uuid.UUID(datasource_id),
                    role=role,
                    attributes=attributes,
                )
            )
        session.commit()
    app.dependency_overrides[get_current_user] = lambda: user


def _get(client: TestClient, datasource_id: str) -> Any:
    return client.get(f"/api/v1/datasources/{datasource_id}/metrics")


def test_administrador_ve_las_metricas_con_el_rol_por_defecto(
    client: TestClient, datasource_id: str
) -> None:
    response = _get(client, datasource_id)
    assert response.status_code == 200, response.text
    metrics = {m["name"]: m for m in response.json()["metrics"]}
    assert set(metrics) == {
        "ventas_netas",
        "ventas_sin_iva",
        "num_facturas",
        "ticket_promedio",
        "unidades_vendidas",
        "clientes_activos",
    }
    ventas = metrics["ventas_netas"]
    assert ventas["label"] == "Ventas netas"
    assert ventas["description"]
    assert ventas["requires_period"] is True
    assert "segmento" in ventas["dimensions"]


def test_gerente_con_sucursales_ve_sus_metricas(
    client: TestClient, factory: sessionmaker[Session], datasource_id: str
) -> None:
    _login_as(factory, datasource_id, "gerente_sucursal", sucursales=[1, 2])
    response = _get(client, datasource_id)
    assert response.status_code == 200, response.text
    assert [m["name"] for m in response.json()["metrics"]] == [
        "ventas_netas",
        "ventas_sin_iva",
        "num_facturas",
        "ticket_promedio",
        "unidades_vendidas",
        "clientes_activos",
    ]


def test_rol_con_tabla_oculta_no_ve_sus_dimensiones(
    client: TestClient, factory: sessionmaker[Session], datasource_id: str
) -> None:
    _login_as(factory, datasource_id, "mercadeo")
    response = _get(client, datasource_id)
    assert response.status_code == 200, response.text
    for metric in response.json()["metrics"]:
        assert "segmento" not in metric["dimensions"]
        assert metric["dimensions"]


def test_la_respuesta_no_trae_campos_internos(
    client: TestClient, factory: sessionmaker[Session], datasource_id: str
) -> None:
    _login_as(factory, datasource_id, "mercadeo")
    body = _get(client, datasource_id).json()
    assert set(body) == {"metrics"}
    allowed = {"name", "label", "description", "requires_period", "default_period", "dimensions"}
    text = _get(client, datasource_id).text
    for metric in body["metrics"]:
        assert set(metric) == allowed
    for word in INTERNAL:
        assert f'"{word}"' not in text
    for physical in ("facturas.", "sucursales.", "clientes.", "SUM(", "estado = "):
        assert physical not in text


def test_usuario_sin_permiso_o_fuente_inexistente_es_404_igual(
    client: TestClient, factory: sessionmaker[Session], datasource_id: str
) -> None:
    _login_as(factory, datasource_id, None)
    denied = _get(client, datasource_id)
    missing = _get(client, str(uuid.uuid4()))
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()


def test_fuente_sin_modelo_es_404_para_quien_no_tiene_permiso(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    with factory() as session:
        source = Datasource(name="Vacía", dialect="sqlite", url_encrypted=b"x")
        session.add(source)
        session.commit()
        empty_id = str(source.id)
    _login_as(factory, empty_id, None)
    assert _get(client, empty_id).status_code == 404


def test_sin_sesion_es_401() -> None:
    response = TestClient(app).get(f"/api/v1/datasources/{uuid.uuid4()}/metrics")
    assert response.status_code == 401
