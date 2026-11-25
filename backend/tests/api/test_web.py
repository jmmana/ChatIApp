from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

INDEX = "<!doctype html><title>ChatIApp</title><div id=root></div>"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log('hola')")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secreto.txt").write_text("no")
    return tmp_path


@pytest.fixture
def client(static_dir: Path) -> TestClient:
    return TestClient(create_app(static_dir=static_dir))


@pytest.mark.parametrize("path", ["/", "/chat", "/modelo-semantico", "/fuentes-de-datos/nueva"])
def test_rutas_de_la_interfaz_devuelven_index(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


def test_sirve_assets_y_archivos_de_la_raiz(client: TestClient) -> None:
    assert client.get("/assets/index-abc123.js").text == "console.log('hola')"
    assert client.get("/favicon.svg").text == "<svg/>"


def test_asset_inexistente_es_404(client: TestClient) -> None:
    assert client.get("/assets/no-existe.js").status_code == 404


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
@pytest.mark.parametrize("path", ["/api", "/api/v1/no-existe", "/api/v2/health"])
def test_api_desconocida_es_404_en_json(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_api_sigue_funcionando(client: TestClient) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_no_sale_del_directorio_estatico(client: TestClient) -> None:
    response = client.get("/%2e%2e/secreto.txt")
    assert response.text != "no"


def test_metodo_no_get_en_ruta_de_interfaz_no_devuelve_index(client: TestClient) -> None:
    response = client.post("/chat")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_sin_interfaz_compilada_solo_hay_api(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=tmp_path))
    assert client.get("/chat").status_code == 404
    assert client.get("/api/v1/health").status_code == 200
