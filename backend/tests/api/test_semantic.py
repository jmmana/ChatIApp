import copy
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, Datasource, User
from app.db.session import get_session, make_engine
from app.main import app
from app.security.auth import get_current_user
from app.semantic.importers.model_file import parse_model_text
from app.semantic.store import dump_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def datasource_id(factory: sessionmaker[Session]) -> uuid.UUID:
    with factory() as session:
        datasource = Datasource(name="Ventas", dialect="sqlite", url_encrypted=b"x")
        session.add(datasource)
        session.commit()
        return datasource.id


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: User(email="a@b.co", is_admin=True)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def model() -> dict[str, Any]:
    parsed = parse_model_text(EXAMPLE.read_text("utf-8"), "yaml")
    return dump_model(parsed)


def _url(datasource_id: uuid.UUID, suffix: str = "") -> str:
    return f"/api/v1/datasources/{datasource_id}/semantic{suffix}"


def _put(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any], base_version: int
) -> Any:
    return client.put(_url(datasource_id), json={"base_version": base_version, "model": model})


def test_sin_modelo_responde_404(client: TestClient, datasource_id: uuid.UUID) -> None:
    response = client.get(_url(datasource_id))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "semantic_model_not_found"
    assert client.get(_url(datasource_id, "/versions")).json() == []


