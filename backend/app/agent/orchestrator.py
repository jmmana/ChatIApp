"""Orquestador del turno: conduce la pregunta por los estados del agente y emite sus eventos.

Implementa la máquina de estados de docs/FLUJO_CONVERSACIONAL.md#estados-del-agente:
Entender → (Explicar | Aclarar | Verificar → Construir | SQL libre) → Validar → (Reparar) →
Ejecutar → Responder. La IA solo propone el plan y redacta la respuesta; el SQL del catálogo, el
período, el guardián y la ejecución son código (ADR 0001).

`Orchestrator.run` es un generador síncrono de `Event`: el endpoint de chat lo recorre en un hilo
y reenvía cada evento por SSE. Un fallo en cualquier etapa termina con un evento `error`, nunca
con una excepción. Al final del turno se guardan el mensaje del asistente con sus eventos, el
`last_plan` de la conversación y un `QueryRun` (el registro de auditoría), con o sin consulta.
"""

import logging
import time
import uuid
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from opentelemetry.trace import Tracer
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.answer import AnswerWriter
from app.agent.answer import Outcome as _Outcome
from app.agent.clarify import (
    Pending,
    apply_reply,
    assumed_period_note,
    dimension_question,
    metric_question,
    pending_clarification,
    period_question,
    should_assume_default,
    trailing_clarifications,
)
from app.agent.dimensions import unrequested_dimensions
from app.agent.entities import EntityQuestion, resolve_filters
from app.agent.events import (
    Answer,
    ClarificationData,
    ErrorData,
    Event,
    Origin,
    PeriodData,
    Reasoning,
    ResultData,
    SqlData,
    Step,
    StepStatus,
    TurnCompleted,
    TurnStarted,
    UsageData,
)
from app.agent.free_sql import RepairError, repair_sql
from app.agent.plan import Plan
from app.agent.planner import PlannerError, Turn, plan_question
from app.db.models import Conversation, Datasource, Message, QueryRun, User
from app.engine.builder import BuilderError, OrderTerm, build_sql
from app.engine.catalog import (
    AmbiguousMetricError,
    Catalog,
    CatalogError,
    DimensionNotAllowedError,
    PlanFilter,
    VerifiedPlan,
)
from app.engine.compare import CompareError, compare_previous
from app.engine.dialects import Dialect
from app.engine.executor import (
    QueryExecutionError,
    QueryExecutor,
    QueryResult,
    QueryTimeoutError,
    executor,
)
from app.engine.guard import GuardCache, GuardResult, check_sql, guards
from app.engine.guard import UnknownRoleError as GuardRoleError
from app.engine.periods import PeriodConfig, PeriodRange, resolve_period
from app.engine.rls import role_row_filters
from app.engine.summary import plan_for_summary, route_summary
from app.llm.gateway import Gateway, ProviderConfig, Usage
from app.llm.privacy import PrivacyGateway, PrivacyLog, parse_level
from app.llm.routing import LlmClient, Router, TaskGateway
from app.observability import LogScope, Totals, TurnObserver, metrics
from app.security.grants import ViewAs, resolve_access
from app.semantic.context import Privacy
from app.semantic.schema import Metric, SemanticModel

logger = logging.getLogger(__name__)

_HISTORY_WINDOW = 12

_LABELS = {
    "understand": "Entendiendo la pregunta",
    "replan": "Corrigiendo el plan",
    "verify": "Verificando la métrica y los permisos",
    "period": "Resolviendo el período",
    "build": "Construyendo la consulta",
    "guard": "Validando el SQL",
    "repair": "Reparando el SQL",
    "compare": "Comparando con el período anterior",
    "execute": "Ejecutando la consulta",
    "answer": "Redactando la respuesta",
}


# --------------------------------------------------------------------------- control interno


class _Ask(Exception):
    """El turno termina pidiendo una aclaración al usuario."""

    def __init__(
        self, question: str, options: Sequence[str], slot: str | None, step: str | None = None
    ) -> None:
        super().__init__(question)
        self.question = question
        self.options = list(options)
        self.slot = slot
        self.step = step


