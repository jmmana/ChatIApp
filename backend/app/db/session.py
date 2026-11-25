"""Motor y sesión de la base de datos de la app."""

import os
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./chatiapp.db"


def get_database_url() -> str:
    return os.environ.get("CHATIAPP_DATABASE_URL") or DEFAULT_DATABASE_URL


def make_engine(url: str) -> Engine:
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine(get_database_url())


def get_session() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición."""
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        yield session
