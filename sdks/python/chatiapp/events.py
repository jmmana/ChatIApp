"""Eventos SSE tipados de `POST /api/v1/chat/stream` (docs/FLUJO_CONVERSACIONAL.md)."""

import json
from collections.abc import Iterable, Iterator
from typing import Any, Literal, cast

from pydantic import BaseModel, ValidationError

StepStatus = Literal["running", "done", "warning", "error"]
Scalar = str | int | float | bool | None


class TurnStartedData(BaseModel):
    turn_id: str
    conversation_id: str


class StepData(BaseModel):
    id: str
    label: str
    status: StepStatus
    detail: str | None = None


class ReasoningData(BaseModel):
    text: str


class ClarificationData(BaseModel):
    question: str
    options: list[str] = []
    slot: str | None = None


class PeriodData(BaseModel):
    label: str
    start: str
    end_exclusive: str


class SqlData(BaseModel):
    sql: str
    dialect: str
    origin: Literal["catalog", "llm"]
    summary_table: str | None = None
    filters_applied: list[str] = []
    period: PeriodData | None = None
    metric: str | None = None


class ResultData(BaseModel):
    columns: list[str]
    rows: list[list[Scalar]]
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: int = 0


class AnswerDeltaData(BaseModel):
    text: str


class AnswerData(BaseModel):
    text: str


class ErrorData(BaseModel):
    code: str
    message: str
    recoverable: bool = False


class UsageData(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


class TurnCompletedData(BaseModel):
    usage: UsageData
    elapsed_ms: int = 0


class TurnStartedEvent(BaseModel):
    type: Literal["turn.started"] = "turn.started"
    data: TurnStartedData


class StepEvent(BaseModel):
    type: Literal["step"] = "step"
    data: StepData


class ReasoningEvent(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    data: ReasoningData


class ClarificationEvent(BaseModel):
    type: Literal["clarification"] = "clarification"
    data: ClarificationData


class SqlEvent(BaseModel):
    type: Literal["sql"] = "sql"
    data: SqlData


class ResultEvent(BaseModel):
    type: Literal["result"] = "result"
    data: ResultData


class AnswerDeltaEvent(BaseModel):
    type: Literal["answer.delta"] = "answer.delta"
    data: AnswerDeltaData


class AnswerEvent(BaseModel):
    type: Literal["answer"] = "answer"
    data: AnswerData


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    data: ErrorData


class TurnCompletedEvent(BaseModel):
    type: Literal["turn.completed"] = "turn.completed"
    data: TurnCompletedData


class UnknownEvent(BaseModel):
    """Un evento que esta versión del SDK no conoce (el servidor puede ser más nuevo)."""

    type: str
    data: dict[str, Any] = {}


StreamEvent = (
    TurnStartedEvent
    | StepEvent
    | ReasoningEvent
    | ClarificationEvent
    | SqlEvent
    | ResultEvent
    | AnswerDeltaEvent
    | AnswerEvent
    | ErrorEvent
    | TurnCompletedEvent
    | UnknownEvent
)

_KNOWN: dict[str, type[BaseModel]] = {
    "turn.started": TurnStartedEvent,
    "step": StepEvent,
    "reasoning": ReasoningEvent,
    "clarification": ClarificationEvent,
    "sql": SqlEvent,
    "result": ResultEvent,
    "answer.delta": AnswerDeltaEvent,
    "answer": AnswerEvent,
    "error": ErrorEvent,
    "turn.completed": TurnCompletedEvent,
}


def build_event(event_type: str, data: dict[str, Any]) -> StreamEvent:
    """Convierte un `event:`/`data:` en su modelo.

    Lo desconocido o malformado va a `UnknownEvent`.
    """
    model = _KNOWN.get(event_type)
    if model is not None:
        try:
            return cast(StreamEvent, model.model_validate({"type": event_type, "data": data}))
        except ValidationError:
            pass
    return UnknownEvent(type=event_type, data=data)


def parse_sse(lines: Iterable[str]) -> Iterator[StreamEvent]:
    """Interpreta líneas `text/event-stream` (sin salto de línea final) y emite eventos.

    Ignora los comentarios (`: keep-alive`) y los bloques sin `event:`.
    """
    event_type: str | None = None
    data_lines: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if event_type is not None and data_lines:
                yield build_event(event_type, _loads("\n".join(data_lines)))
            event_type, data_lines = None, []
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event_type = value
            elif field == "data":
                data_lines.append(value)
    if event_type is not None and data_lines:  # el servidor cerró sin la línea en blanco final
        yield build_event(event_type, _loads("\n".join(data_lines)))


def _loads(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    return value if isinstance(value, dict) else {"value": value}
