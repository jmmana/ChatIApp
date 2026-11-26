"""Administración de API keys (docs/API.md#integraciones-m3).

`main.create_app` incluye este router con `require_admin`: solo un administrador con sesión de
usuario (JWT) lo usa; ninguna API key puede administrar keys.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.models import ApiKey
from app.db.session import get_session
from app.integrations import api_keys as service
from app.security.auth import AuthError

router = APIRouter(prefix="/api-keys", tags=["integraciones"])

Scope = Literal["chat", "embed", "sql:preview", "semantic:read", "semantic:write"]
SessionDep = Annotated[Session, Depends(get_session)]

# Campos de la edición que admiten `null` (quitar el límite o la expiración).
_NULLABLE = {"rate_limit_per_minute", "monthly_budget_usd", "expires_at"}


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    scopes: list[Scope] = Field(min_length=1)
    datasources: list[str] = []
    allowed_roles: list[str] = []
    allowed_origins: list[str] = []
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    monthly_budget_usd: Decimal | None = Field(default=None, ge=0)
    expires_at: datetime | None = None


class ApiKeyUpdate(BaseModel):
    """Solo se cambian los campos enviados."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    scopes: list[Scope] | None = Field(default=None, min_length=1)
    datasources: list[str] | None = None
    allowed_roles: list[str] | None = None
    allowed_origins: list[str] | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    monthly_budget_usd: Decimal | None = Field(default=None, ge=0)
    expires_at: datetime | None = None


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    datasources: list[str]
    allowed_roles: list[str]
    allowed_origins: list[str]
    rate_limit_per_minute: int | None
    monthly_budget_usd: Decimal | None
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    secret: str  # solo se devuelve en esta respuesta


def _out(api_key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut.model_validate(api_key, from_attributes=True)


def _invalid(exc: ValueError) -> AuthError:
    return AuthError(422, "validation_error", str(exc))


@router.get("", summary="Lista las API keys")
def list_keys(session: SessionDep) -> list[ApiKeyOut]:
    return [_out(k) for k in service.list_api_keys(session)]


@router.post("", status_code=201, summary="Crea una API key; el secreto se muestra una sola vez")
def create_key(body: ApiKeyCreate, session: SessionDep) -> ApiKeyCreated:
    try:
        api_key, secret = service.create_api_key(session, **body.model_dump())
    except ValueError as exc:
        raise _invalid(exc) from exc
    return ApiKeyCreated(**_out(api_key).model_dump(), secret=secret)


@router.patch("/{key_id}", summary="Edita alcances, fuentes, roles, orígenes, límites o expiración")
def update_key(key_id: uuid.UUID, body: ApiKeyUpdate, session: SessionDep) -> ApiKeyOut:
    changes = body.model_dump(exclude_unset=True)
    if any(value is None for field, value in changes.items() if field not in _NULLABLE):
        raise AuthError(422, "validation_error", "Solo los límites y la expiración admiten null.")
    try:
        return _out(service.update_api_key(session, key_id, changes))
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.post("/{key_id}/revoke", summary="Revoca la key al instante")
def revoke_key(key_id: uuid.UUID, session: SessionDep) -> ApiKeyOut:
    return _out(service.revoke_api_key(session, key_id))
