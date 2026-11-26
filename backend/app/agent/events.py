"""Eventos de streaming del turno (docs/FLUJO_CONVERSACIONAL.md#eventos-de-streaming).

Cada evento tiene un `type` y un `data` JSON. Los modelos de `data` son estrictos para que el
contrato no se desvíe sin que fallen las pruebas; `Event` los envuelve y los serializa.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

EventType = Literal[
    "turn.started",
    "step",
    "reasoning",
    "clarification",
    "sql",
    "result",
    "answer.delta",
    "answer",
    "error",
    "turn.completed",
]
StepStatus = Literal["running", "done", "warning", "error"]
Origin = Literal["catalog", "llm"]
JsonValue = str | int | float | bool | None


class _Data(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnStarted(_Data):
    turn_id: str
    conversation_id: str


class Step(_Data):
    id: str
    label: str
    status: StepStatus
    detail: str | None = None


class Reasoning(_Data):
    text: str


class ClarificationData(_Data):
    question: str
    options: list[str] = []
    slot: str | None = None


class PeriodData(_Data):
    label: str
    start: str
    end_exclusive: str


class SqlData(_Data):
    sql: str
    dialect: str
    origin: Origin
    summary_table: str | None = None
    filters_applied: list[str] = []
    period: PeriodData | None = None


class ResultData(_Data):
    columns: list[str]
    rows: list[list[JsonValue]]
    row_count: int
    truncated: bool
    elapsed_ms: int


class AnswerDelta(_Data):
    text: str


class Answer(_Data):
    text: str


class ErrorData(_Data):
    code: str
    message: str
    recoverable: bool


class UsageData(_Data):
    tokens_in: int
    tokens_out: int
    cost_usd: float


class TurnCompleted(_Data):
    usage: UsageData
    elapsed_ms: int


_TYPES: dict[type[_Data], EventType] = {
    TurnStarted: "turn.started",
    Step: "step",
    Reasoning: "reasoning",
    ClarificationData: "clarification",
    SqlData: "sql",
    ResultData: "result",
    AnswerDelta: "answer.delta",
    Answer: "answer",
    ErrorData: "error",
    TurnCompleted: "turn.completed",
}


@dataclass(frozen=True)
class Event:
    """Un evento del turno: su `type` sale del tipo de `data`."""

    data: _Data

    @property
    def type(self) -> EventType:
        return _TYPES[type(self.data)]

    def payload(self) -> dict[str, Any]:
        """El `data` JSON del evento; los campos opcionales ausentes se omiten."""
        return self.data.model_dump(mode="json", exclude_none=True)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.payload()}

    def sse(self) -> str:
        """Trama `text/event-stream`: `event: <type>` y `data: <JSON>`."""
        body = json.dumps(self.payload(), ensure_ascii=False)
        return f"event: {self.type}\ndata: {body}\n\n"
