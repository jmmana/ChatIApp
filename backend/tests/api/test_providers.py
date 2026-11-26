from fastapi.testclient import TestClient

from app.llm.catalog import CATALOG
from app.main import create_app
from app.security.auth import get_current_user

application = create_app()
application.dependency_overrides[get_current_user] = lambda: object()
client = TestClient(application)


def test_catalogo_devuelve_todas_las_entradas() -> None:
    response = client.get("/api/v1/providers/catalog")

    assert response.status_code == 200
    body = response.json()
    assert [item["kind"] for item in body] == [spec.kind for spec in CATALOG]
    first = body[0]
    assert {"kind", "label", "category", "litellm_prefix", "fields", "docs_url"} <= first.keys()
    assert {"name", "label", "type", "required", "default", "help"} <= first["fields"][0].keys()
