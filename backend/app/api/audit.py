"""Auditoría de turnos (docs/API.md#administración-m3).

`main.create_app` incluye este router con `require_admin`: solo administradores.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit import service
from app.audit.service import AuditEntry, AuditFilters
from app.db.session import get_session

router = APIRouter(prefix="/audit", tags=["auditoría"])

SessionDep = Annotated[Session, Depends(get_session)]
Status = Literal["ok", "rejected", "error"]


class AuditEntryOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    status: str
    error_code: str | None
    user_id: uuid.UUID | None
    user_email: str | None
    external_user_id: str | None
    api_key_id: uuid.UUID | None
    api_key_name: str | None
    role: str | None
    datasource_id: uuid.UUID | None
    datasource: str | None
    semantic_version: int | None
    question: str | None
    plan: dict[str, Any] | None
    origin: str
    sql_candidate: str | None
    sql_final: str | None
    filters_applied: dict[str, Any] | None
    summary_table: str | None
    row_count: int | None  # solo el conteo: nunca el contenido de las filas
    provider_kind: str | None
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: Decimal | None
    elapsed_ms: int | None


class AuditPage(BaseModel):
    items: list[AuditEntryOut]
    total: int
    page: int
    page_size: int


def _out(entry: AuditEntry) -> AuditEntryOut:
    run = entry.run
    return AuditEntryOut(
        id=run.id,
        created_at=run.created_at,
        status=run.status,
        error_code=run.error_code,
        user_id=run.user_id,
        user_email=entry.user_email,
        external_user_id=run.external_user_id,
        api_key_id=run.api_key_id,
        api_key_name=entry.api_key_name,
        role=run.role,
        datasource_id=run.datasource_id,
        datasource=entry.datasource_name,
        semantic_version=run.semantic_version,
        question=run.question,
        plan=run.plan,
        origin=run.origin,
        sql_candidate=run.sql_candidate,
        sql_final=run.sql_final,
        filters_applied=run.filters_applied,
        summary_table=run.summary_table,
        row_count=run.row_count,
        provider_kind=run.provider_kind,
        model=run.model,
        tokens_in=run.tokens_in,
        tokens_out=run.tokens_out,
        cost_usd=run.cost_usd,
        elapsed_ms=run.elapsed_ms,
    )


def _filters(
    user_id: uuid.UUID | None = None,
    external_user_id: str | None = None,
    datasource_id: uuid.UUID | None = None,
    api_key_id: uuid.UUID | None = None,
    status: Status | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> AuditFilters:
    return AuditFilters(
        user_id, external_user_id, datasource_id, api_key_id, status, date_from, date_to
    )


FiltersDep = Annotated[AuditFilters, Depends(_filters)]


@router.get("", summary="Auditoría de turnos, con filtros y paginada")
def list_audit(
    filters: FiltersDep,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPage:
    entries, total = service.list_entries(session, filters, page=page, page_size=page_size)
    return AuditPage(items=[_out(e) for e in entries], total=total, page=page, page_size=page_size)


@router.get("/export", summary="Exporta la auditoría filtrada en CSV")
def export_audit(filters: FiltersDep, session: SessionDep) -> Response:
    body = service.to_csv(service.export_entries(session, filters))
    return Response(
        content="﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="auditoria.csv"'},
    )
