"""Операции над проектами: адрес (slug), удаление проекта и подключений, отметки календаря."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Annotation,
    CwvWeekly,
    DailyMetric,
    FavoriteProject,
    Integration,
    Keyword,
    MonitoredUrl,
    PeriodMetric,
    Project,
    PsiRun,
    Signal,
    SignalRule,
    SiteIssue,
    SitemapSnapshot,
    SyncRun,
)

#: Метрики, по наличию которых определяется день съёма позиций.
POSITION_CHECK_METRICS = ("topvisor.keywords_total", "seranking.keywords_total")


def slugify_domain(domain: str) -> str:
    """Построить адрес проекта из домена: точки и прочие знаки заменяются дефисом.

    ``auto-parts.kz`` → ``auto-parts-kz``. Адрес из одних цифр получает префикс,
    чтобы не путаться с числовым ID проекта.
    """
    slug = re.sub(r"[^\w]+", "-", domain.strip().lower().replace("_", "-")).strip("-")
    if not slug:
        slug = "project"
    return f"site-{slug}" if slug.isdigit() else slug


def unique_slug(session: Session, domain: str, exclude_id: int | None = None) -> str:
    """Подобрать свободный адрес проекта: при совпадении добавляется ``-2``, ``-3`` и т. д."""
    base = slugify_domain(domain)
    taken = set(session.scalars(
        select(Project.slug).where(Project.slug.like(f"{base}%"), Project.id != (exclude_id or 0))
    ))
    slug, number = base, 1
    while slug in taken:
        number += 1
        slug = f"{base}-{number}"
    return slug


def find_project(session: Session, ref: str | int) -> Project | None:
    """Найти проект по адресу (slug) или числовому ID."""
    text = str(ref)
    if text.isdigit():
        return session.get(Project, int(text))
    return session.scalar(select(Project).where(Project.slug == text))


def delete_project(session: Session, project: Project) -> dict[str, int]:
    """Полностью удалить проект со всеми подключениями и накопленной историей.

    Действие необратимо. Доступы (``credentials``) и журнал изменений сохраняются.

    Returns:
        Количество удалённых строк по основным таблицам — для журнала изменений.
    """
    integrations = list(session.scalars(
        select(Integration).where(Integration.project_id == project.id)))
    url_ids = list(session.scalars(
        select(MonitoredUrl.id).where(MonitoredUrl.project_id == project.id)))
    stats = delete_integrations(session, integrations)

    def purge(model, condition) -> None:
        session.execute(delete(model).where(condition))

    if url_ids:
        purge(PsiRun, PsiRun.monitored_url_id.in_(url_ids))
    purge(MonitoredUrl, MonitoredUrl.project_id == project.id)
    purge(SignalRule, SignalRule.project_id == project.id)
    purge(Annotation, Annotation.project_id == project.id)
    session.delete(project)
    return stats


def delete_integrations(session: Session, integrations: list[Integration]) -> dict[str, int]:
    """Удалить подключения вместе с собранной по ним историей. Действие необратимо.

    Returns:
        Количество удалённых строк по основным таблицам — для журнала изменений.
    """
    ids = [i.id for i in integrations]
    stats: dict[str, int] = {"integrations": len(ids)}
    if not ids:
        return stats

    def purge(model, column, key: str | None = None) -> None:
        result = session.execute(delete(model).where(column.in_(ids)))
        if key:
            stats[key] = result.rowcount or 0

    purge(Signal, Signal.integration_id)
    # Позиции удаляются каскадно вместе с запросами.
    purge(Keyword, Keyword.integration_id, "keywords")
    purge(SiteIssue, SiteIssue.integration_id)
    purge(SitemapSnapshot, SitemapSnapshot.integration_id)
    purge(CwvWeekly, CwvWeekly.integration_id)
    purge(PeriodMetric, PeriodMetric.integration_id)
    purge(DailyMetric, DailyMetric.integration_id, "daily_metrics")
    # Сырые ответы удаляются каскадно вместе с запусками.
    purge(SyncRun, SyncRun.integration_id, "sync_runs")
    for integration in integrations:
        session.delete(integration)  # вместе с избранными целями (cascade)
    session.flush()
    return stats


def calendar_marks(session: Session, project: Project) -> dict[str, Any]:
    """Отметки для календаря выбора периода.

    Returns:
        ``checks`` — даты съёмов позиций; ``alerts`` — даты, когда обнаружены резкие
        изменения, новые ошибки диагностики или ошибки карт сайта; ``history_from`` —
        первая дата, за которую есть данные.
    """
    ids = list(session.scalars(select(Integration.id).where(
        Integration.project_id == project.id, Integration.disabled_at.is_(None))))
    if not ids:
        return {"checks": [], "alerts": [], "history_from": None}

    checks = set(session.scalars(select(DailyMetric.date).distinct().where(
        DailyMetric.integration_id.in_(ids), DailyMetric.metric_code.in_(POSITION_CHECK_METRICS))))
    alerts: set[date] = set()
    alerts |= set(session.scalars(select(func.date(Signal.detected_at)).distinct().where(
        Signal.integration_id.in_(ids))))
    alerts |= set(session.scalars(select(func.date(SiteIssue.first_seen_at)).distinct().where(
        SiteIssue.integration_id.in_(ids))))
    alerts |= set(session.scalars(select(SitemapSnapshot.snapshot_date).distinct().where(
        SitemapSnapshot.integration_id.in_(ids), SitemapSnapshot.status == "error")))
    history_from = session.scalar(select(func.min(DailyMetric.date)).where(
        DailyMetric.integration_id.in_(ids)))
    return {
        "checks": sorted(d.isoformat() for d in checks),
        "alerts": sorted(d.isoformat() for d in alerts if d is not None),
        "history_from": history_from.isoformat() if history_from else None,
    }


def favorite_project_ids(session: Session, owner: str) -> set[int]:
    """ID проектов, отмеченных сотрудником как избранные."""
    return set(session.scalars(
        select(FavoriteProject.project_id).where(FavoriteProject.owner == owner)))
