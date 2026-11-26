"""Observación de un turno: un span por etapa, métricas y etapa actual para los logs.

El orquestador le pasa los pasos que ya emite (`step`) y el error final; no hay lógica de negocio
aquí. Los spans llevan proveedor, tokens, costo y tablas usadas; nunca SQL, preguntas ni filas.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from app.observability import metrics
from app.observability.logs import LogScope
from app.observability.tracing import get_tracer

logger = logging.getLogger(__name__)

# Etapa del flujo (id del paso del orquestador) → nombre del span. Los pasos que no están aquí
# conservan su id (verify, period, compare, repair).
STAGES = {
    "understand": "planner",
    "build": "builder",
    "guard": "guard",
    "execute": "executor",
    "answer": "answer",
}
_LLM_STAGES = {"planner", "repair", "answer"}
_TABLE_STAGES = {"builder", "guard", "executor", "compare"}
_GUARD_ERROR_CODES = {"sql_rejected", "user_config"}


@dataclass
class Totals:
    """Uso acumulado del turno hasta el momento."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass
class _Open:
    span: Span
    started: float
    before: Totals


class TurnObserver:
    def __init__(
        self,
        scope: LogScope,
        *,
        turn_id: str,
        conversation_id: str,
        user: str | None,
        provider: str | None,
        model: str | None,
        role: str | None,
        datasource_id: str,
        tracer: Tracer | None = None,
    ) -> None:
        self.scope = scope
        self.provider = provider or "desconocido"
        self.model = model
        self._tracer = tracer or get_tracer()
        self._open: dict[str, _Open] = {}
        self._error_code: str | None = None
        self._asked = False
        self._done = False
        self._started = time.perf_counter()
        scope.update(turn_id=turn_id)
        self.span = self._tracer.start_span(
            "chatiapp.turn",
            attributes=_attrs(
                {
                    "chatiapp.turn_id": turn_id,
                    "chatiapp.conversation_id": conversation_id,
                    "chatiapp.user": user,
                    "chatiapp.role": role,
                    "chatiapp.datasource_id": datasource_id,
                }
            ),
        )
        self._context = trace.set_span_in_context(self.span)

    # ---------------------------------------------------------------- eventos

    def step(self, step_id: str, status: str, totals: Totals, tables: list[str]) -> None:
        """Un evento `step`: `running` abre el span de la etapa y el resto lo cierra."""
        stage = STAGES.get(step_id, step_id)
        if status == "running":
            self._close(stage, "done", totals, tables)  # por si quedó una etapa abierta
            self.scope.update(stage=stage)
            span = self._tracer.start_span(
                f"chatiapp.{stage}",
                context=self._context,
                attributes=_attrs(
                    {
                        "chatiapp.stage": stage,
                        "llm.provider": self.provider if stage in _LLM_STAGES else None,
                        "llm.model": self.model if stage in _LLM_STAGES else None,
                    }
                ),
            )
            self._open[stage] = _Open(span, time.perf_counter(), _copy(totals))
            return
        self._close(stage, status, totals, tables)
        if stage == "guard" and status == "warning":
            metrics.GUARD_REJECTIONS.inc()
        if stage == "answer" and status == "warning":
            metrics.PROVIDER_ERRORS.labels(self.provider).inc()

    def error(self, code: str) -> None:
        self._error_code = code
        if code == "provider_error":
            metrics.PROVIDER_ERRORS.labels(self.provider).inc()
        elif code in _GUARD_ERROR_CODES:
            metrics.GUARD_REJECTIONS.inc()

    def clarification(self) -> None:
        self._asked = True

    def finish(self, totals: Totals, tables: list[str], *, completed: bool = True) -> None:
        """Cierra el turno: spans abiertos, métricas globales y el span raíz. Es idempotente."""
        if self._done:
            return
        self._done = True
        for stage in list(self._open):
            self._close(stage, "error" if self._error_code else "done", totals, tables)
        if not completed:
            outcome = "cancelled"
        elif self._error_code is not None:
            outcome = "error"
        elif self._asked:
            outcome = "clarification"
        else:
            outcome = "ok"
        elapsed = time.perf_counter() - self._started
        metrics.TURNS.labels(outcome).inc()
        metrics.TURN_SECONDS.observe(elapsed)
        metrics.TOKENS.labels("input").inc(totals.tokens_in)
        metrics.TOKENS.labels("output").inc(totals.tokens_out)
        metrics.COST_USD.inc(totals.cost_usd)
        self.span.set_attributes(
            _attrs(
                {
                    "chatiapp.outcome": outcome,
                    "chatiapp.error_code": self._error_code,
                    "chatiapp.tables": ",".join(tables) or None,
                    "llm.provider": self.provider,
                    "llm.model": self.model,
                    "llm.tokens.input": totals.tokens_in,
                    "llm.tokens.output": totals.tokens_out,
                    "llm.cost_usd": totals.cost_usd,
                }
            )
        )
        if outcome == "error":
            self.span.set_status(Status(StatusCode.ERROR))
        self.span.end()
        self.scope.update(stage=None)
        logger.info(
            "Turno terminado",
            extra={
                "status": outcome,
                "code": self._error_code,
                "duration_ms": int(elapsed * 1000),
                "tokens_in": totals.tokens_in,
                "tokens_out": totals.tokens_out,
                "cost_usd": totals.cost_usd,
            },
        )

    # ---------------------------------------------------------------- interno

    def _close(self, stage: str, status: str, totals: Totals, tables: list[str]) -> None:
        opened = self._open.pop(stage, None)
        if opened is None:
            return
        elapsed = time.perf_counter() - opened.started
        tokens_in = totals.tokens_in - opened.before.tokens_in
        tokens_out = totals.tokens_out - opened.before.tokens_out
        cost = totals.cost_usd - opened.before.cost_usd
        attributes: dict[str, Any] = {"chatiapp.status": status}
        if stage in _LLM_STAGES:
            attributes["llm.tokens.input"] = tokens_in
            attributes["llm.tokens.output"] = tokens_out
            attributes["llm.cost_usd"] = cost
        if stage in _TABLE_STAGES and tables:
            attributes["db.tables"] = ",".join(tables)
        opened.span.set_attributes(_attrs(attributes))
        if status == "error":
            opened.span.set_status(Status(StatusCode.ERROR))
        opened.span.end()
        metrics.STAGE_SECONDS.labels(stage).observe(elapsed)
        logger.info(
            "Etapa terminada",
            extra={
                "status": status,
                "duration_ms": int(elapsed * 1000),
                "tokens_in": tokens_in if stage in _LLM_STAGES else None,
                "tokens_out": tokens_out if stage in _LLM_STAGES else None,
            },
        )


def _copy(totals: Totals) -> Totals:
    return Totals(totals.tokens_in, totals.tokens_out, totals.cost_usd)


def _attrs(values: dict[str, Any]) -> dict[str, str | int | float | bool]:
    return {k: v for k, v in values.items() if v is not None}
