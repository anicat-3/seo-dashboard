"""Адрес проекта (slug) и название проекта в журнале изменений.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _slugify(domain: str) -> str:
    """Копия правила из app.services.projects на момент миграции."""
    slug = re.sub(r"[^\w]+", "-", domain.strip().lower().replace("_", "-")).strip("-") or "project"
    return f"site-{slug}" if slug.isdigit() else slug


def upgrade() -> None:
    op.add_column("projects", sa.Column("slug", sa.String(255), nullable=True))
    conn = op.get_bind()
    taken: set[str] = set()
    for project_id, domain in conn.execute(sa.text("SELECT id, domain FROM projects ORDER BY id")):
        base = _slugify(domain)
        slug, number = base, 1
        while slug in taken:
            number += 1
            slug = f"{base}-{number}"
        taken.add(slug)
        conn.execute(sa.text("UPDATE projects SET slug = :slug WHERE id = :id"),
                     {"slug": slug, "id": project_id})
    op.alter_column("projects", "slug", nullable=False)
    op.create_unique_constraint(op.f("uq_projects_slug"), "projects", ["slug"])

    op.add_column("audit_log", sa.Column("project_name", sa.String(200), nullable=True))
    # Заполнить название проекта для уже накопленных записей журнала.
    op.execute("""
        UPDATE audit_log a SET project_name = p.name
        FROM projects p
        WHERE a.entity = 'project' AND a.entity_id = p.id::text
    """)
    op.execute("""
        UPDATE audit_log a SET project_name = p.name
        FROM integrations i JOIN projects p ON p.id = i.project_id
        WHERE a.entity = 'integration' AND a.entity_id = i.id::text
    """)
    op.execute("""
        UPDATE audit_log a SET project_name = p.name
        FROM annotations n JOIN projects p ON p.id = n.project_id
        WHERE a.entity = 'annotation' AND a.entity_id = n.id::text
    """)
    op.execute("""
        UPDATE audit_log a SET project_name = p.name
        FROM monitored_urls u JOIN projects p ON p.id = u.project_id
        WHERE a.entity = 'monitored_url' AND a.entity_id = u.id::text
    """)
    op.execute("""
        UPDATE audit_log a SET project_name = p.name
        FROM signal_rules r JOIN projects p ON p.id = r.project_id
        WHERE a.entity = 'signal_rule' AND a.entity_id = r.id::text
    """)


def downgrade() -> None:
    op.drop_column("audit_log", "project_name")
    op.drop_constraint(op.f("uq_projects_slug"), "projects", type_="unique")
    op.drop_column("projects", "slug")
