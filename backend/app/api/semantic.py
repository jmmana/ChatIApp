"""Endpoints del modelo semántico versionado (docs/API.md#fuentes-de-datos)."""

import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import PurePath
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import Datasource, SemanticModelVersion, User
from app.db.session import get_session
from app.llm.gateway import GatewayError
from app.llm.routing import LlmClient, load_router
from app.security.auth import require_admin
from app.semantic import store
from app.semantic.context import Privacy
from app.semantic.importers.ddl import import_ddl
from app.semantic.importers.dictionary import (
    DictionaryError,
    DictionaryResult,
    parse_dictionary_csv,
    parse_dictionary_xlsx,
)
from app.semantic.importers.model_file import parse_model_text
from app.semantic.merge import Imported, merge_import
from app.semantic.schema import Issue, SemanticModelError, parse_semantic_model
from app.semantic.suggest import Suggestion, suggest

router = APIRouter(prefix="/datasources/{datasource_id}/semantic", tags=["modelo semántico"])
# Ver el modelo basta con sesión; publicar versiones es administración.
# El modelo incluye columnas ocultas y filtros por rol: leerlo también es administración.
ADMIN = [Depends(require_admin)]

SessionDep = Annotated[Session, Depends(get_session)]


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=0, description="Versión vigente que vio el cliente (0 si no hay)")
    model: dict[str, Any]


class ImportPreview(BaseModel):
    model: dict[str, Any]
    diff: dict[str, list[dict[str, Any]]]
    warnings: list[dict[str, str]]


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


class SuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tables: list[str] | None = Field(
        default=None, description="Limita las sugerencias a estas tablas (por defecto, todas)"
    )


def get_suggest_llm(session: SessionDep) -> LlmClient:
    """Pasarela de la tarea `suggest` del enrutamiento (con su respaldo)."""
    return load_router(session).for_task("suggest")


@router.post(
    "/suggest",
    summary="Sugerencias de la IA para descripciones, sinónimos y roles vacíos (no guarda)",
    dependencies=ADMIN,
)
def suggest_semantic(
    datasource_id: uuid.UUID,
    session: SessionDep,
    llm: Annotated[LlmClient, Depends(get_suggest_llm)],
    body: SuggestRequest | None = None,
) -> list[Suggestion]:
    datasource = session.get(Datasource, datasource_id)
    if datasource is None:
        raise ApiError(404, "datasource_not_found", "La fuente de datos no existe")
    model = store.load_model(_current_or_404(session, datasource_id))
    privacy: Privacy = (
        cast(Privacy, datasource.privacy)
        if datasource.privacy in ("schema", "aggregates", "samples")
        else "schema"
    )
    tables = body.tables if body is not None else None
    try:
        return suggest(model, llm, privacy=privacy, tables=tables)
    except GatewayError as exc:
        raise ApiError(
            502, "ai_unavailable", f"La IA no pudo generar sugerencias: {exc.message}"
        ) from exc


MAX_IMPORT_BYTES = 5 * 1024 * 1024
_MODEL_FORMATS = {".yaml": "yaml", ".yml": "yaml", ".json": "json"}
_SUPPORTED = ".sql, .csv, .xlsx, .yaml, .yml o .json"


def _errors_detail(exc: SemanticModelError) -> dict[str, Any]:
    return {"errors": [{"path": i.path, "message": i.message} for i in exc.issues]}


def _from_dictionary(result: DictionaryResult) -> Imported:
    warnings = [Issue(f"fila {i.row}", i.message) for i in result.issues]
    return Imported(tables=result.tables, warnings=warnings)


def _read_import(name: str, content: bytes, dialect: str | None) -> Imported:
    """Lee el archivo subido según su extensión. Lanza `ApiError` 422 si no se puede leer."""
    suffix = PurePath(name).suffix.lower()
    if suffix not in {".sql", ".csv", ".xlsx", *_MODEL_FORMATS}:
        raise ApiError(
            422, "unsupported_format", f"Extensión «{suffix}» no soportada: usa {_SUPPORTED}"
        )
    try:
        if suffix == ".xlsx":
            return _from_dictionary(parse_dictionary_xlsx(content))
        text = content.decode("utf-8-sig")
        if suffix == ".sql":
            ddl = import_ddl(text, dialect)
            return Imported(ddl.tables, ddl.relationships, ddl.warnings)
        if suffix == ".csv":
            return _from_dictionary(parse_dictionary_csv(text))
        parsed = parse_model_text(text, _MODEL_FORMATS[suffix])
        imported = Imported(parsed.tables, parsed.relationships)
        if parsed.metrics or parsed.summary_tables or parsed.security.roles:
            imported.warnings.append(
                Issue("", "Solo se importan tablas y relaciones; el resto del modelo se ignora")
            )
        return imported
    except UnicodeDecodeError as exc:
        raise ApiError(422, "invalid_file", "El archivo no está en UTF-8") from exc
    except DictionaryError as exc:
        raise ApiError(422, "invalid_file", str(exc)) from exc
    except SemanticModelError as exc:
        raise ApiError(
            422, "invalid_semantic_model", "El modelo importado no es válido", _errors_detail(exc)
        ) from exc


@router.post(
    "/import",
    summary="Vista previa de importar un archivo sobre el modelo vigente (no guarda)",
    dependencies=ADMIN,
)
async def import_semantic(
    datasource_id: uuid.UUID, file: UploadFile, session: SessionDep
) -> ImportPreview:
    datasource = session.get(Datasource, datasource_id)
    if datasource is None:
        raise ApiError(404, "datasource_not_found", "La fuente de datos no existe")
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise ApiError(422, "file_too_large", "El archivo supera los 5 MB")
    row = store.current(session, datasource_id)
    existing = store.load_model(row) if row else None
    dialect = (existing.dialect if existing else None) or datasource.dialect
    imported = _read_import(file.filename or "", content, dialect)
    try:
        result = merge_import(existing, imported, datasource.name)
    except SemanticModelError as exc:
        raise ApiError(
            422, "invalid_semantic_model", "El modelo fusionado no es válido", _errors_detail(exc)
        ) from exc
    diff = asdict(result.diff)
    return ImportPreview(
        model=store.dump_model(result.model),
        diff={key: diff[key] for key in ("added", "changed", "missing", "suggestions")},
        warnings=[{"path": w.path, "message": w.message} for w in result.warnings],
    )
