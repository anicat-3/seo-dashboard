"""Обращения команды; допустимые типы доступа — ``oauth`` и ``api_key``.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("author_name", sa.String(100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("page", sa.String(300), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_name", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"],
                                name=op.f("fk_feedback_account_id_accounts")),
        sa.CheckConstraint(
            "status IN ('new', 'closed', 'rejected', 'paused', 'postponed')",
            name=op.f("ck_feedback_status")),
    )
    op.create_index(op.f("ix_feedback_status"), "feedback", ["status"])
    op.create_index(op.f("ix_feedback_created_at"), "feedback", ["created_at"])

    op.drop_constraint(op.f("ck_credentials_auth_type"), "credentials", type_="check")
    op.create_check_constraint("auth_type", "credentials",
                               "auth_type IN ('oauth', 'api_key')")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_credentials_auth_type"), "credentials", type_="check")
    op.create_check_constraint("auth_type", "credentials",
                               "auth_type IN ('oauth', 'api_key', 'demo')")
    op.drop_table("feedback")
