"""Tokens de sesión cortos para el chat embebido (docs/INTEGRACION.md#chat-embebido).

El backend de la app anfitriona cambia su API key (alcance `embed`) por un JWT firmado por
ChatIApp, atado a un usuario final, una fuente, un rol con sus atributos y un origen. El
navegador solo ve ese token, que sirve únicamente para el chat y las conversaciones de ese
usuario. Cada petición vuelve a leer la key: revocarla, vencerla o quitarle el origen o el
alcance `embed` invalida sus tokens en la siguiente petición.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db.models import ApiKey, User
from app.db.session import get_session
from app.engine.rls import AttributeValue
from app.integrations.api_keys import as_utc, bearer_token, looks_like_api_key
from app.security.auth import ALGORITHM, AuthError, get_current_user, get_secret_key

TOKEN_TYPE = "embed"
EMBED_SCOPE = "embed"
TOKEN_SCOPES = ("chat",)  # lo único que un token de sesión puede hacer
DEFAULT_TTL_SECONDS = 900
MAX_TTL_SECONDS = 3600


def normalize_origin(origin: str) -> str:
    """`esquema://host[:puerto]` en minúsculas y sin barra final; `ValueError` si no lo es."""
    parts = urlsplit(origin.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("El origen debe tener la forma https://dominio[:puerto].")
    if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username:
        raise ValueError("El origen no lleva ruta, parámetros ni credenciales.")
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname}{port}".lower()


def origin_allowed(api_key: ApiKey, origin: str) -> bool:
    for allowed in api_key.allowed_origins:
        try:
            if normalize_origin(allowed) == origin:
                return True
        except ValueError:
            continue
    return False


@dataclass(frozen=True)
class EmbedSession:
    """Un token de sesión ya verificado, con la key que lo emitió."""

    user_id: str
    datasource_id: uuid.UUID
    role: str | None
    attributes: dict[str, AttributeValue]
    origin: str
    api_key: ApiKey
    scopes: frozenset[str]


def create_embed_token(
    api_key: ApiKey,
    *,
    user_id: str,
    datasource_id: uuid.UUID,
    role: str,
    attributes: Mapping[str, AttributeValue],
    origin: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Firma el token. Devuelve el JWT y su expiración (UTC, al segundo)."""
    if not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds debe estar entre 1 y {MAX_TTL_SECONDS}.")
    issued = (now or datetime.now(UTC)).replace(microsecond=0)
    expires = issued + timedelta(seconds=ttl_seconds)
    claims: dict[str, Any] = {
        "typ": TOKEN_TYPE,
        "sub": user_id,
        "ds": str(datasource_id),
        "role": role,
        "attrs": dict(attributes),
        "origin": normalize_origin(origin),
        "kid": str(api_key.id),
        "scopes": list(TOKEN_SCOPES),
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, get_secret_key(), algorithm=ALGORITHM), expires


def is_embed_token(token: str) -> bool:
    """¿Dice ser un token de sesión? Solo orienta el enrutado: `verify_embed_token` lo valida."""
    if looks_like_api_key(token):
        return False
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError:
        return False
    return claims.get("typ") == TOKEN_TYPE


def verify_embed_token(
    session: Session, token: str, origin: str | None, *, now: datetime | None = None
) -> EmbedSession:
    """Valida firma, expiración, key viva y origen.

    401 `token_expired` si venció (el widget pide otro), 401 `invalid_token` si no es válido,
    401 `invalid_api_key` si la key se revocó o venció, 403 `origin_not_allowed` si el `Origin`
    de la petición no es el del token (o ya no está permitido en la key).
    """
    try:
        claims = jwt.decode(
            token,
            get_secret_key(),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "kid", "ds", "origin"]},
        )
        if claims.get("typ") != TOKEN_TYPE:
            raise jwt.InvalidTokenError("tipo de token incorrecto")
        key_id = uuid.UUID(str(claims["kid"]))
        datasource_id = uuid.UUID(str(claims["ds"]))
        scopes = frozenset(str(s) for s in claims.get("scopes", ()))
        attributes = dict(claims.get("attrs") or {})
        user_id = str(claims["sub"])
        role = claims.get("role")
        token_origin = str(claims["origin"])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError(
            401, "token_expired", "El token de sesión expiró: pide otro a tu backend."
        ) from exc
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise AuthError(401, "invalid_token", "Token de sesión inválido.") from exc
    if not scopes <= set(TOKEN_SCOPES):
        raise AuthError(401, "invalid_token", "Token de sesión inválido.")
    api_key = session.get(ApiKey, key_id)
    now = now or datetime.now(UTC)
    if (
        api_key is None
        or api_key.revoked_at is not None
        or (api_key.expires_at is not None and as_utc(api_key.expires_at) <= now)
        or EMBED_SCOPE not in api_key.scopes
    ):
        raise AuthError(401, "invalid_api_key", "La API key del token fue revocada o expiró.")
    if origin is None or origin.strip().lower().rstrip("/") != token_origin:
        raise AuthError(403, "origin_not_allowed", "El token no se puede usar desde este origen.")
    if not origin_allowed(api_key, token_origin):
        raise AuthError(403, "origin_not_allowed", "La API key ya no permite este origen.")
    return EmbedSession(user_id, datasource_id, role, attributes, token_origin, api_key, scopes)


@dataclass(frozen=True)
class Caller:
    """Quien usa el chat: un usuario con sesión o un usuario final con token de sesión."""

    user: User | None = None
    embed: EmbedSession | None = None

    @property
    def owner(self) -> str:
        """Dueño de los turnos: no se mezcla entre usuarios ni entre keys."""
        if self.embed is not None:
            return f"{self.embed.api_key.id}:{self.embed.user_id}"
        assert self.user is not None
        return str(self.user.id)


def get_caller(request: Request, session: Annotated[Session, Depends(get_session)]) -> Caller:
    """Credencial de las rutas de chat y de lectura de conversaciones: sesión o token de sesión."""
    token = bearer_token(request)
    if is_embed_token(token):
        return Caller(embed=verify_embed_token(session, token, request.headers.get("Origin")))
    return Caller(user=get_current_user(request, session))
