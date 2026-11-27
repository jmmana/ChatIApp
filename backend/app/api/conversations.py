"""Conversaciones del usuario (docs/API.md#chat-y-conversaciones).

Cada usuario ve solo las suyas; una conversación ajena responde 404, igual que una inexistente.
Los mensajes del asistente guardan sus eventos para reconstruir la conversación en la interfaz.

Un token de sesión del chat embebido solo lista y lee las conversaciones de su usuario final
(las de su API key y su `external_user_id`); renombrar y eliminar exigen sesión de usuario.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import Conversation, Message, User
from app.db.session import get_session
from app.integrations.embed_sessions import Caller, get_caller
from app.security.auth import get_current_user

# Sin dependencia a nivel de router: lectura con sesión o token de sesión; el resto, solo sesión.
router = APIRouter(prefix="/conversations", tags=["conversaciones"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]
CallerDep = Annotated[Caller, Depends(get_caller)]


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    datasource_id: uuid.UUID
    created_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    events: list[Any] | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)


def _out(conversation: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        datasource_id=conversation.datasource_id,
        created_at=conversation.created_at,
    )


def _owned_by(caller: Caller) -> list[ColumnElement[bool]]:
    """Filtro de dueño: el usuario de sesión, o la API key más el usuario final del token."""
    if caller.embed is not None:
        return [
            Conversation.api_key_id == caller.embed.api_key.id,
            Conversation.external_user_id == caller.embed.user_id,
        ]
    assert caller.user is not None
    return [Conversation.user_id == caller.user.id]


def _get_own(session: Session, caller: Caller, conversation_id: uuid.UUID) -> Conversation:
    conversation = session.scalar(
        select(Conversation).where(Conversation.id == conversation_id, *_owned_by(caller))
    )
    if conversation is None:
        raise ApiError(404, "conversation_not_found", "La conversación no existe")
    return conversation


@router.get("", summary="Conversaciones del usuario, las más recientes primero")
def list_conversations(session: SessionDep, caller: CallerDep) -> list[ConversationOut]:
    rows = session.scalars(
        select(Conversation).where(*_owned_by(caller)).order_by(Conversation.created_at.desc())
    ).all()
    return [_out(c) for c in rows]


@router.get("/{conversation_id}", summary="Mensajes de la conversación con sus eventos")
def get_conversation(
    conversation_id: uuid.UUID, session: SessionDep, caller: CallerDep
) -> ConversationDetail:
    conversation = _get_own(session, caller, conversation_id)
    messages = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.role.desc())
    ).all()
    return ConversationDetail(
        **_out(conversation).model_dump(),
        messages=[
            MessageOut(
                id=m.id, role=m.role, content=m.content, events=m.events, created_at=m.created_at
            )
            for m in messages
        ],
    )


@router.patch("/{conversation_id}", summary="Renombrar")
def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, session: SessionDep, user: UserDep
) -> ConversationOut:
    conversation = _get_own(session, Caller(user=user), conversation_id)
    conversation.title = body.title.strip()
    session.commit()
    return _out(conversation)


@router.delete("/{conversation_id}", status_code=204, summary="Eliminar")
def delete_conversation(conversation_id: uuid.UUID, session: SessionDep, user: UserDep) -> Response:
    conversation = _get_own(session, Caller(user=user), conversation_id)
    # Borrado en la base (ON DELETE CASCADE) para no depender del ORM con los mensajes.
    session.execute(delete(Conversation).where(Conversation.id == conversation.id))
    session.commit()
    return Response(status_code=204)
