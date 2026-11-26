"""Aplicación FastAPI de ChatIApp."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import health, providers
from app.settings.env import get_settings
from app.settings.startup import load_and_register
from app.version import __version__
from app.web import mount_web

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Una configuración inválida lanza ConfigError y la app no arranca.
    load_and_register(get_settings())
    yield


def create_app(static_dir: Path | None = None) -> FastAPI:
    """Crea la app. Si hay interfaz compilada (`CHATIAPP_STATIC_DIR`), la sirve en `/`."""
    application = FastAPI(
        lifespan=lifespan,
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
