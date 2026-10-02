"""Периоды дашборда и базы сравнения."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class CompareMode(StrEnum):
    """База сравнения периода."""

    PREVIOUS = "previous"
    """Предыдущий период той же длины."""
    PREVIOUS_MONTH = "previous_month"
    """Предыдущий календарный месяц."""
    YEAR_AGO = "year_ago"
    """Тот же период год назад."""
    CUSTOM = "custom"
    """Произвольный период, выбранный пользователем."""


class Granularity(StrEnum):
    """Группировка точек на графиках."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


#: Самый длинный период, для которого графики строятся по дням.
MAX_DAILY_DAYS = 62


@dataclass(frozen=True, slots=True)
class Period:
    """Закрытый интервал дат ``[date_from, date_to]``."""

    date_from: date
    date_to: date

    def __post_init__(self) -> None:
        if self.date_from > self.date_to:
            raise ValueError("Начало периода позже окончания")

    @property
    def days(self) -> int:
        """Длина периода в днях."""
        return (self.date_to - self.date_from).days + 1

    def dates(self) -> list[date]:
        """Все даты периода по порядку."""
        return [self.date_from + timedelta(days=i) for i in range(self.days)]

    def contains(self, day: date) -> bool:
        """Входит ли дата в период."""
        return self.date_from <= day <= self.date_to


def _shift_year(day: date, years: int) -> date:
    """Сдвинуть дату на ``years`` лет; 29 февраля превращается в 28-е."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def month_period(year: int, month: int) -> Period:
    """Календарный месяц как период."""
    last_day = calendar.monthrange(year, month)[1]
    return Period(date(year, month, 1), date(year, month, last_day))


def previous_month_of(day: date) -> Period:
    """Календарный месяц, предшествующий месяцу даты ``day``."""
    first = day.replace(day=1) - timedelta(days=1)
    return month_period(first.year, first.month)


def compare_period(period: Period, mode: CompareMode) -> Period:
    """Вернуть базу сравнения для периода.

    Args:
        period: Выбранный период.
        mode: Режим сравнения.
    """
    if mode is CompareMode.PREVIOUS:
        end = period.date_from - timedelta(days=1)
        return Period(end - timedelta(days=period.days - 1), end)
    if mode is CompareMode.PREVIOUS_MONTH:
        return previous_month_of(period.date_from)
    if mode is CompareMode.YEAR_AGO:
        return Period(_shift_year(period.date_from, -1), _shift_year(period.date_to, -1))
    if mode is CompareMode.CUSTOM:
        raise ValueError("Для произвольного сравнения период задаётся явно")
    raise ValueError(f"Неизвестный режим сравнения: {mode}")


@dataclass(frozen=True, slots=True)
class Comparison:
    """Выбранный период, режим сравнения и база сравнения."""

    period: Period
    mode: CompareMode
    base: Period


def last_days(yesterday: date, days: int) -> Period:
    """Последние ``days`` дней, заканчивая ``yesterday`` включительно."""
    return Period(yesterday - timedelta(days=days - 1), yesterday)


def last_calendar_week(yesterday: date) -> Period:
    """Последняя полностью завершённая календарная неделя (пн–вс)."""
    end = yesterday - timedelta(days=(yesterday.weekday() + 1) % 7)
    return Period(end - timedelta(days=6), end)


def last_calendar_month(yesterday: date) -> Period:
    """Последний полностью завершённый календарный месяц."""
    if yesterday.day == calendar.monthrange(yesterday.year, yesterday.month)[1]:
        return month_period(yesterday.year, yesterday.month)
    return previous_month_of(yesterday)


def standard_periods(yesterday: date) -> list[Period]:
    """Стандартные периоды, итоги по которым готовятся ночью.

    Последние 7 и 30 дней, прошлые календарные неделя и месяц, а также
    предшествующие им периоды для сравнения.
    """
    periods: list[Period] = []
    for base in (last_days(yesterday, 7), last_days(yesterday, 30),
                 last_calendar_week(yesterday)):
        periods += [base, compare_period(base, CompareMode.PREVIOUS)]
    month = last_calendar_month(yesterday)
    periods += [month, compare_period(month, CompareMode.PREVIOUS_MONTH)]
    return list(dict.fromkeys(periods))


def allowed_granularities(period: Period) -> list[Granularity]:
    """Доступные группировки графиков для периода.

    По дням — только для периодов до :data:`MAX_DAILY_DAYS` дней (иначе точки
    сливаются); по неделям — от двух недель; по месяцам — от двух месяцев.
    """
    allowed = []
    if period.days <= MAX_DAILY_DAYS:
        allowed.append(Granularity.DAY)
    if period.days >= 14:
        allowed.append(Granularity.WEEK)
    if period.days >= 60:
        allowed.append(Granularity.MONTH)
    return allowed or [Granularity.DAY]


def resolve_granularity(period: Period, requested: Granularity | None) -> Granularity:
    """Выбрать группировку: запрошенную, если она доступна, иначе самую подробную."""
    allowed = allowed_granularities(period)
    return requested if requested in allowed else allowed[0]


def bucket_start(day: date, granularity: Granularity) -> date:
    """Начало интервала группировки: сам день, понедельник недели или первое число месяца."""
    if granularity is Granularity.WEEK:
        return day - timedelta(days=day.weekday())
    if granularity is Granularity.MONTH:
        return day.replace(day=1)
    return day
