"""Trazas OpenTelemetry con exportador OTLP (HTTP) configurable.

Sin `CHATIAPP_OTEL_ENDPOINT` no se instala ningún exportador y los spans son no-op.
"""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.version import __version__

logger = logging.getLogger(__name__)

_provider: TracerProvider | None = None


def traces_url(endpoint: str) -> str:
    """`http://colector:4318` → `http://colector:4318/v1/traces`."""
    base = endpoint.rstrip("/")
    return base if base.endswith("/v1/traces") else f"{base}/v1/traces"


def setup_tracing(endpoint: str | None, service_name: str = "chatiapp") -> TracerProvider | None:
    """Instala el proveedor global con exportador OTLP; devuelve `None` si no hay endpoint."""
    global _provider
    if not endpoint:
        return None
    if _provider is not None:
        return _provider
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name, "service.version": __version__})
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_url(endpoint))))
    trace.set_tracer_provider(provider)
    _provider = provider
    logger.info("Trazas OpenTelemetry activas hacia %s", endpoint)
    return provider


def shutdown_tracing() -> None:
    """Vacía los spans pendientes al apagar la app."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("chatiapp")
