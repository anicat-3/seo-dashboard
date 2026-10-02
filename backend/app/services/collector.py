"""Запуск коннекторов: ежедневный сбор, загрузка истории, ручной перезапуск.

Каждый запуск пишет запись в ``sync_runs``.
"""

from __future__ import annotations

import logging
import time as time_module
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.catalog import METRICS
from app.config import get_settings
from app.connectors.base import (
    AuthError,
    CollectResult,
    Connector,
    ConnectorError,
    IntegrationContext,
    QuotaError,
)
from app.connectors.registry import get_connector
from app.db import session_scope
from app.models import Credential, Integration, MonitoredUrl, Project, RawResponse, SyncRun
from app.models.metrics import AGG_PERIOD_ONLY
from app.models.sync import JOB_BACKFILL, JOB_DAILY, JOB_MANUAL
from app.security import decrypt_secret, encrypt_secret
from app.services import signals as signal_service
from app.services.periods import Period, standard_periods
from app.services.writer import NewIssue, write_period_values, write_result

logger = logging.getLogger(__name__)

#: Пауза перед повторами при превышении квоты.
QUOTA_RETRY_DELAYS: tuple[float, ...] = (5.0, 20.0, 60.0)

#: Размер окна при загрузке длинной истории: API отдают данные частями.
BACKFILL_CHUNK_DAYS = 31

#: Ключ advisory-блокировки PostgreSQL для ежедневного сбора (один запуск на БД).
DAILY_LOCK_KEY = 804_221_001

#: Системы с несуммируемыми метриками, для которых готовятся итоги за периоды.
PERIOD_SYSTEMS = {m.system_code for m in METRICS if m.aggregation == AGG_PERIOD_ONLY}
PERIOD_SEGMENTS = ["all", "organic"]


@dataclass(slots=True)
class SyncOutcome:
    """Итог запуска коннектора."""

    sync_run_id: int
    status: str
    rows_written: int
    new_issues: list[NewIssue]
    error: str | None = None


def source_yesterday(integration: Integration, now: datetime | None = None) -> date:
    """«Вчера» в часовом поясе источника данных."""
    now = now or datetime.now(UTC)
    try:
        tz = ZoneInfo(integration.timezone)
    except (KeyError, ValueError):
        tz = UTC
    return now.astimezone(tz).date() - timedelta(days=1)


def build_context(session: Session, integration: Integration) -> IntegrationContext:
    """Собрать параметры подключения для коннектора."""
    project = session.get(Project, integration.project_id)
    urls = session.execute(
        select(MonitoredUrl.id, MonitoredUrl.url).where(
            MonitoredUrl.project_id == integration.project_id, MonitoredUrl.is_active.is_(True)
        ).order_by(MonitoredUrl.id)
    ).all()
    return IntegrationContext(
        integration_id=integration.id,
        external_id=integration.external_id,
        timezone=integration.timezone,
        settings=dict(integration.settings or {}),
        goal_ids=[g.external_goal_id for g in integration.goals if g.is_favorite],
        monitored_urls=[(row.id, row.url) for row in urls],
        domain=project.domain if project else "",
    )


def credential_secret(credential: Credential) -> dict:
    """Расшифровать секрет доступа."""
    if not credential.secret_encrypted:
        return {}
    return decrypt_secret(credential.secret_encrypted)


def persist_secret(credential: Credential | None, connector: Connector) -> None:
    """Сохранить секрет, если коннектор обновил его (новый OAuth-токен)."""
    if credential is not None and connector.secret_updated:
        credential.secret_encrypted = encrypt_secret(connector.secret)
        connector.secret_updated = False


def make_connector(session: Session, integration: Integration) -> Connector:
    """Создать коннектор подключения с расшифрованным секретом и контекстом."""
    credential = session.get(Credential, integration.credential_id)
    if credential is None:
        raise ConnectorError("Доступ подключения удалён")
    return get_connector(integration.system_code, credential.auth_type,
                         credential_secret(credential), build_context(session, integration))


def _with_quota_retries(call, delays: tuple[float, ...] = QUOTA_RETRY_DELAYS):
    """Выполнить вызов API, повторяя его при превышении квоты с нарастающей паузой.

    Raises:
        QuotaError: Квота превышена и после всех повторов.
    """
    for attempt, delay in enumerate((*delays, None)):
        try:
            return call()
        except QuotaError:
            if delay is None:
                raise
            logger.warning("Квота API превышена, повтор %s через %s с", attempt + 1, delay)
            time_module.sleep(delay)
    raise AssertionError("unreachable")


