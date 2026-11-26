"""Endpoints del modelo semántico versionado (docs/API.md#fuentes-de-datos)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import Datasource, SemanticModelVersion, User
from app.db.session import get_session
from app.security.auth import require_admin
from app.semantic import store
from app.semantic.schema import SemanticModelError, parse_semantic_model

router = APIRouter(prefix="/datasources/{datasource_id}/semantic", tags=["modelo semántico"])
# Ver el modelo basta con sesión; publicar versiones es administración.
# El modelo incluye columnas ocultas y filtros por rol: leerlo también es administración.
ADMIN = [Depends(require_admin)]

SessionDep = Annotated[Session, Depends(get_session)]


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=0, description="Versión vigente que vio el cliente (0 si no hay)")
    model: dict[str, Any]


class VersionInfo(BaseModel):
    version: int
    created_by: uuid.UUID | None
    created_at: datetime


class VersionOut(VersionInfo):
    model: dict[str, Any]


def _info(row: SemanticModelVersion) -> VersionInfo:
    return VersionInfo(version=row.version, created_by=row.created_by, created_at=row.created_at)


def _out(row: SemanticModelVersion) -> VersionOut:
    return VersionOut(
        version=row.version, created_by=row.created_by, created_at=row.created_at, model=row.model
    )


def _check_datasource(session: Session, datasource_id: uuid.UUID) -> None:
    if session.get(Datasource, datasource_id) is None:
        raise ApiError(404, "datasource_not_found", "La fuente de datos no existe")


def _current_or_404(session: Session, datasource_id: uuid.UUID) -> SemanticModelVersion:
    _check_datasource(session, datasource_id)
    row = store.current(session, datasource_id)
    if row is None:
        raise ApiError(404, "semantic_model_not_found", "La fuente aún no tiene modelo semántico")
    return row


@router.get("", summary="Versión vigente del modelo semántico", dependencies=ADMIN)
def get_semantic(datasource_id: uuid.UUID, session: SessionDep) -> VersionOut:
    return _out(_current_or_404(session, datasource_id))


@router.put("", summary="Publica una versión nueva del modelo", dependencies=ADMIN)
def put_semantic(
    datasource_id: uuid.UUID,
    body: PublishRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_admin)],
) -> VersionOut:
    _check_datasource(session, datasource_id)
    try:
        model = parse_semantic_model(body.model)
    except SemanticModelError as exc:
        raise ApiError(
            422,
            "invalid_semantic_model",
            "El modelo semántico no es válido",
            {"errors": [{"path": i.path, "message": i.message} for i in exc.issues]},
        ) from exc
    try:
        row = store.publish(session, datasource_id, model, body.base_version, user)
    except store.VersionConflictError as exc:
        raise ApiError(
            409,
            "version_conflict",
            "Alguien publicó una versión nueva antes: recarga el modelo y vuelve a intentar",
            {"current_version": exc.current_version},
        ) from exc
    return _out(row)


@router.get(
    "/versions", summary="Historial de versiones (la más reciente primero)", dependencies=ADMIN
)
def list_versions(datasource_id: uuid.UUID, session: SessionDep) -> list[VersionInfo]:
    _check_datasource(session, datasource_id)
    return [_info(row) for row in store.list_versions(session, datasource_id)]


@router.get(
    "/versions/{version}", summary="Una versión del historial, con su modelo", dependencies=ADMIN
)
def get_version(datasource_id: uuid.UUID, version: int, session: SessionDep) -> VersionOut:
    _check_datasource(session, datasource_id)
    row = store.get_version(session, datasource_id, version)
    if row is None:
        raise ApiError(404, "version_not_found", f"No existe la versión {version}")
    return _out(row)


@router.get("/export", summary="Exporta el modelo vigente a YAML o JSON", dependencies=ADMIN)
def export_semantic(
    datasource_id: uuid.UUID, session: SessionDep, format: Literal["yaml", "json"] = "yaml"
) -> Response:
    row = _current_or_404(session, datasource_id)
    text = store.export_model(store.load_model(row), format)
    media = "application/json" if format == "json" else "application/yaml"
    return Response(
        content=text,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="modelo-v{row.version}.{format}"'},
    )
