"""Запись результата коннектора в БД.

Все операции идемпотентны: повторная выгрузка за ту же дату перезаписывает строки
(upsert по естественному ключу), дубликатов не возникает.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.connectors.base import CollectResult, IssueState
from app.models import (
    CwvWeekly,
    DailyMetric,
    Keyword,
    KeywordPosition,
    PeriodMetric,
    PsiRun,
    RawResponse,
    SiteIssue,
    SitemapSnapshot,
)

#: Размер пачки для многострочных INSERT.
_CHUNK = 2000


def _chunks(rows: Sequence[dict[str, Any]], size: int = _CHUNK) -> Iterable[Sequence[dict]]:
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def _upsert(session: Session, model, rows: list[dict[str, Any]], key: list[str],
            update_cols: list[str]) -> int:
    """Вставить строки с обновлением при конфликте по ключу ``key``."""
    if not rows:
        return 0
    # Внутри одной пачки ключ должен быть уникален, иначе PostgreSQL отклонит ON CONFLICT.
    unique = {tuple(r[k] for k in key): r for r in rows}
    rows = list(unique.values())
    for chunk in _chunks(rows):
        stmt = insert(model).values(list(chunk))
        stmt = stmt.on_conflict_do_update(
            index_elements=key, set_={c: stmt.excluded[c] for c in update_cols}
        )
        session.execute(stmt)
    return len(rows)


class NewIssue:
    """Сведения о новой ошибке диагностики — для создания сигнала."""

    def __init__(self, issue_id: int, title: str):
        self.issue_id = issue_id
        self.title = title


def write_result(session: Session, integration_id: int, sync_run_id: int,
                 result: CollectResult) -> tuple[int, list[NewIssue]]:
    """Сохранить результат сбора.

    Args:
        session: Открытая сессия (коммит выполняет вызывающий код).
        integration_id: Подключение, к которому относятся данные.
        sync_run_id: Запуск, к которому привязываются сырые ответы.
        result: Данные, полученные коннектором.

    Returns:
        Число записанных строк и список новых ошибок диагностики.
    """
    written = 0
    for call in result.raw:
        session.add(RawResponse(sync_run_id=sync_run_id, endpoint=call.endpoint,
                                request_params=call.request_params, response=call.response))

    written += _upsert(
        session, DailyMetric,
        [{"integration_id": integration_id, "date": v.date, "metric_code": v.metric_code,
          "segment": v.segment, "value": v.value} for v in result.daily],
        key=["integration_id", "date", "metric_code", "segment"], update_cols=["value"],
    )
    written += write_period_values(session, integration_id, result.period)

    if result.sitemaps is not None and result.snapshot_date is not None:
        written += _upsert(
            session, SitemapSnapshot,
            [{"integration_id": integration_id, "snapshot_date": result.snapshot_date,
              "sitemap_url": s.sitemap_url, "is_index": s.is_index,
              "submitted_urls": s.submitted_urls, "errors": s.errors, "warnings": s.warnings,
              "status": s.status, "raw_status": s.raw_status,
              "last_downloaded_at": s.last_downloaded_at} for s in result.sitemaps],
            key=["integration_id", "snapshot_date", "sitemap_url"],
            update_cols=["is_index", "submitted_urls", "errors", "warnings", "status",
                         "raw_status", "last_downloaded_at"],
        )

    new_issues: list[NewIssue] = []
    if result.issues is not None:
        seen_at = datetime.combine(result.snapshot_date or date.today(), time(4, 0), tzinfo=UTC)
        new_issues = _sync_issues(session, integration_id, result.issues, seen_at)
        written += len(result.issues)

    written += _upsert(
        session, CwvWeekly,
        [{"integration_id": integration_id, "period_end": p.period_end, "scope": p.scope,
          "url": p.url, "device": p.device, "metric": p.metric, "p75": p.p75,
          "good_pct": p.good_pct, "ni_pct": p.ni_pct, "poor_pct": p.poor_pct}
         for p in result.cwv],
        key=["integration_id", "period_end", "scope", "url", "device", "metric"],
        update_cols=["p75", "good_pct", "ni_pct", "poor_pct"],
    )

    written += _write_psi(session, result)
    written += _write_keywords(session, integration_id, result)
    return written, new_issues


def write_period_values(session: Session, integration_id: int, values) -> int:
    """Сохранить итоги за период в ``period_metrics`` (upsert)."""
    return _upsert(
        session, PeriodMetric,
        [{"integration_id": integration_id, "metric_code": v.metric_code, "segment": v.segment,
          "date_from": v.date_from, "date_to": v.date_to, "value": v.value,
          "fetched_at": datetime.now(UTC)} for v in values],
        key=["integration_id", "metric_code", "segment", "date_from", "date_to"],
        update_cols=["value", "fetched_at"],
    )


def _sync_issues(session: Session, integration_id: int, current: list[IssueState],
                 seen_at: datetime) -> list[NewIssue]:
    """Обновить жизненный цикл ошибок: новые открыть, пропавшие закрыть."""
    open_issues = {
        issue.issue_code: issue
        for issue in session.scalars(
            select(SiteIssue).where(SiteIssue.integration_id == integration_id,
                                    SiteIssue.state == "open")
        )
    }
    new: list[NewIssue] = []
    current_codes = set()
    for state in current:
        current_codes.add(state.issue_code)
        existing = open_issues.get(state.issue_code)
        if existing is not None:
            existing.last_seen_at = max(existing.last_seen_at, seen_at)
            existing.affected_count = state.affected_count
            existing.title = state.title
            existing.severity = state.severity
            existing.details = state.details
            continue
        issue = SiteIssue(
            integration_id=integration_id, issue_code=state.issue_code, title=state.title,
            severity=state.severity, state="open", first_seen_at=seen_at, last_seen_at=seen_at,
            affected_count=state.affected_count, details=state.details,
        )
        session.add(issue)
        session.flush()
        new.append(NewIssue(issue.id, state.title))
    for code, issue in open_issues.items():
        if code not in current_codes:
            issue.state = "resolved"
            issue.resolved_at = seen_at
    return new


def _write_psi(session: Session, result: CollectResult) -> int:
    """Сохранить результаты PSI: одна запись на URL, устройство и день."""
    if not result.psi:
        return 0
    for run in result.psi:
        # Повторный запуск в тот же день заменяет предыдущий результат.
        session.execute(
            PsiRun.__table__.delete().where(
                PsiRun.monitored_url_id == run.monitored_url_id,
                PsiRun.device == run.device,
                func.date(PsiRun.run_at) == run.run_at.date(),
            )
        )
    session.execute(insert(PsiRun), [
        {"monitored_url_id": r.monitored_url_id, "run_at": r.run_at, "device": r.device,
         "performance_score": r.performance_score, "field_lcp": r.field_lcp,
         "field_inp": r.field_inp, "field_cls": r.field_cls, "field_fcp": r.field_fcp,
         "field_ttfb": r.field_ttfb, "field_category": r.field_category,
         "is_origin_fallback": r.is_origin_fallback} for r in result.psi
    ])
    return len(result.psi)


def _write_keywords(session: Session, integration_id: int, result: CollectResult) -> int:
    """Сохранить запросы и позиции; секции таблицы позиций создаются по мере надобности."""
    if not result.keywords:
        return 0
    _upsert(
        session, Keyword,
        [{"integration_id": integration_id, "external_keyword_id": k.external_keyword_id,
          "keyword": k.keyword, "search_engine": k.search_engine, "region": k.region,
          "device": k.device, "group_name": k.group_name, "is_active": True}
         for k in result.keywords],
        key=["integration_id", "external_keyword_id", "search_engine", "region", "device"],
        update_cols=["keyword", "group_name", "is_active"],
    )
    ids = {
        (row.external_keyword_id, row.search_engine, row.region, row.device): row.id
        for row in session.execute(
            select(Keyword.id, Keyword.external_keyword_id, Keyword.search_engine,
                   Keyword.region, Keyword.device).where(Keyword.integration_id == integration_id)
        )
    }
    rows = []
    months: set[date] = set()
    for k in result.keywords:
        keyword_id = ids[(k.external_keyword_id, k.search_engine, k.region, k.device)]
        for check_date, position, url in k.positions:
            months.add(check_date.replace(day=1))
            rows.append({"keyword_id": keyword_id, "check_date": check_date,
                         "position": position, "url": url})
    for month in sorted(months):
        session.execute(text("SELECT ensure_keyword_positions_partition(:d)"), {"d": month})
    return _upsert(session, KeywordPosition, rows, key=["keyword_id", "check_date"],
                   update_cols=["position", "url"])
