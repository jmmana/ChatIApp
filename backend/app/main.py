"""Aplicación FastAPI de ChatIApp."""

import os
from pathlib import Path

from fastapi import FastAPI

from app.api import health, providers
from app.version import __version__
from app.web import mount_web

API_PREFIX = "/api/v1"


def create_app(static_dir: Path | None = None) -> FastAPI:
    """Crea la app. Si hay interfaz compilada (`CHATIAPP_STATIC_DIR`), la sirve en `/`."""
    application = FastAPI(
        title="ChatIApp",
        version=__version__,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
    )
    application.include_router(health.router, prefix=API_PREFIX)
    application.include_router(providers.router, prefix=API_PREFIX)

    if static_dir is None and (env_dir := os.environ.get("CHATIAPP_STATIC_DIR")):
        static_dir = Path(env_dir)
    if static_dir is not None:
        mount_web(application, static_dir)
    return application


app = create_app()
