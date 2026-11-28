"""Construcción de la llamada de LiteLLM para cada plataforma cloud, sin red."""

import json
from typing import Any

import pytest

from app.llm.catalog import get_spec
from app.llm.gateway import Gateway, GatewayError, ProviderConfig, build_call_kwargs

KEY = "clave-de-prueba-1234"
SERVICE_ACCOUNT = json.dumps({"type": "service_account", "project_id": "mi-proyecto"})


def _kwargs(
    kind: str,
    model: str,
    config: dict[str, Any] | None = None,
    secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    provider = ProviderConfig(kind=kind, model=model, config=config or {}, secrets=secrets or {})
    return build_call_kwargs(provider)


def test_bedrock_con_llaves() -> None:
    kwargs = _kwargs(
        "bedrock",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        config={"aws_region": "us-west-2", "aws_access_key_id": "id-de-prueba"},
        secrets={"aws_secret_access_key": KEY},
    )
    assert kwargs["model"] == "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
    assert kwargs["aws_region_name"] == "us-west-2"
    assert kwargs["aws_access_key_id"] == "id-de-prueba"
    assert kwargs["aws_secret_access_key"] == KEY


def test_bedrock_con_rol_iam_no_envia_llaves() -> None:
    kwargs = _kwargs(
        "bedrock",
        "amazon.nova-pro-v1:0",
        config={"aws_region": "us-east-1", "aws_access_key_id": ""},
    )
    assert kwargs["aws_region_name"] == "us-east-1"
    assert "aws_access_key_id" not in kwargs
    assert "aws_secret_access_key" not in kwargs


def test_bedrock_perfil_de_inferencia() -> None:
    kwargs = _kwargs(
        "bedrock",
        "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        config={"aws_region": "us-east-1"},
    )
    assert kwargs["model"] == "bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0"
    arn = "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/abc"
    kwargs = _kwargs("bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0", {"model_id": arn})
    assert kwargs["model_id"] == arn


def test_azure_openai() -> None:
    kwargs = _kwargs(
        "azure_openai",
        "mi-deployment",
        config={"api_base": "https://mi-recurso.openai.azure.com", "api_version": "2024-10-21"},
        secrets={"api_key": KEY},
    )
    assert kwargs["model"] == "azure/mi-deployment"
    assert kwargs["api_base"] == "https://mi-recurso.openai.azure.com"
    assert kwargs["api_version"] == "2024-10-21"
    assert kwargs["api_key"] == KEY


def test_azure_ai_foundry() -> None:
    kwargs = _kwargs(
        "azure_ai",
        "Llama-3.3-70B-Instruct",
        config={"api_base": "https://mi-proyecto.services.ai.azure.com"},
        secrets={"api_key": KEY},
    )
    assert kwargs["model"] == "azure_ai/Llama-3.3-70B-Instruct"
    assert kwargs["api_base"] == "https://mi-proyecto.services.ai.azure.com"
    assert kwargs["api_key"] == KEY


def test_vertex_ai() -> None:
    kwargs = _kwargs(
        "vertex_ai",
        "gemini-2.5-pro",
        config={"vertex_project": "mi-proyecto", "vertex_location": "europe-west4"},
        secrets={"vertex_credentials": SERVICE_ACCOUNT},
    )
    assert kwargs["model"] == "vertex_ai/gemini-2.5-pro"
    assert kwargs["vertex_project"] == "mi-proyecto"
    assert kwargs["vertex_location"] == "europe-west4"
    assert kwargs["vertex_credentials"] == SERVICE_ACCOUNT


def test_vertex_guarda_la_cuenta_de_servicio_como_secreto() -> None:
    spec = get_spec("vertex_ai")
    assert spec is not None
    field = next(f for f in spec.fields if f.name == "vertex_credentials")
    assert field.type == "secret"


@pytest.mark.parametrize(
    ("kind", "model", "expected"),
    [
        ("openrouter", "anthropic/claude-sonnet-5-5", "openrouter/anthropic/claude-sonnet-5-5"),
    ],
)
def test_agregador(kind: str, model: str, expected: str) -> None:
    kwargs = _kwargs(kind, model, secrets={"api_key": KEY})
    assert kwargs["model"] == expected
    assert kwargs["api_key"] == KEY


def test_gateway_entrega_los_argumentos_a_litellm() -> None:
    seen: dict[str, Any] = {}

    def completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        raise RuntimeError("sin red")

    provider = ProviderConfig(
        kind="vertex_ai",
        model="gemini-2.5-flash",
        config={"vertex_project": "p", "vertex_location": "us-central1"},
        secrets={"vertex_credentials": SERVICE_ACCOUNT},
    )
    with pytest.raises(GatewayError):
        Gateway(provider, completion=completion).complete([{"role": "user", "content": "hola"}])
    assert seen["model"] == "vertex_ai/gemini-2.5-flash"
    assert seen["vertex_credentials"] == SERVICE_ACCOUNT
