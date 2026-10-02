"""Избранные проекты сотрудников.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "favorite_projects",
        sa.Column("owner", sa.String(32), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.PrimaryKeyConstraint("owner", "project_id", name=op.f("pk_favorite_projects")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE",
                                name=op.f("fk_favorite_projects_project_id_projects")),
    )


def downgrade() -> None:
    op.drop_table("favorite_projects")
