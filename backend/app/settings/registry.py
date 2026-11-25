"""Registro en la BD de los proveedores y fuentes declarados en `chatiapp.yaml`."""

import json
import uuid

from cryptography.fernet import MultiFernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Datasource, Provider
from app.settings.project import SECRET_PROVIDER_FIELDS, ConfigError, ProjectConfig

MANAGED_BY = "config"
_NAMESPACE = uuid.UUID("6f0c2f8e-5d57-4c0e-9a0e-1c4f0d6f9a11")


def provider_uuid(config_id: str) -> uuid.UUID:
    """UUID estable derivado del `id` del archivo, para actualizar en cada arranque."""
    return uuid.uuid5(_NAMESPACE, f"provider:{config_id}")


def datasource_uuid(config_id: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"datasource:{config_id}")


def sync_config_to_db(session: Session, config: ProjectConfig, cipher: MultiFernet) -> None:
    """Crea o actualiza (con `managed_by="config"`) lo declarado en el archivo."""
    for p in config.ai.providers:
        fields = p.model_dump(exclude={"id", "kind", "model"}, exclude_none=True)
        secrets = {k: v for k, v in fields.items() if k in SECRET_PROVIDER_FIELDS}
        plain = {k: v for k, v in fields.items() if k not in SECRET_PROVIDER_FIELDS}
        provider = session.get(Provider, provider_uuid(p.id))
        if provider is None:
            if session.scalar(select(Provider.id).where(Provider.name == p.id)) is not None:
                raise ConfigError([_name_taken(f"ai.providers[{p.id}]", p.id)])
            provider = Provider(id=provider_uuid(p.id), name=p.id)
            session.add(provider)
        provider.kind = p.kind
        provider.model = p.model
        provider.config = plain
        provider.secrets_encrypted = (
            cipher.encrypt(json.dumps(secrets).encode()) if secrets else None
        )
        provider.managed_by = MANAGED_BY

    for d in config.datasources:
        datasource = session.get(Datasource, datasource_uuid(d.id))
        if datasource is None:
            if session.scalar(select(Datasource.id).where(Datasource.name == d.name)) is not None:
                raise ConfigError([_name_taken(f"datasources[{d.id}]", d.name)])
            datasource = Datasource(id=datasource_uuid(d.id), name=d.name)
            session.add(datasource)
        datasource.name = d.name
        datasource.dialect = d.dialect
        datasource.url_encrypted = cipher.encrypt(d.url.encode())
        datasource.execute = d.execute
        datasource.max_rows = d.max_rows
        datasource.timeout_seconds = d.timeout_seconds
        datasource.privacy = config.ai.privacy
        datasource.managed_by = MANAGED_BY
    session.commit()


def _name_taken(where: str, name: str) -> str:
    return f"{where}: ya existe un registro con el nombre «{name}» que no viene del archivo"
