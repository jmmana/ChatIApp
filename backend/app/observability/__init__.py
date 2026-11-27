"""Observabilidad: logs JSON, trazas OpenTelemetry y métricas Prometheus.

Ver docs/OBSERVABILIDAD.md.
"""

from app.observability.logs import JsonFormatter, LogScope, configure_logging, redact
from app.observability.metrics import render as render_metrics
from app.observability.tracing import setup_tracing, shutdown_tracing
from app.observability.turn import Totals, TurnObserver

__all__ = [
    "JsonFormatter",
    "LogScope",
    "Totals",
    "TurnObserver",
    "configure_logging",
    "redact",
    "render_metrics",
    "setup_tracing",
    "shutdown_tracing",
]
