"""Planificador: convierte la pregunta en un `Plan` validado con la pasarela de IA.

Un JSON inválido o que no cumple el esquema se reintenta una vez con el error (lo hace
`Gateway.complete_json`); si vuelve a fallar, se lanza `PlannerError`.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agent.plan import Plan
from app.llm.gateway import Gateway, GatewayError, InvalidJsonError, Usage
from app.semantic.context import Privacy, build_context
from app.semantic.schema import SemanticModel

PROMPT_PATH = Path(__file__).parent / "prompts" / "planner.md"
MAX_HISTORY = 6
_MAX_MESSAGE_CHARS = 1000

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


class PlannerError(Exception):
    """El planificador no pudo producir un plan; `kind` distingue la causa."""

    def __init__(self, kind: Literal["invalid_plan", "gateway"], message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class PlanResult:
    plan: Plan
    usage: Usage


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def escape_data(text: str) -> str:
    """Escapa `&`, `<` y `>` para que un dato no pueda abrir ni cerrar etiquetas del prompt."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _history_text(history: list[Turn]) -> str:
    recent = history[-MAX_HISTORY:]
    if not recent:
        return "(sin historial)"
    return "\n".join(
        f"- {t.role}: {escape_data(' '.join(t.content.split())[:_MAX_MESSAGE_CHARS])}"
        for t in recent
    )


def render_prompt(
    model: SemanticModel,
    question: str,
    *,
    now: datetime,
    history: list[Turn] | None = None,
    last_plan: Plan | None = None,
    privacy: Privacy = "schema",
    role: str | None = None,
    max_context_tokens: int | None = None,
) -> str:
    """Prompt del sistema: instrucciones, contexto semántico, fecha, historial y último plan."""
    tz_name = model.settings.timezone
    zone = _zone(tz_name)
    local = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    values = {
        "contexto_semantico": build_context(
            model, question, privacy=privacy, role=role, max_tokens=max_context_tokens
        ),
        "fecha_actual": f"{_WEEKDAYS[local.weekday()]} {local.date().isoformat()}",
        "zona_horaria": tz_name,
        "historial": _history_text(history or []),
        "ultimo_plan": (
            escape_data(json.dumps(last_plan.model_dump(), ensure_ascii=False))
            if last_plan is not None
            else "(ninguno)"
        ),
    }
    parts = PROMPT_PATH.read_text(encoding="utf-8").split("{{")
    out = [parts[0]]
    # Una sola pasada: el texto insertado no se vuelve a interpretar como marcador.
    for part in parts[1:]:
        key, sep, rest = part.partition("}}")
        out.append(values[key] + rest if sep and key in values else "{{" + part)
    return "".join(out)


def plan_question(
    gateway: Gateway,
    model: SemanticModel,
    question: str,
    *,
    now: datetime,
    history: list[Turn] | None = None,
    last_plan: Plan | None = None,
    privacy: Privacy = "schema",
    role: str | None = None,
    max_context_tokens: int | None = None,
) -> PlanResult:
    """Entiende la pregunta y devuelve el plan validado con el uso de IA acumulado."""
    system = render_prompt(
        model,
        question,
        now=now,
        history=history,
        last_plan=last_plan,
        privacy=privacy,
        role=role,
        max_context_tokens=max_context_tokens,
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    try:
        result = gateway.complete_json(messages, Plan)
    except InvalidJsonError as exc:
        message = f"No se pudo entender la pregunta: {exc.message}"
        raise PlannerError("invalid_plan", message) from exc
    except GatewayError as exc:
        raise PlannerError("gateway", exc.message) from exc
    return PlanResult(result.data, result.usage)
