"""Chat sin streaming (docs/API.md#chat-y-conversaciones): `POST /api/v1/chat`.

Acepta la sesión de un usuario o una API key con alcance `chat`. Con API key, la identidad sale
del campo `user` dentro del techo de la key (`integrations/end_user.py`); con sesión, del permiso
del usuario en la fuente. Las conversaciones quedan ligadas a su dueño y no se comparten.
"""

import contextlib
import uuid
from typing import Annotated, Any

from cryptography.fernet import MultiFernet
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.orchestrator import Orchestrator
from app.api.datasources import get_request_cipher
from app.api.errors import ApiError
from app.api.preview import ViewAs, _load
from app.db.models import Conversation, Datasource, Provider
from app.db.session import get_session
from app.integrations.api_keys import Principal, require_scope
from app.integrations.end_user import EndUser, EndUserError, resolve_end_user
from app.llm.gateway import Gateway, ProviderConfig
from app.security.crypto import decrypt
from app.security.grants import GrantError, resolve_access
from app.security.grants import ViewAs as GrantViewAs
from app.security.limits import check_api_key_budget, check_turn
from app.settings.registry import datasource_uuid

# Acepta sesión de usuario o API key; `require_scope` responde 401 sin credencial válida.
router = APIRouter(tags=["chat"], dependencies=[Depends(require_scope("chat"))])

SessionDep = Annotated[Session, Depends(get_session)]
CipherDep = Annotated[MultiFernet, Depends(get_request_cipher)]
PrincipalDep = Annotated[Principal, Depends(require_scope("chat"))]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    datasource_id: str = Field(min_length=1, description="UUID o `id` de `chatiapp.yaml`")
    conversation_id: uuid.UUID | None = None
    view_as: ViewAs | None = None
    user: EndUser | None = Field(
        default=None, description="Usuario final: obligatorio con API key, se ignora sin ella"
    )


def _find_datasource(session: Session, ref: str) -> Datasource:
    candidates: list[uuid.UUID] = [datasource_uuid(ref)]
    with contextlib.suppress(ValueError):
        candidates.insert(0, uuid.UUID(ref))
    for candidate in candidates:
        datasource = session.get(Datasource, candidate)
        if datasource is not None:
            return datasource
    raise ApiError(404, "datasource_not_found", "La fuente de datos no existe")


def _provider(session: Session) -> Provider:
    providers = list(session.scalars(select(Provider).order_by(Provider.name)))
    chosen = next((p for p in providers if p.is_default), providers[0] if providers else None)
    if chosen is None:
        raise ApiError(409, "no_provider", "No hay un proveedor de IA configurado")
    return chosen


def _conversation(
    session: Session, principal: Principal, datasource: Datasource, body: ChatRequest, owner: str
) -> Conversation:
    """La conversación pedida si es del mismo dueño; si no, 404 (no se revela que existe)."""
    if body.conversation_id is None:
        conversation = Conversation(
            datasource_id=datasource.id,
            user_id=principal.user_id,
            api_key_id=principal.api_key_id,
            external_user_id=owner if principal.api_key is not None else None,
        )
        session.add(conversation)
        session.commit()
        return conversation
    conversation = session.get(Conversation, body.conversation_id)
    mine = (
        conversation is not None
        and conversation.datasource_id == datasource.id
        and conversation.user_id == principal.user_id
        and conversation.api_key_id == principal.api_key_id
        and (principal.api_key is None or conversation.external_user_id == owner)
    )
    if conversation is None or not mine:
        raise ApiError(404, "conversation_not_found", "La conversación no existe")
    return conversation


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


@router.post("/chat", summary="Un turno de chat sin streaming")
def chat(
    body: ChatRequest, session: SessionDep, cipher: CipherDep, principal: PrincipalDep
) -> dict[str, Any]:
    datasource = _find_datasource(session, body.datasource_id)
    _, model, version = _load(session, datasource.id)
    role: str | None
    context: dict[str, Any]
    try:
        if principal.api_key is not None:
            access = resolve_end_user(principal.api_key, datasource, model, body.user)
            role, context, owner = access.role, access.context, access.external_user_id
        else:
            assert principal.user is not None
            view_as = (
                GrantViewAs(body.view_as.role, body.view_as.attributes) if body.view_as else None
            )
            granted = resolve_access(session, principal.user, datasource, model, view_as)
            role, context, owner = granted.role, granted.context, str(principal.user.id)
    except EndUserError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    except GrantError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc

    # Nada se ejecuta hasta aquí: la identidad ya está validada.
    check_turn(principal)
    if principal.api_key is not None:
        check_api_key_budget(session, principal.api_key)
    conversation = _conversation(session, principal, datasource, body, owner)
    provider = _provider(session)
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
