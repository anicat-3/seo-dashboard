"""Обращения без адреса страницы.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("feedback", "page")


def downgrade() -> None:
    op.add_column("feedback", sa.Column("page", sa.String(300), nullable=True))
