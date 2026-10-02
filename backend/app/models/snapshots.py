"""Снимки состояния: карты сайта, ошибки диагностики, Core Web Vitals, прогоны PSI.

Снимки задним числом не восстанавливаются: если сбор за день не прошёл,
в истории остаётся пробел.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SitemapSnapshot(Base):
    """Состояние одной карты сайта (GSC, Вебмастер, Bing) на дату."""

    __tablename__ = "sitemap_snapshots"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'pending', 'warning', 'error')", name="status"),
    )

    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrations.id"), primary_key=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    sitemap_url: Mapped[str] = mapped_column(Text, primary_key=True)
    is_index: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_urls: Mapped[int | None] = mapped_column(Integer)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))
    raw_status: Mapped[str | None] = mapped_column(String(100))
    last_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SiteIssue(Base):
    """Жизненный цикл ошибки диагностики Вебмастера: когда появилась и когда исчезла."""

    __tablename__ = "site_issues"
    __table_args__ = (
        CheckConstraint("state IN ('open', 'resolved')", name="state"),
        # Одна открытая запись на код проблемы в подключении.
        Index(
            "uq_site_issues_open",
            "integration_id",
            "issue_code",
            unique=True,
            postgresql_where=text("state = 'open'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"), index=True)
    issue_code: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), default="open")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    affected_count: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class CwvWeekly(Base):
    """Недельная точка Core Web Vitals из CrUX History API.

    Для ``scope = 'origin'`` поле ``url`` — пустая строка (участвует в первичном ключе).
    """

    __tablename__ = "cwv_weekly"
    __table_args__ = (
        CheckConstraint("scope IN ('origin', 'url')", name="scope"),
        CheckConstraint("metric IN ('lcp', 'inp', 'cls', 'fcp', 'ttfb')", name="metric"),
    )

    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrations.id"), primary_key=True
    )
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    scope: Mapped[str] = mapped_column(String(8), primary_key=True)
    url: Mapped[str] = mapped_column(Text, primary_key=True, default="")
    device: Mapped[str] = mapped_column(String(16), primary_key=True)
    metric: Mapped[str] = mapped_column(String(8), primary_key=True)
    p75: Mapped[float | None] = mapped_column(Float)
    good_pct: Mapped[float | None] = mapped_column(Float)
    ni_pct: Mapped[float | None] = mapped_column(Float)
    poor_pct: Mapped[float | None] = mapped_column(Float)


class PsiRun(Base):
    """Результат проверки URL в PageSpeed Insights (медиана из нескольких прогонов)."""

    __tablename__ = "psi_runs"
    __table_args__ = (
        CheckConstraint("device IN ('mobile', 'desktop')", name="device"),
        Index("ix_psi_runs_url_run_at", "monitored_url_id", "run_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    monitored_url_id: Mapped[int] = mapped_column(ForeignKey("monitored_urls.id"))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    device: Mapped[str] = mapped_column(String(16))
    performance_score: Mapped[float | None] = mapped_column(Float)
    field_lcp: Mapped[float | None] = mapped_column(Float)
    field_inp: Mapped[float | None] = mapped_column(Float)
    field_cls: Mapped[float | None] = mapped_column(Float)
    field_fcp: Mapped[float | None] = mapped_column(Float)
    field_ttfb: Mapped[float | None] = mapped_column(Float)
    field_category: Mapped[str | None] = mapped_column(String(32))
    is_origin_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
