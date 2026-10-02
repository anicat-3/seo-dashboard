"""Расчёт итогов метрик за период по данным ``daily_metrics`` и ``period_metrics``.

Правила (см. раздел «Общие правила» архитектуры):

* ``sum`` — сумма дневных значений;
* ``weighted_avg`` — среднее, взвешенное по метрике-весу (CTR и позиция — по показам),
  так же считает сам GSC; простое среднее по дням дало бы расхождение с интерфейсом;
* ``last`` — последнее известное значение в периоде;
* ``period_only`` — только готовый итог из ``period_metrics`` (пользователи
  не суммируются по дням). Для длительности и отказов при отсутствии итога
  используется запасной вариант — среднее, взвешенное по сеансам.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import METRICS_BY_CODE, MetricDef
from app.models import DailyMetric, PeriodMetric
from app.models.metrics import AGG_LAST, AGG_PERIOD_ONLY, AGG_SUM, AGG_WEIGHTED_AVG
from app.services.periods import Granularity, Period, bucket_start

MetricKey = tuple[str, str]  # (metric_code, segment)


@dataclass(slots=True)
class PeriodTotals:
    """Итоги метрик одного подключения за период.

    Attributes:
        values: Значения по ключу ``(metric_code, segment)``.
        missing_period_only: Ключи ``period_only``-метрик без готового итога.
    """

    values: dict[MetricKey, float | None] = field(default_factory=dict)
    missing_period_only: set[MetricKey] = field(default_factory=set)

    def get(self, metric_code: str, segment: str = "all") -> float | None:
        """Значение метрики или ``None``, если данных нет."""
        return self.values.get((metric_code, segment))


def aggregate(defn: MetricDef, rows: list[tuple[date, float | None]],
              weights: dict[date, float] | None = None) -> float | None:
    """Свести дневные значения одной метрики в итог за период.

    Args:
        defn: Описание метрики (правило агрегации).
        rows: Пары ``(дата, значение)``.
        weights: Веса по датам для ``weighted_avg``.

    Returns:
        Итог или ``None``, если значений нет.
    """
    values = [(d, v) for d, v in rows if v is not None]
    if not values:
        return None
    if defn.aggregation == AGG_SUM:
        return float(sum(v for _, v in values))
    if defn.aggregation == AGG_LAST:
        return max(values, key=lambda item: item[0])[1]
    if defn.aggregation in (AGG_WEIGHTED_AVG, AGG_PERIOD_ONLY):
        if weights:
            total_weight = sum(weights.get(d, 0.0) for d, _ in values)
            if total_weight > 0:
                return sum(v * weights.get(d, 0.0) for d, v in values) / total_weight
        if defn.aggregation == AGG_WEIGHTED_AVG:
            return sum(v for _, v in values) / len(values)
        return None
    raise ValueError(f"Неизвестное правило агрегации: {defn.aggregation}")


def is_daily_total(defn: MetricDef) -> bool:
    """Несуммируемая метрика без веса (пользователи): в интервале — сумма дневных значений."""
    return defn.aggregation == AGG_PERIOD_ONLY and not defn.weight_metric_code


def bucketize(defn: MetricDef, rows: list[tuple[date, float | None]],
              weights: dict[date, float] | None,
              granularity: Granularity) -> list[tuple[date, float | None]]:
    """Сгруппировать дневной ряд по неделям или месяцам для графика.

    Внутри интервала действует правило агрегации метрики. Для пользователей
    берётся сумма дневных значений: так удобнее сравнивать интервалы между собой.
    Повторные визиты одного человека в разные дни при этом считаются отдельно,
    поэтому сумма по неделям больше точного итога за период в карточке.

    Returns:
        Пары ``(начало интервала, значение)`` по возрастанию даты.
    """
    if granularity is Granularity.DAY:
        return rows
    buckets: dict[date, list[tuple[date, float | None]]] = defaultdict(list)
    for day, value in rows:
        buckets[bucket_start(day, granularity)].append((day, value))
    result = []
    for start in sorted(buckets):
        items = buckets[start]
        if is_daily_total(defn):
            values = [v for _, v in items if v is not None]
            result.append((start, float(sum(values)) if values else None))
        else:
            result.append((start, aggregate(defn, items, weights)))
    return result


def load_daily(session: Session, integration_id: int, metric_codes: set[str],
               period: Period) -> dict[MetricKey, list[tuple[date, float | None]]]:
    """Загрузить дневные значения метрик подключения за период."""
    stmt = select(DailyMetric.metric_code, DailyMetric.segment, DailyMetric.date,
                  DailyMetric.value).where(
        DailyMetric.integration_id == integration_id,
        DailyMetric.metric_code.in_(metric_codes),
        DailyMetric.date.between(period.date_from, period.date_to),
    ).order_by(DailyMetric.date)
    series: dict[MetricKey, list[tuple[date, float | None]]] = defaultdict(list)
    for metric_code, segment, day, value in session.execute(stmt):
        series[(metric_code, segment)].append((day, value))
    return series


def period_totals(session: Session, integration_id: int, metric_codes: list[str],
                  period: Period) -> PeriodTotals:
    """Посчитать итоги метрик подключения за период.

    Args:
        session: Сессия БД.
        integration_id: Подключение.
        metric_codes: Коды метрик из каталога.
        period: Период.
    """
    defs = [METRICS_BY_CODE[c] for c in metric_codes if c in METRICS_BY_CODE]
    needed = {d.code for d in defs} | {d.weight_metric_code for d in defs if d.weight_metric_code}
    daily = load_daily(session, integration_id, needed, period)

    stored = {
        (row.metric_code, row.segment): row.value
        for row in session.scalars(
            select(PeriodMetric).where(
                PeriodMetric.integration_id == integration_id,
                PeriodMetric.metric_code.in_([d.code for d in defs
                                              if d.aggregation == AGG_PERIOD_ONLY]),
                PeriodMetric.date_from == period.date_from,
                PeriodMetric.date_to == period.date_to,
            )
        )
    }

    totals = PeriodTotals()
    for defn in defs:
        segments = {seg for code, seg in daily if code == defn.code}
        segments |= {seg for code, seg in stored if code == defn.code}
        for segment in segments:
            key = (defn.code, segment)
            if defn.aggregation == AGG_PERIOD_ONLY and key in stored:
                totals.values[key] = stored[key]
                continue
            weights = None
            if defn.weight_metric_code:
                weight_rows = daily.get((defn.weight_metric_code, segment), [])
                weights = {d: v or 0.0 for d, v in weight_rows}
            totals.values[key] = aggregate(defn, daily.get(key, []), weights)
            if defn.aggregation == AGG_PERIOD_ONLY:
                totals.missing_period_only.add(key)
    return totals


def change_pct(value: float | None, baseline: float | None) -> float | None:
    """Изменение значения к базе в процентах; ``None``, если база нулевая или неизвестна."""
    if value is None or baseline is None or baseline == 0:
        return None
    return (value - baseline) / abs(baseline) * 100
