"""API keys de servidor: creación, verificación, revocación y el `Principal` común (ADR 0007).

Formato `chia_<id>_<secreto>`. En la base solo vive el HMAC-SHA256 del secreto calculado con una
llave del servidor; el secreto completo se devuelve una única vez al crear la key.
"""

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ApiKey, User
from app.db.session import get_session
from app.security.auth import AuthError, decode_token
from app.security.crypto import api_key_hmac_key

KEY_PREFIX = "chia"
SECRET_BYTES = 32  # al menos 32 bytes aleatorios
ID_BYTES = 6

SCOPES = ("chat", "embed", "sql:preview", "semantic:read", "semantic:write")

# Campos que `update_api_key` permite cambiar.
UPDATABLE_FIELDS = frozenset(
    {
        "name",
        "scopes",
        "datasources",
        "allowed_roles",
        "allowed_origins",
        "rate_limit_per_minute",
        "monthly_budget_usd",
        "expires_at",
    }
)

_INVALID_KEY = AuthError(401, "invalid_api_key", "API key inválida, expirada o revocada.")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """SQLite devuelve las fechas sin zona horaria: se interpretan como UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def hash_secret(secret: str) -> str:
    """HMAC-SHA256 del secreto con la llave del servidor, en hexadecimal."""
    return hmac.new(api_key_hmac_key(), secret.encode(), hashlib.sha256).hexdigest()


def parse_api_key(raw: str) -> tuple[str, str] | None:
    """Separa `chia_<id>_<secreto>` en (`chia_<id>`, secreto); `None` si no tiene el formato."""
    head, sep, secret = raw.partition("_")
    if head != KEY_PREFIX or not sep:
        return None
    key_id, sep, secret = secret.partition("_")
    if not key_id or not sep or not secret:
        return None
    return f"{KEY_PREFIX}_{key_id}", secret


def looks_like_api_key(token: str) -> bool:
    return token.startswith(f"{KEY_PREFIX}_")


def _clean_list(values: Iterable[str] | None) -> list[str]:
    seen: list[str] = []
    for value in values or ():
        item = value.strip()
        if item and item not in seen:
            seen.append(item)
    return seen


def _validate_scopes(scopes: Iterable[str]) -> list[str]:
    cleaned = _clean_list(scopes)
    unknown = [s for s in cleaned if s not in SCOPES]
    if unknown:
        valid = ", ".join(SCOPES)
        raise ValueError(f"Alcances desconocidos: {', '.join(unknown)}. Válidos: {valid}")
    if not cleaned:
        raise ValueError("La key necesita al menos un alcance.")
    return cleaned


def _validate_limits(rate_limit_per_minute: int | None, monthly_budget_usd: Decimal | None) -> None:
    if rate_limit_per_minute is not None and rate_limit_per_minute < 1:
        raise ValueError("rate_limit_per_minute debe ser al menos 1.")
    if monthly_budget_usd is not None and monthly_budget_usd < 0:
        raise ValueError("monthly_budget_usd no puede ser negativo.")


def _validate_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("El nombre no puede estar vacío.")
    return cleaned


def _validate_expiry(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None
    expires_at = _aware(expires_at)
    if expires_at <= _now():
        raise ValueError("La expiración debe estar en el futuro.")
    return expires_at


# --- Administración ---------------------------------------------------------------------------


def create_api_key(
    session: Session,
    *,
    name: str,
    scopes: Iterable[str],
    datasources: Iterable[str] | None = None,
    allowed_roles: Iterable[str] | None = None,
    allowed_origins: Iterable[str] | None = None,
    rate_limit_per_minute: int | None = None,
    monthly_budget_usd: Decimal | None = None,
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    """Crea una key. Devuelve la fila y el secreto completo, que no se podrá volver a obtener."""
    _validate_limits(rate_limit_per_minute, monthly_budget_usd)
    api_key = ApiKey(
        name=_validate_name(name),
        scopes=_validate_scopes(scopes),
        datasources=_clean_list(datasources),
        allowed_roles=_clean_list(allowed_roles),
        allowed_origins=_clean_list(allowed_origins),
        rate_limit_per_minute=rate_limit_per_minute,
        monthly_budget_usd=monthly_budget_usd,
        expires_at=_validate_expiry(expires_at),
    )
    for _ in range(5):  # el id público es corto: se reintenta ante una colisión improbable
        key_id = secrets.token_hex(ID_BYTES)
        secret = secrets.token_urlsafe(SECRET_BYTES)
        api_key.prefix = f"{KEY_PREFIX}_{key_id}"
        api_key.secret_hash = hash_secret(secret)
        session.add(api_key)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            continue
        return api_key, f"{api_key.prefix}_{secret}"
    raise RuntimeError("No se pudo generar un identificador único para la API key.")


def list_api_keys(session: Session) -> list[ApiKey]:
    return list(session.scalars(select(ApiKey).order_by(ApiKey.created_at, ApiKey.name)))


def get_api_key(session: Session, key_id: uuid.UUID) -> ApiKey:
    api_key = session.get(ApiKey, key_id)
    if api_key is None:
        raise AuthError(404, "not_found", "No existe esa API key.")
    return api_key


def find_api_key(session: Session, ref: str) -> ApiKey:
    """Busca por id (UUID) o por prefijo visible (`chia_<id>`)."""
    try:
        return get_api_key(session, uuid.UUID(ref))
    except ValueError:
        pass
    api_key = session.scalar(select(ApiKey).where(ApiKey.prefix == ref))
    if api_key is None:
        raise AuthError(404, "not_found", "No existe esa API key.")
    return api_key


def update_api_key(session: Session, key_id: uuid.UUID, changes: dict[str, Any]) -> ApiKey:
    """Aplica solo los campos presentes en `changes` (los de `UPDATABLE_FIELDS`)."""
    api_key = get_api_key(session, key_id)
    if api_key.revoked_at is not None:
        raise AuthError(409, "revoked", "La key está revocada y no se puede editar.")
    unknown = set(changes) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"Campos no editables: {', '.join(sorted(unknown))}")
    if "name" in changes:
        api_key.name = _validate_name(changes["name"])
    if "scopes" in changes:
        api_key.scopes = _validate_scopes(changes["scopes"])
    for field in ("datasources", "allowed_roles", "allowed_origins"):
        if field in changes:
            setattr(api_key, field, _clean_list(changes[field]))
    _validate_limits(changes.get("rate_limit_per_minute"), changes.get("monthly_budget_usd"))
    if "rate_limit_per_minute" in changes:
        api_key.rate_limit_per_minute = changes["rate_limit_per_minute"]
    if "monthly_budget_usd" in changes:
        api_key.monthly_budget_usd = changes["monthly_budget_usd"]
    if "expires_at" in changes:
        api_key.expires_at = _validate_expiry(changes["expires_at"])
    session.commit()
    return api_key


def revoke_api_key(session: Session, key_id: uuid.UUID) -> ApiKey:
    """Revoca la key; la siguiente petición con ella recibe 401. Es idempotente."""
    api_key = get_api_key(session, key_id)
    if api_key.revoked_at is None:
        api_key.revoked_at = _now()
        session.commit()
    return api_key


# --- Verificación -----------------------------------------------------------------------------


def authenticate_api_key(session: Session, raw: str, *, now: datetime | None = None) -> ApiKey:
    """Valida una API key completa y registra su último uso. Lanza `AuthError` 401 si no sirve."""
    parsed = parse_api_key(raw)
    if parsed is None:
        raise _INVALID_KEY
    prefix, secret = parsed
    api_key = session.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
    candidate = hash_secret(secret)
    # Se compara siempre, exista o no la key, y en tiempo constante.
    stored = api_key.secret_hash if api_key is not None else "0" * len(candidate)
    matches = hmac.compare_digest(candidate.encode(), stored.encode())
    if api_key is None or not matches:
        raise _INVALID_KEY
    now = now or _now()
    if api_key.revoked_at is not None:
        raise _INVALID_KEY
    if api_key.expires_at is not None and _aware(api_key.expires_at) <= now:
        raise _INVALID_KEY
    api_key.last_used_at = now
    session.commit()
    return api_key


# --- Principal común --------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """Quien hace la petición: un usuario (JWT) o una API key. El resto del código solo ve esto."""

    kind: str  # "user" | "api_key"
    scopes: frozenset[str]
    user: User | None = None
    api_key: ApiKey | None = None

    @property
    def is_admin(self) -> bool:
        """Solo un usuario administrador: ninguna key administra usuarios ni keys."""
        return self.user is not None and self.user.is_admin

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user else None

    @property
    def api_key_id(self) -> uuid.UUID | None:
        return self.api_key.id if self.api_key else None


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError(401, "not_authenticated", "Falta la credencial Bearer.")
    return token.strip()


def get_principal(request: Request, session: Annotated[Session, Depends(get_session)]) -> Principal:
    """Acepta JWT de usuario o API key en `Authorization: Bearer`.

    Los usuarios tienen todos los alcances (sus límites son sus permisos y concesiones); las keys,
    solo los suyos.
    """
    token = _bearer_token(request)
    if looks_like_api_key(token):
        api_key = authenticate_api_key(session, token)
        return Principal("api_key", frozenset(api_key.scopes), api_key=api_key)
    user = session.get(User, decode_token(token, "access"))
    if user is None:
        raise AuthError(401, "invalid_token", "Credencial inválida o expirada.")
    return Principal("user", frozenset(SCOPES), user=user)


def require_scope(scope: str) -> Callable[[Principal], Principal]:
    """Dependencia que responde 403 si el principal no tiene el alcance: `require_scope("chat")`."""
    if scope not in SCOPES:
        raise ValueError(f"Alcance desconocido: {scope}")

    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if scope not in principal.scopes:
            raise AuthError(403, "insufficient_scope", f"Falta el alcance requerido: {scope}.")
        return principal

    return dependency
