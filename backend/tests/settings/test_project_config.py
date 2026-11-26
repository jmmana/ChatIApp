import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.models import Base, Datasource, Provider
from app.db.session import make_engine
from app.security.crypto import make_cipher
from app.settings.env import Settings
from app.settings.project import ConfigError, load_project_config
from app.settings.registry import sync_config_to_db
from app.settings.startup import load_and_register

EXAMPLE = Path(__file__).parents[3] / "examples" / "chatiapp.example.yaml"
ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-prueba",
    "DEEPSEEK_API_KEY": "sk-ds-prueba",
    "BEDROCK_MODEL_ID": "anthropic.claude-prueba",
    "VENTAS_DB_URL": "postgresql+psycopg://ro:clave@localhost/ventas",
}

BASE_YAML = """
version: 1
ai:
  providers:
    - id: claude
      kind: anthropic
      model: m
      api_key: ${ANTHROPIC_API_KEY}
datasources:
  - id: ventas
    name: Ventas
    dialect: sqlite
    url: sqlite:///x.db
    semantic_model: ./modelo.yaml
"""


def _write(tmp_path: Path, text: str, with_model: bool = True) -> Path:
    if with_model:
        (tmp_path / "modelo.yaml").write_text("version: 1\n")
    path = tmp_path / "chatiapp.yaml"
    path.write_text(text)
    return path


def test_ejemplo_se_carga_y_valida() -> None:
    config = load_project_config(EXAMPLE, ENV)

    assert [p.id for p in config.ai.providers] == ["claude", "deepseek", "bedrock", "local"]
    assert config.ai.providers[0].api_key == "sk-ant-prueba"
    assert config.ai.providers[2].model == "anthropic.claude-prueba"
    assert config.datasources[0].url == ENV["VENTAS_DB_URL"]
    assert config.datasources[0].semantic_model.is_file()


def test_variable_faltante_nombra_variable_y_ruta(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE_YAML)

    with pytest.raises(ConfigError, match=r"ai\.providers\[0\]\.api_key.*ANTHROPIC_API_KEY"):
        load_project_config(path, {})


def test_clave_desconocida_da_ruta(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE_YAML.replace("kind: anthropic", "kind: anthropic\n      foo: 1"))

    with pytest.raises(ConfigError, match=r"ai\.providers\[0\]\.foo"):
        load_project_config(path, ENV)


def test_valor_fuera_de_rango_da_ruta(tmp_path: Path) -> None:
    text = BASE_YAML + "    max_rows: 0\n"
    path = _write(tmp_path, text)

    with pytest.raises(ConfigError, match=r"datasources\[0\]\.max_rows"):
        load_project_config(path, ENV)


def test_routing_con_proveedor_inexistente(tmp_path: Path) -> None:
    text = BASE_YAML.replace("datasources:", "  routing:\n    planner: nadie\ndatasources:")
    path = _write(tmp_path, text)

    with pytest.raises(ConfigError, match="nadie"):
        load_project_config(path, ENV)


def test_semantic_model_inexistente(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE_YAML, with_model=False)

    with pytest.raises(ConfigError, match=r"datasources\[0\]\.semantic_model"):
        load_project_config(path, ENV)


def test_semantic_model_es_relativo_al_archivo(tmp_path: Path) -> None:
    sub = tmp_path / "conf"
    sub.mkdir()
    (sub / "modelo.yaml").write_text("version: 1\n")
    path = sub / "chatiapp.yaml"
    path.write_text(BASE_YAML)

    config = load_project_config(path, ENV)

    assert config.datasources[0].semantic_model == (sub / "modelo.yaml").resolve()


def test_settings_lee_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_DATABASE_URL", "sqlite:///otra.db")
    monkeypatch.setenv("CHATIAPP_SECRET_KEY", "s1")
    monkeypatch.setenv("CHATIAPP_SECRET_KEY_PREVIOUS", "s0")
    monkeypatch.setenv("CHATIAPP_CONFIG", "/config/chatiapp.yaml")
    monkeypatch.setenv("CHATIAPP_ENV", "test")

    settings = Settings()

    assert settings.database_url == "sqlite:///otra.db"
    assert settings.secret_key is not None and settings.secret_key.get_secret_value() == "s1"
    assert settings.secret_key_previous is not None
    assert settings.secret_key_previous.get_secret_value() == "s0"
    assert settings.config == Path("/config/chatiapp.yaml")
    assert settings.env == "test"


@pytest.mark.parametrize("value", ["sk-ant-en-claro", "prefijo-${ANTHROPIC_API_KEY}", 123])
def test_secreto_en_claro_se_rechaza(tmp_path: Path, value: object) -> None:
    yaml_text = BASE_YAML.replace("${ANTHROPIC_API_KEY}", str(value))
    path = _write(tmp_path, yaml_text)

    with pytest.raises(ConfigError, match=r"ai\.providers\[0\]\.api_key.*\$\{VARIABLE\}"):
        load_project_config(path, {"ANTHROPIC_API_KEY": "sk-ant-prueba"})


def test_secret_key_vacia_cuenta_como_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_SECRET_KEY", "")
    monkeypatch.setenv("CHATIAPP_ENV", "production")

    with pytest.raises(ValidationError, match="CHATIAPP_SECRET_KEY"):
        Settings()


def test_produccion_exige_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHATIAPP_SECRET_KEY", raising=False)
    monkeypatch.setenv("CHATIAPP_ENV", "production")

    with pytest.raises(ValidationError, match="CHATIAPP_SECRET_KEY"):
        Settings()


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(eng)
    return eng


def test_registra_proveedores_y_fuentes_como_config(tmp_path: Path, engine: Engine) -> None:
    config = load_project_config(EXAMPLE, ENV)
    cipher = make_cipher("clave")

    with Session(engine) as session:
        sync_config_to_db(session, config, cipher)
        sync_config_to_db(session, config, cipher)  # idempotente

        providers = session.scalars(select(Provider)).all()
        datasources = session.scalars(select(Datasource)).all()

        assert {p.name for p in providers} == {"claude", "deepseek", "bedrock", "local"}
        assert all(p.managed_by == "config" for p in providers)
        claude = next(p for p in providers if p.name == "claude")
        assert claude.secrets_encrypted is not None
        assert b"sk-ant-prueba" not in claude.secrets_encrypted
        decrypted = json.loads(cipher.decrypt(claude.secrets_encrypted))
        assert decrypted == {"api_key": "sk-ant-prueba"}
        local = next(p for p in providers if p.name == "local")
        assert local.secrets_encrypted is None
        assert local.config == {"api_base": "http://ollama:11434"}

        assert len(datasources) == 1
        assert datasources[0].managed_by == "config"
        assert datasources[0].privacy == "aggregates"
        assert cipher.decrypt(datasources[0].url_encrypted).decode() == ENV["VENTAS_DB_URL"]


def test_arranque_con_archivo_invalido_falla(tmp_path: Path) -> None:
    path = _write(tmp_path, "version: 2\n")
    settings = Settings(config=path)

    with pytest.raises(ConfigError, match="version"):
        load_and_register(settings)