class _Fail(Exception):
    """El turno termina con un evento `error`; `step` es la etapa que se marca como fallida."""

    def __init__(self, step: str, code: str, message: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.step = step
        self.code = code
        self.message = message
        self.recoverable = recoverable


class _ExecError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class _Run:
    """Lo que se guarda en `QUERY_RUN`."""

    origin: Origin
    status: Literal["ok", "rejected", "error"]
    sql_final: str | None = None
    summary_table: str | None = None
    filters_applied: dict[str, list[str]] = field(default_factory=dict)
    row_count: int | None = None
    elapsed_ms: int | None = None


@dataclass
class _Turn:
    conversation: Conversation
    question: str
    user_message: Message
    assistant: Message
    history: list[Turn]
    prior_plan: Plan | None
    previous_clarifications: int
    pending: Pending | None = None
    started: float = field(default_factory=time.perf_counter)
    usage: Usage = field(default_factory=Usage)
    events: list[Event] = field(default_factory=list)
    last_plan: dict[str, Any] | None = None
    run: _Run | None = None
    notes: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)  # tablas de la consulta, para las trazas
    fallbacks: list[str] = field(default_factory=list)  # avisos de respaldo de `_repair`
    text: str = ""  # lo que se guarda como contenido del mensaje del asistente
    plan: dict[str, Any] | None = None  # plan de la IA tal como llegó (auditoría)
    sql_candidate: str | None = None  # SQL antes del guardián (auditoría)
    error_code: str | None = None
    failed: bool = False


# --------------------------------------------------------------------------- orquestador


