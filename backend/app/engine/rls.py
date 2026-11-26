"""Filtros por rol (ADR 0004): traduce los roles del modelo semántico a sqlguardllm.

La inyección del filtro la hace sqlguardllm (`row_filters` de la `Policy`); aquí solo se arman
los filtros del rol y el contexto `{"user": {...}}`. La sintaxis `{user.x}` del modelo semántico
es la misma de sqlguardllm, así que las condiciones pasan tal cual. Los atributos salen siempre
del usuario autenticado (o de `view_as` para administradores), nunca del modelo de IA.
"""

from collections.abc import Mapping
from typing import Any

from app.semantic.schema import Role

MISSING_CONTEXT = "missing_context"

AttributeValue = str | int | float | bool | list[str | int | float]


class ViewAsNotAllowedError(PermissionError):
    """Solo un administrador puede ver la aplicación con los atributos de otro usuario."""


def role_row_filters(role: Role) -> dict[str, str]:
    """`row_filters` de la `Policy`: tabla → condición.

    Incluye las tablas base y las resumidas, porque el modelo declara un filtro por tabla. Si el
    rol repite una tabla, las condiciones se combinan con AND.
    """
    grouped: dict[str, list[str]] = {}
    for rule in role.filters:
        grouped.setdefault(rule.table, []).append(rule.condition)
    return {
        table: conditions[0] if len(conditions) == 1 else " AND ".join(f"({c})" for c in conditions)
        for table, conditions in grouped.items()
    }


def build_user_context(
    attributes: Mapping[str, AttributeValue],
    *,
    view_as: Mapping[str, AttributeValue] | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    """Arma el contexto `{"user": {...}}` para `Guard.check`.

    `attributes` son los del usuario autenticado. `view_as` (atributos del usuario suplantado)
    solo se acepta si `is_admin`; así el contexto nunca depende de lo que diga el modelo de IA.
    """
    if view_as is not None:
        if not is_admin:
            raise ViewAsNotAllowedError("Solo un administrador puede usar «ver como»")
        attributes = view_as
    return {"user": dict(attributes)}


def missing_context_message(attribute_message: str) -> str:
    """Mensaje para el usuario cuando sqlguardllm responde `missing_context`.

    Es un problema de configuración del usuario (le falta un atributo que su rol necesita), no
    de la pregunta: no se ejecuta nada y quien administra debe completar el atributo.
    """
    return (
        "Tu usuario no tiene configurado un atributo que tu rol necesita para filtrar los "
        f"datos. Pide a un administrador que lo complete. Detalle: {attribute_message}"
    )
