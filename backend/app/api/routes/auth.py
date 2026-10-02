"""Вход с выбором сотрудника, выход и управление паролями.

Вход двухшаговый:

1. ``POST /auth/login`` — логин и пароль. Если пароль верный, в сессии сохраняется
   «ожидающий» вход, а в ответе приходит список сотрудников команды. Список
   отдаётся только после проверки пароля и наружу не публикуется.
2. ``POST /auth/member`` — выбор сотрудника. Только после этого сессия становится
   рабочей. Без выбора имени войти нельзя.

Администратор имя не выбирает: учётная запись администратора одна и
закреплена за одним человеком, вход для него завершается на первом шаге.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import Admin, DbSession, User, session_stamp
from app.api.schemas import (
    AccountOut,
    LoginIn,
    LoginStepOut,
    MemberChoiceIn,
    MeOut,
    PasswordIn,
    TeamMemberShort,
)
from app.models import Account, TeamMember
from app.models.team import EVENT_LOGIN, EVENT_LOGOUT
from app.security import hash_password, verify_password
from app.services.activity import log_event
from app.services.audit import audit

router = APIRouter(tags=["auth"])

#: Имя администратора в журналах и пометках.
BOOTSTRAP_ADMIN_NAME = "Администратор"


def _active_members(db) -> list[TeamMember]:
    return list(db.scalars(select(TeamMember).where(TeamMember.is_active.is_(True))
                           .order_by(TeamMember.full_name)))


def _start_session(request: Request, db, account: Account, member: TeamMember | None) -> MeOut:
    """Сделать сессию рабочей и записать вход в журнал действий."""
    actor_name = member.full_name if member else BOOTSTRAP_ADMIN_NAME
    request.session.clear()
    request.session.update({
        "account_id": account.id,
        "member_id": member.id if member else None,
        "actor_name": actor_name,
        "stamp": session_stamp(account),
    })
    log_event(db, account_id=account.id, member_id=member.id if member else None,
              actor_name=actor_name, event=EVENT_LOGIN)
    db.commit()
    return MeOut(account_id=account.id, login=account.login, role=account.role,
                 actor_name=actor_name, member_id=member.id if member else None)


@router.post("/auth/login", response_model=LoginStepOut)
def login(payload: LoginIn, request: Request, db: DbSession) -> LoginStepOut:
    """Шаг 1: проверить логин и пароль и вернуть список сотрудников для выбора."""
    account = db.scalar(select(Account).where(Account.login == payload.login))
    if account is None or not account.is_active or not verify_password(
            account.password_hash, payload.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    if account.role == "admin":
        return LoginStepOut(status="done", me=_start_session(request, db, account, None))
    members = _active_members(db)
    if not members:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Список команды пуст. Обратитесь к администратору.")
    request.session.clear()
    request.session.update({"pending_account_id": account.id,
                            "pending_stamp": session_stamp(account)})
    return LoginStepOut(status="choose_member",
                        members=[TeamMemberShort(id=m.id, full_name=m.full_name)
                                 for m in members])


@router.post("/auth/member", response_model=MeOut)
def choose_member(payload: MemberChoiceIn, request: Request, db: DbSession) -> MeOut:
    """Шаг 2: выбрать себя из списка команды и завершить вход."""
    account_id = request.session.get("pending_account_id")
    account = db.get(Account, account_id) if account_id else None
    if account is None or request.session.get("pending_stamp") != session_stamp(account):
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Введите логин и пароль заново")
    member = db.get(TeamMember, payload.member_id)
    if member is None or not member.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Выберите сотрудника из списка")
    return _start_session(request, db, account, member)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: DbSession) -> None:
    """Завершить сессию и записать выход в журнал действий."""
    account_id = request.session.get("account_id")
    if account_id:
        log_event(db, account_id=account_id, member_id=request.session.get("member_id"),
                  actor_name=request.session.get("actor_name", "?"), event=EVENT_LOGOUT)
        db.commit()
    request.session.clear()


@router.get("/auth/me", response_model=MeOut)
def me(user: User) -> MeOut:
    """Текущий пользователь."""
    return MeOut(account_id=user.account_id, login=user.login, role=user.role,
                 actor_name=user.actor_name, member_id=user.member_id)


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(_: Admin, db: DbSession) -> list[Account]:
    """Список учётных записей (только администратор)."""
    return list(db.scalars(select(Account).order_by(Account.id)))


@router.post("/accounts/{account_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(account_id: int, payload: PasswordIn, request: Request, user: Admin,
                    db: DbSession) -> None:
    """Сменить пароль учётной записи; активные сессии этой записи завершаются."""
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Учётная запись не найдена")
    try:
        account.password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    account.password_changed_at = datetime.now(UTC)
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="change_password",
          entity="account", entity_id=account.id, changes={"login": account.login})
    db.commit()
    if account.id == user.account_id:
        # Собственная сессия администратора остаётся действительной.
        request.session["stamp"] = session_stamp(account)
