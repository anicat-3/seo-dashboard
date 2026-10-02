"""Общие зависимости API: текущий пользователь, проверка прав, разбор периода."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Account, Project, TeamMember
from app.services.periods import CompareMode, Comparison, Period, compare_period, last_days
from app.services.projects import find_project

DbSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Пользователь запроса: учётная запись и имя сотрудника из сессии."""

    account_id: int
    login: str
    role: str
    actor_name: str
    member_id: int | None = None

    @property
    def is_admin(self) -> bool:
        """Является ли учётная запись администраторской."""
        return self.role == "admin"

    @property
    def owner_key(self) -> str:
        """Владелец личных настроек (избранного): сотрудник, а без него — учётная запись.

        Под общей учётной записью работает вся команда, поэтому избранное закрепляется
        за выбранным при входе сотрудником.
        """
        return f"member:{self.member_id}" if self.member_id else f"account:{self.account_id}"


def session_stamp(account: Account) -> str:
    """Отметка версии пароля: при смене пароля старые сессии становятся недействительны."""
    return account.password_changed_at.isoformat()


def get_current_user(request: Request, db: DbSession) -> CurrentUser:
    """Вернуть пользователя по cookie сессии.

    Имя сотрудника берётся из списка команды при каждом запросе, поэтому
    переименование сразу отражается в журналах, а выключенный сотрудник
    теряет доступ без смены пароля.

    Raises:
        HTTPException: 401, если сессии нет, учётная запись отключена, пароль сменён
            или сотрудник исключён из команды.
    """
    data = request.session
    account_id = data.get("account_id")
    if not account_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
    account = db.get(Account, account_id)
    if account is None or not account.is_active or data.get("stamp") != session_stamp(account):
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия завершена, войдите снова")
    member_id = data.get("member_id")
    actor_name = data.get("actor_name", "?")
    if member_id is not None:
        member = db.get(TeamMember, member_id)
        if member is None or not member.is_active:
            request.session.clear()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                "Сотрудник исключён из команды, войдите снова")
        actor_name = member.full_name
    return CurrentUser(account.id, account.login, account.role, actor_name, member_id)


User = Annotated[CurrentUser, Depends(get_current_user)]


def require_admin(user: User) -> CurrentUser:
    """Разрешить действие только администратору."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Действие доступно только администратору")
    return user


Admin = Annotated[CurrentUser, Depends(require_admin)]


def get_project_or_404(db: Session, project_ref: str | int) -> Project:
    """Найти проект по адресу (slug) или числовому ID; иначе — 404."""
    project = find_project(db, project_ref)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    return project


def app_yesterday() -> date:
    """Вчерашний день по времени приложения — последний полный день данных."""
    return datetime.now(get_settings().tz).date() - timedelta(days=1)


def _checked_period(date_from: date, date_to: date, what: str) -> Period:
    if date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"{what}: начало позже окончания")
    if (date_to - date_from).days > 800:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{what}: не длиннее 800 дней")
    return Period(date_from, date_to)


def period_params(
    date_from: Annotated[date | None, Query(description="Начало периода, YYYY-MM-DD")] = None,
    date_to: Annotated[date | None, Query(description="Конец периода, YYYY-MM-DD")] = None,
    compare: Annotated[CompareMode, Query(description="База сравнения")] = CompareMode.PREVIOUS,
    compare_from: Annotated[date | None, Query(description="Начало своей базы сравнения")] = None,
    compare_to: Annotated[date | None, Query(description="Конец своей базы сравнения")] = None,
) -> Comparison:
    """Разобрать период и базу сравнения; по умолчанию — последние 7 дней к предыдущим 7.

    При ``compare=custom`` база сравнения задаётся датами ``compare_from`` и ``compare_to``.
    """
    if date_from is None or date_to is None:
        period = last_days(app_yesterday(), 7)
    else:
        period = _checked_period(date_from, date_to, "Период")
    if compare is CompareMode.CUSTOM:
        if compare_from is None or compare_to is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Укажите даты периода для сравнения")
        base = _checked_period(compare_from, compare_to, "Период сравнения")
    else:
        base = compare_period(period, compare)
    return Comparison(period, compare, base)


PeriodParams = Annotated[Comparison, Depends(period_params)]
