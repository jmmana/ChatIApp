"""Endpoints de proveedores de IA: catálogo y CRUD con secretos cifrados.

Los campos `secret` del catálogo se guardan cifrados (JSON cifrado con Fernet, igual que los
declarados en `chatiapp.yaml`) y solo se devuelven enmascarados.
"""

import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import Provider
from app.db.session import get_session
from app.llm.catalog import CATALOG, ProviderField, ProviderSpec
from app.security.crypto import decrypt, encrypt, mask

router = APIRouter(prefix="/providers", tags=["proveedores"])

Task = Literal["planner", "sql", "answer", "suggest"]
MANAGED_BY_CONFIG = "config"
_SPECS = {spec.kind: spec for spec in CATALOG}

SessionDep = Annotated[Session, Depends(get_session)]


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str
    model: str = Field(min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    tasks: list[Task] = Field(default_factory=list)
    is_default: bool = False


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    secrets: dict[str, str] | None = None
    params: dict[str, Any] | None = None
    tasks: list[Task] | None = None
    is_default: bool | None = None


class ProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    model: str
    config: dict[str, Any]
    secrets: dict[str, str]
    params: dict[str, Any]
    tasks: list[str]
    is_default: bool
    managed_by: str


class RoutingIn(BaseModel):
    """Tarea → id de proveedor, y cadena de respaldo en orden."""

    tasks: dict[Task, uuid.UUID] = Field(default_factory=dict)
    fallback: list[uuid.UUID] = Field(default_factory=list)


def _load_secrets(provider: Provider) -> dict[str, str]:
    if provider.secrets_encrypted is None:
        return {}
    loaded = json.loads(decrypt(provider.secrets_encrypted))
    return {str(k): str(v) for k, v in loaded.items()}


def _store_secrets(provider: Provider, secrets: dict[str, str]) -> None:
    provider.secrets_encrypted = encrypt(json.dumps(secrets)) if secrets else None


def _to_out(provider: Provider) -> ProviderOut:
    params = dict(provider.params or {})
    tasks = params.pop("tasks", [])
    return ProviderOut(
        id=provider.id,
        name=provider.name,
        kind=provider.kind,
        model=provider.model,
        config=provider.config or {},
        secrets={k: mask(v) for k, v in _load_secrets(provider).items()},
        params=params,
        tasks=tasks,
        is_default=provider.is_default,
        managed_by=provider.managed_by,
    )


def _spec(kind: str) -> ProviderSpec:
    spec = _SPECS.get(kind)
    if spec is None:
        raise ApiError(422, "unknown_kind", f"Tipo de proveedor desconocido: {kind}.")
    return spec


def _validate_fields(spec: ProviderSpec, config: dict[str, Any], secrets: dict[str, str]) -> None:
    """Valida `config` y `secrets` contra los campos del catálogo del `kind`."""
    by_name: dict[str, ProviderField] = {f.name: f for f in spec.fields}
    errors: dict[str, str] = {}
    for name in config:
        field = by_name.get(name)
        if field is None or field.type == "secret":
            errors[name] = "Campo no permitido en `config` para este tipo."
        elif (
            field.type == "select"
            and field.options
            and str(config[name]) not in {o.value for o in field.options}
        ):
            errors[name] = "Valor fuera de las opciones permitidas."
    for name in secrets:
        field = by_name.get(name)
        if field is None or field.type != "secret":
            errors[name] = "Campo no permitido en `secrets` para este tipo."
    for field in spec.fields:
        if not field.required or field.default is not None:
            continue
        value = secrets.get(field.name) if field.type == "secret" else config.get(field.name)
        if value is None or value == "":
            errors.setdefault(field.name, "Campo obligatorio.")
    if errors:
        raise ApiError(422, "invalid_provider", "Configuración inválida.", {"fields": errors})


def _get(session: Session, provider_id: uuid.UUID) -> Provider:
    provider = session.get(Provider, provider_id)
    if provider is None:
        raise ApiError(404, "provider_not_found", "Proveedor no encontrado.")
    return provider


def _ensure_editable(provider: Provider) -> None:
    if provider.managed_by == MANAGED_BY_CONFIG:
        raise ApiError(
            409,
            "managed_by_config",
            "Este proveedor se define en chatiapp.yaml y no se edita desde la API.",
        )


def _clear_default(session: Session, keep: uuid.UUID) -> None:
    session.execute(update(Provider).where(Provider.id != keep).values(is_default=False))


def _commit(session: Session, *, flush_only: bool = False) -> None:
    """Confirma (o solo envía) los cambios; un nombre repetido es 409, no un error 500."""
    try:
        session.flush() if flush_only else session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(409, "name_taken", "Ya existe un proveedor con ese nombre.") from exc


@router.get("/catalog", summary="Catálogo de proveedores de IA")
def get_catalog() -> list[ProviderSpec]:
    return list(CATALOG)


@router.get("", summary="Proveedores configurados (secretos enmascarados)")
def list_providers(session: SessionDep) -> list[ProviderOut]:
    rows = session.scalars(select(Provider).order_by(Provider.name)).all()
    return [_to_out(p) for p in rows]


@router.post("", status_code=201, summary="Crea un proveedor")
def create_provider(body: ProviderCreate, session: SessionDep) -> ProviderOut:
    _validate_fields(_spec(body.kind), body.config, body.secrets)
    provider = Provider(
        name=body.name,
        kind=body.kind,
        model=body.model,
        config=body.config,
        params={**body.params, "tasks": list(body.tasks)},
        is_default=body.is_default,
        managed_by="ui",
    )
    _store_secrets(provider, body.secrets)
    session.add(provider)
    _commit(session, flush_only=True)
    if body.is_default:
        _clear_default(session, provider.id)
    _commit(session)
    return _to_out(provider)


@router.put("/routing", summary="Asigna tareas y cadena de respaldo")
def put_routing(body: RoutingIn, session: SessionDep) -> list[ProviderOut]:
    ids = {*body.tasks.values(), *body.fallback}
    providers = {p.id: p for p in session.scalars(select(Provider)).all()}
    missing = sorted(str(i) for i in ids if i not in providers)
    if missing:
        raise ApiError(404, "provider_not_found", "Proveedor no encontrado.", {"ids": missing})
    for provider_id in ids:
        _ensure_editable(providers[provider_id])
    for provider in providers.values():
        if provider.managed_by == MANAGED_BY_CONFIG:
            continue
        params = dict(provider.params or {})
        params["tasks"] = [t for t, pid in body.tasks.items() if pid == provider.id]
        if provider.id in body.fallback:
            params["fallback"] = body.fallback.index(provider.id)
        else:
            params.pop("fallback", None)
        provider.params = params
    _commit(session)
    return [_to_out(p) for p in sorted(providers.values(), key=lambda p: p.name)]


@router.patch("/{provider_id}", summary="Actualiza un proveedor")
def update_provider(
    provider_id: uuid.UUID, body: ProviderUpdate, session: SessionDep
) -> ProviderOut:
    provider = _get(session, provider_id)
    _ensure_editable(provider)
    config = body.config if body.config is not None else dict(provider.config or {})
    # Un secreto solo cambia si se envía (y no vacío): los demás se conservan.
    secrets = _load_secrets(provider)
    secrets.update({k: v for k, v in (body.secrets or {}).items() if v != ""})
    _validate_fields(_spec(provider.kind), config, secrets)

    if body.name is not None:
        provider.name = body.name
    if body.model is not None:
        provider.model = body.model
    provider.config = config
    _store_secrets(provider, secrets)
    params = dict(provider.params or {})
    if body.params is not None:
        kept = {k: v for k, v in params.items() if k in ("tasks", "fallback")}
        params = {**body.params, **kept}
    if body.tasks is not None:
        params["tasks"] = list(body.tasks)
    provider.params = params
    if body.is_default is not None:
        provider.is_default = body.is_default
        if body.is_default:
            _clear_default(session, provider.id)
    _commit(session)
    return _to_out(provider)


@router.delete("/{provider_id}", status_code=204, summary="Elimina un proveedor")
def delete_provider(provider_id: uuid.UUID, session: SessionDep) -> Response:
    provider = _get(session, provider_id)
    _ensure_editable(provider)
    session.delete(provider)
    session.commit()
    return Response(status_code=204)
