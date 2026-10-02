from datetime import date

from app.catalog import METRICS_BY_CODE
from app.services.aggregation import aggregate, change_pct

D1, D2 = date(2026, 9, 1), date(2026, 9, 2)


def test_sum():
    assert aggregate(METRICS_BY_CODE["gsc.clicks"], [(D1, 10), (D2, 5)]) == 15


def test_ctr_is_weighted_by_impressions_like_gsc():
    # День 1: 10 кликов из 100 показов (10%), день 2: 1 клик из 1000 (0,1%).
    ctr = aggregate(METRICS_BY_CODE["gsc.ctr"], [(D1, 10.0), (D2, 0.1)],
                    weights={D1: 100, D2: 1000})
    assert round(ctr, 4) == round(11 / 1100 * 100, 4)  # 1% — как клики ÷ показы
    # Простое среднее дало бы 5,05% — именно эту ошибку исключает взвешивание.


def test_last_takes_latest_date():
    assert aggregate(METRICS_BY_CODE["ywm.pages_in_search"], [(D2, 7), (D1, 3)]) == 7


def test_period_only_without_weights_is_unknown():
    assert aggregate(METRICS_BY_CODE["ga4.users"], [(D1, 100), (D2, 120)]) is None


def test_nulls_are_ignored():
    assert aggregate(METRICS_BY_CODE["gsc.clicks"], [(D1, None)]) is None


def test_change_pct():
    assert change_pct(90, 100) == -10
    assert change_pct(5, 0) is None
    assert change_pct(None, 10) is None
