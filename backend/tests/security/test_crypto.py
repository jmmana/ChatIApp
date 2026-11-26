import logging
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Base, Datasource, Provider
from app.db.session import make_engine
from app.security.crypto import (
    SecretKeyError,
    _ephemeral_key,
    decrypt,
    derive_key,
    encrypt,
    get_cipher,
    jwt_signing_key,
    make_cipher,
    mask,
    resolve_secret_key,
)
from app.security.rotate import rotate_secrets
from app.settings.env import Settings


def test_ida_y_vuelta() -> None:
    cipher = make_cipher("clave")
    token = encrypt("sk-secreto", cipher)
    assert b"sk-secreto" not in token
    assert decrypt(token, cipher) == "sk-secreto"


def test_llave_equivocada_falla_con_mensaje_claro() -> None:
    token = encrypt("x", make_cipher("a"))
    with pytest.raises(SecretKeyError, match="CHATIAPP_SECRET_KEY"):
        decrypt(token, make_cipher("b"))


def test_llave_anterior_descifra_datos_antiguos() -> None:
    old = encrypt("dato", make_cipher("vieja"))
    assert decrypt(old, make_cipher("nueva", "vieja")) == "dato"


def test_derivacion_distinta_por_uso() -> None:
    assert derive_key("s", "credentials") != derive_key("s", "jwt")
    assert derive_key("s", "jwt") == derive_key("s", "jwt")
    assert len(derive_key("s", "jwt")) == 32


def test_llave_jwt_no_es_la_llave_cruda() -> None:
    settings = Settings(secret_key=SecretStr("s"), env="test")
    assert jwt_signing_key(settings) != "s"


def test_get_cipher_usa_settings_y_previous() -> None:
    old = encrypt("dato", make_cipher("vieja"))
    settings = Settings(
        secret_key=SecretStr("nueva"), secret_key_previous=SecretStr("vieja"), env="test"
    )
    assert decrypt(old, get_cipher(settings)) == "dato"


def test_produccion_sin_llave_falla() -> None:
    settings = Settings.model_construct(secret_key=None, secret_key_previous=None, env="production")
    with pytest.raises(SecretKeyError, match="CHATIAPP_SECRET_KEY"):
        resolve_secret_key(settings)


def test_desarrollo_genera_llave_temporal_y_avisa(caplog: pytest.LogCaptureFixture) -> None:
    _ephemeral_key.cache_clear()
    settings = Settings(secret_key=None, env="development")
    with caplog.at_level(logging.WARNING):
        first = resolve_secret_key(settings)
    assert first and resolve_secret_key(settings) == first
    assert "llave temporal" in caplog.text


def test_mask_deja_prefijo_y_ultimos_cuatro() -> None:
    assert mask("sk-abcdefgh3xyz") == "sk-...3xyz"
    assert mask("sk-ant-api03-zzzz1234") == "sk-ant-...1234"
    assert "abcdefgh" not in mask("sk-abcdefgh3xyz")


def test_mask_valores_cortos_se_ocultan_por_completo() -> None:
    assert mask("corto") == "*****"
    assert mask("") == "***"


def test_rotacion_recifra_con_la_llave_actual(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    old_cipher = make_cipher("vieja")
    with Session(engine) as session:
        session.add(
            Datasource(name="d", dialect="sqlite", url_encrypted=encrypt("sqlite:///x", old_cipher))
        )
        session.add(
            Provider(
                name="p",
                kind="fake",
                model="m",
                secrets_encrypted=encrypt('{"api_key": "k"}', old_cipher),
            )
        )
        session.add(Provider(name="q", kind="fake", model="m"))
        session.commit()

        assert rotate_secrets(session, make_cipher("nueva", "vieja")) == 2

        only_new = make_cipher("nueva")
        datasource = session.scalars(select(Datasource)).one()
        assert decrypt(datasource.url_encrypted, only_new) == "sqlite:///x"
        provider = session.scalars(select(Provider).where(Provider.name == "p")).one()
        assert provider.secrets_encrypted is not None
        assert decrypt(provider.secrets_encrypted, only_new) == '{"api_key": "k"}'