def test_fuente_inexistente_responde_404(client: TestClient) -> None:
    response = client.get(_url(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "datasource_not_found"


def test_publica_y_lee_la_version_vigente(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    response = _put(client, datasource_id, model, 0)

    assert response.status_code == 200, response.text
    assert response.json()["version"] == 1
    current = client.get(_url(datasource_id)).json()
    assert current["version"] == 1
    assert current["model"] == model


def test_modelo_invalido_da_422_con_rutas_y_no_guarda(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    broken = copy.deepcopy(model)
    broken["metrics"][0]["table"] = "no_existe"
    broken["campo_raro"] = 1

    response = _put(client, datasource_id, broken, 0)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_semantic_model"
    paths = {item["path"] for item in error["details"]["errors"]}
    assert "campo_raro" in paths
    assert client.get(_url(datasource_id, "/versions")).json() == []


def test_base_version_es_obligatorio(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    response = client.put(_url(datasource_id), json={"model": model})

    assert response.status_code == 422


def test_base_version_desactualizado_da_409(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    assert _put(client, datasource_id, model, 0).status_code == 200

    stale = _put(client, datasource_id, model, 0)

    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current_version"] == 1
    assert len(client.get(_url(datasource_id, "/versions")).json()) == 1


def test_cada_publicacion_crea_version_inmutable(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    _put(client, datasource_id, model, 0)
    changed = copy.deepcopy(model)
    changed["name"] = "Otro nombre"
    assert _put(client, datasource_id, changed, 1).json()["version"] == 2

    versions = client.get(_url(datasource_id, "/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert client.get(_url(datasource_id, "/versions/1")).json()["model"] == model
    assert client.get(_url(datasource_id, "/versions/2")).json()["model"]["name"] == "Otro nombre"
    assert client.get(_url(datasource_id, "/versions/9")).status_code == 404


def test_version_anterior_se_republica_como_nueva(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    _put(client, datasource_id, model, 0)
    changed = copy.deepcopy(model)
    changed["name"] = "Otro nombre"
    _put(client, datasource_id, changed, 1)

    old = client.get(_url(datasource_id, "/versions/1")).json()["model"]
    response = _put(client, datasource_id, old, 2)

    assert response.status_code == 200
    assert response.json()["version"] == 3
    assert client.get(_url(datasource_id)).json()["model"] == model
    assert len(client.get(_url(datasource_id, "/versions")).json()) == 3


@pytest.mark.parametrize("fmt", ["yaml", "json"])
def test_exportar_e_importar_da_un_modelo_identico(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any], fmt: str
) -> None:
    _put(client, datasource_id, model, 0)

    response = client.get(_url(datasource_id, f"/export?format={fmt}"))

    assert response.status_code == 200
    reimported = parse_model_text(response.text, fmt)
    assert dump_model(reimported) == model
    if fmt == "yaml":
        assert yaml.safe_load(response.text) == model


def test_exportar_formato_desconocido_da_422(client: TestClient, datasource_id: uuid.UUID) -> None:
    assert client.get(_url(datasource_id, "/export?format=xml")).status_code == 422


def test_solo_administradores_publican(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    app.dependency_overrides[get_current_user] = lambda: User(email="u@b.co", is_admin=False)

    response = _put(client, datasource_id, model, 0)

    assert response.status_code == 403


def test_solo_administradores_leen_el_modelo(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    assert _put(client, datasource_id, model, 0).status_code in (200, 201)
    app.dependency_overrides[get_current_user] = lambda: User(email="u@b.co", is_admin=False)
    base = f"/api/v1/datasources/{datasource_id}/semantic"

    for path in ("", "/versions", "/versions/1", "/export?format=yaml"):
        assert client.get(base + path).status_code == 403, path


SCHEMA_SQL = EXAMPLE.parent / "schema.sql"


def _import(client: TestClient, datasource_id: uuid.UUID, name: str, content: bytes) -> Any:
    return client.post(_url(datasource_id, "/import"), files={"file": (name, content)})


def test_importar_sql_no_altera_descripciones_manuales_ni_guarda(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    assert _put(client, datasource_id, model, 0).status_code in (200, 201)

    response = _import(client, datasource_id, "schema.sql", SCHEMA_SQL.read_bytes())

    assert response.status_code == 200
    body = response.json()
    assert set(body["diff"]) == {"added", "changed", "missing", "suggestions"}
    merged = {t["name"]: t for t in body["model"]["tables"]}
    for table in model["tables"]:
        if table.get("description"):
            assert merged[table["name"]]["description"] == table["description"]
        columns = {c["name"]: c for c in merged[table["name"]]["columns"]}
        for column in table["columns"]:
            if column.get("description"):
                assert columns[column["name"]]["description"] == column["description"]
    versions = client.get(_url(datasource_id, "/versions")).json()
    assert [v["version"] for v in versions] == [1]


def test_importar_dos_veces_el_mismo_archivo_no_da_diferencias(
    client: TestClient, datasource_id: uuid.UUID, model: dict[str, Any]
) -> None:
    assert _put(client, datasource_id, model, 0).status_code in (200, 201)
    content = SCHEMA_SQL.read_bytes()
    first = _import(client, datasource_id, "schema.sql", content).json()
    assert _put(client, datasource_id, first["model"], 1).status_code in (200, 201)

    second = _import(client, datasource_id, "schema.sql", content).json()

    # Nada nuevo, cambiado ni faltante. Las descripciones escritas a mano se conservan y la
    # de la fuente vuelve como sugerencia (docs/MODELO_SEMANTICO.md): son las mismas que antes.
    diff = second["diff"]
    assert (diff["added"], diff["changed"], diff["missing"]) == ([], [], [])
    assert diff["suggestions"] == first["diff"]["suggestions"]


def test_importar_sin_modelo_previo_crea_uno_nuevo(
    client: TestClient, datasource_id: uuid.UUID
) -> None:
    csv_text = "tabla,columna,tipo,descripcion\nt,a,int,Una columna\n"

    response = _import(client, datasource_id, "diccionario.CSV", csv_text.encode())

    assert response.status_code == 200
    assert response.json()["model"]["tables"][0]["columns"][0]["description"] == "Una columna"
    assert len(response.json()["diff"]["added"]) == 2


def test_importar_extension_desconocida_da_422(
    client: TestClient, datasource_id: uuid.UUID
) -> None:
    response = _import(client, datasource_id, "datos.txt", b"x")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_format"


def test_importar_en_fuente_inexistente_da_404(client: TestClient) -> None:
    response = _import(client, uuid.uuid4(), "schema.sql", b"")

    assert response.status_code == 404


def test_solo_administradores_importan(client: TestClient, datasource_id: uuid.UUID) -> None:
    app.dependency_overrides[get_current_user] = lambda: User(email="u@b.co", is_admin=False)

    assert _import(client, datasource_id, "schema.sql", b"").status_code == 403
