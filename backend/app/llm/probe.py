"""Probar la conexión de un proveedor y listar sus modelos (docs/PROVEEDORES_IA.md#probar-conexión).

`probe_connection` hace una llamada mínima por la pasarela y clasifica el resultado con los mismos
tipos de error que ella. `list_models` consulta el endpoint de modelos de las APIs que lo ofrecen
(compatibles con OpenAI, Anthropic, Gemini y Ollama); en las demás responde `supported: False`.
Ninguna prueba tarda más de `PROBE_TIMEOUT` segundos y ningún mensaje incluye secretos.
"""

import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.llm.gateway import (
    _MESSAGES,
    CompletionFn,
    ErrorKind,
    Gateway,
    GatewayError,
    ProviderConfig,
    scrub,
)

PROBE_TIMEOUT = 15.0
_PING = [{"role": "user", "content": "Responde solo: ok"}]
_ANTHROPIC_VERSION = "2023-06-01"

# Tipos con endpoint `GET {base}/models` al estilo OpenAI, y su URL base por defecto.
_OPENAI_STYLE: dict[str, str | None] = {
    "openai": "https://api.openai.com/v1",
    "openai_compatible": None,
    "vllm": "http://localhost:8000/v1",
    "lm_studio": "http://localhost:1234/v1",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "xai": "https://api.x.ai/v1",
    "deepseek": "https://api.deepseek.com",
    "openrouter": "https://openrouter.ai/api/v1",
}
_ANTHROPIC_BASE = "https://api.anthropic.com/v1"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_OLLAMA_BASE = "http://localhost:11434"


class ProbeResult(BaseModel):
    ok: bool
    latency_ms: float
    error_kind: ErrorKind | None = None
    message: str | None = None


class ModelsResult(BaseModel):
    supported: bool
    models: list[str] = Field(default_factory=list)
    error_kind: ErrorKind | None = None
    message: str | None = None


def probe_connection(
    provider: ProviderConfig,
    *,
    completion: CompletionFn | None = None,
    timeout: float = PROBE_TIMEOUT,
) -> ProbeResult:
    """Llamada mínima al proveedor; nunca lanza: el fallo se devuelve clasificado."""
    started = time.perf_counter()
    try:
        # Sin reintentos: el tope de `timeout` segundos debe valer para toda la prueba.
        Gateway(provider, completion=completion).complete(
            _PING, max_tokens=16, timeout=timeout, num_retries=0
        )
    except GatewayError as exc:
        return ProbeResult(
            ok=False, latency_ms=_elapsed(started), error_kind=exc.kind, message=exc.message
        )
    return ProbeResult(ok=True, latency_ms=_elapsed(started))


def list_models(
    provider: ProviderConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = PROBE_TIMEOUT,
) -> ModelsResult:
    """Modelos que ofrece el proveedor, o `supported: False` si su API no los lista."""
    request = _models_request(provider)
    if request is None:
        return ModelsResult(supported=False)
    url, headers, params, parse = request
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(url, headers=headers, params=params)
        if response.status_code >= 400:
            kind = _status_kind(response.status_code)
            detail = f"HTTP {response.status_code}"
            return _failure(kind, detail, provider.secrets)
        models = sorted(set(parse(response.json())))
    except httpx.TimeoutException as exc:
        return _failure("timeout", type(exc).__name__, provider.secrets)
    except httpx.HTTPError as exc:
        return _failure("network", type(exc).__name__, provider.secrets)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return _failure("provider_error", "Respuesta inesperada: " + type(exc).__name__, {})
    return ModelsResult(supported=True, models=models)


def _failure(kind: ErrorKind, detail: str, secrets: dict[str, str]) -> ModelsResult:
    return ModelsResult(
        supported=True, error_kind=kind, message=scrub(f"{_MESSAGES[kind]} ({detail})", secrets)
    )


def _status_kind(status: int) -> ErrorKind:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "quota"
    if status == 404:
        return "model_not_found"
    if status in (408, 504):
        return "timeout"
    return "provider_error"


def _elapsed(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _models_request(
    provider: ProviderConfig,
) -> tuple[str, dict[str, str], dict[str, Any], Any] | None:
    """URL, cabeceras, parámetros y lector de la lista de modelos; `None` si no se puede listar."""
    kind = provider.kind
    base = str(provider.config.get("api_base") or "").rstrip("/")
    key = provider.secrets.get("api_key", "")
    if kind in _OPENAI_STYLE:
        base = base or (_OPENAI_STYLE[kind] or "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return f"{base}/models", headers, {}, _parse_openai
    if kind == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": _ANTHROPIC_VERSION}
        return f"{base or _ANTHROPIC_BASE}/models", headers, {"limit": 1000}, _parse_openai
    if kind == "gemini":
        headers = {"x-goog-api-key": key}
        return f"{base or _GEMINI_BASE}/models", headers, {"pageSize": 1000}, _parse_gemini
    if kind == "ollama":
        return f"{base or _OLLAMA_BASE}/api/tags", {}, {}, _parse_ollama
    return None


def _parse_openai(body: Any) -> list[str]:
    """`{"data": [{"id": ...}]}`: OpenAI, Anthropic y servidores compatibles."""
    return [str(item["id"]) for item in body["data"]]


def _parse_gemini(body: Any) -> list[str]:
    """`{"models": [{"name": "models/…", "supportedGenerationMethods": [...]}]}`."""
    names = []
    for item in body.get("models", []):
        if "generateContent" in item.get("supportedGenerationMethods", ["generateContent"]):
            names.append(str(item["name"]).removeprefix("models/"))
    return names


def _parse_ollama(body: Any) -> list[str]:
    """`{"models": [{"name": "llama3.1:latest"}]}`."""
    return [str(item["name"]) for item in body.get("models", [])]
