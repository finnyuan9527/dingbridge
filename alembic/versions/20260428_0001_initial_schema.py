"""initial schema

Revision ID: 20260428_0001
Revises:
Create Date: 2026-04-28 11:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0001"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def upgrade() -> None:
    if not _has_table("idp_settings"):
        op.create_table(
            "idp_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("oidc_issuer", sa.String(length=500), nullable=False),
            sa.Column("oidc_id_token_exp_minutes", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("dingtalk_apps"):
        op.create_table(
            "dingtalk_apps",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("app_key", sa.String(length=200), nullable=False),
            sa.Column("app_secret", sa.Text(), nullable=False),
            sa.Column("callback_url", sa.String(length=500), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("oidc_clients"):
        op.create_table(
            "oidc_clients",
            sa.Column("client_id", sa.String(length=200), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("client_secret", sa.Text(), nullable=False),
            sa.Column("redirect_uris", sa.JSON(), nullable=False),
            sa.Column("dingtalk_app_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["dingtalk_app_id"], ["dingtalk_apps.id"]),
            sa.PrimaryKeyConstraint("client_id"),
        )


def downgrade() -> None:
    op.drop_table("oidc_clients")
    op.drop_table("dingtalk_apps")
    op.drop_table("idp_settings")
