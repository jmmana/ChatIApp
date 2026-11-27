from types import SimpleNamespace
from typing import Any

import httpx
import litellm
import pytest

from app.llm.gateway import ProviderConfig
from app.llm.probe import PROBE_TIMEOUT, list_models, probe_connection

SECRET = "clave-de-prueba-1234"
STATUS_KINDS = [
    (401, "auth"),
    (403, "auth"),
    (429, "quota"),
    (404, "model_not_found"),
    (500, "provider_error"),
]


@pytest.fixture(autouse=True)
def _cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0)


def _provider(kind: str = "openai", **config: Any) -> ProviderConfig:
    return ProviderConfig(kind=kind, model="gpt-4o", config=config, secrets={"api_key": SECRET})


def _ok_completion(**_: Any) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
    )


def _http_error(status: int) -> Any:
    def completion(**_: Any) -> Any:
        request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        response = httpx.Response(status, request=request, json={"error": SECRET})
        raise litellm.exceptions.APIError(
            status_code=status,
            message=f"fallo con {SECRET}",
            llm_provider="openai",
            model="gpt-4o",
            request=request,
        ) from httpx.HTTPStatusError("x", request=request, response=response)

    return completion


# --- probe_connection ---


def test_conexion_exitosa() -> None:
    result = probe_connection(_provider(), completion=_ok_completion)
    assert result.ok is True
    assert result.latency_ms >= 0
    assert result.error_kind is None


def test_llamada_minima_con_tope_de_15_segundos() -> None:
    seen: dict[str, Any] = {}

    def completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return _ok_completion()

    probe_connection(_provider(), completion=completion)
    assert seen["timeout"] == PROBE_TIMEOUT == 15.0
    assert seen["max_tokens"] <= 16
    assert seen["num_retries"] == 0


@pytest.mark.parametrize(("status", "kind"), STATUS_KINDS)
def test_errores_http_clasificados(status: int, kind: str) -> None:
    result = probe_connection(_provider(), completion=_http_error(status))
    assert result.ok is False
    assert result.error_kind == kind
    assert result.message
    assert SECRET not in result.message


def test_timeout_y_red() -> None:
    def timeout(**_: Any) -> Any:
        raise litellm.exceptions.Timeout("lento", model="gpt-4o", llm_provider="openai")

    def network(**_: Any) -> Any:
        raise ConnectionError("sin DNS")

    assert probe_connection(_provider(), completion=timeout).error_kind == "timeout"
    assert probe_connection(_provider(), completion=network).error_kind == "network"


def test_proveedor_simulado() -> None:
    ok = probe_connection(ProviderConfig(kind="fake", model="fake-1"))
    assert ok.ok is True
    fail = probe_connection(ProviderConfig(kind="fake", model="fake-1", config={"error": "auth"}))
    assert (fail.ok, fail.error_kind) == (False, "auth")


# --- list_models ---


def _transport(
    status: int, body: Any, seen: list[httpx.Request] | None = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def test_modelos_openai() -> None:
    seen: list[httpx.Request] = []
    body = {"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}
    result = list_models(_provider(), transport=_transport(200, body, seen))
    assert result.supported is True
    assert result.models == ["gpt-4o", "gpt-4o-mini"]
    assert seen[0].url.path == "/v1/models"
    assert seen[0].headers["authorization"] == f"Bearer {SECRET}"


def test_modelos_compatible_usa_api_base() -> None:
    seen: list[httpx.Request] = []
    provider = _provider("openai_compatible", api_base="http://servidor:8000/v1/")
    result = list_models(provider, transport=_transport(200, {"data": [{"id": "m1"}]}, seen))
    assert result.models == ["m1"]
    assert str(seen[0].url) == "http://servidor:8000/v1/models"


def test_modelos_anthropic() -> None:
    seen: list[httpx.Request] = []
    body = {"data": [{"id": "claude-sonnet-5-5"}]}
    result = list_models(_provider("anthropic"), transport=_transport(200, body, seen))
    assert result.models == ["claude-sonnet-5-5"]
    assert seen[0].headers["x-api-key"] == SECRET
    assert "anthropic-version" in seen[0].headers


def test_modelos_gemini_solo_los_que_generan_contenido() -> None:
    body = {
        "models": [
            {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
        ]
    }
    result = list_models(_provider("gemini"), transport=_transport(200, body))
    assert result.models == ["gemini-2.5-pro"]


def test_modelos_ollama() -> None:
    seen: list[httpx.Request] = []
    body = {"models": [{"name": "llama3.1:latest"}, {"name": "qwen2.5:7b"}]}
    provider = _provider("ollama", api_base="http://localhost:11434")
    result = list_models(provider, transport=_transport(200, body, seen))
    assert result.models == ["llama3.1:latest", "qwen2.5:7b"]
    assert seen[0].url.path == "/api/tags"
    assert seen[0].headers["authorization"] == f"Bearer {SECRET}"


def test_modelos_ollama_sin_clave_no_envia_authorization() -> None:
    seen: list[httpx.Request] = []
    provider = ProviderConfig(
        kind="ollama", model="llama3.1", config={"api_base": "http://localhost:11434"}, secrets={}
    )
    list_models(provider, transport=_transport(200, {"models": []}, seen))
    assert "authorization" not in seen[0].headers


@pytest.mark.parametrize("kind", ["bedrock", "azure_openai", "vertex_ai", "doubao"])
def test_modelos_no_soportado(kind: str) -> None:
    result = list_models(_provider(kind), transport=_transport(500, {}))
    assert result.supported is False
    assert result.models == []


@pytest.mark.parametrize(("status", "kind"), STATUS_KINDS)
def test_modelos_errores_http(status: int, kind: str) -> None:
    result = list_models(_provider(), transport=_transport(status, {"error": SECRET}))
    assert result.supported is True
    assert result.error_kind == kind
    assert result.message
    assert SECRET not in result.message


def test_modelos_timeout_y_red() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    def network(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin DNS", request=request)

    assert list_models(_provider(), transport=httpx.MockTransport(timeout)).error_kind == "timeout"
    assert list_models(_provider(), transport=httpx.MockTransport(network)).error_kind == "network"


def test_modelos_respuesta_inesperada() -> None:
    result = list_models(_provider(), transport=_transport(200, {"otra": "cosa"}))
    assert result.error_kind == "provider_error"
