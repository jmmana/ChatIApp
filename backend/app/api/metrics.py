"""Métricas sugeridas para cualquier usuario con acceso a la fuente (docs/API.md#métricas)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.api.preview import load_model
from app.db.models import User
from app.db.session import get_session
from app.security.auth import get_current_user
from app.security.grants import GrantError, resolve_access
from app.semantic.schema import Column, Metric, SemanticModel

router = APIRouter(prefix="/datasources/{datasource_id}/metrics", tags=["métricas"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]


def _not_found() -> ApiError:
    return ApiError(404, "datasource_not_found", "La fuente de datos no existe")


class SuggestedMetric(BaseModel):
    name: str
    label: str
    description: str | None
    requires_period: bool
    default_period: str | None
    dimensions: list[str]


class MetricsOut(BaseModel):
    metrics: list[SuggestedMetric]


def _dimension_label(column: Column) -> str:
    """Nombre para mostrar de una dimensión: su primer sinónimo o el nombre legible."""
    return column.synonyms[0] if column.synonyms else column.name.replace("_", " ")


def _visible_dimensions(model: SemanticModel, metric: Metric, hidden: set[str]) -> list[str]:
    tables = {t.name: t for t in model.tables}
    labels: list[str] = []
    for ref in metric.dimensions:
        table_name, _, column_name = ref.rpartition(".")
        table = tables.get(table_name)
        column = next((c for c in table.columns if c.name == column_name), None) if table else None
        if column is None or column.hidden or table_name in hidden:
            continue
        label = _dimension_label(column)
        if label not in labels:
            labels.append(label)
    return labels


@router.get("", summary="Métricas que el rol del usuario puede consultar")
def list_metrics(datasource_id: uuid.UUID, session: SessionDep, user: UserDep) -> MetricsOut:
    try:
        datasource, model, _ = load_model(session, datasource_id)
        access = resolve_access(session, user, datasource, model)
    except (GrantError, ApiError) as exc:
        # Sin fuente, sin modelo o sin permiso: la misma 404, sin revelar que existe.
        raise _not_found() from exc
    role = next((r for r in model.security.roles if r.name == access.role), None)
    if access.role is not None and role is None:
        return MetricsOut(metrics=[])  # rol que ya no existe: falla cerrado
    hidden = set(role.hidden_tables) if role else set()
    return MetricsOut(
        metrics=[
            SuggestedMetric(
                name=m.name,
                label=m.label,
                description=m.description,
                requires_period=m.requires_period,
                default_period=m.default_period,
                dimensions=_visible_dimensions(model, m, hidden),
            )
            for m in model.metrics
            if m.table not in hidden
        ]
    )
