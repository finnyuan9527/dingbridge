"""add per-client PKCE requirement

Revision ID: 20260428_0003
Revises: 20260428_0002
Create Date: 2026-05-11 16:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0003"
down_revision = "20260428_0002"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    columns = sa.inspect(bind).get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def upgrade() -> None:
    if _has_column("oidc_clients", "require_pkce"):
        return
    op.add_column(
        "oidc_clients",
        sa.Column("require_pkce", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    if _has_column("oidc_clients", "require_pkce"):
        op.drop_column("oidc_clients", "require_pkce")
