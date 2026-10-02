"""Обращения SEO-команды: предложения и замечания по работе дашборда."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

#: Статусы обращения: новое и решения администратора.
FEEDBACK_STATUSES = ("new", "closed", "rejected", "paused", "postponed")


class Feedback(Base):
    """Обращение сотрудника; администратор меняет статус и может оставить ответ."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(f"status IN {FEEDBACK_STATUSES}", name="status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    author_name: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    admin_note: Mapped[str | None] = mapped_column(Text)
    resolved_by_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
