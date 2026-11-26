"""Ninguna ruta de la API queda pública por accidente: todo exige sesión salvo esta lista."""

from fastapi.testclient import TestClient

from app.main import API_PREFIX, create_app

PUBLIC = {
    ("GET", f"{API_PREFIX}/health"),
    ("POST", f"{API_PREFIX}/auth/login"),
    ("POST", f"{API_PREFIX}/auth/refresh"),
    ("POST", f"{API_PREFIX}/auth/logout"),
}


def test_toda_ruta_de_la_api_fuera_de_la_lista_exige_sesion() -> None:
    application = create_app()
    client = TestClient(application)
    # El esquema OpenAPI lista todas las rutas, también las de routers incluidos.
    paths = application.openapi()["paths"]
    checked = []
    for path, operations in paths.items():
        for method in operations:
            key = (method.upper(), path)
            if key in PUBLIC:
                continue
            url = path.replace("{", "").replace("}", "")
            response = client.request(method.upper(), url)
            assert response.status_code == 401, f"{key} → {response.status_code}"
            checked.append(key)
    assert ("GET", f"{API_PREFIX}/providers/catalog") in checked
    assert ("GET", f"{API_PREFIX}/auth/me") in checked
