"""Экран ошибок сбора и доступов, журнал изменений."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import Admin, DbSession
from app.api.schemas import AuditOut
from app.catalog import SYSTEM_NAMES
from app.models import AuditLog, Credential, Integration, Project, SyncRun
from app.scheduler import get_scheduler, submit_daily_sync
from app.services.audit import audit

router = APIRouter(tags=["admin"])


@router.get("/admin/errors")
def errors(_: Admin, db: DbSession) -> dict:
    """Доступы и подключения в статусе «ошибка» и последние неуспешные запуски."""
    credentials = db.scalars(select(Credential).where(Credential.status == "error")
                             .order_by(Credential.system_code)).all()
    integrations = db.execute(
        select(Integration, Project.name, Project.slug).join(Project)
        .where(Integration.status == "error", Integration.disabled_at.is_(None))
        .order_by(Project.name)
    ).all()
    runs = db.execute(
        select(SyncRun, Integration.system_code, Project.name, Project.slug)
        .join(Integration, Integration.id == SyncRun.integration_id).join(Project)
        .where(SyncRun.status.in_(("error", "partial")))
        .order_by(SyncRun.started_at.desc()).limit(50)
    ).all()
    return {
        "credentials": [{"id": c.id, "system_code": c.system_code,
                         "system_name": SYSTEM_NAMES.get(c.system_code), "label": c.label,
                         "status_message": c.status_message,
                         "last_checked_at": c.last_checked_at} for c in credentials],
        "integrations": [{"id": i.id, "project_id": i.project_id, "project_name": name,
                          "system_code": i.system_code,
                          "system_name": SYSTEM_NAMES.get(i.system_code),
                          "external_id": i.external_id, "last_error": i.last_error,
                          "credential_id": i.credential_id, "project_slug": slug}
                         for i, name, slug in integrations],
        "runs": [{"id": r.id, "integration_id": r.integration_id, "system_code": code,
                  "system_name": SYSTEM_NAMES.get(code), "project_name": name,
                  "project_slug": pid, "job_type": r.job_type, "status": r.status,
                  "started_at": r.started_at, "date_from": r.date_from, "date_to": r.date_to,
                  "error_message": r.error_message} for r, code, name, pid in runs],
    }


@router.get("/admin/scheduler")
def scheduler_state(_: Admin) -> dict:
    """Состояние планировщика и время следующего ежедневного сбора."""
    scheduler = get_scheduler()
    if scheduler is None:
        return {"enabled": False, "jobs": []}
    return {"enabled": True, "jobs": [
        {"id": job.id, "next_run_time": job.next_run_time} for job in scheduler.get_jobs()
    ]}


@router.post("/admin/sync-all", status_code=status.HTTP_202_ACCEPTED)
def sync_all(user: Admin, db: DbSession) -> dict:
    """Запустить ежедневный сбор по всем подключениям немедленно."""
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="sync_all",
          entity="system")
    db.commit()
    submit_daily_sync()
    return {"status": "scheduled"}


@router.get("/audit", response_model=list[AuditOut])
def audit_log(_: Admin, db: DbSession, limit: int = 200) -> list[AuditLog]:
    """Журнал изменений настроек."""
    return list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc())
                           .limit(min(limit, 1000))))
