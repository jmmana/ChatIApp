"""Pasarela de IA sobre LiteLLM (docs/PROVEEDORES_IA.md, ADR 0002).

Una sola interfaz (`complete`, `complete_json`, `stream`) para cualquier proveedor del catálogo.
Cada llamada devuelve su uso (tokens, latencia y costo estimado) y los errores se clasifican en
un conjunto cerrado. Los secretos descifrados nunca se escriben en logs ni en excepciones.
"""

import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import litellm
import litellm.exceptions as litellm_exc
from pydantic import BaseModel, ValidationError

from app.db.models import Provider
from app.llm.catalog import get_spec
from app.llm.fake import FAKE_KIND, FakeProvider
from app.security.crypto import decrypt

logger = logging.getLogger(__name__)

ErrorKind = Literal["auth", "quota", "model_not_found", "timeout", "network", "provider_error"]
ERROR_KINDS: tuple[ErrorKind, ...] = (
    "auth",
    "quota",
    "model_not_found",
    "timeout",
    "network",
    "provider_error",
)

_MESSAGES: dict[ErrorKind, str] = {
    "auth": "El proveedor rechazó las credenciales.",
    "quota": "El proveedor rechazó la llamada por cuota o límite de uso.",
    "model_not_found": "El proveedor no reconoce el modelo.",
    "timeout": "El proveedor tardó demasiado en responder.",
    "network": "No se pudo conectar con el proveedor.",
    "provider_error": "El proveedor devolvió un error.",
}

# Campos del catálogo que LiteLLM espera con otro nombre.
_RENAMED = {"aws_region": "aws_region_name"}
DEFAULT_TIMEOUT = 60.0

CompletionFn = Callable[..., Any]


class GatewayError(Exception):
    """Error de la pasarela con su clasificación; el mensaje nunca contiene secretos."""

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message


class InvalidJsonError(GatewayError):
    """El modelo no devolvió JSON válido para el esquema, tras el reintento."""

    def __init__(self, message: str) -> None:
        super().__init__("provider_error", message)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float | None = None

    def __add__(self, other: "Usage") -> "Usage":
        cost = None
        if self.cost_usd is not None or other.cost_usd is not None:
            cost = (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.latency_ms + other.latency_ms,
            cost,
        )


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage


@dataclass(frozen=True)
class JsonCompletion[T: BaseModel]:
    data: T
    usage: Usage


@dataclass(frozen=True)
class StreamEvent:
    """Un trozo de texto; el último evento trae `usage` y un `delta` vacío."""

    delta: str = ""
    usage: Usage | None = None


@dataclass(frozen=True)
class ProviderConfig:
    """Proveedor guardado, con los secretos ya descifrados. No se imprime con `repr`."""

    kind: str
    model: str
    config: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict, repr=False)
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_provider(cls, provider: Provider) -> "ProviderConfig":
        """Arma la configuración desde la fila guardada, descifrando sus secretos."""
        secrets: dict[str, str] = {}
        if provider.secrets_encrypted is not None:
            loaded = json.loads(decrypt(provider.secrets_encrypted))
            secrets = {str(k): str(v) for k, v in loaded.items()}
        params = {
            k: v for k, v in (provider.params or {}).items() if k not in ("tasks", "fallback")
        }
        return cls(provider.kind, provider.model, dict(provider.config or {}), secrets, params)


def build_call_kwargs(provider: ProviderConfig) -> dict[str, Any]:
    """Argumentos de `litellm.completion` desde el proveedor guardado."""
    spec = get_spec(provider.kind)
    if spec is None:
        raise GatewayError("provider_error", f"Tipo de proveedor desconocido: {provider.kind}.")
    model = provider.model
    if not model.startswith(spec.litellm_prefix):
        model = spec.litellm_prefix + model
    kwargs: dict[str, Any] = {"model": model, "drop_params": True, "timeout": DEFAULT_TIMEOUT}
    values = {**provider.config, **provider.secrets}
    for name, value in values.items():
        if value is None or value == "":
            continue
        kwargs[_RENAMED.get(name, name)] = value
    kwargs.update(provider.params)
    return kwargs


def classify_error(exc: BaseException) -> ErrorKind:
    """Clasifica una excepción de LiteLLM (o del transporte) en un `ErrorKind`."""
    # `Timeout` hereda de la excepción de conexión: va primero.
    if isinstance(exc, litellm_exc.Timeout | TimeoutError):
        return "timeout"
    if isinstance(exc, litellm_exc.AuthenticationError | litellm_exc.PermissionDeniedError):
        return "auth"
    if isinstance(exc, litellm_exc.RateLimitError | litellm_exc.BudgetExceededError):
        return "quota"
    if isinstance(exc, litellm_exc.NotFoundError):
        return "model_not_found"
    if isinstance(exc, litellm_exc.APIConnectionError | ConnectionError):
        return "network"
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "quota"
    if status == 404:
        return "model_not_found"
    if status in (408, 504):
        return "timeout"
    return "provider_error"


def scrub(text: str, secrets: dict[str, str]) -> str:
    """Reemplaza los valores secretos que aparezcan en `text`."""
    for value in secrets.values():
        if value and len(value) >= 4:
            text = text.replace(value, "***")
    return text


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _extract_json(text: str) -> str:
    text = text.strip()
    match = _FENCE.match(text)
    return match.group(1) if match else text


