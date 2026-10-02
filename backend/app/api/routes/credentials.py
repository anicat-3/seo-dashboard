"""Доступы к аккаунтам внешних систем."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import Admin, DbSession, User, get_project_or_404
from app.api.schemas import (
    CredentialIn,
    CredentialOut,
    CredentialUpdate,
    GoalOut,
    ResourceOut,
    SystemOut,
)
from app.connectors.base import ConnectorError, IntegrationContext
from app.connectors.registry import get_connector
from app.models import Credential, Integration, System
from app.security import encrypt_secret
from app.services.audit import audit
from app.services.collector import credential_secret, persist_secret

router = APIRouter(tags=["credentials"])


@router.get("/systems", response_model=list[SystemOut])
def list_systems(_: User, db: DbSession) -> list[System]:
    """Справочник систем."""
    return list(db.scalars(select(System).order_by(System.sort_order)))


def _to_out(db, credential: Credential) -> CredentialOut:
    out = CredentialOut.model_validate(credential)
    out.has_secret = bool(credential.secret_encrypted)
    out.integrations_count = db.scalar(
        select(func.count()).select_from(Integration).where(
            Integration.credential_id == credential.id, Integration.disabled_at.is_(None))
    ) or 0
    return out


def _get(db, credential_id: int) -> Credential:
    credential = db.get(Credential, credential_id)
    if credential is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Доступ не найден")
    return credential


@router.get("/credentials", response_model=list[CredentialOut])
def list_credentials(_: User, db: DbSession, system_code: str | None = None) -> list[CredentialOut]:
    """Доступы к аккаунтам; можно отфильтровать по системе."""
    stmt = select(Credential).order_by(Credential.system_code, Credential.label)
    if system_code:
        stmt = stmt.where(Credential.system_code == system_code)
    return [_to_out(db, c) for c in db.scalars(stmt)]


@router.post("/credentials", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
def create_credential(payload: CredentialIn, user: Admin, db: DbSession) -> CredentialOut:
    """Подключить аккаунт системы по API-ключу.

    Доступы Google и Яндекса по OAuth создаются в :mod:`app.api.routes.oauth`.
    """
    if db.get(System, payload.system_code) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная система")
    if payload.auth_type == "oauth":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Аккаунты Google и Яндекса подключаются кнопкой «Войти через …»")
    if payload.auth_type == "api_key" and not payload.secret:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите API-ключ")
    credential = Credential(
        system_code=payload.system_code, label=payload.label,
        account_login=payload.account_login, auth_type=payload.auth_type,
        secret_encrypted=encrypt_secret(payload.secret) if payload.secret else None,
        status="unchecked",
        created_by_name=user.actor_name,
    )
    db.add(credential)
    db.flush()
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="create",
          entity="credential", entity_id=credential.id,
          changes={"system_code": credential.system_code, "label": credential.label,
                   "auth_type": credential.auth_type})
    db.commit()
    return _to_out(db, credential)


@router.patch("/credentials/{credential_id}", response_model=CredentialOut)
def update_credential(credential_id: int, payload: CredentialUpdate, user: Admin,
                      db: DbSession) -> CredentialOut:
    """Переименовать доступ или заменить секрет (переподключение аккаунта)."""
    credential = _get(db, credential_id)
    changes: dict[str, object] = {}
    if payload.label is not None:
        credential.label = changes["label"] = payload.label
    if payload.account_login is not None:
        credential.account_login = changes["account_login"] = payload.account_login
    if payload.secret:
        credential.secret_encrypted = encrypt_secret(payload.secret)
        credential.status, credential.status_message = "unchecked", None
        changes["secret"] = "обновлён"
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="update",
          entity="credential", entity_id=credential.id, changes=changes)
    db.commit()
    return _to_out(db, credential)


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(credential_id: int, user: Admin, db: DbSession) -> None:
    """Удалить доступ, если он не используется ни одним подключением."""
    credential = _get(db, credential_id)
    used = db.scalar(select(func.count()).select_from(Integration)
                     .where(Integration.credential_id == credential.id))
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Доступ используется подключениями; сначала переключите их")
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="delete",
          entity="credential", entity_id=credential.id, changes={"label": credential.label})
    db.delete(credential)
    db.commit()


@router.post("/credentials/{credential_id}/check", response_model=CredentialOut)
def check_credential(credential_id: int, _: Admin, db: DbSession) -> CredentialOut:
    """Проверить доступ: запросить список ресурсов аккаунта."""
    credential = _get(db, credential_id)
    try:
        connector = get_connector(credential.system_code, credential.auth_type,
                                  credential_secret(credential))
        credential.status_message = connector.check_access()
        credential.status = "ok"
        persist_secret(credential, connector)
    except ConnectorError as exc:
        credential.status, credential.status_message = "error", str(exc)
    credential.last_checked_at = datetime.now(UTC)
    db.commit()
    return _to_out(db, credential)


@router.get("/credentials/{credential_id}/resources", response_model=list[ResourceOut])
def list_resources(credential_id: int, _: User, db: DbSession,
                   project_id: str | None = None) -> list[ResourceOut]:
    """Ресурсы аккаунта для выпадающего списка при подключении.

    Для систем без собственного списка ресурсов (PSI, CrUX) ресурсы строятся
    из домена проекта ``project_id``.
    """
    credential = _get(db, credential_id)
    context = None
    if project_id is not None:
        project = get_project_or_404(db, project_id)
        context = IntegrationContext(integration_id=0, external_id="", domain=project.domain)
    try:
        connector = get_connector(credential.system_code, credential.auth_type,
                                  credential_secret(credential), context)
        resources = connector.list_resources()
        persist_secret(credential, connector)
        db.commit()
        return [ResourceOut(external_id=r.external_id, name=r.name, timezone=r.timezone,
                            extra=r.extra) for r in resources]
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("/credentials/{credential_id}/goals", response_model=list[GoalOut])
def list_goals(credential_id: int, external_id: str, _: User, db: DbSession) -> list[GoalOut]:
    """Цели ресурса GA4/Метрики для выбора избранных."""
    credential = _get(db, credential_id)
    try:
        connector = get_connector(credential.system_code, credential.auth_type,
                                  credential_secret(credential),
                                  IntegrationContext(integration_id=0, external_id=external_id))
        goals = connector.list_goals()
        persist_secret(credential, connector)
        db.commit()
        return [GoalOut(external_goal_id=g.external_goal_id, name=g.name) for g in goals]
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
