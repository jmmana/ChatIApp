"""Métricas Prometheus de ChatIApp, expuestas en `/metrics`.

Las etiquetas son de cardinalidad baja (resultado, etapa, tipo de proveedor): nunca llevan
usuario, pregunta, SQL ni datos.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

REGISTRY = CollectorRegistry(auto_describe=True)

_SECONDS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 90.0)

TURNS = Counter(
    "chatiapp_turns_total",
    "Turnos terminados, por resultado (ok, clarification, error).",
    ["outcome"],
    registry=REGISTRY,
)
GUARD_REJECTIONS = Counter(
    "chatiapp_guard_rejections_total",
    "SQL rechazado por el guardián (cada rechazo cuenta, aunque luego se repare).",
    registry=REGISTRY,
)
PROVIDER_ERRORS = Counter(
    "chatiapp_provider_errors_total",
    "Fallos de proveedores de IA, por tipo de proveedor.",
    ["provider"],
    registry=REGISTRY,
)
TURN_SECONDS = Histogram(
    "chatiapp_turn_duration_seconds",
    "Duración de un turno completo.",
    buckets=_SECONDS,
    registry=REGISTRY,
)
STAGE_SECONDS = Histogram(
    "chatiapp_stage_duration_seconds",
    "Duración de cada etapa del turno.",
    ["stage"],
    buckets=_SECONDS,
    registry=REGISTRY,
)
TOKENS = Counter(
    "chatiapp_llm_tokens_total",
    "Tokens consumidos en proveedores de IA.",
    ["direction"],
    registry=REGISTRY,
)
COST_USD = Counter(
    "chatiapp_llm_cost_usd_total",
    "Costo acumulado de las llamadas a IA, en dólares.",
    registry=REGISTRY,
)


def render() -> tuple[bytes, str]:
    """Cuerpo y `Content-Type` de la exposición en texto de Prometheus."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
