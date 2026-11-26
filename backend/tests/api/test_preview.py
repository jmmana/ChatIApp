import importlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.datasources import get_request_cipher
from app.db.models import Base, Grant, SemanticModelVersion, User
from app.db.session import get_session, make_engine
from app.engine.guard import guards
from app.main import app
from app.security.auth import get_current_user
from app.security.crypto import make_cipher

ROOT = Path(__file__).parents[3]
EXAMPLE = ROOT / "examples" / "ventas" / "semantic-model.yaml"
CIPHER = make_cipher("clave-de-prueba")
SUCURSALES = {"role": "gerente_sucursal", "attributes": {"sucursales": [1, 2]}}


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

    guards.clear()
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_request_cipher] = lambda: CIPHER
    app.dependency_overrides[get_current_user] = lambda: User(email="a@b.co", is_admin=True)
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


def _preview(client: TestClient, datasource_id: str, **body: Any) -> Any:
    return client.post(f"/api/v1/datasources/{datasource_id}/preview", json=body)


def test_ventas_netas_este_mes_usa_la_resumida_diaria(
    client: TestClient, datasource_id: str
) -> None:
    response = _preview(
        client,
        datasource_id,
        metric="ventas_netas",
        period="este mes",
        view_as={"role": "gerencia_general"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "ventas_diarias" in data["sql"]
    assert data["summary_table"] == "ventas_diarias"
    assert data["reason"]
    assert data["period"]["is_current"] is True
    assert data["period"]["grain"] == "month"
    assert data["guard"]["allowed"] is True
    sources = {f["source"] for f in data["filters_applied"]}
    assert "period" in sources
    assert "role" not in sources


def test_filtros_por_rol_con_view_as(client: TestClient, datasource_id: str) -> None:
    response = _preview(
        client, datasource_id, metric="ventas_netas", period="este mes", view_as=SUCURSALES
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["role"] == "gerente_sucursal"
    assert "sucursal_id IN (1, 2)" in data["sql"]
    assert "role" in {f["source"] for f in data["filters_applied"]}


def test_sin_atributo_requerido_el_guardian_lo_senala(
    client: TestClient, datasource_id: str
) -> None:
    response = _preview(
        client,
        datasource_id,
        metric="ventas_netas",
        period="este mes",
        view_as={"role": "gerente_sucursal"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["guard"]["allowed"] is False
    assert "missing_context" in {v["code"] for v in data["guard"]["violations"]}


def test_metrica_desconocida_es_422(client: TestClient, datasource_id: str) -> None:
    response = _preview(client, datasource_id, metric="margen_magico", period="este mes")
    assert response.status_code == 422
    assert response.json()["error"]["message"]


def test_dimension_no_permitida_es_422(client: TestClient, datasource_id: str) -> None:
    response = _preview(
        client,
        datasource_id,
        metric="ventas_netas",
        period="este mes",
        dimensions=["clientes.documento"],
        view_as=SUCURSALES,
    )
    assert response.status_code == 422


def test_periodo_ilegible_es_422(client: TestClient, datasource_id: str) -> None:
    response = _preview(client, datasource_id, metric="ventas_netas", period="cuando llueva")
    assert response.status_code == 422
    assert "cuando llueva" in response.json()["error"]["message"]


def test_metrica_que_exige_periodo_sin_periodo_es_422(
    client: TestClient, datasource_id: str
) -> None:
    response = _preview(client, datasource_id, metric="ventas_netas", view_as=SUCURSALES)
    assert response.status_code == 422
    assert "período" in response.json()["error"]["message"]


def test_rol_inexistente_es_422(client: TestClient, datasource_id: str) -> None:
    response = _preview(
        client,
        datasource_id,
        metric="ventas_netas",
        period="este mes",
        view_as={"role": "fantasma"},
    )
    assert response.status_code == 422


def test_fuente_sin_modelo_o_inexistente_es_404(client: TestClient) -> None:
    created = client.post(
        "/api/v1/datasources",
        json={"name": "Vacía", "dialect": "sqlite", "url": "sqlite:///y.db"},
    ).json()
    for target in (created["id"], str(uuid.uuid4())):
        response = _preview(client, target, metric="ventas_netas", period="este mes")
        assert response.status_code == 404


def test_validate_sql_acepta_una_consulta_valida_con_filtro_de_rol(
    client: TestClient, datasource_id: str
) -> None:
    response = client.post(
        f"/api/v1/datasources/{datasource_id}/validate-sql",
        json={"sql": "SELECT SUM(total) FROM facturas", "view_as": SUCURSALES},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["allowed"] is True
    assert data["tables"] == ["facturas"]
    assert "sucursal_id IN (1, 2)" in data["sql"]


def test_validate_sql_rechaza_escrituras_y_columnas_ocultas(
    client: TestClient, datasource_id: str
) -> None:
    url = f"/api/v1/datasources/{datasource_id}/validate-sql"
    view_as = {"role": "gerencia_general"}
    borrar = client.post(url, json={"sql": "DELETE FROM facturas", "view_as": view_as})
    oculta = client.post(url, json={"sql": "SELECT email FROM clientes", "view_as": view_as})
    for response in (borrar, oculta):
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["allowed"] is False
        assert data["sql"] is None
        assert data["violations"]
    assert "hidden_column" in {v["code"] for v in oculta.json()["violations"]}


def test_usuario_sin_permiso_recibe_403(
    client: TestClient, factory: sessionmaker[Session], datasource_id: str
) -> None:
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@b.co", is_admin=False
    )
    response = _preview(client, datasource_id, metric="ventas_netas", period="este mes")
    assert response.status_code == 403


def test_view_as_solo_para_administradores(
    client: TestClient, factory: sessionmaker[Session], datasource_id: str
) -> None:
    user = User(id=uuid.uuid4(), email="u@b.co", password_hash="x", is_admin=False)
    with factory() as session:
        session.add(user)
        session.add(
            Grant(
                user_id=user.id,
                datasource_id=uuid.UUID(datasource_id),
                role="gerente_sucursal",
                attributes={"sucursales": [3]},
            )
        )
        session.commit()
    app.dependency_overrides[get_current_user] = lambda: user

    propio = _preview(client, datasource_id, metric="ventas_netas", period="este mes")
    assert propio.status_code == 200, propio.text
    assert "sucursal_id IN (3)" in propio.json()["sql"]

    ajeno = _preview(
        client, datasource_id, metric="ventas_netas", period="este mes", view_as=SUCURSALES
    )
    assert ajeno.status_code == 403


def test_validate_sql_es_solo_para_administradores(client: TestClient, datasource_id: str) -> None:
    # Revela qué columnas están ocultas, igual que leer el modelo.
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@b.co", is_admin=False
    )
    response = client.post(
        f"/api/v1/datasources/{datasource_id}/validate-sql",
        json={"sql": "SELECT documento FROM clientes"},
    )
    assert response.status_code == 403
