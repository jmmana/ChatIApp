"""Auditoría de cada turno: columnas nuevas en query_run

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
    op.add_column("query_run", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("query_run", sa.Column("external_user_id", sa.String(length=255), nullable=True))
    op.add_column("query_run", sa.Column("datasource_id", sa.Uuid(), nullable=True))
    op.add_column("query_run", sa.Column("role", sa.String(length=100), nullable=True))
    op.add_column("query_run", sa.Column("question", sa.Text(), nullable=True))
    op.add_column("query_run", sa.Column("plan", sa.JSON(), nullable=True))
    op.add_column("query_run", sa.Column("sql_candidate", sa.Text(), nullable=True))
    op.add_column("query_run", sa.Column("provider_kind", sa.String(length=50), nullable=True))
    op.add_column("query_run", sa.Column("model", sa.String(length=255), nullable=True))
    op.add_column("query_run", sa.Column("semantic_version", sa.Integer(), nullable=True))
    op.add_column("query_run", sa.Column("error_code", sa.String(length=50), nullable=True))
    op.create_index(op.f("ix_query_run_user_id"), "query_run", ["user_id"])
    op.create_index(op.f("ix_query_run_datasource_id"), "query_run", ["datasource_id"])
    op.create_index(op.f("ix_query_run_api_key_id"), "query_run", ["api_key_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_query_run_api_key_id"), table_name="query_run")
    op.drop_index(op.f("ix_query_run_datasource_id"), table_name="query_run")
    op.drop_index(op.f("ix_query_run_user_id"), table_name="query_run")
    with op.batch_alter_table("query_run") as batch:
        for column in (
            "error_code",
            "semantic_version",
            "model",
            "provider_kind",
            "sql_candidate",
            "plan",
            "question",
            "role",
            "datasource_id",
            "external_user_id",
            "user_id",
        ):
            batch.drop_column(column)
