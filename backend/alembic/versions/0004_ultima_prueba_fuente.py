"""Último resultado de la prueba de conexión en datasource

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
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
    with op.batch_alter_table("datasource") as batch:
        batch.drop_column("last_test_error_kind")
        batch.drop_column("last_test_at")
        batch.drop_column("last_test_ok")
