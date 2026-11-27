from typing import Any

import httpx
import pytest

from app.llm.catalog import get_spec
from app.llm.gateway import ProviderConfig, build_call_kwargs
from app.llm.probe import list_models

LOCAL = {
    "ollama": ("ollama_chat/", "http://localhost:11434"),
    "vllm": ("hosted_vllm/", "http://localhost:8000/v1"),
    "lm_studio": ("lm_studio/", "http://localhost:1234/v1"),
    "openai_compatible": ("openai/", None),
}


def _transport(body: Any, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(("kind", "expected"), LOCAL.items())
def test_catalogo_local(kind: str, expected: tuple[str, str | None]) -> None:
    spec = get_spec(kind)
    assert spec is not None
    assert spec.category == "local"
    assert spec.litellm_prefix == expected[0]
    fields = {f.name: f for f in spec.fields}
    assert fields["api_base"].default == expected[1]
    assert fields["api_key"].required is False


@pytest.mark.parametrize("kind", LOCAL)
def test_prefijo_y_api_base_en_la_llamada(kind: str) -> None:
    provider = ProviderConfig(kind=kind, model="m", config={"api_base": "http://srv:1/v1"})
    kwargs = build_call_kwargs(provider)
    assert kwargs["model"] == LOCAL[kind][0] + "m"
    assert kwargs["api_base"] == "http://srv:1/v1"
    assert "api_key" not in kwargs


def test_ollama_lista_desde_api_tags() -> None:
    seen: list[httpx.Request] = []
    provider = ProviderConfig(kind="ollama", model="m", config={"api_base": "http://srv:11434"})
    result = list_models(provider, transport=_transport({"models": [{"name": "llama3.1"}]}, seen))
    assert result.models == ["llama3.1"]
    assert seen[0].url.path == "/api/tags"


@pytest.mark.parametrize("kind", ["vllm", "lm_studio", "openai_compatible"])
def test_otros_listan_desde_v1_models_sin_clave(kind: str) -> None:
    seen: list[httpx.Request] = []
    provider = ProviderConfig(kind=kind, model="m", config={"api_base": "http://srv:1/v1"})
    result = list_models(provider, transport=_transport({"data": [{"id": "qwen"}]}, seen))
    assert result.models == ["qwen"]
    assert seen[0].url.path == "/v1/models"
    assert "authorization" not in seen[0].headers


def test_api_key_opcional_se_envia_si_existe() -> None:
    seen: list[httpx.Request] = []
    provider = ProviderConfig(
        kind="vllm",
        model="m",
        config={"api_base": "http://srv:1/v1"},
        secrets={"api_key": "clave-de-prueba-1234"},
    )
    list_models(provider, transport=_transport({"data": []}, seen))
    assert seen[0].headers["authorization"] == "Bearer clave-de-prueba-1234"
