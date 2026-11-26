from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from pydantic import BaseModel

from app.llm.catalog import get_spec
from app.llm.gateway import Gateway, ProviderConfig, build_call_kwargs

SECRET = "clave-de-prueba-1234"

# kind, prefijo, modelo de ejemplo, endpoint internacional por defecto
CASES = [
    ("deepseek", "deepseek/", "deepseek-chat", "https://api.deepseek.com"),
    (
        "qwen",
        "dashscope/",
        "qwen-max",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    ),
    ("kimi", "moonshot/", "kimi-k2-0905-preview", "https://api.moonshot.ai/v1"),
    ("glm", "zai/", "glm-4.6", "https://api.z.ai/api/paas/v4"),
    ("minimax", "minimax/", "MiniMax-M2", "https://api.minimax.io/v1"),
    ("doubao", "volcengine/", "ep-20250101-abcde", "https://ark.cn-beijing.volces.com/api/v3"),
]

CHINA = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "minimax": "https://api.minimaxi.com/v1",
}


class Answer(BaseModel):
    total: int


@pytest.fixture(autouse=True)
def _cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0)


def _api_base(kind: str) -> Any:
    spec = get_spec(kind)
    assert spec is not None
    return next(f for f in spec.fields if f.name == "api_base")


@pytest.mark.parametrize(("kind", "prefix", "model", "endpoint"), CASES)
def test_catalogo_usa_prefijo_y_endpoint_por_defecto(
    kind: str, prefix: str, model: str, endpoint: str
) -> None:
    spec = get_spec(kind)
    assert spec is not None
    assert spec.category == "chinese"
    assert spec.litellm_prefix == prefix
    assert _api_base(kind).default == endpoint


@pytest.mark.parametrize(("kind", "prefix", "model", "endpoint"), CASES)
def test_construye_la_llamada(kind: str, prefix: str, model: str, endpoint: str) -> None:
    provider = ProviderConfig(
        kind=kind, model=model, config={"api_base": endpoint}, secrets={"api_key": SECRET}
    )
    kwargs = build_call_kwargs(provider)
    assert kwargs["model"] == prefix + model
    assert kwargs["api_base"] == endpoint
    assert kwargs["api_key"] == SECRET


@pytest.mark.parametrize(("kind", "china"), CHINA.items())
def test_region_china_cambia_api_base(kind: str, china: str) -> None:
    options = {o.value for o in _api_base(kind).options}
    assert china in options
    assert _api_base(kind).default in options
    provider = ProviderConfig(
        kind=kind, model="modelo", config={"api_base": china}, secrets={"api_key": SECRET}
    )
    assert build_call_kwargs(provider)["api_base"] == china


def test_complete_json_con_modelo_de_razonamiento() -> None:
    """`deepseek-reasoner` separa el razonamiento (`reasoning_content`) del contenido."""
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        message = SimpleNamespace(
            content='{"total": 42}',
            reasoning_content="El usuario pide el total; sumo las ventas y respondo en JSON.",
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=30),
        )

    gateway = Gateway(
        ProviderConfig(kind="deepseek", model="deepseek-reasoner", secrets={"api_key": SECRET}),
        completion=completion,
    )
    result = gateway.complete_json([{"role": "user", "content": "total"}], Answer)
    assert result.data == Answer(total=42)
    assert len(calls) == 1
    assert calls[0]["model"] == "deepseek/deepseek-reasoner"
    assert result.usage.output_tokens == 30
