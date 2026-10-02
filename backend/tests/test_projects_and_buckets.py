from datetime import date, timedelta

from app.catalog import METRICS_BY_CODE
from app.services.aggregation import bucketize
from app.services.periods import (
    Granularity,
    Period,
    allowed_granularities,
    bucket_start,
    resolve_granularity,
)
from app.services.projects import slugify_domain


def test_slug_replaces_dots_with_hyphens():
    assert slugify_domain("auto-parts.kz") == "auto-parts-kz"
    assert slugify_domain("Shop.Example.BY") == "shop-example-by"
    assert slugify_domain("сайт.бел") == "сайт-бел"


def test_numeric_slug_does_not_clash_with_id():
    assert slugify_domain("123") == "site-123"


def test_daily_granularity_unavailable_for_quarter():
    quarter = Period(date(2026, 7, 2), date(2026, 9, 29))  # 90 дней
    assert Granularity.DAY not in allowed_granularities(quarter)
    assert resolve_granularity(quarter, Granularity.DAY) is Granularity.WEEK
    assert resolve_granularity(quarter, Granularity.MONTH) is Granularity.MONTH


def test_week_is_available_only_from_two_weeks():
    week = Period(date(2026, 9, 23), date(2026, 9, 29))
    assert allowed_granularities(week) == [Granularity.DAY]


def test_bucket_start():
    assert bucket_start(date(2026, 9, 30), Granularity.WEEK) == date(2026, 9, 28)  # понедельник
    assert bucket_start(date(2026, 9, 30), Granularity.MONTH) == date(2026, 9, 1)


def _rows(start: date, values: list[float]):
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_weekly_sum():
    rows = _rows(date(2026, 9, 21), [1] * 7 + [2] * 7)  # две полные недели с понедельника
    result = bucketize(METRICS_BY_CODE["gsc.clicks"], rows, None, Granularity.WEEK)
    assert result == [(date(2026, 9, 21), 7.0), (date(2026, 9, 28), 14.0)]


def test_weekly_users_are_sum_of_days():
    rows = _rows(date(2026, 9, 21), [100, 200, 300, 100, 200, 300, 200])
    result = bucketize(METRICS_BY_CODE["ga4.users"], rows, None, Granularity.WEEK)
    assert result == [(date(2026, 9, 21), 1400.0)]


def test_weekly_session_duration_is_weighted_by_sessions():
    rows = [(date(2026, 9, 21), 100.0), (date(2026, 9, 22), 200.0)]
    weights = {date(2026, 9, 21): 3, date(2026, 9, 22): 1}
    (_, value), = bucketize(METRICS_BY_CODE["ga4.avg_session_duration"], rows, weights,
                            Granularity.WEEK)
    assert value == 125.0


def test_weekly_ctr_is_weighted_by_impressions():
    rows = [(date(2026, 9, 21), 10.0), (date(2026, 9, 22), 0.1)]
    weights = {date(2026, 9, 21): 100, date(2026, 9, 22): 1000}
    (_, value), = bucketize(METRICS_BY_CODE["gsc.ctr"], rows, weights, Granularity.WEEK)
    assert round(value, 4) == 1.0
