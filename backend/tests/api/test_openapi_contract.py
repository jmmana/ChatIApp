from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.deprecation import deprecated_route, deprecation_headers
from app.api.openapi import SPEC_PATH, main, render_spec
from app.main import create_app


def test_openapi_publicado_coincide_con_docs_openapi_v1() -> None:
    application = create_app()
    served = TestClient(application).get("/api/v1/openapi.json").json()

    assert SPEC_PATH.exists(), "Falta docs/openapi/v1.json: `uv run python -m app.api.openapi`"
    assert SPEC_PATH.read_text(encoding="utf-8") == render_spec(application), (
        "docs/openapi/v1.json está desactualizado: `uv run python -m app.api.openapi`"
    )
    assert served["paths"]
    assert all(path.startswith("/api/v1/") for path in served["paths"])


def test_exportador_escribe_y_verifica(tmp_path: Path) -> None:
    destino = tmp_path / "v1.json"

    assert main(["--check", "--output", str(destino)]) == 1
    assert main(["--output", str(destino)]) == 0
    assert main(["--check", "--output", str(destino)]) == 0


def test_cabeceras_deprecation_y_sunset() -> None:
    headers = deprecation_headers(date(2027, 6, 1), deprecated_since=date(2026, 11, 28))

    epoch = int(datetime(2026, 11, 28, tzinfo=UTC).timestamp())
    assert headers["Deprecation"] == f"@{epoch}"
    assert headers["Sunset"] == "Tue, 01 Jun 2027 00:00:00 GMT"


def test_sunset_debe_ser_posterior() -> None:
    with pytest.raises(ValueError):
        deprecation_headers(date(2026, 1, 1), deprecated_since=date(2026, 1, 1))


def test_endpoint_obsoleto_agrega_cabeceras_y_marca_openapi() -> None:
    router = APIRouter()

    @router.get("/viejo", **deprecated_route(date(2099, 1, 1), date(2026, 11, 28)))
    def viejo() -> dict[str, str]:
        return {"ok": "sí"}

    @router.get("/nuevo")
    def nuevo() -> dict[str, str]:
        return {"ok": "sí"}

    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    client = TestClient(application)

    obsoleto = client.get("/api/v1/viejo")
    assert obsoleto.status_code == 200
    epoch = int(datetime(2026, 11, 28, tzinfo=UTC).timestamp())
    assert obsoleto.headers["Deprecation"] == f"@{epoch}"
    assert obsoleto.headers["Sunset"] == "Thu, 01 Jan 2099 00:00:00 GMT"
    vigente = client.get("/api/v1/nuevo")
    assert "Deprecation" not in vigente.headers
    assert "Sunset" not in vigente.headers
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/v1/viejo"]["get"]["deprecated"] is True
    assert "deprecated" not in paths["/api/v1/nuevo"]["get"]
