import json
import logging
from types import SimpleNamespace
from typing import Any

import httpx
import litellm
import pytest
from pydantic import BaseModel

from app.db.models import Provider
from app.llm.gateway import (
    Gateway,
    GatewayError,
    InvalidJsonError,
    ProviderConfig,
    build_call_kwargs,
    classify_error,
)
from app.security.crypto import encrypt

SECRET = "clave-de-prueba-1234"
MESSAGES = [{"role": "user", "content": "cuánto vendí hoy"}]


class Answer(BaseModel):
    total: int
    moneda: str


def _fake(**config: Any) -> Gateway:
    return Gateway(ProviderConfig(kind="fake", model="fake-1", config=config))


def _response(text: str, prompt: int = 7, completion: int = 3) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


@pytest.fixture(autouse=True)
def _cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.002)


def _openai(completion: Any, **kwargs: Any) -> Gateway:
    provider = ProviderConfig(
        kind="openai",
        model="gpt-4o",
        config={"organization": "org-1"},
        secrets={"api_key": SECRET},
        params=kwargs,
    )
    return Gateway(provider, completion=completion)


# --- Construcción de la llamada ---


def test_kwargs_desde_proveedor_guardado() -> None:
    provider = ProviderConfig(
        kind="qwen",
        model="qwen-max",
        config={"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        secrets={"api_key": SECRET},
        params={"temperature": 0.1},
    )
    kwargs = build_call_kwargs(provider)
    assert kwargs["model"] == "dashscope/qwen-max"
    assert kwargs["api_key"] == SECRET
    assert kwargs["api_base"].endswith("/compatible-mode/v1")
    assert kwargs["temperature"] == 0.1
    assert kwargs["drop_params"] is True


def test_kwargs_no_repite_prefijo_y_renombra_region() -> None:
    provider = ProviderConfig(
        kind="bedrock", model="bedrock/amazon.nova-pro-v1:0", config={"aws_region": "us-east-1"}
    )
    kwargs = build_call_kwargs(provider)
    assert kwargs["model"] == "bedrock/amazon.nova-pro-v1:0"
    assert kwargs["aws_region_name"] == "us-east-1"


def test_kind_desconocido() -> None:
    with pytest.raises(GatewayError) as info:
        build_call_kwargs(ProviderConfig(kind="no-existe", model="m"))
    assert info.value.kind == "provider_error"


def test_desde_fila_descifra_secretos() -> None:
    row = Provider(
        name="p",
        kind="openai",
        model="gpt-4o",
        config={},
        params={"tasks": ["sql"], "fallback": 0, "temperature": 0},
        secrets_encrypted=encrypt(json.dumps({"api_key": SECRET})),
    )
    config = ProviderConfig.from_provider(row)
    assert config.secrets == {"api_key": SECRET}
    assert config.params == {"temperature": 0}
    assert SECRET not in repr(config)


# --- complete / stream con LiteLLM simulado ---


def test_complete_pasa_argumentos_y_devuelve_uso() -> None:
    seen: dict[str, Any] = {}

    def completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return _response("hola")

    result = _openai(completion, temperature=0).complete(MESSAGES)
    assert seen["model"] == "openai/gpt-4o"
    assert seen["api_key"] == SECRET
    assert seen["drop_params"] is True
    assert seen["messages"] == MESSAGES
    assert result.text == "hola"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (7, 3)
    assert result.usage.cost_usd == 0.002
    assert result.usage.latency_ms >= 0


def test_costo_desconocido_es_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_: Any) -> float:
        raise ValueError("modelo sin precio")

    monkeypatch.setattr(litellm, "completion_cost", boom)
    result = _openai(lambda **_: _response("x")).complete(MESSAGES)
    assert result.usage.cost_usd is None


def test_stream_emite_trozos_y_uso_final(monkeypatch: pytest.MonkeyPatch) -> None:
    def chunk(text: str | None) -> Any:
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])

    seen: dict[str, Any] = {}

    def completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return iter([chunk("ho"), chunk("la"), chunk(None)])

    monkeypatch.setattr(litellm, "stream_chunk_builder", lambda chunks, messages: _response("hola"))
    events = list(_openai(completion).stream(MESSAGES))
    assert seen["stream"] is True
    assert [e.delta for e in events[:-1]] == ["ho", "la"]
    assert events[-1].delta == ""
    assert events[-1].usage is not None
    assert events[-1].usage.output_tokens == 3
    assert events[-1].usage.cost_usd == 0.002


# --- JSON ---


def test_complete_json_valida() -> None:
    gateway = _fake(responses=['{"total": 10, "moneda": "USD"}'])
    result = gateway.complete_json(MESSAGES, Answer)
    assert result.data == Answer(total=10, moneda="USD")
    assert result.usage.output_tokens > 0


def test_complete_json_acepta_bloque_de_codigo() -> None:
    gateway = _fake(responses=['```json\n{"total": 1, "moneda": "EUR"}\n```'])
    assert gateway.complete_json(MESSAGES, Answer).data.total == 1


