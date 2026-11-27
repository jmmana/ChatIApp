"""CORS del chat embebido: solo los orígenes permitidos de alguna API key viva con alcance `embed`.

Sin lista global ni comodines. Un `Origin` que no coincide no recibe cabeceras CORS (el navegador
bloquea la respuesta) y su preflight responde 403. La verificación estricta del origen de cada
token vive en `embed_sessions.verify_embed_token`.
"""

from collections.abc import Callable, Generator, MutableMapping
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.db.models import ApiKey
from app.db.session import get_session
from app.integrations.api_keys import as_utc
from app.integrations.embed_sessions import EMBED_SCOPE, normalize_origin

ALLOW_METHODS = "GET, POST, OPTIONS"
ALLOW_HEADERS = "Authorization, Content-Type"
MAX_AGE = "600"


def allowed_origins(session: Session, *, now: datetime | None = None) -> set[str]:
    """Orígenes permitidos por las keys vigentes (no revocadas ni vencidas) con alcance `embed`."""
    now = now or datetime.now(UTC)
    found: set[str] = set()
    for key in session.scalars(select(ApiKey).where(ApiKey.revoked_at.is_(None))):
        if EMBED_SCOPE not in key.scopes:
            continue
        if key.expires_at is not None and as_utc(key.expires_at) <= now:
            continue
        for origin in key.allowed_origins:
            try:
                found.add(normalize_origin(origin))
            except ValueError:
                continue
    return found


SessionFactory = Callable[[], Generator[Session, None, None]]


def _is_allowed(session_factory: SessionFactory, origin: str) -> bool:
    normalized = origin.strip().lower().rstrip("/")
    with closing(session_factory()) as gen:
        session = next(gen)
        return normalized in allowed_origins(session)


class EmbedCORSMiddleware:
    """Middleware ASGI puro (sin buffer: no rompe el SSE) para las rutas bajo `prefix`."""

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.prefix):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is None:
            await self.app(scope, receive, send)
            return
        # Se respeta `dependency_overrides[get_session]`, igual que el resto de la app.
        overrides: MutableMapping[Any, Any] = getattr(scope.get("app"), "dependency_overrides", {})
        factory = overrides.get(get_session, get_session)
        allowed = await run_in_threadpool(_is_allowed, factory, origin)
        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            response: Response
            if allowed:
                response = Response(
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": ALLOW_METHODS,
                        "Access-Control-Allow-Headers": ALLOW_HEADERS,
                        "Access-Control-Max-Age": MAX_AGE,
                        "Vary": "Origin",
                    },
                )
            else:
                response = PlainTextResponse("Origen no permitido.", status_code=403)
            await response(scope, receive, send)
            return
        if not allowed:
            await self.app(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["Access-Control-Allow-Origin"] = origin
                response_headers.append("Vary", "Origin")
            await send(message)

        await self.app(scope, receive, send_with_cors)
