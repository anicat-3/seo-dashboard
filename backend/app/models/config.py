"""Таблицы конфигурации: учётные записи, проекты, системы, доступы, подключения."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Account(Base):
    """Учётная запись приложения.

    Их ровно две (``admin`` и ``specialist``), создаются скриптом установки.
    Смена ``password_changed_at`` завершает все активные сессии этой записи.
    """

    __tablename__ = "accounts"
    __table_args__ = (CheckConstraint("role IN ('admin', 'specialist')", name="role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Project(Base):
    """Проект — сайт, для которого собираются данные."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(255))
    #: Адрес проекта в URL, строится из домена: ``auto-parts.kz`` → ``auto-parts-kz``.
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    created_by_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    integrations: Mapped[list[Integration]] = relationship(back_populates="project")


class System(Base):
    """Справочник внешних систем (gsc, ga4, metrika, ywm, bing, topvisor, seranking, psi, crux)."""

    __tablename__ = "systems"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    auth_type: Mapped[str] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(default=0)


class Credential(Base):
    """Доступ к одному аккаунту внешней системы.

    ``auth_type``:
        * ``oauth`` — Google/Яндекс, в секрете хранится refresh-токен;
        * ``api_key`` — Bing, Topvisor, SE Ranking, PSI/CrUX.

    Секрет (словарь) хранится в ``secret_encrypted``, зашифрованным ключом из окружения.
    """

    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint("auth_type IN ('oauth', 'api_key')", name="auth_type"),
        CheckConstraint("status IN ('ok', 'error', 'unchecked')", name="status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    system_code: Mapped[str] = mapped_column(ForeignKey("systems.code"))
    label: Mapped[str] = mapped_column(String(200))
    account_login: Mapped[str | None] = mapped_column(String(255))
    auth_type: Mapped[str] = mapped_column(String(16))
    secret_encrypted: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="unchecked")
    status_message: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    system: Mapped[System] = relationship()


class Integration(Base):
    """Подключение системы к проекту: проект + система + ресурс во внешней системе.

    Все собранные данные привязаны к подключению, а не к проекту напрямую, поэтому
    у проекта может быть любой набор систем.
    """

    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("project_id", "system_code", "external_id"),
        CheckConstraint("status IN ('ok', 'error', 'pending')", name="status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    system_code: Mapped[str] = mapped_column(ForeignKey("systems.code"))
    credential_id: Mapped[int] = mapped_column(ForeignKey("credentials.id"))
    external_id: Mapped[str] = mapped_column(String(255))
    external_name: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    collect_from: Mapped[date | None] = mapped_column(Date)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="integrations")
    credential: Mapped[Credential] = relationship()
    system: Mapped[System] = relationship()
    goals: Mapped[list[IntegrationGoal]] = relationship(
        back_populates="integration", cascade="all, delete-orphan"
    )


class IntegrationGoal(Base):
    """Цель GA4 (key event) или Метрики, отмеченная как избранная для дашборда."""

    __tablename__ = "integration_goals"
    __table_args__ = (UniqueConstraint("integration_id", "external_goal_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"))
    external_goal_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=True)

    integration: Mapped[Integration] = relationship(back_populates="goals")


class MonitoredUrl(Base):
    """URL проекта, который проверяется в PageSpeed Insights."""

    __tablename__ = "monitored_urls"
    __table_args__ = (UniqueConstraint("project_id", "url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    template_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
