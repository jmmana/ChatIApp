"""Aplicación FastAPI de ChatIApp."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api import auth, health
from app.db.session import get_engine
from app.security.auth import AuthError, ensure_initial_admin
from app.version import __version__

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    with Session(get_engine()) as session:
        ensure_initial_admin(session)
    yield


def _auth_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AuthError)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": {}}},
        headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
    )


def create_app() -> FastAPI:
    """Crea la app.

    `health` y `auth` son públicas. Todo router nuevo bajo `/api/v1` se incluye con
    `dependencies=[Depends(get_current_user)]` (o `require_admin` si es de administración).
    """
    application = FastAPI(
        title="ChatIApp",
        version=__version__,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    application.add_exception_handler(AuthError, _auth_error_handler)
    application.include_router(health.router, prefix=API_PREFIX)
    application.include_router(auth.router, prefix=API_PREFIX)
    return application


app = create_app()
