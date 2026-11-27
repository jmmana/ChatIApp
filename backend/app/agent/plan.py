"""Contrato del plan (docs/FLUJO_CONVERSACIONAL.md#el-plan).

Es la salida de «Entender»: la IA propone y el motor dispone (ADR 0001). El plan no lleva
fechas calculadas ni permisos; `period_text` conserva el período tal como lo dijo el usuario.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Intent = Literal["metric", "sql", "clarify", "explain", "out_of_scope"]
FilterOp = Literal["=", "!=", ">", ">=", "<", "<=", "in", "contains"]
TimeGrain = Literal["day", "week", "month", "quarter", "year"]
FilterValue = str | int | float | bool | list[str | int | float] | None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanFilter(_Strict):
    field: str = Field(min_length=1)
    op: FilterOp
    value: FilterValue = None


class Order(_Strict):
    by: str = Field(min_length=1)
    direction: Literal["asc", "desc"] = "desc"


class Clarification(_Strict):
    question: str = Field(min_length=1)
    options: list[str] = []
    slot: str | None = None


class Plan(_Strict):
    intent: Intent
    reasoning: str = ""
    metric: str | None = None
    dimensions: list[str] = []
    filters: list[PlanFilter] = []
    time_grain: TimeGrain | None = None
    period_text: str | None = None
    compare_previous: bool = False
    order: Order | None = None
    limit: int | None = Field(default=None, gt=0)
    clarification: Clarification | None = None
    sql: str | None = None
    answer: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        """Cada intención exige su campo y prohíbe los de otras rutas."""
        required: dict[str, tuple[str, object]] = {
            "metric": ("metric", self.metric),
            "clarify": ("clarification", self.clarification),
            "sql": ("sql", self.sql),
            "explain": ("answer", self.answer),
            "out_of_scope": ("answer", self.answer),
        }
        name, value = required[self.intent]
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"intent={self.intent} exige el campo «{name}»")
        if self.intent != "clarify" and self.clarification is not None:
            raise ValueError("«clarification» solo se admite con intent=clarify")
        if self.intent != "sql" and self.sql is not None:
            raise ValueError("«sql» solo se admite con intent=sql")
        if self.intent not in ("explain", "out_of_scope") and self.answer is not None:
            raise ValueError("«answer» solo se admite con intent=explain u out_of_scope")
        return self
