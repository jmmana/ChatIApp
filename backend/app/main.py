"""Aplicación FastAPI de ChatIApp."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, providers
from app.settings.env import get_settings
from app.settings.startup import load_and_register
from app.version import __version__

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Una configuración inválida lanza ConfigError y la app no arranca.
    load_and_register(get_settings())
    yield


def create_app() -> FastAPI:
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
    return application


app = create_app()
