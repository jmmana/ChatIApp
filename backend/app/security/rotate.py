"""Vuelve a cifrar todos los secretos con la llave actual.

Uso: `uv run python -m app.security.rotate` con `CHATIAPP_SECRET_KEY` (nueva) y
`CHATIAPP_SECRET_KEY_PREVIOUS` (anterior) definidas.
"""

from cryptography.fernet import MultiFernet
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Datasource, Provider
from app.db.session import get_engine
from app.security.crypto import SecretKeyError, get_cipher, resolve_secret_key


def rotate_secrets(session: Session, cipher: MultiFernet) -> int:
    """Re-cifra fuentes y proveedores; devuelve cuántos valores se re-cifraron."""
    count = 0
    for datasource in session.scalars(select(Datasource)):
        datasource.url_encrypted = cipher.rotate(datasource.url_encrypted)
        count += 1
    for provider in session.scalars(select(Provider)):
        if provider.secrets_encrypted is not None:
            provider.secrets_encrypted = cipher.rotate(provider.secrets_encrypted)
            count += 1
    session.commit()
    return count


def main() -> int:
    try:
        resolve_secret_key()
    except SecretKeyError as exc:
        print(f"Error: {exc}")
        return 1
    with sessionmaker(bind=get_engine(), expire_on_commit=False)() as session:
        try:
            count = rotate_secrets(session, get_cipher())
        except Exception as exc:  # token que ninguna llave descifra
            session.rollback()
            print(f"Error: no se pudo rotar ({type(exc).__name__}). Revisa las llaves.")
            return 1
    print(f"Secretos re-cifrados: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
