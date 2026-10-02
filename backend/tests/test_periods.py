from datetime import date

import pytest

from app.services.periods import (
    CompareMode,
    Period,
    compare_period,
    last_calendar_month,
    last_calendar_week,
    standard_periods,
)


def test_previous_period_has_same_length():
    period = Period(date(2026, 9, 1), date(2026, 9, 7))
    assert compare_period(period, CompareMode.PREVIOUS) == Period(date(2026, 8, 25),
                                                                  date(2026, 8, 31))


def test_previous_month_is_calendar_month():
    period = Period(date(2026, 3, 10), date(2026, 3, 16))
    assert compare_period(period, CompareMode.PREVIOUS_MONTH) == Period(date(2026, 2, 1),
                                                                        date(2026, 2, 28))


def test_year_ago_handles_leap_day():
    period = Period(date(2028, 2, 29), date(2028, 3, 1))
    assert compare_period(period, CompareMode.YEAR_AGO) == Period(date(2027, 2, 28),
                                                                  date(2027, 3, 1))


def test_last_calendar_week_ends_on_sunday():
    week = last_calendar_week(date(2026, 9, 30))  # среда
    assert week == Period(date(2026, 9, 21), date(2026, 9, 27))
    assert last_calendar_week(date(2026, 9, 27)) == week  # воскресенье — неделя закрыта


def test_last_calendar_month():
    assert last_calendar_month(date(2026, 9, 28)) == Period(date(2026, 8, 1), date(2026, 8, 31))
    assert last_calendar_month(date(2026, 9, 30)) == Period(date(2026, 9, 1), date(2026, 9, 30))


def test_standard_periods_are_unique_and_include_comparisons():
    periods = standard_periods(date(2026, 9, 28))
    assert len(periods) == len(set(periods))
    assert Period(date(2026, 9, 22), date(2026, 9, 28)) in periods  # последние 7 дней
    assert Period(date(2026, 9, 15), date(2026, 9, 21)) in periods  # предыдущие 7 дней


def test_invalid_period_rejected():
    with pytest.raises(ValueError):
        Period(date(2026, 9, 2), date(2026, 9, 1))
