"""Endpoints de fuentes de datos (docs/API.md#fuentes-de-datos)."""

import uuid
from typing import Annotated, Literal

from cryptography.fernet import MultiFernet
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import Datasource
from app.db.session import get_session
from app.engine.connections import (
    ConnectionFailure,
    InvalidUrlError,
    check_connection,
    mask_url,
    validate_url,
)
from app.engine.dialects import Dialect
from app.security.crypto import SecretKeyError, decrypt, encrypt, get_cipher

router = APIRouter(prefix="/datasources", tags=["fuentes de datos"])

Privacy = Literal["schema", "aggregates", "samples"]
MaxRows = Annotated[int, Field(ge=1, le=100_000)]
TimeoutSeconds = Annotated[int, Field(ge=1, le=600)]
Name = Annotated[str, Field(min_length=1, max_length=255)]


class DatasourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    dialect: Dialect
    url: Annotated[str, Field(min_length=1)]
    execute: bool = False
    max_rows: MaxRows = 1000
    timeout_seconds: TimeoutSeconds = 30
    privacy: Privacy = "schema"


class DatasourceUpdate(BaseModel):
    """Todos los campos son opcionales; ``url`` solo se reemplaza si se envía."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    dialect: Dialect | None = None
    url: Annotated[str, Field(min_length=1)] | None = None
    execute: bool | None = None
    max_rows: MaxRows | None = None
    timeout_seconds: TimeoutSeconds | None = None
    privacy: Privacy | None = None


class DatasourceOut(BaseModel):
    id: uuid.UUID
    name: str
    dialect: str
    url: str = Field(description="URL con usuario y contraseña ocultos")
    execute: bool
    max_rows: int
    timeout_seconds: int
    privacy: str
    managed_by: str


class TestError(BaseModel):
    kind: Literal["auth", "network", "driver_missing", "unknown"]
    message: str


class TestResult(BaseModel):
    __test__ = False  # no es una clase de prueba para pytest

    ok: bool
    latency_ms: int | None = None
    server_version: str | None = None
    error: TestError | None = None


def get_request_cipher() -> MultiFernet:
    # Envoltorio sin parámetros: FastAPI no debe leer `settings` de `get_cipher` como entrada.
    return get_cipher()


SessionDep = Annotated[Session, Depends(get_session)]
CipherDep = Annotated[MultiFernet, Depends(get_request_cipher)]


def _out(datasource: Datasource, cipher: MultiFernet) -> DatasourceOut:
    try:
        url = mask_url(decrypt(datasource.url_encrypted, cipher))
    except SecretKeyError:
        url = "***"  # la lista debe poder verse aunque la llave haya cambiado
    return DatasourceOut(
        id=datasource.id,
        name=datasource.name,
        dialect=datasource.dialect,
        url=url,
        execute=datasource.execute,
        max_rows=datasource.max_rows,
        timeout_seconds=datasource.timeout_seconds,
        privacy=datasource.privacy,
        managed_by=datasource.managed_by,
    )


def _get_or_404(session: Session, datasource_id: uuid.UUID) -> Datasource:
    datasource = session.get(Datasource, datasource_id)
    if datasource is None:
        raise ApiError(404, "datasource_not_found", "La fuente de datos no existe")
    return datasource


def _check_url(url: str) -> None:
    try:
        validate_url(url)
    except InvalidUrlError as exc:
        raise ApiError(422, "invalid_url", str(exc)) from exc


def _check_name_free(session: Session, name: str, own_id: uuid.UUID | None = None) -> None:
    existing = session.scalar(select(Datasource.id).where(Datasource.name == name))
    if existing is not None and existing != own_id:
        raise ApiError(409, "name_taken", f"Ya existe una fuente de datos llamada «{name}»")


def _ensure_editable(datasource: Datasource) -> None:
    if datasource.managed_by == "config":
        raise ApiError(
            409,
            "managed_by_config",
            "La fuente viene del archivo de configuración: edítala allí",
        )


@router.get("", summary="Lista de fuentes de datos (URL enmascarada)")
def list_datasources(session: SessionDep, cipher: CipherDep) -> list[DatasourceOut]:
    rows = session.scalars(select(Datasource).order_by(Datasource.name))
    return [_out(row, cipher) for row in rows]


@router.post("", status_code=201, summary="Crea una fuente de datos")
def create_datasource(
    body: DatasourceCreate, session: SessionDep, cipher: CipherDep
) -> DatasourceOut:
    _check_url(body.url)
    _check_name_free(session, body.name)
    datasource = Datasource(
        name=body.name,
        dialect=body.dialect,
        url_encrypted=encrypt(body.url, cipher),
        execute=body.execute,
        max_rows=body.max_rows,
        timeout_seconds=body.timeout_seconds,
        privacy=body.privacy,
        managed_by="ui",
    )
    session.add(datasource)
    session.commit()
    return _out(datasource, cipher)


@router.patch("/{datasource_id}", summary="Actualiza una fuente de datos")
def update_datasource(
    datasource_id: uuid.UUID, body: DatasourceUpdate, session: SessionDep, cipher: CipherDep
) -> DatasourceOut:
    datasource = _get_or_404(session, datasource_id)
    _ensure_editable(datasource)
    changes = body.model_dump(exclude_unset=True)
    # Un null explícito no tiene sentido en estos campos: se ignora.
    changes = {key: value for key, value in changes.items() if value is not None}
    if "name" in changes:
        _check_name_free(session, changes["name"], datasource.id)
    if "url" in changes:
        _check_url(changes["url"])
        datasource.url_encrypted = encrypt(changes.pop("url"), cipher)
    for key, value in changes.items():
        setattr(datasource, key, value)
    session.commit()
    return _out(datasource, cipher)


@router.delete("/{datasource_id}", status_code=204, summary="Elimina una fuente de datos")
def delete_datasource(datasource_id: uuid.UUID, session: SessionDep) -> Response:
    datasource = _get_or_404(session, datasource_id)
    _ensure_editable(datasource)
    session.delete(datasource)
    session.commit()
    return Response(status_code=204)


@router.post("/{datasource_id}/test", summary="Prueba la conexión")
def test_datasource(datasource_id: uuid.UUID, session: SessionDep, cipher: CipherDep) -> TestResult:
    datasource = _get_or_404(session, datasource_id)
    try:
        url = decrypt(datasource.url_encrypted, cipher)
    except SecretKeyError as exc:
        return TestResult(ok=False, error=TestError(kind="unknown", message=str(exc)))
    dialect: Dialect = datasource.dialect  # type: ignore[assignment]
    result = check_connection(url, dialect, datasource.timeout_seconds)
    failure: ConnectionFailure | None = result.error
    return TestResult(
        ok=result.ok,
        latency_ms=result.latency_ms,
        server_version=result.server_version,
        error=TestError(kind=failure.kind, message=failure.message) if failure else None,
    )
