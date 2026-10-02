"""Начальная схема: конфигурация, журнал сбора, данные, подсветка изменений.

Revision ID: 0001
Revises:
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TSTZ = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def _pk(table: str, *cols: str) -> sa.PrimaryKeyConstraint:
    return sa.PrimaryKeyConstraint(*cols, name=op.f(f"pk_{table}"))


def _fk(table: str, col: str, ref_table: str, ref_col: str = "id",
        ondelete: str | None = None) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{ref_table}.{ref_col}"],
        name=op.f(f"fk_{table}_{col}_{ref_table}"), ondelete=ondelete,
    )


def _ck(table: str, name: str, sqltext: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sqltext, name=op.f(f"ck_{table}_{name}"))


def upgrade() -> None:
    # ---------------------------------------------------------------- конфигурация
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("login", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("password_changed_at", TSTZ, server_default=NOW, nullable=False),
        _pk("accounts", "id"),
        sa.UniqueConstraint("login", name=op.f("uq_accounts_login")),
        _ck("accounts", "role", "role IN ('admin', 'specialist')"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("created_by_name", sa.String(100), nullable=False),
        sa.Column("created_at", TSTZ, server_default=NOW, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("archived_at", TSTZ, nullable=True),
        _pk("projects", "id"),
    )
    op.create_table(
        "systems",
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("auth_type", sa.String(16), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        _pk("systems", "code"),
    )
    op.create_table(
        "credentials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("system_code", sa.String(32), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("account_login", sa.String(255), nullable=True),
        sa.Column("auth_type", sa.String(16), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("expires_at", TSTZ, nullable=True),
        sa.Column("last_checked_at", TSTZ, nullable=True),
        sa.Column("created_by_name", sa.String(100), nullable=True),
        sa.Column("created_at", TSTZ, server_default=NOW, nullable=False),
        _pk("credentials", "id"),
        _fk("credentials", "system_code", "systems", "code"),
        _ck("credentials", "auth_type", "auth_type IN ('oauth', 'api_key', 'demo')"),
        _ck("credentials", "status", "status IN ('ok', 'error', 'unchecked')"),
    )
    op.create_table(
        "integrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("system_code", sa.String(32), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("external_name", sa.String(255), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("collect_from", sa.Date(), nullable=True),
        sa.Column("disabled_at", TSTZ, nullable=True),
        sa.Column("created_by_name", sa.String(100), nullable=False),
        sa.Column("created_at", TSTZ, server_default=NOW, nullable=False),
        _pk("integrations", "id"),
        _fk("integrations", "project_id", "projects"),
        _fk("integrations", "system_code", "systems", "code"),
        _fk("integrations", "credential_id", "credentials"),
        sa.UniqueConstraint(
            "project_id", "system_code", "external_id",
            name=op.f("uq_integrations_project_id_system_code_external_id"),
        ),
        _ck("integrations", "status", "status IN ('ok', 'error', 'pending')"),
    )
    op.create_index(op.f("ix_integrations_project_id"), "integrations", ["project_id"])
    op.create_table(
        "integration_goals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("external_goal_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        _pk("integration_goals", "id"),
        _fk("integration_goals", "integration_id", "integrations", ondelete="CASCADE"),
        sa.UniqueConstraint(
            "integration_id", "external_goal_id",
            name=op.f("uq_integration_goals_integration_id_external_goal_id"),
        ),
    )
    op.create_table(
        "monitored_urls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("template_name", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _pk("monitored_urls", "id"),
        _fk("monitored_urls", "project_id", "projects"),
        sa.UniqueConstraint("project_id", "url", name=op.f("uq_monitored_urls_project_id_url")),
    )
    op.create_index(op.f("ix_monitored_urls_project_id"), "monitored_urls", ["project_id"])

    # --------------------------------------------------------------- журнал сбора
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(16), nullable=False),
        sa.Column("started_at", TSTZ, server_default=NOW, nullable=False),
        sa.Column("finished_at", TSTZ, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_by_name", sa.String(100), nullable=True),
        _pk("sync_runs", "id"),
        _fk("sync_runs", "integration_id", "integrations"),
        _ck("sync_runs", "status", "status IN ('running', 'success', 'partial', 'error')"),
        _ck("sync_runs", "job_type", "job_type IN ('daily', 'backfill', 'manual', 'period')"),
    )
    op.create_index(
        "ix_sync_runs_integration_started", "sync_runs", ["integration_id", "started_at"]
    )
    op.create_table(
        "raw_responses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("request_params", postgresql.JSONB(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=True),
        sa.Column("fetched_at", TSTZ, server_default=NOW, nullable=False),
        _pk("raw_responses", "id"),
        _fk("raw_responses", "sync_run_id", "sync_runs", ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_raw_responses_sync_run_id"), "raw_responses", ["sync_run_id"])
    op.create_index(op.f("ix_raw_responses_fetched_at"), "raw_responses", ["fetched_at"])

    # ---------------------------------------------------------- временные ряды
    op.create_table(
        "metric_catalog",
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("system_code", sa.String(32), nullable=False),
        sa.Column("name_ru", sa.String(200), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("aggregation", sa.String(16), nullable=False),
        sa.Column("weight_metric_code", sa.String(64), nullable=True),
        sa.Column("higher_is_better", sa.Boolean(), nullable=False),
        _pk("metric_catalog", "code"),
        _fk("metric_catalog", "system_code", "systems", "code"),
        _ck(
            "metric_catalog", "aggregation",
            "aggregation IN ('sum', 'weighted_avg', 'last', 'period_only')",
        ),
    )
    op.create_table(
        "daily_metrics",
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("metric_code", sa.String(64), nullable=False),
        sa.Column("segment", sa.String(128), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        _pk("daily_metrics", "integration_id", "date", "metric_code", "segment"),
        _fk("daily_metrics", "integration_id", "integrations"),
    )
    op.create_index("ix_daily_metrics_metric_date", "daily_metrics", ["metric_code", "date"])
    op.create_table(
        "period_metrics",
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(64), nullable=False),
        sa.Column("segment", sa.String(128), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("fetched_at", TSTZ, server_default=NOW, nullable=False),
        _pk("period_metrics", "integration_id", "metric_code", "segment", "date_from", "date_to"),
        _fk("period_metrics", "integration_id", "integrations"),
    )

    # ----------------------------------------------------------- снимки состояния
    op.create_table(
        "sitemap_snapshots",
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("sitemap_url", sa.Text(), nullable=False),
        sa.Column("is_index", sa.Boolean(), nullable=False),
        sa.Column("submitted_urls", sa.Integer(), nullable=True),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("warnings", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("raw_status", sa.String(100), nullable=True),
        sa.Column("last_downloaded_at", TSTZ, nullable=True),
        _pk("sitemap_snapshots", "integration_id", "snapshot_date", "sitemap_url"),
        _fk("sitemap_snapshots", "integration_id", "integrations"),
        _ck("sitemap_snapshots", "status", "status IN ('ok', 'pending', 'warning', 'error')"),
    )
    op.create_table(
        "site_issues",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("issue_code", sa.String(128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("first_seen_at", TSTZ, nullable=False),
        sa.Column("last_seen_at", TSTZ, nullable=False),
        sa.Column("resolved_at", TSTZ, nullable=True),
        sa.Column("affected_count", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        _pk("site_issues", "id"),
        _fk("site_issues", "integration_id", "integrations"),
        _ck("site_issues", "state", "state IN ('open', 'resolved')"),
    )
    op.create_index(op.f("ix_site_issues_integration_id"), "site_issues", ["integration_id"])
    op.create_index(
        "uq_site_issues_open", "site_issues", ["integration_id", "issue_code"],
        unique=True, postgresql_where=sa.text("state = 'open'"),
    )
    op.create_table(
        "cwv_weekly",
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("scope", sa.String(8), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("device", sa.String(16), nullable=False),
        sa.Column("metric", sa.String(8), nullable=False),
        sa.Column("p75", sa.Float(), nullable=True),
        sa.Column("good_pct", sa.Float(), nullable=True),
        sa.Column("ni_pct", sa.Float(), nullable=True),
        sa.Column("poor_pct", sa.Float(), nullable=True),
        _pk("cwv_weekly", "integration_id", "period_end", "scope", "url", "device", "metric"),
        _fk("cwv_weekly", "integration_id", "integrations"),
        _ck("cwv_weekly", "scope", "scope IN ('origin', 'url')"),
        _ck("cwv_weekly", "metric", "metric IN ('lcp', 'inp', 'cls', 'fcp', 'ttfb')"),
    )
    op.create_table(
        "psi_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("monitored_url_id", sa.Integer(), nullable=False),
        sa.Column("run_at", TSTZ, nullable=False),
        sa.Column("device", sa.String(16), nullable=False),
        sa.Column("performance_score", sa.Float(), nullable=True),
        sa.Column("field_lcp", sa.Float(), nullable=True),
        sa.Column("field_inp", sa.Float(), nullable=True),
        sa.Column("field_cls", sa.Float(), nullable=True),
        sa.Column("field_fcp", sa.Float(), nullable=True),
        sa.Column("field_ttfb", sa.Float(), nullable=True),
        sa.Column("field_category", sa.String(32), nullable=True),
        sa.Column("is_origin_fallback", sa.Boolean(), nullable=False),
        _pk("psi_runs", "id"),
        _fk("psi_runs", "monitored_url_id", "monitored_urls"),
        _ck("psi_runs", "device", "device IN ('mobile', 'desktop')"),
    )
    op.create_index("ix_psi_runs_url_run_at", "psi_runs", ["monitored_url_id", "run_at"])

    # ------------------------------------------------------------------ позиции
    op.create_table(
        "keywords",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("external_keyword_id", sa.String(64), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("search_engine", sa.String(32), nullable=False),
        sa.Column("region", sa.String(128), nullable=False),
        sa.Column("device", sa.String(16), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _pk("keywords", "id"),
        _fk("keywords", "integration_id", "integrations"),
        sa.UniqueConstraint(
            "integration_id", "external_keyword_id", "search_engine", "region", "device",
            name="uq_keywords_natural_key",
        ),
    )
    op.create_index(op.f("ix_keywords_integration_id"), "keywords", ["integration_id"])
    # Секционированная таблица: первичный ключ (keyword_id, check_date) служит и индексом.
    op.create_table(
        "keyword_positions",
        sa.Column("keyword_id", sa.BigInteger(), nullable=False),
        sa.Column("check_date", sa.Date(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        _pk("keyword_positions", "keyword_id", "check_date"),
        _fk("keyword_positions", "keyword_id", "keywords", ondelete="CASCADE"),
        postgresql_partition_by="RANGE (check_date)",
    )
    op.execute(
        """
        CREATE FUNCTION ensure_keyword_positions_partition(d date) RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            start_date date := date_trunc('month', d)::date;
            end_date   date := (date_trunc('month', d) + interval '1 month')::date;
            part_name  text := format('keyword_positions_y%sm%s',
                                      to_char(start_date, 'YYYY'), to_char(start_date, 'MM'));
        BEGIN
            IF to_regclass(part_name) IS NULL THEN
                EXECUTE format(
                    'CREATE TABLE %I PARTITION OF keyword_positions FOR VALUES FROM (%L) TO (%L)',
                    part_name, start_date, end_date);
            END IF;
        END;
        $$;
        """
    )

    # --------------------------------------------- подсветка изменений и пометки
    op.create_table(
        "signal_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("metric_code", sa.String(64), nullable=False),
        sa.Column("segment", sa.String(128), nullable=False),
        sa.Column("comparison", sa.String(8), nullable=False),
        sa.Column("threshold_pct", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _pk("signal_rules", "id"),
        _fk("signal_rules", "project_id", "projects"),
        _fk("signal_rules", "metric_code", "metric_catalog", "code"),
        _ck("signal_rules", "comparison", "comparison IN ('wow', 'mom')"),
    )
    op.create_index(op.f("ix_signal_rules_project_id"), "signal_rules", ["project_id"])
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(64), nullable=True),
        sa.Column("segment", sa.String(128), nullable=True),
        sa.Column("issue_id", sa.BigInteger(), nullable=True),
        sa.Column("detected_at", TSTZ, server_default=NOW, nullable=False),
        sa.Column("period_from", sa.Date(), nullable=True),
        sa.Column("period_to", sa.Date(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("baseline", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("seen_by_name", sa.String(100), nullable=True),
        sa.Column("resolved_at", TSTZ, nullable=True),
        _pk("signals", "id"),
        _fk("signals", "rule_id", "signal_rules", ondelete="SET NULL"),
        _fk("signals", "integration_id", "integrations"),
        _fk("signals", "issue_id", "site_issues"),
        _ck("signals", "status", "status IN ('new', 'seen')"),
        _ck("signals", "kind", "kind IN ('metric', 'issue')"),
    )
    op.create_index("ix_signals_open", "signals", ["integration_id", "resolved_at"])
    op.create_table(
        "annotations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("author_name", sa.String(100), nullable=False),
        sa.Column("created_at", TSTZ, server_default=NOW, nullable=False),
        _pk("annotations", "id"),
        _fk("annotations", "project_id", "projects"),
    )
    op.create_index(op.f("ix_annotations_project_id"), "annotations", ["project_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(100), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", TSTZ, server_default=NOW, nullable=False),
        _pk("audit_log", "id"),
        _fk("audit_log", "account_id", "accounts"),
    )
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])


def downgrade() -> None:
    for table in (
        "audit_log", "annotations", "signals", "signal_rules", "keyword_positions",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS ensure_keyword_positions_partition(date)")
    for table in (
        "keywords", "psi_runs", "cwv_weekly", "site_issues", "sitemap_snapshots",
        "period_metrics", "daily_metrics", "metric_catalog", "raw_responses", "sync_runs",
        "monitored_urls", "integration_goals", "integrations", "credentials", "systems",
        "projects", "accounts",
    ):
        op.drop_table(table)
