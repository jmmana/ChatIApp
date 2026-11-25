"""Modelos ORM de la base de datos de la app (docs/ARQUITECTURA.md#modelo-de-datos-de-la-app)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    grants: Mapped[list["Grant"]] = relationship(back_populates="user")


class Datasource(Base):
    __tablename__ = "datasource"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    dialect: Mapped[str] = mapped_column(String(50))
    url_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    execute: Mapped[bool] = mapped_column(Boolean, default=False)
    max_rows: Mapped[int] = mapped_column(Integer, default=1000)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    privacy: Mapped[str] = mapped_column(String(20), default="schema")  # schema|aggregates|samples
    managed_by: Mapped[str] = mapped_column(String(20), default="ui")  # ui | config

    grants: Mapped[list["Grant"]] = relationship(back_populates="datasource")
    versions: Mapped[list["SemanticModelVersion"]] = relationship(back_populates="datasource")


class Grant(Base):
    __tablename__ = "grant"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasource.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(100))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    user: Mapped[User] = relationship(back_populates="grants")
    datasource: Mapped[Datasource] = relationship(back_populates="grants")


class SemanticModelVersion(Base):
    __tablename__ = "semantic_model_version"
    __table_args__ = (UniqueConstraint("datasource_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasource.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    model: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    datasource: Mapped[Datasource] = relationship(back_populates="versions")


class Provider(Base):
    __tablename__ = "provider"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    kind: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secrets_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    managed_by: Mapped[str] = mapped_column(String(20), default="ui")  # ui | config


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # La tabla API_KEY llega con la tarea de integraciones: por ahora sin clave foránea.
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasource.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="")
    last_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "message"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    events: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    query_run: Mapped["QueryRun | None"] = relationship(back_populates="message", uselist=False)


class QueryRun(Base):
    __tablename__ = "query_run"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), unique=True
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # La tabla API_KEY llega con la tarea de integraciones: por ahora sin clave foránea.
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    origin: Mapped[str] = mapped_column(String(20))  # catalog | llm
    sql_final: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_table: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filters_applied: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # ok | rejected | error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    message: Mapped[Message] = relationship(back_populates="query_run")


class EvalRun(Base):
    __tablename__ = "eval_run"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider.id", ondelete="CASCADE"), index=True
    )
    eval_set: Mapped[str] = mapped_column(String(255))
    accuracy: Mapped[float] = mapped_column(Float)
    p50_latency_ms: Mapped[float] = mapped_column(Float)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
