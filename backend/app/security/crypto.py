"""Cifrado de secretos en reposo con Fernet y rotación con MultiFernet."""

import base64
import hashlib

from cryptography.fernet import Fernet, MultiFernet


def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def make_cipher(secret_key: str, previous_key: str | None = None) -> MultiFernet:
    """Cifra con `secret_key`; descifra también con `previous_key` (rotación)."""
    keys = [_fernet(secret_key)]
    if previous_key:
        keys.append(_fernet(previous_key))
    return MultiFernet(keys)
