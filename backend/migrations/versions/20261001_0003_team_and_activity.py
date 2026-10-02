"""Состав команды и журнал действий сотрудников.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TSTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("full_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", TSTZ, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_members")),
        sa.UniqueConstraint("full_name", name=op.f("uq_team_members_full_name")),
    )
    op.create_table(
        "activity_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(100), nullable=False),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("page", sa.String(200), nullable=True),
        sa.Column("project_name", sa.String(200), nullable=True),
        sa.Column("created_at", TSTZ, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_log")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"],
                                name=op.f("fk_activity_log_account_id_accounts")),
        sa.ForeignKeyConstraint(["member_id"], ["team_members.id"], ondelete="SET NULL",
                                name=op.f("fk_activity_log_member_id_team_members")),
        sa.CheckConstraint("event IN ('login', 'logout', 'view')",
                           name=op.f("ck_activity_log_event")),
    )
    op.create_index(op.f("ix_activity_log_created_at"), "activity_log", ["created_at"])
    op.create_index("ix_activity_log_member_created", "activity_log",
                    ["member_id", "created_at"])


def downgrade() -> None:
    op.drop_table("activity_log")
    op.drop_table("team_members")
