"""Сборка данных дашборда проекта и сводного экрана.

Дашборд читает только БД. Исключение — пользователи GA4/Метрики за нестандартный
период: такой итог один раз запрашивается у API и сохраняется в ``period_metrics``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog import ANY_SEGMENT, METRICS_BY_CODE, SYSTEM_NAMES
from app.models import (
    Annotation,
    CwvWeekly,
    DailyMetric,
    Integration,
    IntegrationGoal,
    MonitoredUrl,
    Project,
    PsiRun,
    Signal,
    SiteIssue,
    SitemapSnapshot,
    SyncRun,
)
from app.services.aggregation import (
    PeriodTotals,
    bucketize,
    change_pct,
    load_daily,
    period_totals,
)
from app.services.collector import ensure_period_totals
from app.services.periods import (
    Comparison,
    Granularity,
    Period,
    allowed_granularities,
    bucket_start,
    resolve_granularity,
)
from app.services.projects import favorite_project_ids

GOALS = "goals"


def is_worse(change: float | None, higher_is_better: bool) -> bool:
    """Изменение в худшую сторону.

    Открытый сигнал подсвечивает карточку, только если ухудшение видно и в выбранном
    сравнении: сигнал считается «неделя к неделе», а за квартал метрика может расти.
    """
    if change is None or change == 0:
        return False
    return change < 0 if higher_is_better else change > 0


@dataclass(frozen=True, slots=True)
class ChartSpec:
    """График блока: несколько линий ``(metric_code, segment)``.

    ``kind = 'multi'`` — сводный график поисковой консоли, как в самой GSC: у каждой
    метрики своя шкала, серии включаются переключателями; ``default_visible`` —
    метрики, показанные по умолчанию.
    """

    title: str
    lines: tuple[tuple[str, str], ...]
    kind: str = "line"
    default_visible: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BlockSpec:
    """Состав блока системы на дашборде.

    ``segment = '*'`` в карточке или графике раскрывается во все сегменты метрики
    (например, поисковик и регион позиций); ``segment = 'goals'`` — в избранные цели.
    """

    cards: tuple[tuple[str, str], ...]
    charts: tuple[ChartSpec, ...] = ()
    extras: frozenset[str] = field(default_factory=frozenset)


def _analytics_block(p: str) -> BlockSpec:
    return BlockSpec(
        cards=((f"{p}.users", "all"), (f"{p}.users", "organic"),
               (f"{p}.avg_session_duration", "all"), (f"{p}.bounce_rate", "all"),
               (f"{p}.goals", GOALS)),
        charts=(
            ChartSpec("Пользователи", ((f"{p}.users", "all"), (f"{p}.users", "organic"))),
            ChartSpec("Избранные цели", ((f"{p}.goals", GOALS),), "bar"),
        ),
    )


def _search_block(p: str, extras: set[str], extra_cards=(), extra_charts=(),
                  with_position: bool = True) -> BlockSpec:
    """Блок поисковой консоли. Bing не отдаёт среднюю позицию по сайту — без неё."""
    base = ((f"{p}.clicks", "all"), (f"{p}.impressions", "all"), (f"{p}.ctr", "all"))
    if with_position:
        base += ((f"{p}.position", "all"),)
    return BlockSpec(
        cards=(*base, *extra_cards),
        charts=(
            ChartSpec("Динамика", base, kind="multi",
                      default_visible=(f"{p}.clicks", f"{p}.impressions")),
            *extra_charts,
        ),
        extras=frozenset(extras),
    )


def _positions_block(p: str) -> BlockSpec:
    return BlockSpec(
        cards=((f"{p}.avg_position", ANY_SEGMENT), (f"{p}.visibility", ANY_SEGMENT),
               (f"{p}.top3", ANY_SEGMENT), (f"{p}.top10", ANY_SEGMENT),
               (f"{p}.top30", ANY_SEGMENT)),
        charts=(ChartSpec("Средняя позиция", ((f"{p}.avg_position", ANY_SEGMENT),)),),
        extras=frozenset({"distribution"}),
    )


BLOCKS: dict[str, BlockSpec] = {
    "ga4": _analytics_block("ga4"),
    "metrika": _analytics_block("metrika"),
    "gsc": _search_block("gsc", {"sitemaps"}),
    "crux": BlockSpec(cards=(), extras=frozenset({"cwv"})),
    "ywm": _search_block(
        "ywm", {"sitemaps", "issues"},
        extra_cards=(("ywm.pages_in_search", "all"), ("ywm.open_issues", "all")),
        extra_charts=(ChartSpec("Страниц в поиске", (("ywm.pages_in_search", "all"),
                                                     ("ywm.excluded_pages", "all"))),),
    ),
    "topvisor": _positions_block("topvisor"),
    "seranking": _positions_block("seranking"),
    "bing": _search_block(
        "bing", {"sitemaps"}, with_position=False,
        extra_cards=(("bing.crawl_4xx", "all"), ("bing.crawl_5xx", "all")),
        extra_charts=(ChartSpec("Ошибки обхода", (("bing.crawl_4xx", "all"),
                                                  ("bing.crawl_5xx", "all"),
                                                  ("bing.dns_failures", "all"),
                                                  ("bing.timeouts", "all")), "bar"),),
    ),
    "psi": BlockSpec(
        cards=(("psi.performance", "mobile"), ("psi.performance", "desktop")),
        charts=(ChartSpec("Оценка производительности", (("psi.performance", "mobile"),
                                                        ("psi.performance", "desktop"))),),
        extras=frozenset({"psi"}),
    ),
}

#: Порядок блоков на дашборде.
#: CrUX и PSI стоят рядом: оба блока — про скорость загрузки.
SYSTEM_ORDER = ["ga4", "metrika", "gsc", "ywm", "topvisor", "seranking", "bing", "crux", "psi"]


# ----------------------------------------------------------------- помощники
def _period_dict(period: Period) -> dict[str, str]:
    return {"date_from": period.date_from.isoformat(), "date_to": period.date_to.isoformat()}


def _segment_label(metric_code: str, segment: str, goal_names: dict[str, str]) -> str:
    if metric_code.endswith(".goals"):
        return goal_names.get(segment, segment)
    return {"all": "", "organic": "органика", "mobile": "мобильные",
            "desktop": "ПК"}.get(segment, segment.replace(":", " · "))


def _metric_label(metric_code: str, segment: str, goal_names: dict[str, str]) -> str:
    base = METRICS_BY_CODE[metric_code].name_ru
    seg = _segment_label(metric_code, segment, goal_names)
    if metric_code.endswith(".goals"):
        return seg
    return f"{base} ({seg})" if seg else base


def _expand(metric_code: str, segment: str, known_segments: dict[str, set[str]],
            goal_ids: list[str]) -> list[tuple[str, str]]:
    if segment == GOALS:
        return [(metric_code, g) for g in goal_ids]
    if segment == ANY_SEGMENT:
        return [(metric_code, s) for s in sorted(known_segments.get(metric_code, set()))]
    return [(metric_code, segment)]


def _totals_with_fetch(session: Session, integration: Integration, codes: list[str],
                       period: Period) -> PeriodTotals:
    """Итоги за период; недостающие итоги пользователей запрашиваются у API один раз."""
    totals = period_totals(session, integration.id, codes, period)
    if totals.missing_period_only:
        segments = sorted({seg for _, seg in totals.missing_period_only} | {"all", "organic"})
        if ensure_period_totals(session, integration, period, segments):
            totals = period_totals(session, integration.id, codes, period)
    return totals


def _incomplete_dates(session: Session, integration_id: int, period: Period) -> list[str]:
    """Даты периода, за которые сбор завершился ошибкой и не был повторён успешно."""
    runs = session.scalars(
        select(SyncRun).where(
            SyncRun.integration_id == integration_id,
            SyncRun.date_from <= period.date_to, SyncRun.date_to >= period.date_from,
            SyncRun.status.in_(("success", "partial", "error")),
        ).order_by(SyncRun.started_at)
    ).all()
    bad: set[date] = set()
    for run in runs:
        days = Period(max(run.date_from, period.date_from), min(run.date_to, period.date_to))
        if run.status == "success":
            bad -= set(days.dates())
        else:
            bad |= set(days.dates())
    return [d.isoformat() for d in sorted(bad)]


def _history_from(session: Session, integration_id: int) -> date | None:
    return session.scalar(
        select(func.min(DailyMetric.date)).where(DailyMetric.integration_id == integration_id)
    )


# ------------------------------------------------------------------- дополнения
def _sitemaps(session: Session, integration_id: int, period: Period,
              base: Period) -> list[dict[str, Any]]:
    def latest(until: date) -> dict[str, SitemapSnapshot]:
        snap_date = session.scalar(
            select(func.max(SitemapSnapshot.snapshot_date)).where(
                SitemapSnapshot.integration_id == integration_id,
                SitemapSnapshot.snapshot_date <= until)
        )
        if snap_date is None:
            return {}
        return {s.sitemap_url: s for s in session.scalars(
            select(SitemapSnapshot).where(SitemapSnapshot.integration_id == integration_id,
                                          SitemapSnapshot.snapshot_date == snap_date))}

    current, previous = latest(period.date_to), latest(base.date_to)
    rows = []
    for url, snap in sorted(current.items()):
        prev = previous.get(url)
        rows.append({
            "sitemap_url": url, "snapshot_date": snap.snapshot_date.isoformat(),
            "status": snap.status, "is_index": snap.is_index,
            "submitted_urls": snap.submitted_urls,
            "submitted_urls_before": prev.submitted_urls if prev else None,
            "errors": snap.errors, "warnings": snap.warnings,
            "last_downloaded_at": snap.last_downloaded_at.isoformat()
            if snap.last_downloaded_at else None,
        })
    return rows


def _issues(session: Session, integration_id: int) -> list[dict[str, Any]]:
    issues = session.scalars(
        select(SiteIssue).where(SiteIssue.integration_id == integration_id,
                                SiteIssue.state == "open").order_by(SiteIssue.first_seen_at.desc())
    )
    return [{"id": i.id, "issue_code": i.issue_code, "title": i.title, "severity": i.severity,
             "first_seen_at": i.first_seen_at.isoformat(), "affected_count": i.affected_count}
            for i in issues]


def _cwv(session: Session, integration_id: int, period: Period) -> dict[str, Any]:
    rows = session.scalars(
        select(CwvWeekly).where(
            CwvWeekly.integration_id == integration_id, CwvWeekly.scope == "origin",
            CwvWeekly.period_end.between(period.date_from - timedelta(days=6 * 7),
                                         period.date_to),
        ).order_by(CwvWeekly.period_end)
    ).all()
    series: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    latest: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in rows:
        series[r.device][r.metric].append([r.period_end.isoformat(), r.p75])
        latest[r.device][r.metric] = {"p75": r.p75, "good_pct": r.good_pct,
                                      "ni_pct": r.ni_pct, "poor_pct": r.poor_pct,
                                      "period_end": r.period_end.isoformat()}
    return {"series": series, "latest": latest}


def _psi(session: Session, project_id: int, period: Period) -> list[dict[str, Any]]:
    result = []
    urls = session.scalars(select(MonitoredUrl).where(MonitoredUrl.project_id == project_id,
                                                      MonitoredUrl.is_active.is_(True)))
    for url in urls:
        entry: dict[str, Any] = {"url": url.url, "template_name": url.template_name}
        for device in ("mobile", "desktop"):
            run = session.scalars(
                select(PsiRun).where(PsiRun.monitored_url_id == url.id, PsiRun.device == device,
                                     func.date(PsiRun.run_at) <= period.date_to)
                .order_by(PsiRun.run_at.desc()).limit(1)
            ).first()
            entry[device] = None if run is None else {
                "run_at": run.run_at.isoformat(), "performance_score": run.performance_score,
                "lcp": run.field_lcp, "inp": run.field_inp, "cls": run.field_cls,
                "fcp": run.field_fcp, "ttfb": run.field_ttfb, "category": run.field_category,
                "is_origin_fallback": run.is_origin_fallback,
            }
        result.append(entry)
    return result


def _distribution(daily: dict, prefix: str, segments: list[str],
                  granularity: Granularity) -> list[dict[str, Any]]:
    """Распределение запросов по топам на даты съёмов (для стекового графика).

    При группировке по неделям или месяцам берётся последний съём интервала.
    """
    result = []
    for segment in segments:
        points = []
        by_date: dict[date, dict[str, float | None]] = defaultdict(dict)
        for code in ("top3", "top10", "top30", "top100", "keywords_total"):
            for day, value in daily.get((f"{prefix}.{code}", segment), []):
                by_date[day][code] = value
        last_in_bucket = {bucket_start(day, granularity): day for day in sorted(by_date)}
        for day in sorted(last_in_bucket.values()):
            v = {k: (x or 0) for k, x in by_date[day].items()}
            points.append({
                "date": day.isoformat(),
                "1-3": v.get("top3", 0), "4-10": v.get("top10", 0) - v.get("top3", 0),
                "11-30": v.get("top30", 0) - v.get("top10", 0),
                "31-100": v.get("top100", 0) - v.get("top30", 0),
                "100+": v.get("keywords_total", 0) - v.get("top100", 0),
            })
        result.append({"segment": segment, "label": segment.replace(":", " · "),
                       "points": points})
    return result


# ------------------------------------------------------------------ дашборд
def build_block(session: Session, integration: Integration, period: Period, base: Period,
                open_signal_keys: set[tuple[str, str]],
                granularity: Granularity = Granularity.DAY) -> dict[str, Any]:
    """Собрать блок одной системы: карточки, графики и дополнительные разделы."""
    spec = BLOCKS[integration.system_code]
    goals = session.scalars(select(IntegrationGoal).where(
        IntegrationGoal.integration_id == integration.id,
        IntegrationGoal.is_favorite.is_(True)).order_by(IntegrationGoal.id)).all()
    goal_ids = [g.external_goal_id for g in goals]
    goal_names = {g.external_goal_id: g.name for g in goals}

    card_codes = sorted({c for c, _ in spec.cards})
    chart_codes = {c for ch in spec.charts for c, _ in ch.lines}
    prefix = integration.system_code
    dist_codes: set[str] = set()
    if "distribution" in spec.extras:
        dist_codes = {f"{prefix}.{c}"
                      for c in ("top3", "top10", "top30", "top100", "keywords_total")}
    weight_codes = {METRICS_BY_CODE[c].weight_metric_code for c in chart_codes
                    if METRICS_BY_CODE[c].weight_metric_code}
    daily = load_daily(session, integration.id,
                       chart_codes | set(card_codes) | dist_codes | weight_codes, period)
    known_segments: dict[str, set[str]] = defaultdict(set)
    for code, seg in daily:
        known_segments[code].add(seg)

    totals_now = _totals_with_fetch(session, integration, card_codes, period) if card_codes \
        else PeriodTotals()
    totals_base = _totals_with_fetch(session, integration, card_codes, base) if card_codes \
        else PeriodTotals()

    cards = []
    for code, seg in spec.cards:
        for metric_code, segment in _expand(code, seg, known_segments, goal_ids):
            defn = METRICS_BY_CODE[metric_code]
            value, baseline = totals_now.get(metric_code, segment), totals_base.get(metric_code,
                                                                                      segment)
            cards.append({
                "metric_code": metric_code, "segment": segment,
                "label": _metric_label(metric_code, segment, goal_names),
                "unit": defn.unit, "value": value, "baseline": baseline,
                "change_pct": change_pct(value, baseline),
                "higher_is_better": defn.higher_is_better,
                "is_signal": ((metric_code, segment) in open_signal_keys
                              and is_worse(change_pct(value, baseline), defn.higher_is_better)),
            })

    charts = []
    for chart in spec.charts:
        series = []
        for code, seg in chart.lines:
            for metric_code, segment in _expand(code, seg, known_segments, goal_ids):
                defn = METRICS_BY_CODE[metric_code]
                weights = None
                if defn.weight_metric_code:
                    weights = {d: v or 0.0
                               for d, v in daily.get((defn.weight_metric_code, segment), [])}
                points = bucketize(defn, daily.get((metric_code, segment), []), weights,
                                   granularity)
                series.append({
                    "name": _metric_label(metric_code, segment, goal_names),
                    "metric_code": metric_code, "segment": segment,
                    "unit": METRICS_BY_CODE[metric_code].unit,
                    "inverse": not METRICS_BY_CODE[metric_code].higher_is_better,
                    "points": [[d.isoformat(), v] for d, v in points],
                })
        if series:
            charts.append({"title": chart.title, "kind": chart.kind, "series": series,
                           "note": None, "default_visible": list(chart.default_visible)})

    extras: dict[str, Any] = {}
    if "sitemaps" in spec.extras:
        extras["sitemaps"] = _sitemaps(session, integration.id, period, base)
    if "issues" in spec.extras:
        extras["issues"] = _issues(session, integration.id)
    if "cwv" in spec.extras:
        extras["cwv"] = _cwv(session, integration.id, period)
    if "psi" in spec.extras:
        extras["psi"] = _psi(session, integration.project_id, period)
    if "distribution" in spec.extras:
        extras["distribution"] = _distribution(
            daily, prefix, sorted(known_segments.get(f"{prefix}.top3", set())), granularity)

    history_from = _history_from(session, integration.id)
    if integration.system_code == "crux":
        history_from = session.scalar(select(func.min(CwvWeekly.period_end)).where(
            CwvWeekly.integration_id == integration.id))
    return {
        "integration_id": integration.id,
        "system_code": integration.system_code,
        "system_name": SYSTEM_NAMES.get(integration.system_code, integration.system_code),
        "external_id": integration.external_id,
        "external_name": integration.external_name,
        "status": integration.status,
        "last_error": integration.last_error,
        "history_from": history_from.isoformat() if history_from else None,
        "incomplete_dates": _incomplete_dates(session, integration.id, period),
        "cards": cards,
        "charts": charts,
        "extras": extras,
    }


def project_dashboard(session: Session, project: Project, comparison: Comparison,
                      granularity: Granularity | None = None) -> dict[str, Any]:
    """Данные дашборда проекта за период со сравнением.

    Args:
        session: Сессия БД.
        project: Проект.
        comparison: Период, режим и база сравнения.
        granularity: Группировка графиков; ``None`` — подобрать по длине периода.
    """
    period, mode, base = comparison.period, comparison.mode, comparison.base
    granularity = resolve_granularity(period, granularity)
    integrations = sorted(
        session.scalars(select(Integration).where(Integration.project_id == project.id,
                                                  Integration.disabled_at.is_(None))).all(),
        key=lambda i: (SYSTEM_ORDER.index(i.system_code)
                       if i.system_code in SYSTEM_ORDER else 99, i.id),
    )
    ids = [i.id for i in integrations]
    signals = session.scalars(
        select(Signal).where(Signal.integration_id.in_(ids), Signal.resolved_at.is_(None))
        .order_by(Signal.detected_at.desc())
    ).all() if ids else []
    keys_by_integration: dict[int, set] = defaultdict(set)
    for s in signals:
        if s.metric_code:
            keys_by_integration[s.integration_id].add((s.metric_code, s.segment))

    blocks = [build_block(session, i, period, base, keys_by_integration[i.id], granularity)
              for i in integrations if i.system_code in BLOCKS]
    annotations = session.scalars(
        select(Annotation).where(Annotation.project_id == project.id,
                                 Annotation.date.between(base.date_from if base.date_from <
                                                         period.date_from else period.date_from,
                                                         period.date_to))
        .order_by(Annotation.date)
    ).all()
    return {
        "project": {"id": project.id, "slug": project.slug, "name": project.name,
                    "domain": project.domain},
        "period": _period_dict(period),
        "compare": {"mode": mode.value, "date_from": base.date_from.isoformat(),
                    "date_to": base.date_to.isoformat()},
        "granularity": {"value": granularity.value,
                        "allowed": [g.value for g in allowed_granularities(period)]},
        "blocks": blocks,
        "annotations": [{"id": a.id, "date": a.date.isoformat(), "text": a.text,
                         "author_name": a.author_name} for a in annotations],
        "signals": [signal_to_dict(s) for s in signals],
    }


def signal_to_dict(signal: Signal) -> dict[str, Any]:
    """Сериализовать сигнал для API."""
    return {
        "id": signal.id, "kind": signal.kind, "integration_id": signal.integration_id,
        "metric_code": signal.metric_code, "segment": signal.segment,
        "detected_at": signal.detected_at.isoformat(),
        "period_from": signal.period_from.isoformat() if signal.period_from else None,
        "period_to": signal.period_to.isoformat() if signal.period_to else None,
        "value": signal.value, "baseline": signal.baseline, "change_pct": signal.change_pct,
        "message": signal.message, "status": signal.status, "seen_by_name": signal.seen_by_name,
        "resolved_at": signal.resolved_at.isoformat() if signal.resolved_at else None,
    }


# ----------------------------------------------------------- сводный экран
#: Колонки сводного экрана: (ключ, заголовок, варианты (система, метрика, сегмент)).
OVERVIEW_COLUMNS: tuple[tuple[str, str, tuple[tuple[str, str, str], ...]], ...] = (
    ("organic_users", "Органика, польз.",
     (("ga4", "ga4.users", "organic"), ("metrika", "metrika.users", "organic"))),
    ("gsc_clicks", "Клики Google", (("gsc", "gsc.clicks", "all"),)),
    ("ywm_clicks", "Клики Яндекс", (("ywm", "ywm.clicks", "all"),)),
    ("pages_in_search", "Страниц в поиске Я", (("ywm", "ywm.pages_in_search", "all"),)),
    ("visibility", "Видимость", (("topvisor", "topvisor.visibility", ANY_SEGMENT),
                                 ("seranking", "seranking.visibility", ANY_SEGMENT))),
    ("psi_mobile", "PSI моб.", (("psi", "psi.performance", "mobile"),)),
)


def overview(session: Session, comparison: Comparison, owner: str | None = None) -> dict[str, Any]:
    """Сводная таблица по активным проектам с изменениями и сигналами.

    Избранные проекты сотрудника (``owner``) идут первыми, затем остальные.
    """
    period, mode, base = comparison.period, comparison.mode, comparison.base
    favorites = favorite_project_ids(session, owner) if owner else set()
    projects = sorted(
        session.scalars(select(Project).where(Project.is_active.is_(True))).all(),
        key=lambda p: (p.id not in favorites, p.name.lower()),
    )
    rows = []
    for project in projects:
        integrations = session.scalars(select(Integration).where(
            Integration.project_id == project.id, Integration.disabled_at.is_(None))).all()
        by_system = {}
        for integ in integrations:
            by_system.setdefault(integ.system_code, integ)
        ids = [i.id for i in integrations]
        open_signals = session.scalars(select(Signal).where(
            Signal.integration_id.in_(ids), Signal.resolved_at.is_(None))).all() if ids else []
        signal_keys = {(s.integration_id, s.metric_code, s.segment) for s in open_signals}
        cells: dict[str, Any] = {}
        for key, _title, options in OVERVIEW_COLUMNS:
            cells[key] = None
            for system, metric_code, segment in options:
                integ = by_system.get(system)
                if integ is None:
                    continue
                now = _totals_with_fetch(session, integ, [metric_code], period)
                before = _totals_with_fetch(session, integ, [metric_code], base)
                seg = segment
                if segment == ANY_SEGMENT:
                    segs = sorted(s for c, s in now.values if c == metric_code)
                    if not segs:
                        continue
                    seg = segs[0]
                value, baseline = now.get(metric_code, seg), before.get(metric_code, seg)
                cells[key] = {
                    "value": value, "baseline": baseline, "change_pct": change_pct(value, baseline),
                    "higher_is_better": METRICS_BY_CODE[metric_code].higher_is_better,
                    "unit": METRICS_BY_CODE[metric_code].unit, "source": system,
                    "metric_code": metric_code,
                    "is_signal": ((integ.id, metric_code, seg) in signal_keys
                                  and is_worse(change_pct(value, baseline),
                                               METRICS_BY_CODE[metric_code].higher_is_better)),
                }
                break
        rows.append({
            "project": {"id": project.id, "slug": project.slug, "name": project.name,
                        "domain": project.domain},
            "systems": sorted(by_system, key=lambda s: SYSTEM_ORDER.index(s)
                              if s in SYSTEM_ORDER else 99),
            "cells": cells,
            "is_favorite": project.id in favorites,
            "signals_new": sum(1 for s in open_signals if s.status == "new"),
            "signals_open": len(open_signals),
            "errors": sum(1 for i in integrations if i.status == "error" and i.is_active),
        })
    return {
        "period": _period_dict(period),
        "compare": {"mode": mode.value, "date_from": base.date_from.isoformat(),
                    "date_to": base.date_to.isoformat()},
        "columns": [{"key": k, "title": t} for k, t, _ in OVERVIEW_COLUMNS],
        "rows": rows,
    }
