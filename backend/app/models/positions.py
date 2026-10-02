"""Позиции по запросам из Topvisor и SE Ranking.

``keyword_positions`` — самая большая таблица (миллионы строк в год). В БД она
секционирована по месяцам (``PARTITION BY RANGE (check_date)``); секции создаёт
функция ``ensure_keyword_positions_partition(date)``, см. первую миграцию.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Keyword(Base):
    """Отслеживаемый запрос в конкретном поисковике, регионе и на устройстве."""

    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint(
            "integration_id", "external_keyword_id", "search_engine", "region", "device",
            name="uq_keywords_natural_key",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"), index=True)
    external_keyword_id: Mapped[str] = mapped_column(String(64))
    keyword: Mapped[str] = mapped_column(Text)
    search_engine: Mapped[str] = mapped_column(String(32))
    region: Mapped[str] = mapped_column(String(128))
    device: Mapped[str] = mapped_column(String(16), default="desktop")
    group_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class KeywordPosition(Base):
    """Позиция запроса на дату съёма. ``position = NULL`` — сайта нет в глубине проверки."""

    __tablename__ = "keyword_positions"
    __table_args__ = {"postgresql_partition_by": "RANGE (check_date)"}

    keyword_id: Mapped[int] = mapped_column(
        ForeignKey("keywords.id", ondelete="CASCADE"), primary_key=True
    )
    check_date: Mapped[date] = mapped_column(Date, primary_key=True)
    position: Mapped[int | None] = mapped_column(SmallInteger)
    url: Mapped[str | None] = mapped_column(Text)
