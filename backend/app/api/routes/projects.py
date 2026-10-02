"""Проекты, подключения систем, URL для PSI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Admin, DbSession, User, app_yesterday, get_project_or_404
from app.api.schemas import (
    GoalIn,
    IntegrationIn,
    IntegrationOut,
    IntegrationUpdate,
    MonitoredUrlIn,
    MonitoredUrlOut,
    ProjectIn,
    ProjectOut,
    SyncIn,
    SyncRunOut,
    TestOut,
)
from app.connectors.base import ConnectorError, IntegrationContext
from app.connectors.registry import get_connector
from app.models import (
    Credential,
    FavoriteProject,
    Integration,
    IntegrationGoal,
    MonitoredUrl,
    Project,
    SyncRun,
)
from app.scheduler import submit_backfill, submit_manual_sync
from app.services.audit import audit
from app.services.collector import credential_secret
from app.services.projects import (
    calendar_marks,
    delete_integrations,
    delete_project,
    favorite_project_ids,
    unique_slug,
)

router = APIRouter(tags=["projects"])


# ------------------------------------------------------------------- проекты
def _project_out(db, project: Project, favorites: set[int] | None = None) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.systems = sorted({i.system_code for i in project.integrations if i.disabled_at is None})
    out.is_favorite = project.id in (favorites or set())
    return out


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(user: User, db: DbSession, include_archived: bool = False) -> list[ProjectOut]:
    """Список проектов: сначала избранные сотрудника, затем остальные по названию."""
    stmt = select(Project)
    if not include_archived:
        stmt = stmt.where(Project.is_active.is_(True))
    favorites = favorite_project_ids(db, user.owner_key)
    projects = sorted(db.scalars(stmt), key=lambda p: (p.id not in favorites, p.name.lower()))
    return [_project_out(db, p, favorites) for p in projects]


@router.put("/projects/{project_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def add_favorite(project_id: str, user: User, db: DbSession) -> None:
    """Добавить проект в избранное текущего сотрудника."""
    project = get_project_or_404(db, project_id)
    if db.get(FavoriteProject, (user.owner_key, project.id)) is None:
        db.add(FavoriteProject(owner=user.owner_key, project_id=project.id))
        db.commit()


@router.delete("/projects/{project_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(project_id: str, user: User, db: DbSession) -> None:
    """Убрать проект из избранного текущего сотрудника."""
    project = get_project_or_404(db, project_id)
    favorite = db.get(FavoriteProject, (user.owner_key, project.id))
    if favorite is not None:
        db.delete(favorite)
        db.commit()


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectIn, user: Admin, db: DbSession) -> ProjectOut:
    """Создать проект."""
    project = Project(name=payload.name, domain=payload.domain,
                      slug=unique_slug(db, payload.domain), created_by_name=user.actor_name,
                      is_active=True)
    db.add(project)
    db.flush()
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="create",
          entity="project", entity_id=project.id, changes=payload.model_dump(),
          project_name=project.name)
    db.commit()
    return _project_out(db, project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, user: User, db: DbSession) -> ProjectOut:
    """Карточка проекта."""
    return _project_out(db, get_project_or_404(db, project_id),
                        favorite_project_ids(db, user.owner_key))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectIn, user: User, db: DbSession) -> ProjectOut:
    """Изменить название и домен проекта."""
    project = get_project_or_404(db, project_id)
    changes = {key: value for key, value in payload.model_dump().items()
               if getattr(project, key) != value}
    if payload.domain != project.domain:
        project.slug = unique_slug(db, payload.domain, exclude_id=project.id)
    project.name, project.domain = payload.name, payload.domain
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="update",
          entity="project", entity_id=project.id, changes=changes, project_name=project.name)
    db.commit()
    return _project_out(db, project)


@router.post("/projects/{project_id}/archive", response_model=ProjectOut)
def archive_project(project_id: str, user: Admin, db: DbSession,
                    restore: bool = False) -> ProjectOut:
    """Архивировать проект (сбор останавливается, история сохраняется) или вернуть из архива."""
    project = get_project_or_404(db, project_id)
    project.is_active = restore
    project.archived_at = None if restore else datetime.now(UTC)
    audit(db, account_id=user.account_id, actor_name=user.actor_name,
          action="restore" if restore else "archive", entity="project", entity_id=project.id,
          project_name=project.name)
    db.commit()
    return _project_out(db, project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project(project_id: str, user: Admin, db: DbSession) -> None:
    """Полностью удалить проект со всеми подключениями и историей. Действие необратимо."""
    project = get_project_or_404(db, project_id)
    name, domain, entity_id = project.name, project.domain, project.id
    stats = delete_project(db, project)
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="delete",
          entity="project", entity_id=entity_id, changes={"domain": domain, **stats},
          project_name=name)
    db.commit()


@router.get("/projects/{project_id}/calendar")
def project_calendar(project_id: str, _: User, db: DbSession) -> dict:
    """Отметки календаря: дни съёма позиций и дни с обнаруженными ошибками."""
    return calendar_marks(db, get_project_or_404(db, project_id))


# --------------------------------------------------------------- подключения
def _integration_out(db, integration: Integration) -> IntegrationOut:
    out = IntegrationOut.model_validate(integration)
    run = db.scalars(select(SyncRun).where(SyncRun.integration_id == integration.id)
                     .order_by(SyncRun.started_at.desc()).limit(1)).first()
    if run is not None:
        out.last_run = SyncRunOut.model_validate(run).model_dump(mode="json")
    return out


def _get_integration(db, integration_id: int) -> Integration:
    integration = db.get(Integration, integration_id)
    if integration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подключение не найдено")
    return integration


def _check_credential(db, credential_id: int, system_code: str) -> Credential:
    credential = db.get(Credential, credential_id)
    if credential is None or credential.system_code != system_code:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Доступ не найден или относится к другой системе")
    return credential


def project_has_urls(db, project_id: int) -> bool:
    """Есть ли у проекта активные URL для проверки в PSI."""
    return db.scalar(select(MonitoredUrl.id).where(MonitoredUrl.project_id == project_id,
                                                   MonitoredUrl.is_active.is_(True)).limit(1)) \
        is not None


def _set_goals(integration: Integration, goals: list[GoalIn]) -> None:
    """Привести избранные цели к списку ``goals``, изменяя существующие записи на месте.

    Полная замена коллекции не подходит: SQLAlchemy вставляет новые строки раньше,
    чем удаляет старые, и повторно выбранная цель нарушила бы уникальность.
    """
    wanted = {g.external_goal_id: g for g in goals}
    for goal in list(integration.goals):
        if goal.external_goal_id in wanted:
            goal.name = wanted.pop(goal.external_goal_id).name
            goal.is_favorite = True
        else:
            integration.goals.remove(goal)
    for goal in wanted.values():
        integration.goals.append(IntegrationGoal(external_goal_id=goal.external_goal_id,
                                                 name=goal.name, is_favorite=True))


@router.get("/projects/{project_id}/integrations", response_model=list[IntegrationOut])
def list_integrations(project_id: str, _: User, db: DbSession) -> list[IntegrationOut]:
    """Подключения проекта, включая приостановленные и отключённые."""
    project = get_project_or_404(db, project_id)
    integrations = db.scalars(select(Integration).where(Integration.project_id == project.id)
                              .order_by(Integration.id))
    return [_integration_out(db, i) for i in integrations]


@router.post("/projects/{project_id}/integrations/test", response_model=TestOut)
def test_integration(project_id: str, payload: IntegrationIn, _: User, db: DbSession) -> TestOut:
    """Пробный запрос за вчерашний день до сохранения подключения."""
    project = get_project_or_404(db, project_id)
    credential = _check_credential(db, payload.credential_id, payload.system_code)
    urls = db.execute(select(MonitoredUrl.id, MonitoredUrl.url).where(
        MonitoredUrl.project_id == project.id)).all()
    context = IntegrationContext(
        integration_id=0, external_id=payload.external_id, timezone=payload.timezone,
        settings=payload.settings, goal_ids=[g.external_goal_id for g in payload.goals],
        monitored_urls=[(r.id, r.url) for r in urls], domain=project.domain,
    )
    try:
        connector = get_connector(payload.system_code, credential.auth_type,
                                  credential_secret(credential), context)
        result = connector.test()
    except ConnectorError as exc:
        return TestOut(ok=False, message=str(exc))
    return TestOut(ok=result.ok, message=result.message, sample=result.sample)


@router.post("/projects/{project_id}/integrations", response_model=IntegrationOut,
             status_code=status.HTTP_201_CREATED)
def create_integration(project_id: str, payload: IntegrationIn, user: User,
                       db: DbSession) -> IntegrationOut:
    """Подключить систему к проекту и поставить загрузку истории.

    Если пробный запрос не прошёл, подключение всё равно сохраняется, но со статусом
    «ошибка» и попадает на экран ошибок.
    """
    project = get_project_or_404(db, project_id)
    _check_credential(db, payload.credential_id, payload.system_code)
    test = test_integration(project_id, payload, user, db)
    integration = Integration(
        project_id=project.id, system_code=payload.system_code,
        credential_id=payload.credential_id, external_id=payload.external_id,
        external_name=payload.external_name, timezone=payload.timezone,
        settings=payload.settings, is_active=True,
        status="pending" if test.ok else "error",
        last_error=None if test.ok else test.message,
        collect_from=payload.collect_from, created_by_name=user.actor_name,
    )
    _set_goals(integration, payload.goals)
    history_days = int((payload.settings or {}).get("history_days") or 0)
    if history_days > 0 and payload.collect_from is None:
        # История позиций за выбранный период: окно загрузки начинается N дней назад.
        integration.collect_from = app_yesterday() - timedelta(days=history_days - 1)
    db.add(integration)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Этот ресурс уже подключён к проекту") from exc
    if payload.system_code == "psi" and not project_has_urls(db, project.id):
        # PSI проверяет URL проекта; без них проверять нечего — начинаем с главной.
        db.add(MonitoredUrl(project_id=project.id, url=payload.external_id,
                            template_name="Главная", is_active=True))
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="create",
          entity="integration", entity_id=integration.id,
          changes={"system_code": payload.system_code, "external_id": payload.external_id},
          project_name=project.name)
    db.commit()
    submit_backfill(integration.id, user.actor_name)
    return _integration_out(db, integration)


@router.patch("/integrations/{integration_id}", response_model=IntegrationOut)
def update_integration(integration_id: int, payload: IntegrationUpdate, user: User,
                       db: DbSession) -> IntegrationOut:
    """Изменить настройки, цели, доступ или приостановить/возобновить сбор."""
    integration = _get_integration(db, integration_id)
    changes = payload.model_dump(exclude_none=True)
    if payload.credential_id is not None:
        _check_credential(db, payload.credential_id, integration.system_code)
        integration.credential_id = payload.credential_id
    if payload.settings is not None:
        integration.settings = payload.settings
    if payload.goals is not None:
        _set_goals(integration, payload.goals)
    if payload.timezone is not None:
        integration.timezone = payload.timezone
    if payload.is_active is not None:
        if integration.disabled_at is not None and payload.is_active:
            integration.disabled_at = None
        integration.is_active = payload.is_active
    audit(db, account_id=user.account_id, actor_name=user.actor_name,
          action="pause" if payload.is_active is False else "update",
          entity="integration", entity_id=integration.id,
          changes={"system_code": integration.system_code, **changes},
          project_name=integration.project.name)
    db.commit()
    return _integration_out(db, integration)


@router.post("/integrations/{integration_id}/disable", response_model=IntegrationOut)
def disable_integration(integration_id: int, user: User, db: DbSession) -> IntegrationOut:
    """Отключить систему от проекта: сбор остановлен, блок скрыт, история сохранена."""
    integration = _get_integration(db, integration_id)
    integration.is_active = False
    integration.disabled_at = datetime.now(UTC)
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="disable",
          entity="integration", entity_id=integration.id,
          changes={"system_code": integration.system_code},
          project_name=integration.project.name)
    db.commit()
    return _integration_out(db, integration)


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_integration(integration_id: int, user: Admin, db: DbSession) -> None:
    """Удалить отключённую систему из проекта вместе с её историей. Действие необратимо."""
    integration = _get_integration(db, integration_id)
    if integration.disabled_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Сначала отключите систему от проекта")
    project_name, system_code = integration.project.name, integration.system_code
    stats = delete_integrations(db, [integration])
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="delete",
          entity="integration", entity_id=integration_id,
          changes={"system_code": system_code, **stats}, project_name=project_name)
    db.commit()


@router.post("/integrations/{integration_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def rerun_sync(integration_id: int, payload: SyncIn, user: User, db: DbSession) -> dict:
    """Перезапустить сбор вручную за период за период: данные будут перезаписаны."""
    integration = _get_integration(db, integration_id)
    if payload.date_from > payload.date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Начало позже окончания")
    date_to = min(payload.date_to, app_yesterday())
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="manual_sync",
          entity="integration", entity_id=integration.id,
          changes={"system_code": integration.system_code,
                   "date_from": payload.date_from.isoformat(), "date_to": date_to.isoformat()},
          project_name=integration.project.name)
    db.commit()
    submit_manual_sync(integration.id, payload.date_from, date_to, user.actor_name)
    return {"status": "scheduled"}


@router.post("/integrations/{integration_id}/backfill", status_code=status.HTTP_202_ACCEPTED)
def rerun_backfill(integration_id: int, user: User, db: DbSession) -> dict:
    """Повторить загрузку истории подключения."""
    integration = _get_integration(db, integration_id)
    submit_backfill(integration.id, user.actor_name)
    return {"status": "scheduled"}


@router.get("/integrations/{integration_id}/runs", response_model=list[SyncRunOut])
def list_runs(integration_id: int, _: User, db: DbSession, limit: int = 30) -> list[SyncRun]:
    """Журнал запусков подключения."""
    _get_integration(db, integration_id)
    return list(db.scalars(select(SyncRun).where(SyncRun.integration_id == integration_id)
                           .order_by(SyncRun.started_at.desc()).limit(min(limit, 200))))


# --------------------------------------------------------------- URL для PSI
@router.get("/projects/{project_id}/urls", response_model=list[MonitoredUrlOut])
def list_urls(project_id: str, _: User, db: DbSession) -> list[MonitoredUrl]:
    """URL проекта для проверки в PSI."""
    project = get_project_or_404(db, project_id)
    return list(db.scalars(select(MonitoredUrl).where(MonitoredUrl.project_id == project.id)
                           .order_by(MonitoredUrl.id)))


@router.post("/projects/{project_id}/urls", response_model=MonitoredUrlOut,
             status_code=status.HTTP_201_CREATED)
def add_url(project_id: str, payload: MonitoredUrlIn, user: User, db: DbSession) -> MonitoredUrl:
    """Добавить URL для проверки в PSI."""
    project = get_project_or_404(db, project_id)
    url = MonitoredUrl(project_id=project.id, url=payload.url,
                       template_name=payload.template_name, is_active=True)
    db.add(url)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой URL уже добавлен") from exc
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="create",
          entity="monitored_url", entity_id=url.id, changes=payload.model_dump(),
          project_name=project.name)
    db.commit()
    return url


@router.patch("/urls/{url_id}", response_model=MonitoredUrlOut)
def toggle_url(url_id: int, is_active: bool, user: User, db: DbSession) -> MonitoredUrl:
    """Включить или выключить проверку URL (история прогонов сохраняется)."""
    url = db.get(MonitoredUrl, url_id)
    if url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "URL не найден")
    url.is_active = is_active
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="update",
          entity="monitored_url", entity_id=url.id,
          changes={"url": url.url, "is_active": is_active},
          project_name=db.get(Project, url.project_id).name)
    db.commit()
    return url
