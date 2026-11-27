from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.observability.tracing import traces_url
from app.settings.env import get_settings


@pytest.fixture(autouse=True)
def _limpia_ajustes() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


TOKEN = "token-de-prueba-1234"


def test_metrics_sin_token_configurado_responde_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHATIAPP_METRICS_TOKEN", raising=False)
    client = TestClient(create_app())

    assert client.get("/metrics").status_code == 404
    assert client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 404


def test_metrics_expone_las_series_en_formato_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_METRICS_TOKEN", TOKEN)
    response = TestClient(create_app()).get(
        "/metrics", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    for name in (
        "chatiapp_turns",
        "chatiapp_guard_rejections",
        "chatiapp_provider_errors",
        "chatiapp_turn_duration_seconds",
        "chatiapp_llm_cost_usd",
    ):
        assert name in response.text


def test_metrics_exige_el_token_si_esta_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_METRICS_TOKEN", TOKEN)
    client = TestClient(create_app())

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer otro"}).status_code == 401
    ok = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200


def test_la_url_de_trazas_agrega_la_ruta_otlp() -> None:
    assert traces_url("http://colector:4318") == "http://colector:4318/v1/traces"
    assert traces_url("http://colector:4318/") == "http://colector:4318/v1/traces"
    assert traces_url("http://c:4318/v1/traces") == "http://c:4318/v1/traces"