class Gateway:
    """Llama a un proveedor guardado. `completion` se inyecta solo en pruebas."""

    def __init__(self, provider: ProviderConfig, *, completion: CompletionFn | None = None) -> None:
        self.provider = provider
        self._completion = completion
        self._fake: FakeProvider | None = None
        if provider.kind == FAKE_KIND:
            self._fake = FakeProvider.from_config(provider.config)

    # --- API pública ---

    def complete(self, messages: list[dict[str, str]], **params: Any) -> Completion:
        """Completa una conversación y devuelve el texto con su uso."""
        started = time.perf_counter()
        if self._fake is not None:
            return self._fake_complete(messages, started)
        response = self._call(messages, params, stream=False)
        text = response.choices[0].message.content or ""
        return Completion(text, self._usage(response, started))

    def complete_json[T: BaseModel](
        self, messages: list[dict[str, str]], schema: type[T], **params: Any
    ) -> JsonCompletion[T]:
        """Completa y valida contra `schema`; reintenta una vez pasando el error al modelo."""
        instruction = (
            "Responde únicamente con un objeto JSON válido, sin texto adicional, que cumpla "
            f"este esquema JSON:\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
        )
        conversation = [{"role": "system", "content": instruction}, *messages]
        total = Usage()
        error = ""
        for attempt in range(2):
            result = self.complete(conversation, **params)
            total = total + result.usage
            try:
                data = schema.model_validate_json(_extract_json(result.text))
                return JsonCompletion(data, total)
            except ValidationError as exc:
                error = _summarize(exc)
            if attempt == 0:
                conversation = [
                    *conversation,
                    {"role": "assistant", "content": result.text},
                    {
                        "role": "user",
                        "content": "Tu respuesta no es válida: "
                        f"{error}\nCorrígela y responde solo con el JSON.",
                    },
                ]
        raise InvalidJsonError(f"El modelo no devolvió JSON válido: {error}")

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]:
        """Emite el texto por trozos; el último evento trae el uso."""
        started = time.perf_counter()
        if self._fake is not None:
            yield from self._fake_stream(messages, started)
            return
        response = self._call(messages, params, stream=True)
        chunks: list[Any] = []
        try:
            for chunk in response:
                chunks.append(chunk)
                choices = getattr(chunk, "choices", None)
                delta = (choices[0].delta.content if choices else None) or ""
                if delta:
                    yield StreamEvent(delta=delta)
        except Exception as exc:
            raise self._wrap(exc) from None
        yield StreamEvent(usage=self._stream_usage(chunks, messages, started))

    # --- Internos ---

    def _call(self, messages: list[dict[str, str]], params: dict[str, Any], *, stream: bool) -> Any:
        completion = self._completion or litellm.completion
        try:
            kwargs = build_call_kwargs(self.provider)
            kwargs.update(params)
            if stream:
                kwargs["stream"] = True
                kwargs["stream_options"] = {"include_usage": True}
            return completion(messages=messages, **kwargs)
        except GatewayError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from None

    def _wrap(self, exc: BaseException) -> GatewayError:
        """Convierte `exc` en `GatewayError` sin secretos y lo registra sin su detalle."""
        kind = classify_error(exc)
        detail = scrub(str(exc), self.provider.secrets)
        logger.warning(
            "Llamada a IA fallida: kind=%s modelo=%s error=%s",
            self.provider.kind,
            self.provider.model,
            kind,
        )
        return GatewayError(kind, f"{_MESSAGES[kind]} ({type(exc).__name__})")

    def _cost(self, response: Any) -> float | None:
        try:
            cost = litellm.completion_cost(completion_response=response)
        except Exception:
            return None
        return float(cost) if cost is not None else None

    def _usage(self, response: Any, started: float) -> Usage:
        usage = getattr(response, "usage", None)
        return Usage(
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - started) * 1000,
            cost_usd=self._cost(response),
        )

    def _stream_usage(
        self, chunks: list[Any], messages: list[dict[str, str]], started: float
    ) -> Usage:
        latency = (time.perf_counter() - started) * 1000
        try:
            full = litellm.stream_chunk_builder(chunks, messages=messages)
        except Exception:
            full = None
        if full is None:
            return Usage(latency_ms=latency)
        usage = self._usage(full, started)
        return Usage(usage.input_tokens, usage.output_tokens, latency, usage.cost_usd)

    def _fake_complete(self, messages: list[dict[str, str]], started: float) -> Completion:
        assert self._fake is not None
        reply = self._fake.reply(messages)
        usage = Usage(
            reply.input_tokens, reply.output_tokens, (time.perf_counter() - started) * 1000, 0.0
        )
        return Completion(reply.text, usage)

    def _fake_stream(self, messages: list[dict[str, str]], started: float) -> Iterator[StreamEvent]:
        assert self._fake is not None
        chunks, reply = self._fake.stream(messages)
        for chunk in chunks:
            yield StreamEvent(delta=chunk)
        latency = (time.perf_counter() - started) * 1000
        yield StreamEvent(usage=Usage(reply.input_tokens, reply.output_tokens, latency, 0.0))


def _summarize(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'raíz'}: {e['msg']}" for e in exc.errors()
    )
