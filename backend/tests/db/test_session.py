from pathlib import Path

from sqlalchemy import text

from app.db.session import make_engine


def test_sqlite_usa_wal_y_claves_foraneas(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
    finally:
        engine.dispose()