def test_complete_json_reintenta_una_vez_con_el_error() -> None:
    sent: list[list[dict[str, str]]] = []
    replies = iter(["no es json", '{"total": 5, "moneda": "MXN"}'])

    def completion(**kwargs: Any) -> Any:
        sent.append(kwargs["messages"])
        return _response(next(replies))

    result = _openai(completion).complete_json(MESSAGES, Answer)
    assert result.data.total == 5
    assert len(sent) == 2
    assert "no es válida" in sent[1][-1]["content"]
    assert result.usage.input_tokens == 14  # suma de los dos intentos


def test_complete_json_falla_tras_un_reintento() -> None:
    calls = 0

    def completion(**_: Any) -> Any:
        nonlocal calls
        calls += 1
        return _response('{"total": "x"}')

    with pytest.raises(InvalidJsonError):
        _openai(completion).complete_json(MESSAGES, Answer)
    assert calls == 2


# --- Errores ---


_REQUEST = httpx.Request("POST", "https://api.example.test/v1/chat")
_FORBIDDEN = httpx.Response(403, request=_REQUEST)


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (litellm.AuthenticationError("x", "openai", "gpt-4o"), "auth"),
        (litellm.PermissionDeniedError("x", "openai", "gpt-4o", _FORBIDDEN), "auth"),
        (litellm.RateLimitError("x", "openai", "gpt-4o"), "quota"),
        (litellm.NotFoundError("x", "gpt-4o", "openai"), "model_not_found"),
        (litellm.Timeout("x", "gpt-4o", "openai"), "timeout"),
        (litellm.APIConnectionError("x", "openai", "gpt-4o", _REQUEST), "network"),
        (ConnectionError("x"), "network"),
        (litellm.InternalServerError("x", "openai", "gpt-4o"), "provider_error"),
        (ValueError("x"), "provider_error"),
    ],
)
def test_clasifica_errores(exc: Exception, kind: str) -> None:
    assert classify_error(exc) == kind


def test_error_se_clasifica_en_la_llamada() -> None:
    def completion(**_: Any) -> Any:
        raise litellm.AuthenticationError("clave mala", "openai", "gpt-4o")

    with pytest.raises(GatewayError) as info:
        _openai(completion).complete(MESSAGES)
    assert info.value.kind == "auth"


# --- Secretos ---


def test_secretos_no_aparecen_en_logs_ni_excepciones(caplog: pytest.LogCaptureFixture) -> None:
    def completion(**_: Any) -> Any:
        raise litellm.AuthenticationError(f"Incorrect API key: {SECRET}", "openai", "gpt-4o")

    caplog.set_level(logging.DEBUG)
    with pytest.raises(GatewayError) as info:
        _openai(completion).complete(MESSAGES)
    assert SECRET not in str(info.value)
    assert SECRET not in repr(info.value)
    assert info.value.__cause__ is None
    assert SECRET not in caplog.text
    assert "auth" in caplog.text


def test_secretos_no_aparecen_en_errores_de_stream(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> Any:
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="a"))])
        raise litellm.APIConnectionError(f"fallo con {SECRET}", "openai", "gpt-4o", _REQUEST)

    caplog.set_level(logging.DEBUG)
    gateway = _openai(lambda **_: broken())
    with pytest.raises(GatewayError) as info:
        list(gateway.stream(MESSAGES))
    assert info.value.kind == "network"
    assert SECRET not in str(info.value)
    assert SECRET not in caplog.text


# --- Proveedor simulado ---


def test_fake_complete_es_determinista() -> None:
    first = _fake(responses=["uno", "dos"]).complete(MESSAGES)
    again = _fake(responses=["uno", "dos"]).complete(MESSAGES)
    assert first.text == again.text == "uno"
    assert first.usage.input_tokens == again.usage.input_tokens == 3
    assert first.usage.cost_usd == 0.0


def test_fake_respuestas_en_orden_y_cicla() -> None:
    gateway = _fake(responses=["uno", "dos"])
    assert [gateway.complete(MESSAGES).text for _ in range(3)] == ["uno", "dos", "uno"]


def test_fake_stream() -> None:
    events = list(_fake(responses=["dos palabras aquí"]).stream(MESSAGES))
    assert "".join(e.delta for e in events) == "dos palabras aquí"
    assert events[-1].usage is not None
    assert events[-1].usage.output_tokens == 3


def test_fake_error_configurado() -> None:
    with pytest.raises(GatewayError) as info:
        _fake(error="quota").complete(MESSAGES)
    assert info.value.kind == "quota"


def test_fake_falla_solo_las_primeras_llamadas() -> None:
    gateway = _fake(error="timeout", fail_first=1, responses=["ok"])
    with pytest.raises(GatewayError):
        gateway.complete(MESSAGES)
    assert gateway.complete(MESSAGES).text == "ok"