def _collect_windows(connector: Connector, job_type: str, date_from: date,
                     date_to: date) -> CollectResult:
    """Выполнить сбор; длинную историю — частями по :data:`BACKFILL_CHUNK_DAYS` дней."""
    if job_type == JOB_BACKFILL:
        merged = CollectResult()
        chunk_end = date_to
        # Идём от свежих дат к старым: снимки состояния берутся из первого (свежего) окна.
        first = True
        while chunk_end >= date_from:
            chunk_start = max(date_from, chunk_end - timedelta(days=BACKFILL_CHUNK_DAYS - 1))
            part = _with_quota_retries(lambda s=chunk_start, e=chunk_end:
                                       connector.backfill(s, e))
            merged.daily += part.daily
            merged.period += part.period
            merged.cwv += part.cwv
            merged.psi += part.psi
            merged.keywords += part.keywords
            merged.raw += part.raw
            merged.messages += part.messages
            merged.partial = merged.partial or part.partial
            if first:
                merged.sitemaps, merged.issues = part.sitemaps, part.issues
                merged.snapshot_date = part.snapshot_date
                first = False
            if connector.backfill_in_one_call():
                break
            chunk_end = chunk_start - timedelta(days=1)
        return merged
    return _with_quota_retries(lambda: connector.collect(date_from, date_to))


def _resolve_window(session: Session, integration: Integration, connector: Connector,
                    job_type: str, date_from: date | None, date_to: date | None) -> Period:
    """Определить окно дат запуска."""
    settings = get_settings()
    yesterday = source_yesterday(integration)
    if job_type == JOB_MANUAL and date_from and date_to:
        return Period(date_from, min(date_to, yesterday))
    if job_type == JOB_BACKFILL:
        history = connector.history_days or 1
        start = integration.collect_from or (yesterday - timedelta(days=history - 1))
        return Period(min(start, yesterday), yesterday)
    # Ежедневный сбор: окно перезаписи, расширенное до последнего успешного запуска,
    # если приложение не работало несколько дней.
    start = yesterday - timedelta(days=settings.rewrite_window_days - 1)
    last_ok = session.scalar(
        select(func.max(SyncRun.date_to)).where(
            SyncRun.integration_id == integration.id,
            SyncRun.status.in_(("success", "partial")),
        )
    )
    if last_ok is not None and last_ok + timedelta(days=1) < start:
        start = max(last_ok + timedelta(days=1), yesterday - timedelta(days=90))
    return Period(start, yesterday)


def run_integration_sync(integration_id: int, job_type: str = JOB_DAILY,
                         date_from: date | None = None, date_to: date | None = None,
                         actor_name: str | None = None) -> SyncOutcome:
    """Выполнить один запуск коннектора по подключению и записать журнал.

    Args:
        integration_id: Подключение.
        job_type: ``daily``, ``backfill`` или ``manual``.
        date_from: Начало периода (для ручного перезапуска).
        date_to: Конец периода (для ручного перезапуска).
        actor_name: Имя сотрудника, запустившего сбор вручную.

    Returns:
        Итог запуска; исключения коннектора не пробрасываются, а фиксируются в журнале.
    """
    with session_scope() as session:
        integration = session.get(Integration, integration_id)
        if integration is None:
            raise ValueError(f"Подключение {integration_id} не найдено")
        run = SyncRun(integration_id=integration_id, job_type=job_type, status="running",
                      started_by_name=actor_name, rows_written=0)
        session.add(run)
        session.commit()
        run_id = run.id

    with session_scope() as session:
        integration = session.get(Integration, integration_id)
        run = session.get(SyncRun, run_id)
        credential = session.get(Credential, integration.credential_id)
        try:
            connector = make_connector(session, integration)
            window = _resolve_window(session, integration, connector, job_type, date_from, date_to)
            run.date_from, run.date_to = window.date_from, window.date_to
            result = _collect_windows(connector, job_type, window.date_from, window.date_to)
            if integration.system_code in PERIOD_SYSTEMS and job_type != JOB_BACKFILL:
                result.period += _fetch_standard_totals(connector, window.date_to)
            persist_secret(credential, connector)
            rows, new_issues = write_result(session, integration.id, run.id, result)
            run.rows_written = rows
            run.status = "partial" if result.partial else "success"
            run.error_message = "; ".join(result.messages) or None
            integration.status = "ok"
            integration.last_error = None
            if credential is not None and credential.status != "ok":
                credential.status, credential.status_message = "ok", None
            if credential is not None:
                credential.last_checked_at = datetime.now(UTC)
        except AuthError as exc:
            session.rollback()
            integration = session.get(Integration, integration_id)
            run = session.get(SyncRun, run_id)
            credential = session.get(Credential, integration.credential_id)
            run.status, run.error_message = "error", f"Ошибка авторизации: {exc}"
            integration.status, integration.last_error = "error", run.error_message
            if credential is not None:
                credential.status, credential.status_message = "error", str(exc)
            new_issues = []
        except QuotaError as exc:
            session.rollback()
            run = session.get(SyncRun, run_id)
            run.status, run.error_message = "partial", f"Квота API исчерпана: {exc}"
            new_issues = []
        except Exception as exc:  # noqa: BLE001 — любой сбой коннектора фиксируется в журнале
            if isinstance(exc, ConnectorError):
                # Ожидаемая ошибка внешней системы: достаточно сообщения, без трассировки.
                logger.warning("Сбор по подключению %s: %s", integration_id, exc)
            else:
                logger.exception("Сбор по подключению %s завершился ошибкой", integration_id)
            session.rollback()
            integration = session.get(Integration, integration_id)
            run = session.get(SyncRun, run_id)
            run.status, run.error_message = "error", str(exc)[:2000]
            integration.status, integration.last_error = "error", run.error_message
            new_issues = []
        run.finished_at = datetime.now(UTC)
        outcome = SyncOutcome(run.id, run.status, run.rows_written, new_issues, run.error_message)
    return outcome


