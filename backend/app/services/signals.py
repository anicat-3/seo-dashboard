"""Подсветка резких изменений и новых ошибок.

После сбора свежие значения сравниваются с правилами ``signal_rules``. Если метрика
ухудшилась на порог и более к базе сравнения или появилась новая ошибка
диагностики, создаётся сигнал. Уже открытый сигнал не дублируется: у него
обновляется значение. Когда ухудшение пропадает, сигнал закрывается.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import ANY_SEGMENT, METRICS_BY_CODE
from app.config import get_settings
from app.models import DailyMetric, Integration, Project, Signal, SignalRule, SiteIssue
from app.models.metrics import AGG_PERIOD_ONLY
from app.models.signals import COMPARISON_MOM
from app.services.aggregation import change_pct, period_totals
from app.services.periods import CompareMode, Period, compare_period, last_days

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Результат проверки правила на одном сегменте."""

    value: float | None
    baseline: float | None
    change_pct: float | None
    is_worse: bool


def evaluate(value: float | None, baseline: float | None, threshold_pct: float,
             higher_is_better: bool) -> Evaluation:
    """Проверить, ухудшилась ли метрика на порог и более.

    Args:
        value: Значение за текущий период.
        baseline: Значение за базовый период.
        threshold_pct: Порог в процентах (положительное число).
        higher_is_better: Направление «лучше» из каталога метрик.
    """
    change = change_pct(value, baseline)
    if change is None:
        return Evaluation(value, baseline, None, False)
    worse = change <= -threshold_pct if higher_is_better else change >= threshold_pct
    return Evaluation(value, baseline, change, worse)


def effective_rules(rules: list[SignalRule], project_id: int) -> list[SignalRule]:
    """Правила для проекта: правило проекта переопределяет общее с той же метрикой и сегментом."""
    chosen: dict[tuple[str, str], SignalRule] = {}
    for rule in sorted(rules, key=lambda r: r.project_id is not None):
        if rule.project_id in (None, project_id):
            chosen[(rule.metric_code, rule.segment)] = rule
    return [r for r in chosen.values() if r.is_active]


def rule_periods(comparison: str, yesterday: date) -> tuple[Period, Period]:
    """Текущий и базовый периоды правила: неделя к неделе или 30 дней к 30."""
    current = last_days(yesterday, 30 if comparison == COMPARISON_MOM else 7)
    return current, compare_period(current, CompareMode.PREVIOUS)


def _segments(session: Session, integration_id: int, metric_code: str, segment: str,
              since: date) -> list[str]:
    if segment != ANY_SEGMENT:
        return [segment]
    return list(session.scalars(
        select(DailyMetric.segment).distinct().where(
            DailyMetric.integration_id == integration_id,
            DailyMetric.metric_code == metric_code,
            DailyMetric.date >= since,
        )
    ))


def is_position_metric(metric_code: str) -> bool:
    """Метрика позиции в выдаче (меньше — лучше, изменение показывается с обратным знаком)."""
    return metric_code.endswith("position")


def _format_message(metric_code: str, segment: str, ev: Evaluation) -> str:
    defn = METRICS_BY_CODE[metric_code]
    labels = {"all": "", "organic": " (органика)", "mobile": " (мобильные)", "desktop": " (ПК)"}
    seg = labels.get(segment, " (" + segment.replace(":", " · ") + ")")
    # Для позиций рост числа — это падение в выдаче: показываем со знаком «−».
    shown = -ev.change_pct if is_position_metric(metric_code) else ev.change_pct
    change = f"{shown:+.1f}".replace(".", ",").replace("-", "−")
    return f"{defn.name_ru}{seg}: {change}% к базе сравнения"


def detect_signals(session: Session, yesterday: date | None = None,
                   new_issues: Mapping[int, list] | None = None) -> int:
    """Проверить правила по всем активным подключениям и обновить сигналы.

    Args:
        session: Сессия БД (коммит выполняет вызывающий код).
        yesterday: Последний полный день; по умолчанию — вчера по времени приложения.
        new_issues: Новые ошибки диагностики по подключениям, найденные при сборе.

    Returns:
        Количество созданных сигналов.
    """
    from app.services.collector import ensure_period_totals

    now = datetime.now(UTC)
    yesterday = yesterday or (datetime.now(get_settings().tz).date() - timedelta(days=1))
    rules = list(session.scalars(select(SignalRule)))
    created = 0

    integrations = session.scalars(
        select(Integration).join(Project).where(
            Integration.is_active.is_(True), Project.is_active.is_(True)
        )
    ).all()
    for integration in integrations:
        applicable = [
            r for r in effective_rules(rules, integration.project_id)
            if METRICS_BY_CODE.get(r.metric_code)
            and METRICS_BY_CODE[r.metric_code].system_code == integration.system_code
        ]
        open_signals = {
            (s.metric_code, s.segment): s
            for s in session.scalars(select(Signal).where(
                Signal.integration_id == integration.id, Signal.kind == "metric",
                Signal.resolved_at.is_(None)))
        }
        for rule in applicable:
            defn = METRICS_BY_CODE[rule.metric_code]
            current, base = rule_periods(rule.comparison, yesterday)
            totals_now = period_totals(session, integration.id, [rule.metric_code], current)
            totals_base = period_totals(session, integration.id, [rule.metric_code], base)
            if defn.aggregation == AGG_PERIOD_ONLY:
                for totals, period in ((totals_now, current), (totals_base, base)):
                    if totals.missing_period_only and ensure_period_totals(
                            session, integration, period, ["all", "organic"]):
                        refreshed = period_totals(session, integration.id,
                                                  [rule.metric_code], period)
                        totals.values.update(refreshed.values)
            for segment in _segments(session, integration.id, rule.metric_code, rule.segment,
                                     base.date_from):
                ev = evaluate(totals_now.get(rule.metric_code, segment),
                              totals_base.get(rule.metric_code, segment),
                              rule.threshold_pct, defn.higher_is_better)
                existing = open_signals.get((rule.metric_code, segment))
                if ev.is_worse:
                    if existing is None:
                        existing = Signal(kind="metric", integration_id=integration.id,
                                          metric_code=rule.metric_code, segment=segment,
                                          status="new", detected_at=now)
                        session.add(existing)
                        created += 1
                    existing.rule_id = rule.id
                    existing.value, existing.baseline = ev.value, ev.baseline
                    existing.change_pct = ev.change_pct
                    existing.period_from, existing.period_to = current.date_from, current.date_to
                    existing.message = _format_message(rule.metric_code, segment, ev)
                elif existing is not None:
                    existing.resolved_at = now

        created += _issue_signals(session, integration, (new_issues or {}).get(integration.id, []),
                                  now)
    session.flush()
    logger.info("Подсветка изменений: создано сигналов %s", created)
    return created


def _issue_signals(session: Session, integration: Integration, new_issues: list,
                   now: datetime) -> int:
    """Сигналы о новых ошибках диагностики; закрыть сигналы по исправленным ошибкам."""
    created = 0
    for issue in new_issues:
        session.add(Signal(kind="issue", integration_id=integration.id, issue_id=issue.issue_id,
                           status="new", detected_at=now,
                           message=f"Новая ошибка диагностики: {issue.title}"))
        created += 1
    resolved = session.scalars(
        select(Signal).join(SiteIssue, SiteIssue.id == Signal.issue_id).where(
            Signal.integration_id == integration.id, Signal.kind == "issue",
            Signal.resolved_at.is_(None), SiteIssue.state == "resolved",
        )
    )
    for signal in resolved:
        signal.resolved_at = now
    return created
