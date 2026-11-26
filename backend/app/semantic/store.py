"""Persistencia del modelo semántico: una fila inmutable por versión (ADR 0005)."""

import json
import uuid
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import SemanticModelVersion, User
from app.semantic.schema import SemanticModel, parse_semantic_model


class VersionConflictError(Exception):
    """Alguien publicó una versión después de la que el cliente tenía (`base_version`)."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"La versión vigente es la {current_version}")


def dump_model(model: SemanticModel) -> dict[str, Any]:
    """Documento JSON del modelo, con los alias del esquema (`from`)."""
    return model.model_dump(mode="json", by_alias=True)


def load_model(row: SemanticModelVersion) -> SemanticModel:
    return parse_semantic_model(row.model)


def current(session: Session, datasource_id: uuid.UUID) -> SemanticModelVersion | None:
    """La versión vigente es la última."""
    return session.scalar(
        select(SemanticModelVersion)
        .where(SemanticModelVersion.datasource_id == datasource_id)
        .order_by(SemanticModelVersion.version.desc())
        .limit(1)
    )


def get_version(
    session: Session, datasource_id: uuid.UUID, version: int
) -> SemanticModelVersion | None:
    return session.scalar(
        select(SemanticModelVersion).where(
            SemanticModelVersion.datasource_id == datasource_id,
            SemanticModelVersion.version == version,
        )
    )


def list_versions(session: Session, datasource_id: uuid.UUID) -> list[SemanticModelVersion]:
    """Historial, de la más reciente a la más antigua."""
    return list(
        session.scalars(
            select(SemanticModelVersion)
            .where(SemanticModelVersion.datasource_id == datasource_id)
            .order_by(SemanticModelVersion.version.desc())
        )
    )


def publish(
    session: Session,
    datasource_id: uuid.UUID,
    model: SemanticModel,
    base_version: int,
    user: User | None = None,
) -> SemanticModelVersion:
    """Crea una versión nueva. `base_version` es la que el cliente vio (0 si no había ninguna).

    Lanza `VersionConflictError` si ya hay una más reciente, incluso si otra petición ganó la
    carrera (la restricción única de `(datasource_id, version)` lo detecta).
    """
    latest = current(session, datasource_id)
    latest_number = latest.version if latest else 0
    if base_version != latest_number:
        raise VersionConflictError(latest_number)
    author_id = None
    if user is not None and user.id is not None and session.get(User, user.id) is not None:
        author_id = user.id
    row = SemanticModelVersion(
        datasource_id=datasource_id,
        version=latest_number + 1,
        model=dump_model(model),
        created_by=author_id,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        newest = current(session, datasource_id)
        raise VersionConflictError(newest.version if newest else 0) from exc
    return row


def export_model(model: SemanticModel, fmt: str) -> str:
    """Serializa el modelo a `yaml` o `json`; reimportarlo da un modelo idéntico."""
    data = dump_model(model)
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
