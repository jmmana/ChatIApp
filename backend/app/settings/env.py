"""Configuración del entorno (variables `CHATIAPP_*`)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Una variable vacía cuenta como no definida: CHATIAPP_SECRET_KEY="" no es una llave.
    model_config = SettingsConfigDict(env_prefix="CHATIAPP_", extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite:///./chatiapp.db"
    secret_key: SecretStr | None = None
    secret_key_previous: SecretStr | None = None
    config: Path | None = None
    env: Literal["development", "test", "production"] = "development"
    # Observabilidad (docs/OBSERVABILIDAD.md). Sin endpoint OTLP no se exportan trazas.
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    otel_endpoint: str | None = None
    otel_service_name: str = "chatiapp"
    # Si se define, `/metrics` exige `Authorization: Bearer <token>`.
    metrics_token: SecretStr | None = None

    @model_validator(mode="after")
    def _secret_key_en_produccion(self) -> Self:
        if self.env == "production" and self.secret_key is None:
            raise ValueError("CHATIAPP_SECRET_KEY es obligatoria cuando CHATIAPP_ENV=production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
