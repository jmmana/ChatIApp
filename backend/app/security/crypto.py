"""Cifrado de secretos en reposo con Fernet, rotación con MultiFernet y enmascarado."""

import base64
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.settings.env import Settings, get_settings

logger = logging.getLogger(__name__)

PURPOSE_CREDENTIALS = "credentials"
PURPOSE_JWT = "jwt"

_MASK_CHAR = "*"
_VISIBLE_TAIL = 4
_MIN_MASKABLE = 12  # por debajo de este largo no se muestra ningún carácter


class SecretKeyError(RuntimeError):
    """La llave secreta falta o no permite descifrar los datos."""


def derive_key(secret: str, purpose: str) -> bytes:
    """Deriva con HKDF-SHA256 una llave de 32 bytes distinta para cada `purpose`."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"chatiapp:{purpose}".encode(),
    ).derive(secret.encode())


def _fernet(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(derive_key(secret, PURPOSE_CREDENTIALS)))


def make_cipher(secret_key: str, previous_key: str | None = None) -> MultiFernet:
    """Cifra con `secret_key`; descifra también con `previous_key` (rotación)."""
    keys = [_fernet(secret_key)]
    if previous_key:
        keys.append(_fernet(previous_key))
    return MultiFernet(keys)


@lru_cache(maxsize=1)
def _ephemeral_key() -> str:
    logger.warning(
        "CHATIAPP_SECRET_KEY no está definida: se usa una llave temporal. "
        "Los secretos cifrados no se podrán descifrar tras reiniciar."
    )
    return Fernet.generate_key().decode()


def resolve_secret_key(settings: Settings | None = None) -> str:
    """Devuelve `CHATIAPP_SECRET_KEY`; en desarrollo genera una temporal y avisa en el log."""
    settings = settings or get_settings()
    if settings.secret_key is not None:
        return settings.secret_key.get_secret_value()
    if settings.env == "production":
        raise SecretKeyError("CHATIAPP_SECRET_KEY es obligatoria cuando CHATIAPP_ENV=production")
    return _ephemeral_key()


def get_cipher(settings: Settings | None = None) -> MultiFernet:
    settings = settings or get_settings()
    previous = settings.secret_key_previous
    return make_cipher(
        resolve_secret_key(settings),
        previous.get_secret_value() if previous else None,
    )


def jwt_signing_key(settings: Settings | None = None) -> str:
    """Llave para firmar los JWT, independiente de la de credenciales."""
    return base64.urlsafe_b64encode(derive_key(resolve_secret_key(settings), PURPOSE_JWT)).decode()


def encrypt(value: str, cipher: MultiFernet | None = None) -> bytes:
    """Cifra `value` con la llave actual."""
    return (cipher or get_cipher()).encrypt(value.encode())


def decrypt(token: bytes, cipher: MultiFernet | None = None) -> str:
    """Descifra con la llave actual o la anterior. Lanza `SecretKeyError` si ninguna sirve."""
    try:
        return (cipher or get_cipher()).decrypt(token).decode()
    except InvalidToken as exc:
        raise SecretKeyError(
            "No se pudo descifrar: revisa CHATIAPP_SECRET_KEY y CHATIAPP_SECRET_KEY_PREVIOUS"
        ) from exc


def mask(value: str) -> str:
    """Deja visibles el prefijo (hasta el último `-` de los primeros 8) y los últimos 4.

    `sk-abc123xyz3xyz` → `sk-...3xyz`. Los valores cortos se enmascaran por completo.
    """
    if len(value) < _MIN_MASKABLE:
        return _MASK_CHAR * max(len(value), 3)
    head = value[:8]
    dash = head.rfind("-")
    prefix = head[: dash + 1] if dash >= 0 else head[:3]
    return f"{prefix}...{value[-_VISIBLE_TAIL:]}"
