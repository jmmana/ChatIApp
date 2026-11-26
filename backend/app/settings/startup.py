"""Carga de `chatiapp.yaml` al arrancar y registro en la BD."""

from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_engine
from app.security.crypto import make_cipher
from app.settings.env import Settings
from app.settings.project import ConfigError, ProjectConfig, load_project_config
from app.settings.registry import sync_config_to_db


def load_and_register(settings: Settings, session: Session | None = None) -> ProjectConfig | None:
    """Valida el archivo de `CHATIAPP_CONFIG` y lo registra. Lanza `ConfigError` si falla.

    Sin `CHATIAPP_CONFIG` no hace nada. Requiere que las migraciones ya estén aplicadas.
    """
    if settings.config is None:
        return None
    config = load_project_config(settings.config)
    if settings.secret_key is None:
        raise ConfigError(["CHATIAPP_SECRET_KEY: es obligatoria para registrar el archivo"])
    previous = settings.secret_key_previous
    cipher = make_cipher(
        settings.secret_key.get_secret_value(),
        previous.get_secret_value() if previous else None,
    )
    if session is not None:
        sync_config_to_db(session, config, cipher)
    else:
        with sessionmaker(bind=get_engine(), expire_on_commit=False)() as own_session:
            sync_config_to_db(own_session, config, cipher)
    return config
