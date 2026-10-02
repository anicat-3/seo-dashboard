"""Временные ряды: справочник метрик, дневные значения и итоги за период."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

#: Правила расчёта значения метрики за период.
AGG_SUM = "sum"
AGG_WEIGHTED_AVG = "weighted_avg"
AGG_LAST = "last"
AGG_PERIOD_ONLY = "period_only"

#: Сегмент по умолчанию (без среза).
SEGMENT_ALL = "all"
SEGMENT_ORGANIC = "organic"


class MetricCatalog(Base):
    """Описание метрики и правило её агрегации за период.

    ``aggregation``:
        * ``sum`` — сумма дневных значений (клики, показы, цели);
        * ``weighted_avg`` — среднее, взвешенное по ``weight_metric_code`` (CTR, позиция);
        * ``last`` — последнее значение в периоде (страниц в поиске, позиции на дату съёма);
        * ``period_only`` — несуммируемые метрики (пользователи): итог берётся
          из ``period_metrics``, дневные значения — только для графиков.
    """

    __tablename__ = "metric_catalog"
    __table_args__ = (
        CheckConstraint(
            "aggregation IN ('sum', 'weighted_avg', 'last', 'period_only')", name="aggregation"
        ),
    )

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    system_code: Mapped[str] = mapped_column(ForeignKey("systems.code"))
    name_ru: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(16), default="")
    aggregation: Mapped[str] = mapped_column(String(16))
    weight_metric_code: Mapped[str | None] = mapped_column(String(64))
    higher_is_better: Mapped[bool] = mapped_column(Boolean, default=True)


class DailyMetric(Base):
    """Дневное значение метрики подключения в разрезе сегмента.

    ``segment`` разделяет срезы одной метрики: ``all``, ``organic``, ``mobile``,
    ``desktop``, ID цели, ``поисковик:регион`` для позиций.
    Дата — в часовом поясе источника (пояс зафиксирован в подключении).
    """

    __tablename__ = "daily_metrics"
    __table_args__ = (Index("ix_daily_metrics_metric_date", "metric_code", "date"),)

    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrations.id"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    metric_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    segment: Mapped[str] = mapped_column(String(128), primary_key=True, default=SEGMENT_ALL)
    value: Mapped[float | None] = mapped_column(Float)


class PeriodMetric(Base):
    """Итог несуммируемой метрики GA4/Метрики за точный период, полученный у API."""

    __tablename__ = "period_metrics"

    integration_id: Mapped[int] = mapped_column(
        ForeignKey("integrations.id"), primary_key=True
    )
    metric_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    segment: Mapped[str] = mapped_column(String(128), primary_key=True, default=SEGMENT_ALL)
    date_from: Mapped[date] = mapped_column(Date, primary_key=True)
    date_to: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float | None] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
