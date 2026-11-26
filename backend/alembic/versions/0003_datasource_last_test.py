"""Guarda el resultado de la última prueba de conexión

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("datasource", sa.Column("last_test_ok", sa.Boolean(), nullable=True))
    op.add_column(
        "datasource", sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "datasource", sa.Column("last_test_error_kind", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("datasource", "last_test_error_kind")
    op.drop_column("datasource", "last_test_at")
    op.drop_column("datasource", "last_test_ok")
