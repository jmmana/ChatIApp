"""Sesiones del chat embebido (docs/API.md#integraciones-m3, docs/INTEGRACION.md).

`POST /embed/sessions` lo llama el backend de la app anfitriona con su API key (alcance `embed`);
el token que devuelve es lo único que ve el navegador.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.responses import Response
from starlette.types import Scope

from app.api.errors import ApiError
from app.api.preview import load_model
from app.db.session import get_session
from app.integrations.api_keys import Principal, require_scope
from app.integrations.embed_sessions import (
    DEFAULT_TTL_SECONDS,
    EMBED_SCOPE,
    MAX_TTL_SECONDS,
    create_embed_token,
    normalize_origin,
    origin_allowed,
)
from app.integrations.end_user import EndUser, EndUserError, resolve_end_user
from app.settings.registry import datasource_uuid

router = APIRouter(prefix="/embed", tags=["embed"])

SessionDep = Annotated[Session, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(require_scope(EMBED_SCOPE))]


class EmbedSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datasource: str = Field(min_length=1, description="UUID o `id` de `chatiapp.yaml`")
    origin: str = Field(min_length=1, description="Origen de la página que embebe el chat")
    user: EndUser
    ttl_seconds: int = Field(default=DEFAULT_TTL_SECONDS, ge=1, le=MAX_TTL_SECONDS)


class EmbedSessionOut(BaseModel):
    token: str
    expires_at: datetime


@router.post("/sessions", summary="Cambia la API key por un token de sesión para el navegador")
def create_session(
    body: EmbedSessionRequest, session: SessionDep, principal: PrincipalDep
) -> EmbedSessionOut:
    api_key = principal.api_key
    if api_key is None:  # un usuario con sesión no emite tokens: solo una API key
        raise ApiError(403, "api_key_required", "Este endpoint se llama con una API key.")
    try:
        origin = normalize_origin(body.origin)
    except ValueError as exc:
        raise ApiError(422, "invalid_origin", str(exc)) from exc
    if not origin_allowed(api_key, origin):
        raise ApiError(403, "origin_not_allowed", "La API key no permite este origen.")
    try:
        datasource_id = uuid.UUID(body.datasource)
    except ValueError:
        datasource_id = datasource_uuid(body.datasource)
    datasource, model, _version = load_model(session, datasource_id)
    try:
        access = resolve_end_user(api_key, datasource, model, body.user)
    except EndUserError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    token, expires_at = create_embed_token(
        api_key,
        user_id=access.external_user_id,
        datasource_id=datasource.id,
        role=access.role,
        attributes=access.context["user"],
        origin=origin,
        ttl_seconds=body.ttl_seconds,
    )
    return EmbedSessionOut(token=token, expires_at=expires_at)


EMBED_ASSETS_ROOT = "/embed/v1"


class _EmbedAssets(StaticFiles):
    """Archivos del widget: públicos y legibles desde cualquier página.

    `chatiapp.js` se carga con `<script src>`, pero importa el módulo del widget con `import()`,
    y los módulos entre orígenes exigen CORS. Son archivos estáticos sin datos ni credenciales.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Cache-Control"] = "public, max-age=300"
        return response


def mount_embed_assets(app: FastAPI, static_dir: Path) -> bool:
    """Sirve `<static_dir>/embed/v1` en `/embed/v1/` (`chatiapp.js` y sus partes).

    Devuelve si lo montó: sin la carpeta (p. ej. en desarrollo) no hay widget que servir.
    """
    directory = static_dir / "embed" / "v1"
    if not (directory / "chatiapp.js").is_file():
        return False
    app.mount(EMBED_ASSETS_ROOT, _EmbedAssets(directory=directory), name="embed-assets")
    return True
