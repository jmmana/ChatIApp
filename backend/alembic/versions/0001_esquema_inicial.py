"""Esquema inicial de la base de datos de la app

Revision ID: 0001
Revises:
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user")),
        sa.UniqueConstraint("email", name=op.f("uq_user_email")),
    )
    op.create_table(
        "datasource",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("dialect", sa.String(length=50), nullable=False),
        sa.Column("url_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("execute", sa.Boolean(), nullable=False),
        sa.Column("max_rows", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("privacy", sa.String(length=20), nullable=False),
        sa.Column("managed_by", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasource")),
        sa.UniqueConstraint("name", name=op.f("uq_datasource_name")),
    )
    op.create_table(
        "provider",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("secrets_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("managed_by", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider")),
        sa.UniqueConstraint("name", name=op.f("uq_provider_name")),
    )
    op.create_table(
        "grant",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("datasource_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["datasource_id"],
            ["datasource.id"],
            name=op.f("fk_grant_datasource_id_datasource"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_grant_user_id_user"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "datasource_id", name=op.f("pk_grant")),
    )
    op.create_table(
        "semantic_model_version",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("datasource_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("model", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
            name=op.f("fk_semantic_model_version_created_by_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["datasource_id"],
            ["datasource.id"],
            name=op.f("fk_semantic_model_version_datasource_id_datasource"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_semantic_model_version")),
        sa.UniqueConstraint(
            "datasource_id", "version", name=op.f("uq_semantic_model_version_datasource_id")
        ),
    )
    op.create_index(
        op.f("ix_semantic_model_version_datasource_id"),
        "semantic_model_version",
        ["datasource_id"],
    )
    op.create_table(
        "conversation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("external_user_id", sa.String(length=255), nullable=True),
        sa.Column("datasource_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("last_plan", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["datasource_id"],
            ["datasource.id"],
            name=op.f("fk_conversation_datasource_id_datasource"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_conversation_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation")),
    )
    op.create_index(op.f("ix_conversation_user_id"), "conversation", ["user_id"])
    op.create_index(op.f("ix_conversation_datasource_id"), "conversation", ["datasource_id"])
    op.create_table(
        "message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_message_conversation_id_conversation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message")),
    )
    op.create_index(op.f("ix_message_conversation_id"), "message", ["conversation_id"])
    op.create_table(
        "query_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=True),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("sql_final", sa.Text(), nullable=True),
        sa.Column("summary_table", sa.String(length=255), nullable=True),
        sa.Column("filters_applied", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["message.id"],
            name=op.f("fk_query_run_message_id_message"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["provider.id"],
            name=op.f("fk_query_run_provider_id_provider"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_run")),
        sa.UniqueConstraint("message_id", name=op.f("uq_query_run_message_id")),
    )
    op.create_index(op.f("ix_query_run_provider_id"), "query_run", ["provider_id"])
    op.create_table(
        "eval_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("eval_set", sa.String(length=255), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("p50_latency_ms", sa.Float(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["provider.id"],
            name=op.f("fk_eval_run_provider_id_provider"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_run")),
    )
    op.create_index(op.f("ix_eval_run_provider_id"), "eval_run", ["provider_id"])


def downgrade() -> None:
    op.drop_table("eval_run")
    op.drop_table("query_run")
    op.drop_table("message")
    op.drop_table("conversation")
    op.drop_table("semantic_model_version")
    op.drop_table("grant")
    op.drop_table("provider")
    op.drop_table("datasource")
    op.drop_table("user")
