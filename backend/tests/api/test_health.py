import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_responde_estado_y_version() -> None:
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text())["project"]["version"]

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": expected}


def test_docs_openapi_disponible() -> None:
    assert client.get("/api/v1/docs").status_code == 200
    assert client.get("/api/v1/openapi.json").status_code == 200
