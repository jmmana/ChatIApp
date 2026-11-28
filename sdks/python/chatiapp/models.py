"""Respuesta de `POST /api/v1/chat` (docs/INTEGRACION.md#sin-streaming)."""

from typing import Literal

from pydantic import BaseModel

from .events import ClarificationData, ErrorData, PeriodData, ResultData, SqlData, UsageData

TurnStatus = Literal["answered", "needs_clarification", "rejected", "error"]


class Turn(BaseModel):
    """Un turno completo.

    `status` es `needs_clarification` cuando falta un dato: responde en la misma conversación
    (`conversation_id`). `rejected` es el guardián de SQL o la configuración; `error`, un fallo.
    """

    conversation_id: str
    status: TurnStatus
    reasoning: str | None = None
    clarification: ClarificationData | None = None
    period: PeriodData | None = None
    sql: SqlData | None = None
    result: ResultData | None = None
    answer: str | None = None
    usage: UsageData | None = None
    error: ErrorData | None = None

    @property
    def needs_clarification(self) -> bool:
        return self.status == "needs_clarification"

    @property
    def answered(self) -> bool:
        return self.status == "answered"