def _fetch_standard_totals(connector: Connector, yesterday: date):
    """Итоги стандартных периодов по несуммируемым метрикам (пользователи и т. п.)."""
    values = []
    for period in standard_periods(yesterday):
        values += _with_quota_retries(
            lambda p=period: connector.fetch_period_totals(p.date_from, p.date_to,
                                                           PERIOD_SEGMENTS)
        )
    return values


def ensure_period_totals(session: Session, integration: Integration, period: Period,
                         segments: list[str]) -> bool:
    """Запросить у API и сохранить итоги за нестандартный период.

    Returns:
        ``True``, если итоги получены.
    """
    try:
        connector = make_connector(session, integration)
        values = connector.fetch_period_totals(period.date_from, period.date_to, segments)
        persist_secret(session.get(Credential, integration.credential_id), connector)
    except ConnectorError as exc:
        logger.warning("Итоги за период для подключения %s не получены: %s", integration.id, exc)
        return False
    write_period_values(session, integration.id, values)
    session.commit()
    return True


def active_integration_ids(session: Session) -> list[int]:
    """Активные подключения активных проектов."""
    return list(session.scalars(
        select(Integration.id).join(Project).where(
            Integration.is_active.is_(True), Project.is_active.is_(True)
        ).order_by(Integration.id)
    ))


def run_daily_sync() -> dict[str, int]:
    """Ежедневный сбор по всем активным подключениям и подсветка изменений.

    Одновременно выполняется не более одного ежедневного сбора на БД
    (advisory-блокировка PostgreSQL).

    Returns:
        Счётчики запусков по статусам.
    """
    from app.db import get_engine

    stats: dict[str, int] = {}
    with get_engine().connect() as lock_conn:
        if not lock_conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": DAILY_LOCK_KEY}):
            logger.info("Ежедневный сбор уже выполняется другим процессом")
            return stats
        try:
            with session_scope() as session:
                ids = active_integration_ids(session)
            new_issues: dict[int, list[NewIssue]] = {}
            for integration_id in ids:
                outcome = run_integration_sync(integration_id, JOB_DAILY)
                stats[outcome.status] = stats.get(outcome.status, 0) + 1
                if outcome.new_issues:
                    new_issues[integration_id] = outcome.new_issues
            with session_scope() as session:
                signal_service.detect_signals(session, new_issues=new_issues)
            cleanup_raw_responses()
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": DAILY_LOCK_KEY})
            lock_conn.commit()
    logger.info("Ежедневный сбор завершён: %s", stats)
    return stats


def cleanup_raw_responses() -> int:
    """Удалить сырые ответы старше срока хранения (по умолчанию 90 дней)."""
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().raw_retention_days)
    with session_scope() as session:
        result = session.execute(delete(RawResponse).where(RawResponse.fetched_at < cutoff))
        return result.rowcount or 0


def last_daily_run_date(session: Session) -> date | None:
    """Дата последнего ежедневного сбора (по времени приложения)."""
    started = session.scalar(
        select(func.max(SyncRun.started_at)).where(SyncRun.job_type == JOB_DAILY)
    )
    return started.astimezone(get_settings().tz).date() if started else None
