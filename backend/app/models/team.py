"""Состав SEO-команды и журнал действий сотрудников."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

#: События журнала действий.
EVENT_LOGIN = "login"
EVENT_LOGOUT = "logout"
EVENT_VIEW = "view"


class TeamMember(Base):
    """Сотрудник, работающий под общей учётной записью.

    Список ведёт администратор; при входе сотрудник выбирает себя из этого списка,
    и его имя попадает в журналы и пометки. Выключенный сотрудник войти не может,
    а его записи в журналах сохраняются.
    """

    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActivityLog(Base):
    """Журнал действий: входы, выходы и просмотры страниц сотрудниками."""

    __tablename__ = "activity_log"
    __table_args__ = (
        CheckConstraint("event IN ('login', 'logout', 'view')", name="event"),
        Index("ix_activity_log_member_created", "member_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("team_members.id", ondelete="SET NULL"))
    actor_name: Mapped[str] = mapped_column(String(100))
    event: Mapped[str] = mapped_column(String(16))
    path: Mapped[str | None] = mapped_column(Text)
    page: Mapped[str | None] = mapped_column(String(200))
    project_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class FavoriteProject(Base):
    """Проект в избранном сотрудника: показывается первым в сводке и в переключателе.

    ``owner`` — ``member:<id>`` для сотрудника или ``account:<id>`` для администратора
    без выбранного имени: под общей учётной записью работает вся команда, поэтому
    избранное закрепляется за сотрудником, а не за учётной записью.
    """

    __tablename__ = "favorite_projects"

    owner: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
