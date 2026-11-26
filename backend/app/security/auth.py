"""Autenticación: hash Argon2, JWT de usuario, bloqueo por intentos y dependencias de acceso."""

import logging
import os
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_session
from app.security.crypto import jwt_signing_key

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=7)
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 15 * 60

_hasher = PasswordHasher()
# Hash de relleno: se verifica cuando el correo no existe para no revelarlo por tiempo de respuesta.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class AuthError(Exception):
    """Error de autenticación o autorización con la forma de error de la API."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


# --- Llave de firma ---------------------------------------------------------------------------


def get_secret_key() -> str:
    """Llave de firma de los JWT: derivada con HKDF de `CHATIAPP_SECRET_KEY` y distinta de la que
    cifra credenciales (`crypto.jwt_signing_key`). Sin llave en desarrollo se usa una temporal y
    en producción el arranque falla."""
    return jwt_signing_key()


# --- Tokens -----------------------------------------------------------------------------------


def _encode(user_id: uuid.UUID, kind: str, ttl: timedelta) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "typ": kind,
        "iat": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, get_secret_key(), algorithm=ALGORITHM)


def create_access_token(user_id: uuid.UUID) -> str:
    return _encode(user_id, "access", ACCESS_TTL)


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _encode(user_id, "refresh", REFRESH_TTL)


def decode_token(token: str, kind: str) -> uuid.UUID:
    """Valida firma, expiración y tipo; devuelve el id de usuario."""
    try:
        claims = jwt.decode(
            token, get_secret_key(), algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
        )
        if claims.get("typ") != kind:
            raise jwt.InvalidTokenError("tipo de token incorrecto")
        return uuid.UUID(str(claims["sub"]))
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise AuthError(401, "invalid_token", "Credencial inválida o expirada.") from exc


# --- Bloqueo por intentos fallidos ------------------------------------------------------------


class LoginThrottle:
    """Cuenta intentos fallidos por correo en una ventana deslizante (en memoria, por proceso)."""

    def __init__(
        self,
        max_attempts: int = MAX_FAILED_ATTEMPTS,
        window_seconds: float = LOCKOUT_WINDOW_SECONDS,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, email: str, now: float) -> deque[float]:
        failures = self._failures[email]
        while failures and now - failures[0] >= self.window_seconds:
            failures.popleft()
        if not failures:
            self._failures.pop(email, None)
        return failures

    def retry_after(self, email: str) -> int:
        """Segundos hasta poder reintentar; 0 si el correo no está bloqueado."""
        now = time.monotonic()
        with self._lock:
            failures = self._prune(email, now)
            if len(failures) < self.max_attempts:
                return 0
            return max(1, int(failures[0] + self.window_seconds - now) + 1)

    def acquire(self, email: str) -> int:
        """Cuenta el intento ANTES de verificar la contraseña, en la misma operación que mira el
        límite: así las peticiones en paralelo no consiguen más intentos. Devuelve los segundos de
        espera si ya no quedan intentos, o 0. Un inicio de sesión correcto llama a `reset`."""
        now = time.monotonic()
        with self._lock:
            failures = self._prune(email, now)
            if len(failures) >= self.max_attempts:
                return max(1, int(failures[0] + self.window_seconds - now) + 1)
            self._failures[email].append(now)
            return 0

    def register_failure(self, email: str) -> None:
        with self._lock:
            self._failures[email].append(time.monotonic())

    def reset(self, email: str) -> None:
        with self._lock:
            self._failures.pop(email, None)


_throttle = LoginThrottle()


def get_throttle() -> LoginThrottle:
    return _throttle


# --- Inicio de sesión -------------------------------------------------------------------------


@dataclass(frozen=True)
class LoginResult:
    user: User
    access_token: str
    refresh_token: str


def authenticate(session: Session, throttle: LoginThrottle, email: str, password: str) -> User:
    key = normalize_email(email)
    wait = throttle.acquire(key)
    if wait:
        raise AuthError(
            429, "too_many_attempts", f"Demasiados intentos fallidos. Reintenta en {wait} s."
        )
    user = session.scalar(select(User).where(User.email == key))
    # Siempre se verifica un hash, exista o no el usuario.
    valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not valid:  # el intento ya quedó contado en `acquire`
        raise AuthError(401, "invalid_credentials", "Correo o contraseña incorrectos.")
    throttle.reset(key)
    return user


def login(session: Session, throttle: LoginThrottle, email: str, password: str) -> LoginResult:
    user = authenticate(session, throttle, email, password)
    return LoginResult(user, create_access_token(user.id), create_refresh_token(user.id))


def user_from_refresh_token(session: Session, token: str) -> User:
    user = session.get(User, decode_token(token, "refresh"))
    if user is None:
        raise AuthError(401, "invalid_token", "Credencial inválida o expirada.")
    return user


# --- Administrador inicial --------------------------------------------------------------------


def ensure_initial_admin(session: Session) -> User | None:
    """Crea el administrador inicial si no hay ninguno.

    Usa `CHATIAPP_ADMIN_EMAIL` y `CHATIAPP_ADMIN_PASSWORD`.
    """
    email = os.environ.get("CHATIAPP_ADMIN_EMAIL")
    password = os.environ.get("CHATIAPP_ADMIN_PASSWORD")
    if not email or not password:
        if session.scalar(select(User).limit(1)) is None:
            logger.warning(
                "No hay usuarios y faltan CHATIAPP_ADMIN_EMAIL o CHATIAPP_ADMIN_PASSWORD: nadie "
                "podrá iniciar sesión. Defínelas y reinicia para crear el administrador inicial."
            )
        return None
    if session.scalar(select(User).where(User.is_admin.is_(True)).limit(1)) is not None:
        return None
    key = normalize_email(email)
    if session.scalar(select(User).where(User.email == key)) is not None:
        return None
    admin = User(email=key, password_hash=hash_password(password), is_admin=True)
    session.add(admin)
    session.commit()
    logger.info("Administrador inicial creado: %s", key)
    return admin


# --- Dependencias de acceso -------------------------------------------------------------------


def get_current_user(request: Request, session: Annotated[Session, Depends(get_session)]) -> User:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError(401, "not_authenticated", "Falta la credencial Bearer.")
    user = session.get(User, decode_token(token.strip(), "access"))
    if user is None:
        raise AuthError(401, "invalid_token", "Credencial inválida o expirada.")
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise AuthError(403, "forbidden", "Se requiere ser administrador.")
    return user