class Orchestrator:
    """Un turno del agente sobre una fuente de datos, con el rol y los atributos del usuario.

    `url` es la URL de la fuente ya descifrada (la descifra quien llama). `context` es
    `{"user": {...}}` (ver `rls.build_user_context`): lo arma el backend, nunca la IA.
    """

    def __init__(
        self,
        session: Session,
        gateway: Gateway | Router,
        datasource: Datasource,
        model: SemanticModel,
        version: int,
        url: str,
        *,
        role: str | None = None,
        context: dict[str, Any] | None = None,
        provider_id: uuid.UUID | None = None,
        api_key_id: uuid.UUID | None = None,
        query_executor: QueryExecutor = executor,
        guard_cache: GuardCache = guards,
        now: datetime | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.tracer = tracer
        self.session = session
        self.gateway = gateway
        self.datasource = datasource
        self.model = model
        self.version = version
        self.url = url
        self.role = role or model.security.default_role
        self.context = context or {}
        self.provider_id = provider_id
        self.api_key_id = api_key_id
        self.query_executor = query_executor
        self.guard_cache = guard_cache
        self._now = now
        self.dialect = cast(Dialect, datasource.dialect)
        self.privacy: Privacy = parse_level(datasource.privacy)
        self.privacy_log = PrivacyLog()
        settings = model.settings
        self.period_config = PeriodConfig(
            timezone=settings.timezone,
            week_starts_on=settings.week_starts_on,
            fiscal_year_start_month=settings.fiscal_year_start_month,
            locale=settings.locale or "es-CO",
        )

    def _llm(self, task: Literal["planner", "sql", "answer"]) -> LlmClient:
        """Pasarela de la tarea: con un `Router`, la de su cadena de respaldo."""
        inner = self.gateway.for_task(task) if isinstance(self.gateway, Router) else self.gateway
        return PrivacyGateway(inner, task, self.privacy, self.privacy_log)

    @staticmethod
    def _notices(llm: LlmClient) -> list[str]:
        """Avisos de respaldo ocurridos en `llm` (vacío si no es una pasarela con respaldo)."""
        return llm.take_notices() if isinstance(llm, TaskGateway | PrivacyGateway) else []

    @classmethod
    def for_user(
        cls,
        session: Session,
        gateway: Gateway | Router,
        datasource: Datasource,
        model: SemanticModel,
        version: int,
        url: str,
        user: User,
        *,
        view_as: ViewAs | None = None,
        **kwargs: Any,
    ) -> "Orchestrator":
        """Orquestador con el rol y los atributos del usuario autenticado en la fuente.

        Sin permiso lanza `GrantError` (403); `view_as` solo lo acepta un administrador.
        """
        access = resolve_access(session, user, datasource, model, view_as)
        return cls(
            session,
            gateway,
            datasource,
            model,
            version,
            url,
            role=access.role,
            context=access.context,
            **kwargs,
        )

    def now(self) -> datetime:
        return self._now or datetime.now(UTC)

    # ---------------------------------------------------------------- turno

    def run(self, conversation: Conversation, question: str) -> Iterator[Event]:
        """Recorre el turno y emite sus eventos; `turn.completed` es siempre el último."""
        user = conversation.user_id or conversation.external_user_id
        scope = LogScope(str(conversation.id), str(user) if user else None)
        return scope.wrap(self._run(conversation, question, scope))

    def _run(self, conversation: Conversation, question: str, scope: LogScope) -> Iterator[Event]:
        started = time.perf_counter()
        conversation_id = str(conversation.id)
        try:
            t = self._begin(conversation, question)
        except Exception:
            # Sin turno no hay nada que guardar, pero el cliente recibe igual su burbuja, un error
            # claro y el cierre del turno: nunca una excepción sin manejar.
            logger.exception("No se pudo iniciar el turno en la conversación %s", conversation_id)
            metrics.TURNS.labels("error").inc()
            if not self.session.is_active:  # un flush fallido deja la transacción por deshacer
                self.session.rollback()
            yield from _begin_failed(conversation_id, started)
            return
        observer = self._observer(t, scope)
        persisted = False
        try:
            for event in self._guarded(t):
                t.events.append(event)
                self._observe(observer, t, event)
                yield event
            usage = t.usage
            completed = Event(
                TurnCompleted(
                    usage=UsageData(
                        tokens_in=usage.input_tokens,
                        tokens_out=usage.output_tokens,
                        cost_usd=usage.cost_usd or 0.0,
                    ),
                    elapsed_ms=_ms(time.perf_counter() - t.started),
                )
            )
            t.events.append(completed)
            self._persist(t)
            persisted = True
            observer.finish(_totals(t.usage), t.tables)
            yield completed
        finally:
            if not persisted:  # el consumidor cerró el generador: se guarda lo que haya
                self._persist(t)
                observer.finish(_totals(t.usage), t.tables, completed=False)

    def _observer(self, t: _Turn, scope: LogScope) -> TurnObserver:
        provider = self._audit_provider()
        conversation = t.conversation
        user = conversation.user_id or conversation.external_user_id
        return TurnObserver(
            scope,
            turn_id=str(t.assistant.id),
            conversation_id=str(conversation.id),
            user=str(user) if user else None,
            provider=getattr(provider, "kind", None),
            model=getattr(provider, "model", None),
            role=self.role,
            datasource_id=str(self.datasource.id),
            tracer=self.tracer,
        )

    @staticmethod
    def _observe(observer: TurnObserver, t: _Turn, event: Event) -> None:
        """Traduce los eventos del turno a spans y métricas; nunca interrumpe el turno."""
        try:
            data = event.data
            if isinstance(data, Step):
                observer.step(data.id, data.status, _totals(t.usage), t.tables)
            elif isinstance(data, ErrorData):
                observer.error(data.code)
            elif isinstance(data, ClarificationData):
                observer.clarification()
        except Exception:
            logger.exception("No se pudo registrar la observabilidad del turno")

    def _begin(self, conversation: Conversation, question: str) -> _Turn:
        recent = list(
            reversed(
                self.session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.created_at.desc())
                    .limit(_HISTORY_WINDOW)
                ).all()
            )
        )
        history = [Turn(cast(Literal["user", "assistant"], m.role), m.content) for m in recent]
        user_message = Message(
            id=uuid.uuid4(), conversation_id=conversation.id, role="user", content=question
        )
        assistant = Message(
            id=uuid.uuid4(), conversation_id=conversation.id, role="assistant", content=""
        )
        self.session.add_all([user_message, assistant])
        self.session.flush()
        return _Turn(
            conversation=conversation,
            question=question,
            user_message=user_message,
            assistant=assistant,
            history=history,
            prior_plan=_load_plan(conversation.last_plan),
            previous_clarifications=trailing_clarifications(recent),
            pending=pending_clarification(recent),
        )

    def _guarded(self, t: _Turn) -> Iterator[Event]:
        try:
            yield from self._flow(t)
        except _Ask as ask:
            yield from self._ask(t, ask)
        except _Fail as fail:
            yield from self._fail(t, fail)
        except Exception:
            logger.exception("Error inesperado en el turno %s", t.assistant.id)
            if t.run is not None and t.run.status == "ok":
                t.run.status = "error"
            yield from self._fail(t, _Fail("answer", "internal_error", _UNEXPECTED))

    def _audit_provider(self) -> ProviderConfig:
        """Proveedor a registrar: con `Router`, el principal de la cadena de respuesta."""
        if isinstance(self.gateway, Router):
            chain = self.gateway.for_task("answer").chain
            if chain:
                return chain[0].gateway.provider
            return ProviderConfig("none", "none")
        return self.gateway.provider

    def _persist(self, t: _Turn) -> None:
        try:
            t.assistant.content = t.text
            t.assistant.events = [e.to_dict() for e in t.events if e.type != "answer.delta"]
            if t.last_plan is not None:
                t.conversation.last_plan = t.last_plan
            # Auditoría: todo turno deja un registro, tenga o no consulta (solo conteos de filas).
            run, usage, conversation = t.run, t.usage, t.conversation
            if run is None:
                intent = (t.plan or {}).get("intent")
                run = _Run("llm" if intent == "sql" else "catalog", "error" if t.failed else "ok")
            provider = self._audit_provider()
            self.session.add(
                QueryRun(
                    message_id=t.assistant.id,
                    provider_id=self.provider_id,
                    api_key_id=self.api_key_id or conversation.api_key_id,
                    user_id=conversation.user_id,
                    external_user_id=conversation.external_user_id,
                    datasource_id=self.datasource.id,
                    role=self.role,
                    question=t.question,
                    plan=t.plan,
                    sql_candidate=t.sql_candidate,
                    provider_kind=provider.kind,
                    model=provider.model,
                    semantic_version=self.version,
                    error_code=t.error_code,
                    origin=run.origin,
                    sql_final=run.sql_final,
                    summary_table=run.summary_table,
                    filters_applied=dict(run.filters_applied),
                    row_count=run.row_count,
                    elapsed_ms=run.elapsed_ms,
                    tokens_in=usage.input_tokens,
                    tokens_out=usage.output_tokens,
                    cost_usd=Decimal(str(usage.cost_usd or 0.0)),
                    status=run.status,
                )
            )
            self.session.commit()
        except Exception:
            logger.exception("No se pudo guardar el turno %s", t.assistant.id)
            self.session.rollback()

    # ---------------------------------------------------------------- estados

    def _flow(self, t: _Turn) -> Iterator[Event]:
        conversation_id = str(t.conversation.id)
        yield Event(TurnStarted(turn_id=str(t.assistant.id), conversation_id=conversation_id))
        plan = self._resume(t)
        if plan is None:
            plan = yield from self._understand(t)
        else:
            yield _step("understand", "done", "Retomando el plan pendiente")
        if plan.reasoning.strip():
            yield Event(Reasoning(text=plan.reasoning.strip()))
        if plan.intent in ("explain", "out_of_scope"):
            yield from self._say(t, plan.answer or "")
            return
        if plan.intent == "clarify":
            plan = self._cap_clarification(t, plan)
        if plan.intent == "sql":
            yield from self._free_sql(t, plan)
        else:
            yield from self._metric(t, plan)

    def _resume(self, t: _Turn) -> Plan | None:
        """Si el usuario responde una aclaración, completa el plan pendiente sin volver a la IA."""
        if t.pending is None or t.prior_plan is None:
            return None
        return apply_reply(
            t.prior_plan, t.pending, t.question, self.model, self.period_config, self.now()
        )

    def _understand(self, t: _Turn) -> Generator[Event, None, Plan]:
        yield _step("understand", "running")
        llm = self._llm("planner")
        try:
            result = plan_question(
                llm,
                self.model,
                t.question,
                now=self.now(),
                history=t.history,
                last_plan=t.prior_plan,
                privacy=self.privacy,
                role=self.role,
            )
        except PlannerError as exc:
            code = "invalid_plan" if exc.kind == "invalid_plan" else "provider_error"
            raise _Fail("understand", code, exc.message) from exc
        except ValueError as exc:  # rol que el modelo semántico no define
            raise _Fail("understand", "unknown_role", str(exc), recoverable=False) from exc
        t.usage += result.usage
        t.plan = result.plan.model_dump(mode="json")
        for notice in self._notices(llm):
            yield _step("understand", "warning", notice)
        yield _step("understand", "done", result.plan.intent)
        return result.plan

    def _cap_clarification(self, t: _Turn, plan: Plan) -> Plan:
        """Máximo 2 aclaraciones seguidas: después se usa el `default_period` de la métrica."""
        clarification = plan.clarification
        assert clarification is not None
        if plan.metric:
            try:
                metric = Catalog(self.model).find_metric(plan.metric)
            except CatalogError:
                metric = None
            if metric is not None and should_assume_default(t.previous_clarifications, metric):
                assert metric.default_period is not None
                t.notes.append(assumed_period_note(metric.default_period))
                return plan.model_copy(
                    update={
                        "intent": "metric",
                        "metric": metric.name,
                        "clarification": None,
                        "period_text": metric.default_period,
                    }
                )
        t.last_plan = plan.model_dump(mode="json")
        raise _Ask(clarification.question, clarification.options, clarification.slot)

    # -- ruta del catálogo

    def _metric(self, t: _Turn, plan: Plan) -> Iterator[Event]:
        assert plan.metric is not None
        yield _step("verify", "running")
        try:
            verified = self._verify(plan, t.question, t.prior_plan)
        except _Fail as fail:
            if fail.code != "invalid_plan" or fail.step != "verify":
                raise
            plan = yield from self._replan(t, plan, fail)
            yield _step("verify", "running")
            try:
                verified = self._verify(plan, t.question, t.prior_plan)
            except _Ask:
                t.last_plan = plan.model_dump(mode="json")
                raise
        except _Ask:
            t.last_plan = plan.model_dump(mode="json")  # queda pendiente para la respuesta
            raise
        t.last_plan = plan.model_dump(mode="json")
        yield _step("verify", "done", verified.metric.label)

        yield _step("period", "running")
        period = self._period(t, plan, verified.metric)
        if period is not None:
            yield _step("period", "done", period.label)
        else:
            yield _step("period", "done", "La métrica no necesita período")

        yield _step("build", "running")
        decision = route_summary(
            self.model, verified, period=period, time_grain=plan.time_grain, role=self.role
        )
        target = verified
        if decision.table is not None:
            target = plan_for_summary(self.model, verified, decision.table)
        try:
            query = build_sql(
                self.model,
                target,
                self.dialect,
                period=period,
                time_grain=plan.time_grain,
                order_by=_order_terms(plan, verified),
                limit=plan.limit,
            )
        except BuilderError as exc:
            raise _Fail("build", "invalid_plan", exc.message) from exc
        t.tables = [decision.table or verified.metric.table]
        yield _step("build", "done", decision.reason)

        filters = self._filters_applied(verified, period)
        t.sql_candidate = query.sql
        t.run = _Run("catalog", "rejected", query.sql, decision.table, filters)
        outcome = _Outcome(metric=verified.metric, period=period)

        wants_comparison = plan.compare_previous
        if wants_comparison:
            reason = _comparison_skipped(plan, verified, period, self.datasource.execute)
            if reason is not None:
                wants_comparison = False
                yield _step("compare", "warning", reason)

        if wants_comparison and period is not None:
            yield from self._compare(t, verified, period, outcome)
        else:
            yield _step("guard", "running")
            guarded = self._validate(t, query.sql)
            if not guarded.allowed:
                raise self._rejection(guarded)
            yield _step("guard", "done", "SQL validado")
            assert guarded.sql is not None
            yield self._sql_event(t, guarded.sql, period)
            yield from self._execute(t, guarded.sql, outcome)
        yield from self._answer(t, outcome)

    def _replan(self, t: _Turn, plan: Plan, fail: _Fail) -> Generator[Event, None, Plan]:
        """Un solo reintento: el planificador recibe el plan rechazado y el error exacto."""
        yield _step("replan", "warning", fail.message)
        llm = self._llm("planner")
        try:
            result = plan_question(
                llm,
                self.model,
                t.question,
                now=self.now(),
                history=t.history,
                last_plan=t.prior_plan,
                privacy=self.privacy,
                role=self.role,
                rejected=(plan, fail.message),
            )
        except PlannerError as exc:
            code = "invalid_plan" if exc.kind == "invalid_plan" else "provider_error"
            raise _Fail("replan", code, exc.message) from exc
        t.usage += result.usage
        new = result.plan
        if new.intent != "metric" or not new.metric:
            raise fail  # el reintento no dio un plan de métrica: termina con el error original
        t.plan = new.model_dump(mode="json")
        return new

    def _verify(
        self, plan: Plan, question: str = "", prior_plan: Plan | None = None
    ) -> VerifiedPlan:
        assert plan.metric is not None
        catalog = Catalog(self.model)
        self._drop_unrequested_dimensions(catalog, plan, question, prior_plan)
        filters = [PlanFilter(f.field, f.op, f.value) for f in plan.filters]
        try:
            verified = catalog.verify(plan.metric, plan.dimensions, filters, self.role)
            if self.datasource.execute and verified.filters:
                found = resolve_filters(self.model, verified.filters, self._search_values)
                verified = replace(verified, filters=found)
            return verified
        except EntityQuestion as exc:
            ask = exc.question
            raise _Ask(ask.question, ask.options, ask.slot, "verify") from exc
        except AmbiguousMetricError as exc:
            ask = metric_question([catalog.find_metric(name) for name in exc.candidates])
            raise _Ask(ask.question, ask.options, ask.slot, "verify") from exc
        except DimensionNotAllowedError as exc:
            ask = dimension_question(exc.metric, exc.dimension, exc.allowed)
            raise _Ask(ask.question, ask.options, ask.slot, "verify") from exc
        except CatalogError as exc:
            raise _Fail("verify", "invalid_plan", exc.message) from exc

    @staticmethod
    def _drop_unrequested_dimensions(
        catalog: Catalog, plan: Plan, question: str, prior_plan: Plan | None
    ) -> None:
        """Quita del plan las dimensiones que la pregunta no nombra y lo deja dicho en el plan.

        Las dimensiones que ya traía el último plan (preguntas de seguimiento) se conservan.
        """
        assert plan.metric is not None
        inherited = prior_plan.dimensions if prior_plan is not None else []
        removed = unrequested_dimensions(catalog, plan.metric, plan.dimensions, question, inherited)
        if not removed:
            return
        plan.dimensions = [d for d in plan.dimensions if d not in removed]
        note = f"Dimensiones descartadas por no estar en la pregunta: {', '.join(removed)}."
        plan.reasoning = f"{plan.reasoning} {note}".strip()

    def _period(self, t: _Turn, plan: Plan, metric: Metric) -> PeriodRange | None:
        """Resuelve el período con el resolutor determinista; si no se puede, pregunta."""
        text = plan.period_text
        if text and (period := resolve_period(text, self.period_config, self.now())):
            return period
        if not text and not metric.requires_period:
            return None
        if should_assume_default(t.previous_clarifications, metric):
            assert metric.default_period is not None
            period = resolve_period(metric.default_period, self.period_config, self.now())
            if period is not None:
                t.notes.append(assumed_period_note(metric.default_period))
                if t.last_plan is not None:
                    t.last_plan["period_text"] = metric.default_period
                return period
        ask = period_question(metric, text)
        raise _Ask(ask.question, ask.options, ask.slot, "period")

    def _compare(
        self, t: _Turn, verified: VerifiedPlan, period: PeriodRange, outcome: _Outcome
    ) -> Iterator[Event]:
        yield _step("compare", "running")
        guarded_sql: dict[str, str] = {}
        started = time.perf_counter()
        calls = 0

        def execute(sql: str) -> list[list[Any]]:
            nonlocal calls
            guarded = self._validate(t, sql, record=calls == 0)
            calls += 1
            if not guarded.allowed or guarded.sql is None:
                if t.run is not None:
                    t.run.status = "rejected"
                raise self._rejection(guarded, "compare")
            guarded_sql[sql] = guarded.sql
            try:
                result, _ = self._run_query(guarded.sql)
            except _ExecError as exc:
                if t.run is not None:
                    t.run.status = "error"
                raise _Fail("compare", "execution_error", exc.message) from exc
            return result.rows

        try:
            comparison = compare_previous(
                self.model,
                verified,
                self.dialect,
                period,
                execute,
                now=self.now(),
                role=self.role,
            )
        except CompareError as exc:
            raise _Fail("compare", "compare_error", exc.message) from exc
        elapsed = _ms(time.perf_counter() - started)
        assert t.run is not None
        t.run.summary_table = comparison.summary_table
        t.run.status = "ok"
        t.run.row_count = 2
        t.run.elapsed_ms = elapsed
        outcome.comparison = comparison
        outcome.columns = ["periodo", "valor"]
        outcome.rows = [
            [comparison.period.label, comparison.value],
            [comparison.previous_period.label, comparison.previous_value],
        ]
        yield _step("compare", "done", comparison.summary_reason)
        yield self._sql_event(t, guarded_sql[comparison.sql], period)
        yield Event(
            ResultData(
                columns=outcome.columns,
                rows=outcome.rows,
                row_count=2,
                truncated=False,
                elapsed_ms=elapsed,
            )
        )

    # -- ruta de SQL libre

    def _free_sql(self, t: _Turn, plan: Plan) -> Iterator[Event]:
        assert plan.sql is not None
        t.last_plan = plan.model_dump(mode="json")
        sql = plan.sql
        t.sql_candidate = sql
        t.run = _Run("llm", "rejected", sql, None, self._role_filters())
        outcome = _Outcome()
        repaired = False
        while True:
            yield _step("guard", "running")
            guarded = self._validate(t, sql)
            if guarded.allowed:
                assert guarded.sql is not None
                yield _step("guard", "done", "SQL validado")
                yield self._sql_event(t, guarded.sql, None)
                try:
                    yield from self._execute(t, guarded.sql, outcome)
                    break
                except _Fail as fail:
                    if repaired or fail.code != "execution_error":
                        raise
                    stage, problem = "execute", fail.message
            else:
                if repaired or guarded.user_config_problem:
                    raise self._rejection(guarded)
                stage, problem = "guard", "; ".join(v.message for v in guarded.violations)
            yield _step(stage, "warning", problem)
            yield _step("repair", "running")
            sql = self._repair(t, sql, problem)
            for notice in t.fallbacks:
                yield _step("repair", "warning", notice)
            t.fallbacks = []
            repaired = True
            yield _step("repair", "done")
        yield from self._answer(t, outcome)

    def _repair(self, t: _Turn, sql: str, problem: str) -> str:
        """Pide a la IA una corrección con el mensaje exacto del guardián o de la base."""
        llm = self._llm("sql")
        try:
            fixed, usage = repair_sql(
                llm,
                self.model,
                t.question,
                sql,
                problem,
                dialect=self.dialect,
                privacy=self.privacy,
                role=self.role,
            )
        except RepairError as exc:
            raise _Fail("repair", exc.kind, exc.message) from exc
        t.fallbacks = self._notices(llm)
        t.usage += usage
        return fixed

    # -- validación y ejecución

    def _validate(self, t: _Turn, sql: str, *, record: bool = True) -> GuardResult:
        """Pasa `sql` por el guardián y deja en `t.run` el SQL final o el rechazado."""
        run = t.run
        assert run is not None
        if record:
            run.sql_final, run.status = sql, "rejected"
        try:
            result = check_sql(
                sql,
                self.model,
                self.datasource,
                self.version,
                self.role,
                cache=self.guard_cache,
                context=self.context,
            )
        except GuardRoleError as exc:
            raise _Fail("guard", "unknown_role", str(exc), recoverable=False) from exc
        if record and result.allowed:
            run.sql_final, run.status = result.sql, "ok"
            t.tables = list(result.tables)
        return result

    @staticmethod
    def _rejection(guarded: GuardResult, step: str = "guard") -> _Fail:
        message = "; ".join(v.message for v in guarded.violations) or "El SQL fue rechazado."
        code = "user_config" if guarded.user_config_problem else "sql_rejected"
        return _Fail(step, code, message, recoverable=False)

    def _search_values(self, sql: str) -> list[str]:
        """Búsqueda de entidades: pasa por el guardián (y el filtro de rol) antes de ejecutarse."""
        try:
            guarded = check_sql(
                sql,
                self.model,
                self.datasource,
                self.version,
                self.role,
                cache=self.guard_cache,
                context=self.context,
            )
        except GuardRoleError as exc:
            raise _Fail("verify", "unknown_role", str(exc), recoverable=False) from exc
        if not guarded.allowed or guarded.sql is None:
            raise self._rejection(guarded, "verify")
        try:
            result, _ = self._run_query(guarded.sql)
        except _ExecError as exc:
            raise _Fail("verify", "execution_error", exc.message) from exc
        return [str(row[0]) for row in result.rows if row and row[0] is not None]

    def _run_query(self, sql: str) -> tuple[QueryResult, int]:
        started = time.perf_counter()
        try:
            result = self.query_executor.execute_sync(
                str(self.datasource.id),
                self.url,
                self.dialect,
                sql,
                execute=self.datasource.execute,
                max_rows=self.datasource.max_rows,
                timeout_seconds=self.datasource.timeout_seconds,
            )
        except (QueryTimeoutError, QueryExecutionError) as exc:
            raise _ExecError(str(exc)) from exc
        return result, _ms(time.perf_counter() - started)

    def _execute(self, t: _Turn, sql: str, outcome: _Outcome) -> Iterator[Event]:
        assert t.run is not None
        if not self.datasource.execute:
            outcome.executed = False
            yield _step("execute", "warning", "La fuente está en modo «solo SQL»: no se ejecutó")
            return
        yield _step("execute", "running")
        try:
            result, elapsed = self._run_query(sql)
        except _ExecError as exc:
            t.run.status = "error"
            raise _Fail("execute", "execution_error", exc.message) from exc
        outcome.columns, outcome.rows = result.columns, result.rows
        outcome.truncated = result.truncated
        t.run.row_count, t.run.elapsed_ms = len(result.rows), elapsed
        notes = list(result.warnings)
        if result.truncated:
            notes.append(f"Se muestran las primeras {len(result.rows)} filas")
        yield _step("execute", "warning" if notes else "done", "; ".join(notes) or None)
        yield Event(
            ResultData(
                columns=result.columns,
                rows=result.rows,
                row_count=len(result.rows),
                truncated=result.truncated,
                elapsed_ms=elapsed,
            )
        )

    # -- salidas

    def _sql_event(self, t: _Turn, sql: str, period: PeriodRange | None) -> Event:
        assert t.run is not None
        applied = t.run.filters_applied
        flat = [*applied.get("metric", []), *applied.get("request", [])]
        flat += [*applied.get("period", []), *applied.get("role", [])]
        period_data = None
        if period is not None:
            period_data = PeriodData(
                label=period.label,
                start=period.start.isoformat(),
                end_exclusive=period.end_exclusive.isoformat(),
            )
        return Event(
            SqlData(
                sql=sql,
                dialect=self.dialect,
                origin=t.run.origin,
                summary_table=t.run.summary_table,
                filters_applied=flat,
                period=period_data,
            )
        )

    def _filters_applied(
        self, verified: VerifiedPlan, period: PeriodRange | None
    ) -> dict[str, list[str]]:
        metric = verified.metric
        applied: dict[str, list[str]] = {
            "metric": list(metric.filters),
            "request": [f"{f.field} {f.op} {f.value!r}" for f in verified.filters],
        }
        if period is not None:
            column = metric.time_column
            bounds = f"{column} >= {period.start} AND {column} < {period.end_exclusive}"
            applied["period"] = [bounds]
        applied["role"] = self._role_filters()["role"]
        return applied

    def _role_filters(self) -> dict[str, list[str]]:
        role = next((r for r in self.model.security.roles if r.name == self.role), None)
        rules = role_row_filters(role) if role is not None else {}
        return {"role": [f"{table}: {condition}" for table, condition in rules.items()]}

    def _answer(self, t: _Turn, outcome: _Outcome) -> Iterator[Event]:
        """Responder: la IA redacta si el nivel de privacidad lo permite; si no, una plantilla."""
        yield _step("answer", "running")
        llm = self._llm("answer")
        writer = AnswerWriter(llm, self.model, self.privacy, t.question)
        yield from writer.stream(outcome)
        t.usage += writer.usage
        if writer.warning is not None:
            yield _step("answer", "warning", writer.warning)
        for notice in self._notices(llm):
            yield _step("answer", "warning", notice)
        yield _step("answer", "done")
        yield from self._say(t, writer.text)

    def _say(self, t: _Turn, text: str) -> Iterator[Event]:
        final = " ".join([text, *t.notes]) if t.notes else text
        t.text = final
        yield Event(Answer(text=final))

    def _ask(self, t: _Turn, ask: _Ask) -> Iterator[Event]:
        if ask.step is not None:
            yield _step(ask.step, "warning", ask.question.splitlines()[0])
        t.text = ask.question
        yield Event(ClarificationData(question=ask.question, options=ask.options, slot=ask.slot))

    def _fail(self, t: _Turn, fail: _Fail) -> Iterator[Event]:
        t.failed, t.error_code = True, fail.code
        if t.run is not None and t.run.status == "ok" and fail.code != "internal_error":
            t.run.status = "error"
        yield _step(fail.step, "error", fail.message)
        t.text = fail.message
        yield Event(ErrorData(code=fail.code, message=fail.message, recoverable=fail.recoverable))


