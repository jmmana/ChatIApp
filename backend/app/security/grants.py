"""Permisos por fuente (ADR 0004): rol y atributos de cada usuario, y su resolución al consultar.

Un `Grant` liga a un usuario con una fuente de datos, un rol del modelo semántico vigente y los
atributos que usan los filtros del rol (`{user.x}`). El orquestador y la vista previa toman la
identidad de aquí: del permiso del usuario autenticado o, solo para administradores, de `view_as`.
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Datasource, Grant, User
from app.engine.rls import AttributeValue, ViewAsNotAllowedError, build_user_context
from app.semantic.schema import SemanticModel

_ATTRIBUTE = re.compile(r"\{user\.([A-Za-z_]\w*)\}")


class GrantError(Exception):
    """Permiso inválido (422) o acceso denegado (403)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ViewAs:
    """Rol y atributos con los que un administrador ve la aplicación."""

    role: str | None = None
    attributes: Mapping[str, AttributeValue] | None = None


@dataclass(frozen=True)
class Access:
    """Identidad con la que se consulta una fuente: rol y contexto `{"user": {...}}`."""

    role: str | None
    context: dict[str, Any]


def required_attributes(model: SemanticModel, role_name: str) -> list[str]:
    """Atributos `{user.x}` que exigen los filtros del rol, en orden de aparición."""
    role = next((r for r in model.security.roles if r.name == role_name), None)
    names: list[str] = []
    for rule in role.filters if role else []:
        for name in _ATTRIBUTE.findall(rule.condition):
            if name not in names:
                names.append(name)
    return names


def validate_grant(model: SemanticModel, role: str, attributes: Mapping[str, Any]) -> None:
    """422 si el rol no existe en el modelo vigente o falta un atributo que sus filtros exigen."""
    if not any(r.name == role for r in model.security.roles):
        raise GrantError(422, "unknown_role", f"El rol «{role}» no existe en el modelo vigente")
    missing = [
        name
        for name in required_attributes(model, role)
        if attributes.get(name) in (None, "", [])
    ]
    if missing:
        raise GrantError(
            422,
            "missing_attributes",
            f"El rol «{role}» exige los atributos: {', '.join(missing)}",
        )


def resolve_access(
    session: Session,
    user: User,
    datasource: Datasource,
    model: SemanticModel,
    view_as: ViewAs | None = None,
) -> Access:
    """Rol y atributos del usuario autenticado en la fuente.

    Sin permiso, 403 (los administradores pueden consultar con el rol por defecto). `view_as`
    solo lo acepta un administrador; para el resto lanza 403.
    """
    grant = session.scalars(
        select(Grant).where(Grant.user_id == user.id, Grant.datasource_id == datasource.id)
    ).first()
    if grant is None and not user.is_admin:
        raise GrantError(403, "no_access", "No tienes acceso a esta fuente de datos")
    role = grant.role if grant else None
    attributes: dict[str, AttributeValue] = dict(grant.attributes) if grant else {}
    try:
        context = build_user_context(
            attributes,
            view_as=(view_as.attributes or {}) if view_as else None,
            is_admin=user.is_admin,
        )
    except ViewAsNotAllowedError as exc:
        raise GrantError(403, "view_as_forbidden", str(exc)) from exc
    if view_as is not None:
        role = view_as.role
    return Access(role or model.security.default_role, context)


def replace_grants(
    session: Session,
    user_id: uuid.UUID,
    entries: Mapping[uuid.UUID, tuple[str, dict[str, Any]]],
) -> None:
    """Deja los permisos del usuario exactamente como `entries` (fuente → rol y atributos)."""
    current = {
        g.datasource_id: g for g in session.scalars(select(Grant).where(Grant.user_id == user_id))
    }
    for datasource_id, grant in current.items():
        if datasource_id not in entries:
            session.delete(grant)
    for datasource_id, (role, attributes) in entries.items():
        existing = current.get(datasource_id)
        if existing is None:
            session.add(
                Grant(
                    user_id=user_id, datasource_id=datasource_id, role=role, attributes=attributes
                )
            )
        else:
            existing.role = role
            existing.attributes = attributes
