"""remove dingtalk fetch user details flag

Revision ID: 20260428_0004
Revises: 20260428_0003
Create Date: 2026-05-14 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0004"
down_revision = "20260428_0003"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    columns = sa.inspect(bind).get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def upgrade() -> None:
    if not _has_column("dingtalk_apps", "fetch_user_details"):
        return
    with op.batch_alter_table("dingtalk_apps") as batch_op:
        batch_op.drop_column("fetch_user_details")


def downgrade() -> None:
    if _has_column("dingtalk_apps", "fetch_user_details"):
        return
    with op.batch_alter_table("dingtalk_apps") as batch_op:
        batch_op.add_column(sa.Column("fetch_user_details", sa.Boolean(), nullable=False, server_default=sa.true()))
