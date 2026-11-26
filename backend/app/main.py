"""Aplicación FastAPI de ChatIApp."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api import auth, health, providers
from app.db.session import get_engine
from app.security.auth import AuthError, ensure_initial_admin, get_current_user
from app.settings.env import get_settings
from app.settings.startup import load_and_register
from app.version import __version__
from app.web import mount_web

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    # Primero la configuración: si es inválida lanza ConfigError y la app no arranca.
    load_and_register(get_settings())
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


def create_app(static_dir: Path | None = None) -> FastAPI:
    """Crea la app. Si hay interfaz compilada (`CHATIAPP_STATIC_DIR`), la sirve en `/`.

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
    # Todo lo que no es health ni auth exige sesión (tests/security/test_routes.py lo vigila).
    protected = [Depends(get_current_user)]
    application.include_router(providers.router, prefix=API_PREFIX, dependencies=protected)
    # Administración de keys: solo administradores con JWT de usuario, nunca una API key.
    application.include_router(
        api_keys.router, prefix=API_PREFIX, dependencies=[Depends(require_admin)]
    )

    if static_dir is None and (env_dir := os.environ.get("CHATIAPP_STATIC_DIR")):
        static_dir = Path(env_dir)
    if static_dir is not None:
        mount_web(application, static_dir)
    return application


app = create_app()
