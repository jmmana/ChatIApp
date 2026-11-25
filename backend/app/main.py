"""Aplicación FastAPI de ChatIApp."""

from fastapi import FastAPI

from app.api import health
from app.version import __version__

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    application = FastAPI(
        title="ChatIApp",
        version=__version__,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
    )
    application.include_router(health.router, prefix=API_PREFIX)
    return application


app = create_app()
