"""Подсветка изменений, пометки на графиках и журнал изменений настроек."""

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
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

#: Базы сравнения для правил: неделя к неделе и 30 дней к 30 дням.
COMPARISON_WOW = "wow"
COMPARISON_MOM = "mom"


class SignalRule(Base):
    """Правило резкого изменения метрики.

    ``project_id = NULL`` — правило для всех проектов; правило проекта с теми же
    ``metric_code`` и ``segment`` его переопределяет. Направление «хуже» берётся
    из ``metric_catalog.higher_is_better``.
    """

    __tablename__ = "signal_rules"
    __table_args__ = (CheckConstraint("comparison IN ('wow', 'mom')", name="comparison"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    metric_code: Mapped[str] = mapped_column(ForeignKey("metric_catalog.code"))
    segment: Mapped[str] = mapped_column(String(128), default="all")
    comparison: Mapped[str] = mapped_column(String(8), default=COMPARISON_WOW)
    threshold_pct: Mapped[float] = mapped_column(Float, default=10.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Signal(Base):
    """Найденное резкое изменение или новая ошибка; показывается только в приложении.

    Сигнал «открыт», пока ``resolved_at IS NULL``: повторная проверка не создаёт
    дубль, а обновляет значение существующего сигнала.
    """

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint("status IN ('new', 'seen')", name="status"),
        CheckConstraint("kind IN ('metric', 'issue')", name="kind"),
        Index("ix_signals_open", "integration_id", "resolved_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), default="metric")
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("signal_rules.id", ondelete="SET NULL"))
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"))
    metric_code: Mapped[str | None] = mapped_column(String(64))
    segment: Mapped[str | None] = mapped_column(String(128))
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("site_issues.id"))
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    value: Mapped[float | None] = mapped_column(Float)
    baseline: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(8), default="new")
    seen_by_name: Mapped[str | None] = mapped_column(String(100))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Annotation(Base):
    """Пометка на графиках проекта: релиз, апдейт поисковика и т. п."""

    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)
    author_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Кто и что менял в настройках. ``actor_name`` — имя сотрудника из сессии."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    actor_name: Mapped[str] = mapped_column(String(100))
    #: Название проекта на момент действия (сохраняется и после удаления проекта).
    project_name: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
