"""Chat por SSE (docs/API.md#chat-y-conversaciones, ADR 0006).

El orquestador es un generador síncrono: cada turno corre en un hilo propio, con su propia sesión
de base de datos, y reenvía sus eventos a una cola que el endpoint vacía hacia el cliente. Así el
bucle de eventos no se bloquea con la IA ni con la base de datos del usuario, se puede mandar un
comentario keep-alive mientras se espera y `cancel` puede cortar el turno sin esperar al hilo.
"""

import asyncio
import contextlib
import logging
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Generator
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, cast

from cryptography.fernet import MultiFernet
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agent.events import ErrorData, Event
from app.agent.orchestrator import Orchestrator
from app.api.datasources import get_request_cipher
from app.api.errors import ApiError
from app.api.preview import ViewAs, load_model, resolve_identity
from app.db.models import Conversation, Datasource, Message, Provider, User
from app.db.session import get_session
from app.engine.rls import AttributeValue
from app.llm.gateway import Gateway, ProviderConfig
from app.security.auth import get_current_user
from app.security.crypto import SecretKeyError, decrypt
from app.semantic.schema import SemanticModel
from app.settings.env import get_settings
from app.settings.registry import datasource_uuid, provider_uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]
CipherDep = Annotated[MultiFernet, Depends(get_request_cipher)]

KEEPALIVE_SECONDS = 15.0
TITLE_LENGTH = 60
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # que un proxy delante no acumule los eventos
    "Connection": "keep-alive",
}
REJECTION_CODES = {"sql_rejected", "user_config"}
CANCELLED = ErrorData(code="cancelled", message="El turno fue cancelado.", recoverable=True)


class EndUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: str | None = None
    attributes: dict[str, AttributeValue] = {}


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID | None = None
    datasource_id: str = Field(min_length=1, description="UUID o `id` de `chatiapp.yaml`")
    message: str = Field(min_length=1, max_length=4000)
    provider_override: str | None = Field(default=None, description="UUID o `id` del archivo")
    view_as: ViewAs | None = None
    # Solo lo usan las API keys (aún no soportadas aquí): con otras credenciales se ignora.
    user: EndUser | None = None


