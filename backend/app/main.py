"""Aplicación FastAPI de ChatIApp."""

import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api import (
    api_keys,
    audit,
    auth,
    chat,
    conversations,
    datasources,
    embed,
    health,
    metrics,
    preview,
    providers,
    semantic,
    users,
)
from app.api.errors import register_error_handlers
from app.db.session import get_engine
from app.integrations.cors import EmbedCORSMiddleware
from app.observability import configure_logging, render_metrics, setup_tracing, shutdown_tracing
from app.security.auth import AuthError, ensure_initial_admin, get_current_user, require_admin
from app.settings.env import get_settings
from app.settings.startup import load_and_register
from app.version import __version__
from app.web import mount_web

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    # Primero la configuración: si es inválida lanza ConfigError y la app no arranca.
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    load_and_register(settings)
    setup_tracing(settings.otel_endpoint, settings.otel_service_name)
    with Session(get_engine()) as session:
        ensure_initial_admin(session)
    try:
        yield
    finally:
        shutdown_tracing()


def _metrics(request: Request) -> Response:
    """Exposición Prometheus. Fuera de `/api/v1` porque así la espera el scraper.

    Seguro por defecto: sin `CHATIAPP_METRICS_TOKEN` la ruta responde 404, como si no existiera.
    Con token exige `Authorization: Bearer <token>` (comparación en tiempo constante).
    """
    token = get_settings().metrics_token
    if token is None:
        return Response(status_code=404)
    sent = request.headers.get("authorization", "")
    expected = f"Bearer {token.get_secret_value()}"
    if not hmac.compare_digest(sent.encode(), expected.encode()):
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    body, content_type = render_metrics()
    return Response(body, media_type=content_type)


def _auth_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AuthError)
    headers: dict[str, str] = {}
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    retry_after = getattr(exc, "retry_after", None)
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": {}}},
        headers=headers or None,
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
    application.include_router(
        audit.router, prefix=API_PREFIX, dependencies=[Depends(require_admin)]
    )
    application.include_router(
        users.router, prefix=API_PREFIX, dependencies=[Depends(require_admin)]
    )
    application.include_router(datasources.router, prefix=API_PREFIX, dependencies=protected)
    application.include_router(semantic.router, prefix=API_PREFIX, dependencies=protected)
    application.include_router(metrics.router, prefix=API_PREFIX, dependencies=protected)
    application.include_router(preview.router, prefix=API_PREFIX, dependencies=protected)
    application.add_api_route("/metrics", _metrics, methods=["GET"], include_in_schema=False)
    # Cada ruta del chat declara su credencial: `/chat/stream` y `cancel` solo sesión; `POST /chat`
    # sesión o API key con alcance `chat`. No lleva `get_current_user` global.
    application.include_router(chat.router, prefix=API_PREFIX)
    # Conversaciones: lectura con sesión o token de sesión; renombrar y eliminar, solo sesión.
    application.include_router(conversations.router, prefix=API_PREFIX)
    # Emisión de tokens de sesión: solo API key con alcance `embed` (`require_scope`).
    application.include_router(embed.router, prefix=API_PREFIX)
    register_error_handlers(application)
    # CORS solo para los orígenes permitidos de las keys con alcance `embed`.
    application.add_middleware(EmbedCORSMiddleware, prefix=API_PREFIX)

    if static_dir is None and (env_dir := os.environ.get("CHATIAPP_STATIC_DIR")):
        static_dir = Path(env_dir)
    if static_dir is not None:
        mount_web(application, static_dir)
    return application


app = create_app()
