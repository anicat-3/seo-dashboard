"""Pydantic-схемы запросов и ответов API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    """Базовая схема, читающая атрибуты ORM-объектов."""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- авторизация
class LoginIn(BaseModel):
    """Вход, шаг 1: логин и пароль."""

    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MemberChoiceIn(BaseModel):
    """Вход, шаг 2: сотрудник из списка команды."""

    member_id: int


class TeamMemberShort(BaseModel):
    """Сотрудник в списке выбора при входе."""

    id: int
    full_name: str


class LoginStepOut(BaseModel):
    """Результат первого шага входа: выбрать сотрудника или вход уже выполнен."""

    status: Literal["choose_member", "done"]
    members: list[TeamMemberShort] = []
    me: MeOut | None = None


class MeOut(BaseModel):
    """Текущий пользователь."""

    account_id: int
    login: str
    role: str
    actor_name: str
    member_id: int | None = None


class TeamMemberIn(BaseModel):
    """Добавление или переименование сотрудника."""

    full_name: str = Field(min_length=3, max_length=100,
                           description="Фамилия и имя, как они будут показаны в журналах")

    @field_validator("full_name")
    @classmethod
    def _normalize(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 3:
            raise ValueError("Укажите фамилию и имя")
        return value


class TeamMemberOut(ORMModel):
    """Сотрудник команды."""

    id: int
    full_name: str
    is_active: bool
    created_at: datetime


class ActivityOut(ORMModel):
    """Запись журнала действий."""

    id: int
    member_id: int | None
    actor_name: str
    event: str
    path: str | None
    page: str | None
    project_name: str | None
    created_at: datetime


class ActivityIn(BaseModel):
    """Просмотр страницы, отправляемый интерфейсом."""

    path: str = Field(min_length=1, max_length=2000, pattern=r"^/")


class AccountOut(ORMModel):
    """Учётная запись (без хэша пароля)."""

    id: int
    login: str
    role: str
    is_active: bool
    password_changed_at: datetime


class PasswordIn(BaseModel):
    """Новый пароль учётной записи."""

    new_password: str = Field(min_length=10, max_length=256)


# ------------------------------------------------------------------- справочники
class SystemOut(ORMModel):
    """Система из справочника."""

    code: str
    name: str
    auth_type: str


# ------------------------------------------------------------------- доступы
class CredentialIn(BaseModel):
    """Новый доступ к аккаунту системы."""

    system_code: str
    label: str = Field(min_length=1, max_length=200)
    account_login: str | None = Field(default=None, max_length=255)
    auth_type: Literal["api_key", "oauth"]
    secret: dict[str, str] | None = Field(
        default=None, description="Ключи доступа; хранятся зашифрованными и не возвращаются")


class CredentialUpdate(BaseModel):
    """Изменение доступа: название или новый секрет (переподключение)."""

    label: str | None = Field(default=None, max_length=200)
    account_login: str | None = Field(default=None, max_length=255)
    secret: dict[str, str] | None = None


class CredentialOut(ORMModel):
    """Доступ к аккаунту системы (секрет не возвращается)."""

    id: int
    system_code: str
    label: str
    account_login: str | None
    auth_type: str
    status: str
    status_message: str | None
    expires_at: datetime | None
    last_checked_at: datetime | None
    created_by_name: str | None
    has_secret: bool = False
    integrations_count: int = 0


class ResourceOut(BaseModel):
    """Ресурс внешней системы, доступный для подключения."""

    external_id: str
    name: str
    timezone: str
    extra: dict[str, Any] = {}


class GoalOut(ORMModel):
    """Цель GA4/Метрики."""

    external_goal_id: str
    name: str


# ------------------------------------------------------------------- проекты
class ProjectIn(BaseModel):
    """Создание или изменение проекта."""

    name: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=3, max_length=255)

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, value: str) -> str:
        value = value.strip().lower()
        for prefix in ("https://", "http://"):
            value = value.removeprefix(prefix)
        return value.strip("/")


class ProjectOut(ORMModel):
    """Проект."""

    id: int
    slug: str
    name: str
    domain: str
    created_by_name: str
    created_at: datetime
    is_active: bool
    archived_at: datetime | None
    systems: list[str] = []
    is_favorite: bool = False


# ---------------------------------------------------------------- подключения
class GoalIn(BaseModel):
    """Избранная цель."""

    external_goal_id: str
    name: str


class IntegrationIn(BaseModel):
    """Подключение системы к проекту."""

    system_code: str
    credential_id: int
    external_id: str = Field(min_length=1, max_length=255)
    external_name: str | None = None
    timezone: str = "UTC"
    settings: dict[str, Any] = {}
    goals: list[GoalIn] = []
    collect_from: date | None = None


class IntegrationUpdate(BaseModel):
    """Изменение подключения."""

    settings: dict[str, Any] | None = None
    goals: list[GoalIn] | None = None
    is_active: bool | None = None
    credential_id: int | None = None
    timezone: str | None = None


class IntegrationOut(ORMModel):
    """Подключение системы к проекту."""

    id: int
    project_id: int
    system_code: str
    credential_id: int
    external_id: str
    external_name: str | None
    timezone: str
    settings: dict[str, Any]
    is_active: bool
    status: str
    last_error: str | None
    collect_from: date | None
    disabled_at: datetime | None
    created_by_name: str
    created_at: datetime
    goals: list[GoalOut] = []
    last_run: dict[str, Any] | None = None


class TestOut(BaseModel):
    """Результат пробного запроса."""

    ok: bool
    message: str
    sample: dict[str, Any] = {}


class SyncIn(BaseModel):
    """Ручной перезапуск сбора за период."""

    date_from: date
    date_to: date


class SyncRunOut(ORMModel):
    """Запуск коннектора."""

    id: int
    integration_id: int
    job_type: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    date_from: date | None
    date_to: date | None
    rows_written: int
    error_message: str | None
    started_by_name: str | None


class MonitoredUrlIn(BaseModel):
    """URL для проверки в PSI."""

    url: str = Field(min_length=8, max_length=2000, pattern=r"^https?://")
    template_name: str | None = Field(default=None, max_length=100)


class MonitoredUrlOut(ORMModel):
    """URL для проверки в PSI."""

    id: int
    project_id: int
    url: str
    template_name: str | None
    is_active: bool


# ------------------------------------------------------ подсветка и пометки
class SignalRuleIn(BaseModel):
    """Правило подсветки изменений."""

    project_id: int | None = None
    metric_code: str
    segment: str = "all"
    comparison: Literal["wow", "mom"] = "wow"
    threshold_pct: float = Field(gt=0, le=100)
    is_active: bool = True


class SignalRuleUpdate(BaseModel):
    """Изменение правила подсветки."""

    threshold_pct: float | None = Field(default=None, gt=0, le=100)
    comparison: Literal["wow", "mom"] | None = None
    is_active: bool | None = None


class SignalRuleOut(ORMModel):
    """Правило подсветки изменений."""

    id: int
    project_id: int | None
    metric_code: str
    segment: str
    comparison: str
    threshold_pct: float
    is_active: bool


class AnnotationIn(BaseModel):
    """Пометка на графике."""

    date: date
    text: str = Field(min_length=1, max_length=1000)


class AnnotationOut(ORMModel):
    """Пометка на графике."""

    id: int
    project_id: int
    date: date
    text: str
    author_name: str
    created_at: datetime


class AuditOut(ORMModel):
    """Запись журнала изменений."""

    id: int
    actor_name: str
    project_name: str | None
    action: str
    entity: str
    entity_id: str | None
    changes: dict[str, Any]
    created_at: datetime


LoginStepOut.model_rebuild()


# ------------------------------------------------------------------ обращения
FeedbackStatus = Literal["new", "closed", "rejected", "paused", "postponed"]


class FeedbackIn(BaseModel):
    """Новое обращение сотрудника."""

    message: str = Field(min_length=3, max_length=5000)


class FeedbackUpdate(BaseModel):
    """Решение администратора по обращению."""

    status: FeedbackStatus | None = None
    admin_note: str | None = Field(default=None, max_length=2000)


class FeedbackOut(ORMModel):
    """Обращение."""

    id: int
    author_name: str
    message: str
    status: str
    admin_note: str | None
    resolved_by_name: str | None
    created_at: datetime
    updated_at: datetime | None
