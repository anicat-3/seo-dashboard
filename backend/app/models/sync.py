"""Журнал сбора: запуски коннекторов и сырые ответы API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

#: Типы заданий сбора.
JOB_DAILY = "daily"
JOB_BACKFILL = "backfill"
JOB_MANUAL = "manual"
JOB_PERIOD = "period"


class SyncRun(Base):
    """Один запуск коннектора по одному подключению."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'partial', 'error')", name="status"
        ),
        CheckConstraint(
            "job_type IN ('daily', 'backfill', 'manual', 'period')", name="job_type"
        ),
        Index("ix_sync_runs_integration_started", "integration_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"))
    job_type: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_by_name: Mapped[str | None] = mapped_column(String(100))


class RawResponse(Base):
    """Сырой ответ API — для отладки и перерасчёта. Хранится 90 дней."""

    __tablename__ = "raw_responses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(String(255))
    request_params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    response: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
