"""Планировщик сбора внутри приложения (отдельная служба не нужна).

* Ежедневный сбор — по расписанию (по умолчанию в 04:00 по времени приложения).
* При старте приложение догоняет пропущенный запуск, если в момент расписания
  оно не работало.
* Разовые задачи (загрузка истории, ручной перезапуск) выполняются в пуле потоков
  планировщика.

Приложение должно работать в одном процессе (uvicorn без ``--workers``);
дополнительная защита от параллельного сбора — advisory-блокировка в БД.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.db import session_scope
from app.models.sync import JOB_BACKFILL, JOB_MANUAL
from app.services import collector

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler | None:
    """Запущенный планировщик или ``None``, если он отключён."""
    return _scheduler


def start_scheduler() -> BackgroundScheduler | None:
    """Запустить планировщик и при необходимости догнать пропущенный сбор."""
    global _scheduler
    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.info("Планировщик отключён (SCHEDULER_ENABLED=false)")
        return None
    scheduler = BackgroundScheduler(
        timezone=settings.tz,
        executors={"default": ThreadPoolExecutor(max_workers=3)},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    scheduler.add_job(
        collector.run_daily_sync, CronTrigger(hour=settings.daily_sync_hour,
                                              minute=settings.daily_sync_minute),
        id="daily_sync", replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    if _missed_daily_run():
        logger.info("Пропущен ежедневный сбор — запускаю догоняющий сбор")
        scheduler.add_job(collector.run_daily_sync, id="daily_sync_catchup",
                          replace_existing=True)
    return scheduler


def shutdown_scheduler() -> None:
    """Остановить планировщик, не дожидаясь завершения длинных задач."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _missed_daily_run() -> bool:
    """Был ли пропущен последний плановый ежедневный сбор."""
    settings = get_settings()
    now = datetime.now(settings.tz)
    scheduled_today = now.replace(hour=settings.daily_sync_hour,
                                  minute=settings.daily_sync_minute, second=0, microsecond=0)
    expected = now.date() if now >= scheduled_today else now.date() - timedelta(days=1)
    with session_scope() as session:
        if not collector.active_integration_ids(session):
            return False
        last = collector.last_daily_run_date(session)
    return last is None or last < expected


def _submit(func, job_id: str, **kwargs) -> None:
    """Поставить разовую задачу; без планировщика (тесты, CLI) выполнить сразу."""
    if _scheduler is None:
        func(**kwargs)
        return
    _scheduler.add_job(func, id=job_id, kwargs=kwargs, replace_existing=True)


def submit_backfill(integration_id: int, actor_name: str | None = None) -> None:
    """Поставить загрузку истории после подключения системы."""
    _submit(collector.run_integration_sync, f"backfill_{integration_id}",
            integration_id=integration_id, job_type=JOB_BACKFILL, actor_name=actor_name)


def submit_manual_sync(integration_id: int, date_from: date, date_to: date,
                       actor_name: str) -> None:
    """Поставить ручной перезапуск сбора за период."""
    _submit(collector.run_integration_sync, f"manual_{integration_id}",
            integration_id=integration_id, job_type=JOB_MANUAL, date_from=date_from,
            date_to=date_to, actor_name=actor_name)


def submit_daily_sync() -> None:
    """Запустить ежедневный сбор немедленно (кнопка администратора)."""
    _submit(collector.run_daily_sync, "daily_sync_now")
