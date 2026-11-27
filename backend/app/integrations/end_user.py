"""Identidad del usuario final en las llamadas con API key (docs/INTEGRACION.md).

La key identifica a la app que integra; el campo `user` (`id`, `role`, `attributes`) dice en
nombre de quién se pregunta. ChatIApp confía en el backend de esa app, pero solo dentro del
techo de la key: fuentes permitidas, roles permitidos (o rol fijo) y los atributos, con su tipo,
que exigen los filtros del rol. Todo se valida antes de ejecutar nada.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ApiKey, Datasource
from app.engine.rls import AttributeValue, build_user_context
from app.security.grants import required_attributes
from app.semantic.schema import SemanticModel


class EndUserError(Exception):
    """El usuario final no es válido (422) o excede el techo de la key (403)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class EndUser(BaseModel):
    """Usuario final en cuyo nombre pregunta la app que integra."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=255)
    role: str | None = None
    attributes: dict[str, AttributeValue] = {}


@dataclass(frozen=True)
class EndUserAccess:
    """Identidad con la que se consulta: rol, contexto `{"user": {...}}` e id externo."""

    role: str
    context: dict[str, Any]
    external_user_id: str


def fixed_role(api_key: ApiKey) -> str | None:
    """Rol fijo de la key: la que permite un único rol lo aplica siempre."""
    return api_key.allowed_roles[0] if len(api_key.allowed_roles) == 1 else None


def _check_datasource(api_key: ApiKey, datasource: Datasource) -> None:
    if not {datasource.name, str(datasource.id)} & set(api_key.datasources):
        raise EndUserError(403, "datasource_not_allowed", "La API key no puede usar esta fuente.")


def _resolve_role(api_key: ApiKey, model: SemanticModel, sent: str | None) -> str:
    fixed = fixed_role(api_key)
    role = fixed or sent
    if not role:
        raise EndUserError(422, "role_required", "Falta el rol del usuario final (`user.role`).")
    if role not in api_key.allowed_roles:
        raise EndUserError(403, "role_not_allowed", f"La API key no puede asignar el rol «{role}».")
    if not any(r.name == role for r in model.security.roles):
        raise EndUserError(422, "unknown_role", f"El rol «{role}» no existe en el modelo vigente.")
    return role


def _expects_list(model: SemanticModel, role_name: str, attribute: str) -> bool:
    """Un atributo usado como `IN ({user.x})` en algún filtro del rol debe ser una lista."""
    pattern = re.compile(rf"\bIN\s*\(\s*\{{user\.{re.escape(attribute)}\}}\s*\)", re.IGNORECASE)
    role = next(r for r in model.security.roles if r.name == role_name)
    return any(pattern.search(rule.condition) for rule in role.filters)


def _valid_scalar(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    return isinstance(value, int | float) or (isinstance(value, str) and value.strip() != "")


def _check_attributes(
    model: SemanticModel, role: str, attributes: Mapping[str, AttributeValue]
) -> dict[str, AttributeValue]:
    """Devuelve solo los atributos que el rol usa, o lanza 422 si faltan o tienen otro tipo."""
    missing: list[str] = []
    wrong: list[str] = []
    selected: dict[str, AttributeValue] = {}
    for name in required_attributes(model, role):
        value = attributes.get(name)
        if value is None or value == "" or value == []:
            missing.append(name)
            continue
        if _expects_list(model, role, name):
            valid = isinstance(value, list) and all(_valid_scalar(v) for v in value)
            expected = "una lista"
        else:
            valid = not isinstance(value, list) and _valid_scalar(value)
            expected = "un valor simple"
        if not valid:
            wrong.append(f"{name} (debe ser {expected})")
            continue
        selected[name] = value
    if missing:
        raise EndUserError(
            422,
            "missing_attributes",
            f"El rol «{role}» exige los atributos: {', '.join(missing)}.",
        )
    if wrong:
        raise EndUserError(
            422, "invalid_attributes", f"Atributos con tipo incorrecto: {', '.join(wrong)}."
        )
    return selected


def resolve_end_user(
    api_key: ApiKey,
    datasource: Datasource,
    model: SemanticModel,
    end_user: EndUser | None,
) -> EndUserAccess:
    """Rol y atributos con los que se consulta en nombre del usuario final.

    422 si falta `user`, el rol o un atributo que los filtros exigen (o tiene otro tipo); 403 si
    la fuente o el rol quedan fuera del techo de la key. Con rol fijo se ignora el enviado.
    """
    if end_user is None:
        raise EndUserError(
            422, "end_user_required", "Con API key hay que indicar el usuario final (`user`)."
        )
    _check_datasource(api_key, datasource)
    role = _resolve_role(api_key, model, end_user.role)
    attributes = _check_attributes(model, role, end_user.attributes)
    return EndUserAccess(role, build_user_context(attributes), end_user.id)
