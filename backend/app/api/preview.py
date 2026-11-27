"""Vista previa sin IA (docs/API.md#fuentes-de-datos): métrica y período a SQL, y validación de SQL.

Sirve para probar el catálogo de métricas y los filtros por rol sin gastar tokens. Todo el SQL
pasa por el guardián, igual que en el chat.
"""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import Datasource, SemanticModelVersion, User
from app.db.session import get_session
from app.engine.builder import BuilderError, build_sql
from app.engine.catalog import Catalog, CatalogError, PlanFilter
from app.engine.dialects import Dialect, Granularity
from app.engine.guard import GuardResult, UnknownRoleError, check_sql
from app.engine.periods import PeriodConfig, resolve_period
from app.engine.rls import AttributeValue, role_row_filters
from app.engine.summary import plan_for_summary, route_summary
from app.security.auth import get_current_user, require_admin
from app.security.grants import GrantError, resolve_access
from app.security.grants import ViewAs as GrantViewAs
from app.semantic.schema import SemanticModel, parse_semantic_model

router = APIRouter(prefix="/datasources", tags=["vista previa"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]


class ViewAs(BaseModel):
    """Rol y atributos con los que un administrador prueba los permisos."""

    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    attributes: dict[str, AttributeValue] = {}


class FilterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, description="`tabla.columna`")
    op: str
    value: Any = None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1)
    period: str | None = Field(default=None, description="Texto: «este mes», «2025»…")
    dimensions: list[str] = []
    filters: list[FilterIn] = []
    granularity: Granularity | None = None
    view_as: ViewAs | None = None


class ValidateSqlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1)
    view_as: ViewAs | None = None


class PeriodOut(BaseModel):
    text: str
    label: str
    start: date
    end_exclusive: date
    grain: str
    is_current: bool


class FilterApplied(BaseModel):
    source: str = Field(description="`metric`, `request`, `period` o `role`")
    text: str


class ViolationOut(BaseModel):
    code: str
    message: str


class GuardOut(BaseModel):
    allowed: bool
    sql: str | None
    tables: list[str]
    violations: list[ViolationOut]


class PreviewOut(BaseModel):
    sql: str = Field(description="SQL final del guardián; si lo rechazó, el SQL armado")
    metric: str
    role: str | None
    summary_table: str | None = Field(description="Tabla resumida elegida; null: tablas base")
    reason: str
    period: PeriodOut | None
    filters_applied: list[FilterApplied]
    guard: GuardOut


class ValidateSqlOut(GuardOut):
    role: str | None


def _guard_out(result: GuardResult) -> GuardOut:
    return GuardOut(
        allowed=result.allowed,
        sql=result.sql,
        tables=list(result.tables),
        violations=[ViolationOut(code=v.code, message=v.message) for v in result.violations],
    )


def load_model(session: Session, datasource_id: uuid.UUID) -> tuple[Datasource, SemanticModel, int]:
    datasource = session.get(Datasource, datasource_id)
    if datasource is None:
        raise ApiError(404, "datasource_not_found", "La fuente de datos no existe")
    version = session.scalars(
        select(SemanticModelVersion)
        .where(SemanticModelVersion.datasource_id == datasource_id)
        .order_by(SemanticModelVersion.version.desc())
        .limit(1)
    ).first()
    if version is None:
        raise ApiError(404, "semantic_model_not_found", "La fuente aún no tiene modelo semántico")
    return datasource, parse_semantic_model(version.model), version.version


def resolve_identity(
    session: Session,
    user: User,
    datasource: Datasource,
    model: SemanticModel,
    view_as: ViewAs | None,
) -> tuple[str | None, dict[str, Any]]:
    """Rol y contexto `{"user": {...}}`: de `view_as` (solo administradores) o del permiso."""
    try:
        access = resolve_access(
            session,
            user,
            datasource,
            model,
            GrantViewAs(view_as.role, view_as.attributes) if view_as else None,
        )
    except GrantError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    return access.role, access.context


def _period_config(model: SemanticModel) -> PeriodConfig:
    settings = model.settings
    return PeriodConfig(
        timezone=settings.timezone,
        week_starts_on=settings.week_starts_on,
        fiscal_year_start_month=settings.fiscal_year_start_month,
        locale=settings.locale or "es-CO",
    )


@router.post("/{datasource_id}/preview", summary="Métrica y período a SQL, sin IA")
def preview(
    datasource_id: uuid.UUID, body: PreviewRequest, session: SessionDep, user: UserDep
) -> PreviewOut:
    datasource, model, version = load_model(session, datasource_id)
    role, context = resolve_identity(session, user, datasource, model, body.view_as)

    period = None
    if body.period is not None:
        period = resolve_period(body.period, _period_config(model))
        if period is None:
            raise ApiError(422, "invalid_period", f"No entiendo el período «{body.period}»")

    try:
        plan = Catalog(model).verify(
            body.metric,
            body.dimensions,
            [PlanFilter(f.field, f.op, f.value) for f in body.filters],
            role,
        )
        decision = route_summary(model, plan, period=period, time_grain=body.granularity, role=role)
        built = plan
        if decision.table is not None:
            built = plan_for_summary(model, plan, decision.table)
        dialect: Dialect = datasource.dialect  # type: ignore[assignment]
        query = build_sql(model, built, dialect, period=period, time_grain=body.granularity)
        result = check_sql(query.sql, model, datasource, version, role, context=context)
    except (CatalogError, BuilderError) as exc:
        raise ApiError(422, "invalid_plan", exc.message) from exc
    except UnknownRoleError as exc:
        raise ApiError(422, "unknown_role", str(exc)) from exc

    applied = [FilterApplied(source="metric", text=f) for f in plan.metric.filters]
    applied += [
        FilterApplied(source="request", text=f"{f.field} {f.op} {f.value!r}") for f in plan.filters
    ]
    period_out = None
    if period is not None:
        column = plan.metric.time_column
        applied.append(
            FilterApplied(
                source="period",
                text=f"{column} >= {period.start} AND {column} < {period.end_exclusive}",
            )
        )
        period_out = PeriodOut(
            text=body.period or "",
            label=period.label,
            start=period.start,
            end_exclusive=period.end_exclusive,
            grain=period.grain,
            is_current=period.is_current,
        )
    role_def = next((r for r in model.security.roles if r.name == role), None)
    if role_def is not None:
        applied += [
            FilterApplied(source="role", text=f"{table}: {condition}")
            for table, condition in role_row_filters(role_def).items()
        ]

    return PreviewOut(
        sql=result.sql or query.sql,
        metric=plan.metric.name,
        role=role,
        summary_table=decision.table,
        reason=decision.reason,
        period=period_out,
        filters_applied=applied,
        guard=_guard_out(result),
    )


@router.post(
    "/{datasource_id}/validate-sql",
    summary="Resultado del guardián para un SQL",
    # Revela qué columnas están ocultas: igual que leer el modelo, es administración.
    dependencies=[Depends(require_admin)],
)
def validate_sql(
    datasource_id: uuid.UUID, body: ValidateSqlRequest, session: SessionDep, user: UserDep
) -> ValidateSqlOut:
    datasource, model, version = load_model(session, datasource_id)
    role, context = resolve_identity(session, user, datasource, model, body.view_as)
    try:
        result = check_sql(body.sql, model, datasource, version, role, context=context)
    except UnknownRoleError as exc:
        raise ApiError(422, "unknown_role", str(exc)) from exc
    return ValidateSqlOut(**_guard_out(result).model_dump(), role=role)
