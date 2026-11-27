"""Aclaraciones del agente (docs/FLUJO_CONVERSACIONAL.md#cuándo-pregunta).

Preguntar en vez de adivinar cuando falta un dato: período faltante o no reconocido, métrica
ambigua y dimensión no permitida (la entidad ambigua se resuelve en `entities.py`). Este módulo
es código puro, sin IA ni red: redacta las preguntas, aplica el tope de aclaraciones seguidas y
retoma el plan pendiente (`conversation.last_plan`) con la respuesta del usuario, sea un botón o
texto escrito.

La comprobación de `requires_period` vive aquí; el catálogo solo verifica métrica, dimensiones
y filtros.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.agent.plan import Plan, PlanFilter
from app.db.models import Message
from app.engine.catalog import Catalog, CatalogError, normalize
from app.engine.periods import PeriodConfig, resolve_period
from app.semantic.schema import Metric, SemanticModel

MAX_CLARIFICATIONS = 2
PERIOD_OPTIONS = ["Hoy", "Esta semana", "Este mes", "Mes pasado", "Este año", "Últimos 30 días"]
ALL_OPTION = "Todas"
ENTITY_SLOT_PREFIX = "entity:"  # el slot de una entidad ambigua es «entity:tabla.columna»
_NO_BREAKDOWN = {"ninguna", "ninguno", "no", "sin desglose", "sin dimension", "ya no"}


@dataclass(frozen=True)
class Question:
    """Una aclaración lista para emitirse: pregunta, opciones de un clic y dato que falta."""

    question: str
    options: list[str]
    slot: str


@dataclass(frozen=True)
class Pending:
    """La aclaración que quedó sin responder al final de la conversación."""

    slot: str | None
    options: list[str]


# --------------------------------------------------------------------------- preguntas


def period_question(metric: Metric, text: str | None) -> Question:
    """Falta el período (o no se reconoce): ofrece los seis períodos habituales."""
    if text:
        question = f"No entendí el período «{text}». ¿Cuál de estos prefieres?"
    else:
        question = f"¿De qué período quieres ver {metric.label.lower()}?"
    return Question(question, list(PERIOD_OPTIONS), "period")


def metric_question(candidates: Sequence[Metric]) -> Question:
    """Dos o más métricas plausibles: las ofrece con su descripción."""
    lines = [f"- {m.label}: {m.description or m.name}" for m in candidates]
    question = "¿A cuál de estas métricas te refieres?\n" + "\n".join(lines)
    return Question(question, [m.label for m in candidates], "metric")


def dimension_question(metric: str, dimension: str, allowed: Sequence[str]) -> Question:
    """Dimensión no permitida: dice cuáles sí hay para la métrica."""
    shown = ", ".join(allowed) or "ninguna"
    question = (
        f"No puedo desglosar «{metric}» por «{dimension}». "
        f"Las dimensiones disponibles son: {shown}. ¿Quieres usar alguna?"
    )
    return Question(question, list(allowed), "dimension")


def assumed_period_note(period_text: str) -> str:
    return f"Asumí «{period_text}»; dime si quieres otro período."


def should_assume_default(previous_clarifications: int, metric: Metric) -> bool:
    """Tras 2 aclaraciones seguidas se usa el `default_period` de la métrica, si existe."""
    return previous_clarifications >= MAX_CLARIFICATIONS and bool(metric.default_period)


# --------------------------------------------------------------------------- conversación


def _clarification_event(message: Message) -> dict[str, Any] | None:
    for event in message.events or []:
        if isinstance(event, dict) and event.get("type") == "clarification":
            data = event.get("data")
            return data if isinstance(data, dict) else {}
    return None


def trailing_clarifications(messages: Sequence[Message]) -> int:
    """Aclaraciones seguidas al final de la conversación (mensajes del asistente)."""
    count = 0
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        if _clarification_event(message) is None:
            break
        count += 1
    return count


def pending_clarification(messages: Sequence[Message]) -> Pending | None:
    """La aclaración del último mensaje del asistente, si el turno anterior terminó preguntando."""
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        data = _clarification_event(message)
        if data is None:
            return None
        slot = data.get("slot")
        options = [str(o) for o in data.get("options") or []]
        return Pending(slot if isinstance(slot, str) else None, options)
    return None


# --------------------------------------------------------------------------- respuesta


def _match_option(reply: str, options: Sequence[str]) -> str | None:
    """La opción que el usuario eligió, con el botón (texto exacto) o escribiéndola."""
    wanted = normalize(reply).strip(" .!¿?")
    for option in options:
        if normalize(option) == wanted:
            return option
    padded = f" {wanted} "
    hits = [o for o in options if f" {normalize(o)} " in padded]
    return hits[0] if len(hits) == 1 else None


def apply_reply(
    plan: Plan,
    pending: Pending,
    reply: str,
    model: SemanticModel,
    config: PeriodConfig,
    now: datetime,
) -> Plan | None:
    """Retoma el plan pendiente con la respuesta; `None` si no resuelve el dato preguntado.

    No llama a la IA: el plan se completa con el dato y el resto queda igual. Si la respuesta
    no se entiende, quien llama puede volver a entender el turno con el plan pendiente.
    """
    if plan.intent != "metric" or not reply.strip():
        return None
    text = reply.strip()
    if pending.slot == "period":
        if resolve_period(text, config, now) is None:
            return None
        return plan.model_copy(update={"period_text": text})
    if pending.slot == "metric":
        choice = _match_option(text, pending.options) or text
        try:
            metric = Catalog(model).find_metric(choice)
        except CatalogError:  # desconocida o todavía ambigua
            return None
        return plan.model_copy(update={"metric": metric.name})
    if pending.slot == "dimension":
        kept = [d for d in plan.dimensions if d in pending.options]
        if normalize(text).strip(" .!") in _NO_BREAKDOWN:
            return plan.model_copy(update={"dimensions": kept})
        picked = _match_option(text, pending.options)
        if picked is None:
            return None
        dimensions = kept if picked in kept else [*kept, picked]
        return plan.model_copy(update={"dimensions": dimensions})
    if pending.slot and pending.slot.startswith(ENTITY_SLOT_PREFIX):
        return _apply_entity_reply(plan, pending, pending.slot[len(ENTITY_SLOT_PREFIX) :], text)
    return None


def _apply_entity_reply(plan: Plan, pending: Pending, field: str, text: str) -> Plan | None:
    """Reemplaza el filtro de `field` por el valor elegido, o por todos los de la lista."""
    values = [o for o in pending.options if o != ALL_OPTION]
    if ALL_OPTION in pending.options and normalize(text).strip(" .!") == normalize(ALL_OPTION):
        chosen = values
    else:
        picked = _match_option(text, values)
        if picked is None:
            return None
        chosen = [picked]
    column = field.rpartition(".")[2]
    replaced = False
    filters: list[PlanFilter] = []
    for item in plan.filters:
        if not replaced and item.field in (field, column):
            if len(chosen) == 1:
                item = PlanFilter(field=item.field, op="=", value=chosen[0])
            else:
                many: list[str | int | float] = list(chosen)
                item = PlanFilter(field=item.field, op="in", value=many)
            replaced = True
        filters.append(item)
    return plan.model_copy(update={"filters": filters}) if replaced else None
