"""Состав команды и журнал действий сотрудников (только администратор)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Admin, DbSession, User
from app.api.schemas import ActivityIn, ActivityOut, TeamMemberIn, TeamMemberOut
from app.config import get_settings
from app.models import ActivityLog, TeamMember
from app.models.team import EVENT_LOGIN, EVENT_VIEW
from app.services.activity import log_event
from app.services.audit import audit

router = APIRouter(tags=["team"])


# ------------------------------------------------------------------ команда
@router.get("/team", response_model=list[TeamMemberOut])
def list_team(_: Admin, db: DbSession) -> list[TeamMember]:
    """Все сотрудники, включая выключенных."""
    return list(db.scalars(select(TeamMember).order_by(TeamMember.is_active.desc(),
                                                        TeamMember.full_name)))


def _save(db, member: TeamMember) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Сотрудник с таким именем уже есть") from exc


@router.post("/team", response_model=TeamMemberOut, status_code=status.HTTP_201_CREATED)
def add_member(payload: TeamMemberIn, user: Admin, db: DbSession) -> TeamMember:
    """Добавить сотрудника в список выбора при входе."""
    member = TeamMember(full_name=payload.full_name, is_active=True)
    db.add(member)
    _save(db, member)
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="create",
          entity="team_member", entity_id=member.id, changes={"full_name": member.full_name})
    db.commit()
    return member


def _get_member(db, member_id: int) -> TeamMember:
    member = db.get(TeamMember, member_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    return member


@router.patch("/team/{member_id}", response_model=TeamMemberOut)
def rename_member(member_id: int, payload: TeamMemberIn, user: Admin,
                  db: DbSession) -> TeamMember:
    """Переименовать сотрудника; новое имя сразу появляется в журналах и пометках."""
    member = _get_member(db, member_id)
    changes = {"old_name": member.full_name, "full_name": payload.full_name}
    member.full_name = payload.full_name
    _save(db, member)
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="update",
          entity="team_member", entity_id=member.id, changes=changes)
    db.commit()
    return member


@router.post("/team/{member_id}/active", response_model=TeamMemberOut)
def set_member_active(member_id: int, is_active: bool, user: Admin,
                      db: DbSession) -> TeamMember:
    """Выключить или снова включить сотрудника.

    Выключенный сотрудник исчезает из списка при входе, его текущая сессия
    завершается; записи в журналах сохраняются.
    """
    member = _get_member(db, member_id)
    member.is_active = is_active
    audit(db, account_id=user.account_id, actor_name=user.actor_name,
          action="restore" if is_active else "disable", entity="team_member",
          entity_id=member.id, changes={"full_name": member.full_name})
    db.commit()
    return member


# ----------------------------------------------------------- журнал действий
@router.post("/activity", status_code=status.HTTP_204_NO_CONTENT)
def track_view(payload: ActivityIn, user: User, db: DbSession) -> None:
    """Записать просмотр страницы (отправляется интерфейсом при переходах)."""
    if log_event(db, account_id=user.account_id, member_id=user.member_id,
                 actor_name=user.actor_name, event=EVENT_VIEW, path=payload.path):
        db.commit()


@router.get("/activity", response_model=list[ActivityOut])
def activity_log(_: Admin, db: DbSession, member_id: int | None = None,
                 date_from: date | None = None, date_to: date | None = None,
                 event: str | None = None, limit: int = 500) -> list[ActivityLog]:
    """События журнала действий с фильтрами по сотруднику, датам и типу события."""
    tz = get_settings().tz
    stmt = select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(min(limit, 2000))
    if member_id is not None:
        stmt = stmt.where(ActivityLog.member_id == member_id)
    if event:
        stmt = stmt.where(ActivityLog.event == event)
    if date_from:
        stmt = stmt.where(ActivityLog.created_at >= datetime.combine(date_from, datetime.min.time(),
                                                                     tzinfo=tz))
    if date_to:
        stmt = stmt.where(ActivityLog.created_at < datetime.combine(
            date_to + timedelta(days=1), datetime.min.time(), tzinfo=tz))
    return list(db.scalars(stmt))


@router.get("/activity/summary")
def activity_summary(_: Admin, db: DbSession, days: int = 7) -> list[dict]:
    """Сводка по сотрудникам: последний вход, число входов и просмотров за период."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(
            TeamMember.id, TeamMember.full_name, TeamMember.is_active,
            func.max(ActivityLog.created_at).filter(ActivityLog.event == EVENT_LOGIN),
            func.max(ActivityLog.created_at),
            func.count(ActivityLog.id).filter(ActivityLog.event == EVENT_LOGIN,
                                              ActivityLog.created_at >= since),
            func.count(ActivityLog.id).filter(ActivityLog.event == EVENT_VIEW,
                                              ActivityLog.created_at >= since),
        )
        .outerjoin(ActivityLog, ActivityLog.member_id == TeamMember.id)
        .group_by(TeamMember.id)
        .order_by(TeamMember.is_active.desc(), TeamMember.full_name)
    ).all()
    return [{"member_id": r[0], "full_name": r[1], "is_active": r[2], "last_login": r[3],
             "last_activity": r[4], "logins": r[5], "views": r[6], "days": days} for r in rows]
