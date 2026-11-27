"""Arranque de la demo «Ventas»: crea la fuente y publica la versión 1 del modelo.

Uso (lo invoca `docker-entrypoint.sh` después de crear `ventas.db`):

    python -m app.demo.bootstrap

Es idempotente y solo actúa la primera vez: no hace nada si `CHATIAPP_DEMO` la desactiva
(`0`, `false`, `no` u `off`), si falta la base de la demo, o si ya existe alguna fuente.
"""

import os
from pathlib import Path

import yaml
from cryptography.fernet import MultiFernet
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Datasource
from app.db.session import get_engine
from app.security.crypto import encrypt, get_cipher
from app.semantic import store
from app.semantic.schema import parse_semantic_model

DEMO_NAME = "Ventas (demo)"
_OFF = {"0", "false", "no", "off"}


def demo_enabled() -> bool:
    return os.environ.get("CHATIAPP_DEMO", "true").strip().lower() not in _OFF


def demo_db_path() -> Path:
    data_dir = os.environ.get("CHATIAPP_DATA_DIR") or "/data"
    return Path(data_dir) / "demo" / "ventas.db"


def _model_file() -> Path:
    # En la imagen: /app/examples; en el repositorio: <raíz>/examples.
    here = Path(__file__).resolve()
    for root in (here.parents[2], here.parents[3]):
        candidate = root / "examples" / "ventas" / "semantic-model.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("No se encontró examples/ventas/semantic-model.yaml")


def bootstrap_demo(session: Session, cipher: MultiFernet, db_path: Path | None = None) -> bool:
    """Crea la fuente de la demo y su modelo 1. Devuelve `True` si creó algo."""
    if not demo_enabled():
        return False
    path = db_path or demo_db_path()
    if not path.is_file():
        return False
    if session.scalar(select(Datasource.id).limit(1)) is not None:
        return False
    model = parse_semantic_model(yaml.safe_load(_model_file().read_text(encoding="utf-8")))
    datasource = Datasource(
        name=DEMO_NAME,
        dialect="sqlite",
        url_encrypted=encrypt(f"sqlite:///{path}", cipher),
        execute=True,
        privacy="aggregates",
        managed_by="ui",
    )
    session.add(datasource)
    session.commit()
    store.publish(session, datasource.id, model, base_version=0)
    return True


def main() -> int:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        created = bootstrap_demo(session, get_cipher())
    if created:
        print(f"chatiapp: fuente «{DEMO_NAME}» creada con el modelo semántico v1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