class ChatTurnOut(BaseModel):
    """Turno completo de `POST /api/v1/chat` (docs/INTEGRACION.md#sin-streaming)."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    status: Literal["answered", "needs_clarification", "rejected", "error"]
    reasoning: str | None = None
    clarification: dict[str, Any] | None = None
    period: dict[str, Any] | None = None
    sql: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    answer: str | None = None
    error: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


class CancelOut(BaseModel):
    turn_id: str
    status: str


# --------------------------------------------------------------------------- turnos en curso


class _Done:
    """Marca de fin de la cola."""


class _Cancelled:
    """Marca de cancelación de la cola."""


@dataclass
class _Turn:
    """Un turno en curso: lo que el hilo y el endpoint comparten."""

    user_id: uuid.UUID
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    cancel: threading.Event = field(default_factory=threading.Event)

    def post(self, item: Any) -> None:
        """Pone `item` en la cola desde cualquier hilo; si el bucle ya cerró, se descarta."""
        with contextlib.suppress(RuntimeError):
            self.loop.call_soon_threadsafe(self.queue.put_nowait, item)


_active: dict[str, _Turn] = {}
_lock = threading.Lock()


def _register(turn_id: str, turn: _Turn) -> None:
    with _lock:
        _active[turn_id] = turn


def _unregister(turn_id: str | None) -> None:
    if turn_id is not None:
        with _lock:
            _active.pop(turn_id, None)


# --------------------------------------------------------------------------- resolución


def _uuid_or_config(value: str, from_config: Callable[[str], uuid.UUID]) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return from_config(value)


def _provider(session: Session, override: str | None) -> Provider:
    if override is not None:
        provider = session.get(Provider, _uuid_or_config(override, provider_uuid))
        if provider is None:
            raise ApiError(404, "provider_not_found", "El proveedor de IA no existe")
        return provider
    provider = session.scalars(select(Provider).where(Provider.is_default.is_(True))).first()
    provider = provider or session.scalars(select(Provider).order_by(Provider.name)).first()
    if provider is None:
        raise ApiError(422, "no_provider", "No hay un proveedor de IA configurado")
    return provider


def _conversation(
    session: Session, user: User, datasource: Datasource, body: ChatRequest
) -> Conversation:
    if body.conversation_id is None:
        conversation = Conversation(
            user_id=user.id, datasource_id=datasource.id, title=body.message.strip()[:TITLE_LENGTH]
        )
        session.add(conversation)
        session.commit()
        return conversation
    existing = session.get(Conversation, body.conversation_id)
    if existing is None or existing.user_id != user.id:
        raise ApiError(404, "conversation_not_found", "La conversación no existe")
    if existing.datasource_id != datasource.id:
        raise ApiError(409, "datasource_mismatch", "La conversación es de otra fuente de datos")
    return existing


@dataclass
class _Plan:
    """Todo lo que el hilo necesita, ya validado antes de abrir el stream."""

    engine: Engine
    conversation_id: uuid.UUID
    datasource_id: uuid.UUID
    provider_id: uuid.UUID
    provider: ProviderConfig
    model: SemanticModel
    version: int
    url: str
    role: str | None
    context: dict[str, Any]
    message: str


# --------------------------------------------------------------------------- el hilo del turno


def _run_turn(plan: _Plan, turn: _Turn) -> None:
    turn_id: str | None = None
    try:
        with Session(plan.engine, expire_on_commit=False) as session:
            datasource = session.get(Datasource, plan.datasource_id)
            conversation = session.get(Conversation, plan.conversation_id)
            assert datasource is not None and conversation is not None
            orchestrator = Orchestrator(
                session,
                Gateway(plan.provider),
                datasource,
                plan.model,
                plan.version,
                plan.url,
                role=plan.role,
                context=plan.context,
                provider_id=plan.provider_id,
            )
            events = cast(
                Generator[Event, None, None], orchestrator.run(conversation, plan.message)
            )
            cancelled = False
            try:
                for event in events:
                    if turn.cancel.is_set():
                        cancelled = True
                        break
                    if event.type == "turn.started":
                        turn_id = str(event.payload()["turn_id"])
                        _register(turn_id, turn)
                    turn.post(event)
            finally:
                events.close()  # el orquestador guarda lo que haya al cerrarse
            if cancelled or turn.cancel.is_set():
                _mark_cancelled(session, turn_id)
    except Exception:
        logger.exception("Falló el turno de chat")
        failure = ErrorData(code="internal_error", message="Error inesperado.", recoverable=True)
        turn.post(Event(failure))
    finally:
        _unregister(turn_id)
        turn.post(_Done())


def _mark_cancelled(session: Session, turn_id: str | None) -> None:
    """Deja el `error` de cancelación en los eventos guardados del mensaje."""
    if turn_id is None:
        return
    try:
        message = session.get(Message, uuid.UUID(turn_id))
        if message is None:
            return
        message.events = [*(message.events or []), Event(CANCELLED).to_dict()]
        message.content = message.content or CANCELLED.message
        session.commit()
    except Exception:
        logger.exception("No se pudo guardar la cancelación del turno %s", turn_id)
        session.rollback()


async def _stream(turn: _Turn) -> AsyncIterator[str]:
    try:
        while True:
            try:
                item = await asyncio.wait_for(turn.queue.get(), KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if isinstance(item, _Done):
                return
            if isinstance(item, _Cancelled):
                yield Event(CANCELLED).sse()
                return
            yield item.sse()
    finally:
        turn.cancel.set()  # el cliente se fue o el turno terminó: que el hilo no siga


# --------------------------------------------------------------------------- rutas


def _start_turn(
    body: ChatRequest, session: Session, user: User, cipher: MultiFernet
) -> tuple[_Turn, uuid.UUID]:
    """Valida el cuerpo y lanza el hilo del turno; devuelve el turno y su conversación."""
    # Todo lo que puede fallar con 4xx pasa antes de empezar a responder.
    datasource_id = _uuid_or_config(body.datasource_id, datasource_uuid)
    datasource, model, version = load_model(session, datasource_id)
    role, context = resolve_identity(session, user, datasource, model, body.view_as)
    provider = _provider(session, body.provider_override)
    try:
        url = decrypt(datasource.url_encrypted, cipher)
    except SecretKeyError as exc:
        raise ApiError(500, "secret_key_invalid", str(exc)) from exc
    conversation = _conversation(session, user, datasource, body)
    engine = session.get_bind()
    assert isinstance(engine, Engine)
    plan = _Plan(
        engine=engine,
        conversation_id=conversation.id,
        datasource_id=datasource.id,
        provider_id=provider.id,
        provider=ProviderConfig.from_provider(provider),
        model=model,
        version=version,
        url=url,
        role=role,
        context=context,
        message=body.message,
    )
    turn = _Turn(user_id=user.id, loop=asyncio.get_running_loop())
    threading.Thread(target=_run_turn, args=(plan, turn), daemon=True).start()
    return turn, conversation.id


def _build_turn(conversation_id: uuid.UUID, events: list[Event]) -> ChatTurnOut:
    """Arma la respuesta JSON a partir de los mismos eventos que emite el stream."""
    out = ChatTurnOut(conversation_id=str(conversation_id), status="answered")
    for event in events:
        data = event.payload()
        match event.type:
            case "reasoning":
                out.reasoning = data["text"]
            case "clarification":
                out.status = "needs_clarification"
                out.clarification = data
            case "sql":
                out.period = data.pop("period", None)
                out.sql = {"text": data.pop("sql"), **data}
            case "result":
                out.result = {key: data[key] for key in ("columns", "rows", "truncated")}
            case "answer":
                out.answer = data["text"]
            case "error":
                out.status = "rejected" if data["code"] in REJECTION_CODES else "error"
                out.error = data
            case "turn.completed":
                out.usage = data["usage"]
            case _:
                pass
    return out


async def _collect(turn: _Turn) -> list[Event]:
    events: list[Event] = []
    while True:
        item = await turn.queue.get()
        if isinstance(item, _Done):
            return events
        if isinstance(item, _Cancelled):
            events.append(Event(CANCELLED))
            return events
        events.append(item)


@router.post("/stream", summary="Envía un mensaje y recibe el turno por SSE")
async def chat_stream(
    body: ChatRequest, session: SessionDep, user: UserDep, cipher: CipherDep
) -> StreamingResponse:
    turn, _ = _start_turn(body, session, user, cipher)
    return StreamingResponse(_stream(turn), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("", summary="Envía un mensaje y recibe el turno completo en un JSON")
async def chat(
    body: ChatRequest, session: SessionDep, user: UserDep, cipher: CipherDep
) -> ChatTurnOut:
    turn, conversation_id = _start_turn(body, session, user, cipher)
    seconds = get_settings().chat_timeout_seconds
    try:
        events = await asyncio.wait_for(_collect(turn), seconds)
    except TimeoutError:
        raise ApiError(
            504, "turn_timeout", f"El turno superó el tiempo máximo de {seconds:g} s"
        ) from None
    finally:
        turn.cancel.set()  # terminó o venció el plazo: que el hilo no siga
    return _build_turn(conversation_id, events)


@router.post("/{turn_id}/cancel", summary="Cancela un turno en curso")
def cancel_turn(turn_id: str, user: UserDep) -> CancelOut:
    with _lock:
        turn = _active.get(turn_id)
        if turn is not None and turn.user_id == user.id:
            del _active[turn_id]  # cancelado: ya no está en curso, aunque el hilo tarde en cerrar
    if turn is None or turn.user_id != user.id:
        raise ApiError(404, "turn_not_found", "El turno no existe o ya terminó")
    turn.cancel.set()
    turn.post(_Cancelled())
    return CancelOut(turn_id=turn_id, status="cancelled")
