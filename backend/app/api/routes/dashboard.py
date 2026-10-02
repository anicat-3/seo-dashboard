"""Сводный экран, дашборд проекта и детализация."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, PeriodParams, User, get_project_or_404
from app.models import Integration, Keyword, KeywordPosition, SiteIssue, SitemapSnapshot
from app.services import dashboard as dashboard_service
from app.services.periods import Granularity

router = APIRouter(tags=["dashboard"])


def csv_response(filename: str, header: Sequence[str],
                 rows: Iterable[Sequence[Any]]) -> StreamingResponse:
    """CSV для Excel: UTF-8 с BOM и разделитель «;»."""
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _integration(db: Session, integration_id: int, systems: set[str] | None = None) -> Integration:
    integration = db.get(Integration, integration_id)
    if integration is None or (systems and integration.system_code not in systems):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подключение не найдено")
    return integration


@router.get("/overview")
def overview(user: User, db: DbSession, period: PeriodParams) -> dict:
    """Сводная таблица проектов (сначала избранные сотрудника) с изменениями и сигналами."""
    return dashboard_service.overview(db, period, owner=user.owner_key)


@router.get("/projects/{project_id}/dashboard")
def project_dashboard(
    project_id: str, _: User, db: DbSession, period: PeriodParams,
    granularity: Annotated[
        Granularity | None,
        Query(description="Группировка графиков; по умолчанию подбирается по длине периода"),
    ] = None,
) -> dict:
    """Дашборд проекта за период со сравнением."""
    project = get_project_or_404(db, project_id)
    return dashboard_service.project_dashboard(db, project, period, granularity=granularity)


# ------------------------------------------------------------------ позиции
def _latest_positions(db: Session, keyword_ids: list[int], date_from: date,
                      date_to: date) -> dict[int, tuple[date, int | None, str | None]]:
    """Последняя позиция каждого запроса в диапазоне дат."""
    if not keyword_ids:
        return {}
    stmt = (
        select(KeywordPosition.keyword_id, KeywordPosition.check_date,
               KeywordPosition.position, KeywordPosition.url)
        .where(KeywordPosition.keyword_id.in_(keyword_ids),
               KeywordPosition.check_date.between(date_from, date_to))
        .distinct(KeywordPosition.keyword_id)
        .order_by(KeywordPosition.keyword_id, KeywordPosition.check_date.desc())
    )
    return {row.keyword_id: (row.check_date, row.position, row.url) for row in db.execute(stmt)}


@router.get("/integrations/{integration_id}/keywords")
def keywords(
    integration_id: int, _: User, db: DbSession, period: PeriodParams,
    segment: str | None = Query(None, description="поисковик:регион"),
    group: str | None = None,
    search: str | None = None,
    top: int | None = Query(None, description="Показать только запросы в ТОП-N"),
    format: str = Query("json", pattern="^(json|csv)$"),
) -> Any:
    """Позиции по запросам за период со сравнением, фильтрами и выгрузкой в CSV."""
    integration = _integration(db, integration_id, {"topvisor", "seranking"})
    current, base = period.period, period.base
    stmt = select(Keyword).where(Keyword.integration_id == integration.id,
                                 Keyword.is_active.is_(True))
    if segment and ":" in segment:
        engine, region = segment.split(":", 1)
        stmt = stmt.where(Keyword.search_engine == engine, Keyword.region == region)
    if group:
        stmt = stmt.where(Keyword.group_name == group)
    if search:
        stmt = stmt.where(Keyword.keyword.ilike(f"%{search}%"))
    kws = db.scalars(stmt.order_by(Keyword.keyword)).all()
    ids = [k.id for k in kws]
    now = _latest_positions(db, ids, current.date_from, current.date_to)
    before = _latest_positions(db, ids, base.date_from, base.date_to)

    rows = []
    for k in kws:
        n, b = now.get(k.id), before.get(k.id)
        pos_now, pos_before = (n[1] if n else None), (b[1] if b else None)
        if top and (pos_now is None or pos_now > top):
            continue
        rows.append({
            "keyword_id": k.id, "keyword": k.keyword, "group": k.group_name,
            "segment": f"{k.search_engine}:{k.region}", "device": k.device,
            "position": pos_now, "position_before": pos_before,
            "change": (pos_before - pos_now) if pos_now and pos_before else None,
            "check_date": n[0].isoformat() if n else None,
            "check_date_before": b[0].isoformat() if b else None,
            "url": n[2] if n else None,
        })
    dates_now = sorted({r["check_date"] for r in rows if r["check_date"]})
    dates_before = sorted({r["check_date_before"] for r in rows if r["check_date_before"]})
    if format == "csv":
        # Если у всех запросов один день съёма — дата в заголовке колонки,
        # иначе отдельные колонки с датой съёма для каждого запроса.
        same_now, same_before = len(dates_now) <= 1, len(dates_before) <= 1
        header = ["Запрос", "Группа", "Поисковик:регион",
                  _position_header(dates_now, "последний съём"),
                  _position_header(dates_before, "съём в базе сравнения"),
                  "Изменение, позиций"]
        header += ([] if same_now else ["Дата съёма"]) + ([] if same_before else
                                                         ["Дата съёма в базе сравнения"])
        header.append("URL")

        def csv_row(r: dict) -> list:
            row = [r["keyword"], r["group"], r["segment"], r["position"], r["position_before"],
                   r["change"]]
            row += ([] if same_now else [r["check_date"]])
            row += ([] if same_before else [r["check_date_before"]])
            return [*row, r["url"]]

        return csv_response(f"positions_{integration.id}_{current.date_to}.csv", header,
                            (csv_row(r) for r in rows))
    groups = sorted({k.group_name for k in kws if k.group_name})
    segments = sorted({f"{s}:{r}" for s, r in db.execute(
        select(Keyword.search_engine, Keyword.region).distinct()
        .where(Keyword.integration_id == integration.id))})
    return {"rows": rows, "groups": groups, "segments": segments,
            "check_dates": dates_now, "check_dates_before": dates_before,
            "period": {"date_from": current.date_from, "date_to": current.date_to},
            "compare": {"date_from": base.date_from, "date_to": base.date_to}}


def _position_header(dates: list[str], fallback: str) -> str:
    """Заголовок колонки позиций: с датой съёма, если она у всех запросов одна."""
    if len(dates) == 1:
        return f"Позиция {date.fromisoformat(dates[0]).strftime('%d.%m.%Y')}"
    return f"Позиция ({fallback})"


@router.get("/integrations/{integration_id}/keywords/{keyword_id}/history")
def keyword_history(integration_id: int, keyword_id: int, _: User, db: DbSession,
                    period: PeriodParams) -> list[dict]:
    """История позиций одного запроса за период."""
    _integration(db, integration_id)
    current = period.period
    stmt = select(KeywordPosition).join(Keyword).where(
        Keyword.integration_id == integration_id, KeywordPosition.keyword_id == keyword_id,
        KeywordPosition.check_date.between(current.date_from, current.date_to),
    ).order_by(KeywordPosition.check_date)
    return [{"date": p.check_date, "position": p.position, "url": p.url} for p in db.scalars(stmt)]


# ------------------------------------------------------- ошибки и карты сайта
@router.get("/integrations/{integration_id}/issues")
def issues(integration_id: int, _: User, db: DbSession,
           state: str = Query("all", pattern="^(all|open|resolved)$"),
           format: str = Query("json", pattern="^(json|csv)$")) -> Any:
    """Ошибки диагностики с историей появления и исправления."""
    _integration(db, integration_id, {"ywm"})
    stmt = select(SiteIssue).where(SiteIssue.integration_id == integration_id)
    if state != "all":
        stmt = stmt.where(SiteIssue.state == state)
    items = db.scalars(stmt.order_by(SiteIssue.state, SiteIssue.first_seen_at.desc())).all()
    rows = [{"id": i.id, "issue_code": i.issue_code, "title": i.title, "severity": i.severity,
             "state": i.state, "first_seen_at": i.first_seen_at, "last_seen_at": i.last_seen_at,
             "resolved_at": i.resolved_at, "affected_count": i.affected_count} for i in items]
    if format == "csv":
        return csv_response(
            f"issues_{integration_id}.csv",
            ["Код", "Ошибка", "Критичность", "Состояние", "Появилась", "Последний раз",
             "Исправлена", "Затронуто"],
            ([r["issue_code"], r["title"], r["severity"], r["state"], r["first_seen_at"],
              r["last_seen_at"], r["resolved_at"], r["affected_count"]] for r in rows),
        )
    return rows


@router.get("/integrations/{integration_id}/sitemaps")
def sitemaps(integration_id: int, _: User, db: DbSession, period: PeriodParams,
             format: str = Query("json", pattern="^(json|csv)$")) -> Any:
    """История снимков карт сайта за период."""
    _integration(db, integration_id, {"gsc", "ywm", "bing"})
    current = period.period
    items = db.scalars(select(SitemapSnapshot).where(
        SitemapSnapshot.integration_id == integration_id,
        SitemapSnapshot.snapshot_date.between(current.date_from, current.date_to),
    ).order_by(SitemapSnapshot.snapshot_date.desc(), SitemapSnapshot.sitemap_url)).all()
    rows = [{"snapshot_date": s.snapshot_date, "sitemap_url": s.sitemap_url,
             "status": s.status, "submitted_urls": s.submitted_urls, "errors": s.errors,
             "warnings": s.warnings, "last_downloaded_at": s.last_downloaded_at}
            for s in items]
    if format == "csv":
        return csv_response(
            f"sitemaps_{integration_id}.csv",
            ["Дата", "Карта сайта", "Статус", "URL", "Ошибки", "Предупреждения",
             "Последняя загрузка"],
            ([r["snapshot_date"], r["sitemap_url"], r["status"], r["submitted_urls"],
              r["errors"], r["warnings"], r["last_downloaded_at"]] for r in rows),
        )
    return rows
