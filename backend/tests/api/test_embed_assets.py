from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

INDEX = "<!doctype html><title>ChatIApp</title><div id=root></div>"
LOADER = "(function(){import('./chatiapp-widget.js')})();"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text(INDEX)
    widget = tmp_path / "embed" / "v1"
    (widget / "chunks").mkdir(parents=True)
    (widget / "chatiapp.js").write_text(LOADER)
    (widget / "chatiapp-widget.js").write_text("export {}")
    (widget / "chunks" / "ResultChart-abc.js").write_text("export default 1")
    return tmp_path


@pytest.fixture
def client(static_dir: Path) -> TestClient:
    return TestClient(create_app(static_dir=static_dir))


def test_sirve_el_cargador_en_la_ruta_documentada(client: TestClient) -> None:
    response = client.get("/embed/v1/chatiapp.js")
    assert response.status_code == 200
    assert response.text == LOADER
    assert "javascript" in response.headers["content-type"]


def test_sirve_el_modulo_y_las_partes_diferidas(client: TestClient) -> None:
    assert client.get("/embed/v1/chatiapp-widget.js").status_code == 200
    assert client.get("/embed/v1/chunks/ResultChart-abc.js").text == "export default 1"


def test_los_archivos_se_pueden_importar_desde_otro_origen(client: TestClient) -> None:
    origin = {"Origin": "https://tienda.test"}
    response = client.get("/embed/v1/chatiapp-widget.js", headers=origin)
    assert response.headers["access-control-allow-origin"] == "*"
    assert "max-age" in response.headers["cache-control"]


def test_archivo_inexistente_es_404_y_no_cae_en_index(client: TestClient) -> None:
    response = client.get("/embed/v1/no-existe.js")
    assert response.status_code == 404
    assert INDEX not in response.text


def test_no_sale_de_la_carpeta_del_widget(client: TestClient, static_dir: Path) -> None:
    (static_dir / "embed" / "secreto.txt").write_text("secreto")
    # El cliente de pruebas normaliza `..`; las formas codificadas llegan tal cual al servidor.
    for path in ("/embed/v1/%2e%2e/secreto.txt", "/embed/v1/..%2fsecreto.txt"):
        assert "secreto" not in client.get(path).text, path


def test_sin_widget_compilado_no_hay_ruta(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(INDEX)
    response = TestClient(create_app(static_dir=tmp_path)).get("/embed/v1/chatiapp.js")
    assert response.status_code == 404