# --------------------------------------------------------------------------- utilidades


def _step(step_id: str, status: StepStatus, detail: str | None = None) -> Event:
    return Event(Step(id=step_id, label=_LABELS[step_id], status=status, detail=detail))


_UNEXPECTED = "Ocurrió un error inesperado al procesar la pregunta."


def _begin_failed(conversation_id: str, started: float) -> Iterator[Event]:
    """Eventos de un turno que no pudo empezar (por ejemplo, la base de la app no responde)."""
    yield Event(TurnStarted(turn_id=str(uuid.uuid4()), conversation_id=conversation_id))
    yield _step("understand", "error", _UNEXPECTED)
    yield Event(ErrorData(code="internal_error", message=_UNEXPECTED, recoverable=True))
    yield Event(
        TurnCompleted(
            usage=UsageData(tokens_in=0, tokens_out=0, cost_usd=0.0),
            elapsed_ms=_ms(time.perf_counter() - started),
        )
    )


def _totals(usage: Usage) -> Totals:
    return Totals(usage.input_tokens, usage.output_tokens, usage.cost_usd or 0.0)


def _ms(seconds: float) -> int:
    return int(seconds * 1000)


def _load_plan(raw: dict[str, Any] | None) -> Plan | None:
    if not raw:
        return None
    try:
        return Plan.model_validate(raw)
    except ValidationError:
        return None


def _order_terms(plan: Plan, verified: VerifiedPlan) -> list[OrderTerm]:
    if plan.order is None:
        return []
    by = plan.order.by
    metric = verified.metric
    if by in (metric.name, metric.label, "valor"):
        key = "valor"
    elif by == "periodo":
        key = "periodo"
    else:
        key = by
    return [OrderTerm(key, plan.order.direction == "desc")]


def _comparison_skipped(
    plan: Plan, verified: VerifiedPlan, period: PeriodRange | None, can_execute: bool
) -> str | None:
    if period is None:
        return "Sin período no hay período anterior con el que comparar"
    if verified.dimensions or plan.time_grain is not None:
        return "La comparación es del total: se omitió por el desglose pedido"
    if not can_execute:
        return "La fuente no ejecuta consultas: no se puede comparar"
    return None
