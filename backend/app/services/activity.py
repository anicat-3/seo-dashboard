"""Журнал действий сотрудников: входы, выходы и просмотры страниц."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityLog, Project
from app.models.team import EVENT_VIEW

#: Повторный просмотр той же страницы в течение этого времени не записывается.
VIEW_DEDUP_WINDOW = timedelta(minutes=2)

#: Названия разделов по адресу страницы (без адреса проекта).
_PAGES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/$"), "Сводка по проектам"),
    (re.compile(r"^/signals$"), "Сигналы"),
    (re.compile(r"^/projects$"), "Список проектов"),
    (re.compile(r"^/projects/[^/]+$"), "Дашборд проекта"),
    (re.compile(r"^/projects/[^/]+/settings$"), "Настройки проекта"),
    (re.compile(r"^/projects/[^/]+/keywords/\d+$"), "Позиции по запросам"),
    (re.compile(r"^/projects/[^/]+/issues/\d+$"), "Ошибки диагностики"),
    (re.compile(r"^/projects/[^/]+/sitemaps/\d+$"), "История карт сайта"),
    (re.compile(r"^/credentials$"), "Подключения API"),
    (re.compile(r"^/rules$"), "Правила подсветки"),
    (re.compile(r"^/errors$"), "Ошибки сбора"),
    (re.compile(r"^/audit$"), "Журнал изменений"),
    (re.compile(r"^/activity$"), "Журнал действий"),
    (re.compile(r"^/team$"), "Команда"),
    (re.compile(r"^/accounts$"), "Учётные записи"),
]
_PROJECT_PATH = re.compile(r"^/projects/([^/]+)")


def describe_path(session: Session, path: str) -> tuple[str, str | None]:
    """Название раздела и проекта для адреса страницы, включая выбранный период.

    Returns:
        Пару ``(раздел, название проекта или None)``.
    """
    parts = urlsplit(path)
    page = next((title for pattern, title in _PAGES if pattern.match(parts.path)), parts.path)
    query = parse_qs(parts.query)
    if "from" in query and "to" in query:
        page = f"{page} · период {query['from'][0]} — {query['to'][0]}"
    project_name = None
    match = _PROJECT_PATH.match(parts.path)
    if match:
        project = session.scalar(select(Project).where(Project.slug == match.group(1)))
        project_name = project.name if project else None
    return page[:200], project_name


def log_event(session: Session, *, account_id: int, member_id: int | None, actor_name: str,
              event: str, path: str | None = None) -> bool:
    """Записать событие журнала действий.

    Повторный просмотр той же страницы тем же сотрудником в течение
    :data:`VIEW_DEDUP_WINDOW` не записывается (обновление страницы, возврат назад).

    Returns:
        ``True``, если запись добавлена.
    """
    page = project_name = None
    if path is not None:
        path = path[:2000]
        page, project_name = describe_path(session, path)
    if event == EVENT_VIEW:
        recent = session.scalar(
            select(ActivityLog.id).where(
                ActivityLog.account_id == account_id,
                ActivityLog.member_id == member_id,
                ActivityLog.event == EVENT_VIEW,
                ActivityLog.path == path,
                ActivityLog.created_at >= datetime.now(UTC) - VIEW_DEDUP_WINDOW,
            ).limit(1)
        )
        if recent is not None:
            return False
    session.add(ActivityLog(account_id=account_id, member_id=member_id, actor_name=actor_name,
                            event=event, path=path, page=page, project_name=project_name))
    return True
