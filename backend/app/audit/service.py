"""Consulta y exportación de la auditoría (docs/SEGURIDAD.md#auditoría).

Cada turno deja un `QueryRun` (lo escribe el orquestador). Aquí solo se lee: se filtra, se pagina y
se exporta a CSV. El registro guarda el conteo de filas, nunca su contenido.
"""

import csv
import io
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ApiKey, Datasource, QueryRun, User

MAX_EXPORT_ROWS = 50_000

CSV_COLUMNS = [
    "created_at",
    "status",
    "error_code",
    "user_email",
    "user_id",
    "external_user_id",
    "api_key_name",
    "api_key_id",
    "role",
    "datasource",
    "semantic_version",
    "question",
    "plan",
    "origin",
    "sql_candidate",
    "sql_final",
    "filters_applied",
    "summary_table",
    "row_count",
    "provider_kind",
    "model",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "elapsed_ms",
]


@dataclass(frozen=True)
class AuditFilters:
    user_id: uuid.UUID | None = None
    external_user_id: str | None = None
    datasource_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    status: str | None = None
    date_from: date | None = None
    date_to: date | None = None  # inclusiva


@dataclass(frozen=True)
class AuditEntry:
    run: QueryRun
    user_email: str | None
    datasource_name: str | None
    api_key_name: str | None


def _day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _query(filters: AuditFilters) -> Any:
    stmt = (
        select(QueryRun, User.email, Datasource.name, ApiKey.name)
        .outerjoin(User, User.id == QueryRun.user_id)
        .outerjoin(Datasource, Datasource.id == QueryRun.datasource_id)
        .outerjoin(ApiKey, ApiKey.id == QueryRun.api_key_id)
    )
    if filters.user_id is not None:
        stmt = stmt.where(QueryRun.user_id == filters.user_id)
    if filters.external_user_id:
        stmt = stmt.where(QueryRun.external_user_id == filters.external_user_id)
    if filters.datasource_id is not None:
        stmt = stmt.where(QueryRun.datasource_id == filters.datasource_id)
    if filters.api_key_id is not None:
        stmt = stmt.where(QueryRun.api_key_id == filters.api_key_id)
    if filters.status:
        stmt = stmt.where(QueryRun.status == filters.status)
    if filters.date_from is not None:
        stmt = stmt.where(QueryRun.created_at >= _day_start(filters.date_from))
    if filters.date_to is not None:
        stmt = stmt.where(QueryRun.created_at < _day_start(filters.date_to + timedelta(days=1)))
    return stmt.order_by(QueryRun.created_at.desc(), QueryRun.id)


def _entries(rows: Any) -> list[AuditEntry]:
    return [AuditEntry(run, email, source, key) for run, email, source, key in rows]


def list_entries(
    session: Session, filters: AuditFilters, *, page: int, page_size: int
) -> tuple[list[AuditEntry], int]:
    """Una página de la auditoría (la más reciente primero) y el total con esos filtros."""
    stmt = _query(filters)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = session.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return _entries(rows), int(total or 0)


def export_entries(session: Session, filters: AuditFilters) -> list[AuditEntry]:
    return _entries(session.execute(_query(filters).limit(MAX_EXPORT_ROWS)).all())


def _safe(value: Any) -> str:
    """Texto de una celda CSV; neutraliza las fórmulas que Excel ejecutaría al abrirla."""
    if value is None:
        return ""
    if isinstance(value, dict | list):
        text = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, datetime):
        text = value.isoformat()
    else:
        text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def to_csv(entries: list[AuditEntry]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for entry in entries:
        run = entry.run
        values = {
            "created_at": run.created_at,
            "status": run.status,
            "error_code": run.error_code,
            "user_email": entry.user_email,
            "user_id": run.user_id,
            "external_user_id": run.external_user_id,
            "api_key_name": entry.api_key_name,
            "api_key_id": run.api_key_id,
            "role": run.role,
            "datasource": entry.datasource_name,
            "semantic_version": run.semantic_version,
            "question": run.question,
            "plan": run.plan,
            "origin": run.origin,
            "sql_candidate": run.sql_candidate,
            "sql_final": run.sql_final,
            "filters_applied": run.filters_applied,
            "summary_table": run.summary_table,
            "row_count": run.row_count,
            "provider_kind": run.provider_kind,
            "model": run.model,
            "tokens_in": run.tokens_in,
            "tokens_out": run.tokens_out,
            "cost_usd": run.cost_usd,
            "elapsed_ms": run.elapsed_ms,
        }
        writer.writerow([_safe(values[c]) for c in CSV_COLUMNS])
    return buffer.getvalue()
