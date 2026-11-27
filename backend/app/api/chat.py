"""Chat (docs/API.md#chat-y-conversaciones, ADR 0006): SSE y `POST /chat` sin streaming.

El orquestador es un generador síncrono: cada turno corre en un hilo propio, con su propia sesión
de base de datos, y reenvía sus eventos a una cola que el endpoint vacía hacia el cliente. Así el
bucle de eventos no se bloquea con la IA ni con la base de datos del usuario, se puede mandar un
comentario keep-alive mientras se espera y `cancel` puede cortar el turno sin esperar al hilo.

`/chat/stream` y `/chat/{turn_id}/cancel` son solo de sesión. `POST /chat` (sin streaming)
acepta además una API key con alcance `chat`; con key, la identidad sale del campo `user` dentro
del techo de la key y las conversaciones se aíslan por `api_key_id` + `external_user_id`.
"""

import asyncio
import contextlib
import logging
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Generator
from dataclasses import dataclass, field
from typing import Annotated, Any, cast

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
from app.db.models import ApiKey, Conversation, Datasource, Message, Provider, User
from app.db.session import get_session
from app.integrations.api_keys import Principal, require_scope
from app.integrations.end_user import EndUser, EndUserError, resolve_end_user
from app.llm.gateway import Gateway, ProviderConfig
from app.security.auth import get_current_user
from app.security.crypto import SecretKeyError, decrypt
from app.security.limits import check_api_key_budget, check_turn
from app.semantic.schema import SemanticModel
from app.settings.registry import datasource_uuid, provider_uuid

logger = logging.getLogger(__name__)

# Sin dependencia a nivel de router: cada ruta declara su credencial (sesión o API key con `chat`).
router = APIRouter(prefix="/chat", tags=["chat"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]
PrincipalDep = Annotated[Principal, Depends(require_scope("chat"))]
CipherDep = Annotated[MultiFernet, Depends(get_request_cipher)]

KEEPALIVE_SECONDS = 15.0
TITLE_LENGTH = 60
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # que un proxy delante no acumule los eventos
    "Connection": "keep-alive",
}
CANCELLED = ErrorData(code="cancelled", message="El turno fue cancelado.", recoverable=True)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID | None = None
    datasource_id: str = Field(min_length=1, description="UUID o `id` de `chatiapp.yaml`")
    message: str = Field(min_length=1, max_length=4000)
    provider_override: str | None = Field(default=None, description="UUID o `id` del archivo")
    view_as: ViewAs | None = None
    # Obligatorio con API key (solo `POST /chat`); con sesión se ignora.
    user: EndUser | None = None


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
    session: Session,
    datasource: Datasource,
    body: ChatRequest,
    *,
    user: User | None,
    api_key: ApiKey | None,
    owner: str | None = None,
) -> Conversation:
    """La conversación pedida si es del mismo dueño; si no, 404 (no se revela que existe).

    Dueño: el usuario de sesión, o la API key más el `external_user_id` del usuario final.
    """
    user_id = user.id if user else None
    api_key_id = api_key.id if api_key else None
    external = owner if api_key is not None else None
    if body.conversation_id is None:
        conversation = Conversation(
            user_id=user_id,
            api_key_id=api_key_id,
            external_user_id=external,
            datasource_id=datasource.id,
            title=body.message.strip()[:TITLE_LENGTH],
        )
        session.add(conversation)
        session.commit()
        return conversation
    existing = session.get(Conversation, body.conversation_id)
    if (
        existing is None
        or existing.user_id != user_id
        or existing.api_key_id != api_key_id
        or existing.external_user_id != external
    ):
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


@router.post("/stream", summary="Envía un mensaje y recibe el turno por SSE")
async def chat_stream(
    body: ChatRequest, session: SessionDep, user: UserDep, cipher: CipherDep
) -> StreamingResponse:
    # Todo lo que puede fallar con 4xx pasa antes de abrir el stream.
    datasource_id = _uuid_or_config(body.datasource_id, datasource_uuid)
    datasource, model, version = load_model(session, datasource_id)
    role, context = resolve_identity(session, user, datasource, model, body.view_as)
    provider = _provider(session, body.provider_override)
    try:
        url = decrypt(datasource.url_encrypted, cipher)
    except SecretKeyError as exc:
        raise ApiError(500, "secret_key_invalid", str(exc)) from exc
    conversation = _conversation(session, datasource, body, user=user, api_key=None)
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
    return StreamingResponse(_stream(turn), media_type="text/event-stream", headers=SSE_HEADERS)


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


# --------------------------------------------------------------------------- sin streaming


def _turn_response(conversation_id: uuid.UUID, events: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, dict[str, Any]] = {e["type"]: e["data"] for e in events}
    out: dict[str, Any] = {"conversation_id": str(conversation_id)}
    if "error" in by_type:
        out["status"] = "error"
        out["error"] = by_type["error"]
    elif "clarification" in by_type:
        out["status"] = "needs_clarification"
        out["clarification"] = by_type["clarification"]
    else:
        out["status"] = "answered"
    if "reasoning" in by_type:
        out["reasoning"] = by_type["reasoning"]["text"]
    if "sql" in by_type:
        sql = dict(by_type["sql"])
        out["period"] = sql.pop("period", None)
        out["sql"] = sql
    if "result" in by_type:
        out["result"] = by_type["result"]
    if "answer" in by_type:
        out["answer"] = by_type["answer"]["text"]
    if "turn.completed" in by_type:
        out["usage"] = by_type["turn.completed"]["usage"]
    return out


@router.post("", summary="Un turno de chat sin streaming (sesión o API key)")
def chat(
    body: ChatRequest, session: SessionDep, cipher: CipherDep, principal: PrincipalDep
) -> dict[str, Any]:
    datasource_id = _uuid_or_config(body.datasource_id, datasource_uuid)
    datasource, model, version = load_model(session, datasource_id)
    role: str | None
    context: dict[str, Any]
    try:
        if principal.api_key is not None:
            access = resolve_end_user(principal.api_key, datasource, model, body.user)
            role, context, owner = access.role, access.context, access.external_user_id
        else:
            assert principal.user is not None
            role, context = resolve_identity(
                session, principal.user, datasource, model, body.view_as
            )
            owner = str(principal.user.id)
    except EndUserError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc

    # Nada se ejecuta hasta aquí: la identidad ya está validada.
    check_turn(principal)
    if principal.api_key is not None:
        check_api_key_budget(session, principal.api_key)
    conversation = _conversation(
        session, datasource, body, user=principal.user, api_key=principal.api_key, owner=owner
    )
    # Una API key no elige proveedor: solo la configuración del administrador.
    override = body.provider_override if principal.api_key is None else None
    provider = _provider(session, override)
    orchestrator = Orchestrator(
        session,
        Gateway(ProviderConfig.from_provider(provider)),
        datasource,
        model,
        version,
        decrypt(datasource.url_encrypted, cipher),
        role=role,
        context=context,
        provider_id=provider.id,
        api_key_id=principal.api_key_id,
    )
    events = [e.to_dict() for e in orchestrator.run(conversation, body.message)]
    return _turn_response(conversation.id, events)
