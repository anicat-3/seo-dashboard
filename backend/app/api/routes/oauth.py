"""Вход через Google и Яндекс (OAuth 2.0) для подключения аккаунтов систем.

1. ``GET /oauth/{provider}/start`` — администратор уходит на страницу входа провайдера.
2. Google возвращает код на ``GET /oauth/google/callback``; Яндекс показывает код
   на своей странице, и администратор отправляет его в ``POST /oauth/yandex/code``.
3. Приложение получает токены и создаёт (или обновляет) доступы для всех систем
   провайдера: Google → GSC и GA4, Яндекс → Метрика и Вебмастер.

Повторный вход тем же аккаунтом обновляет токены существующих доступов —
так выполняется «переподключение» после отзыва доступа.

У провайдера может быть несколько OAuth-приложений из ``.env``; приложение выбирается
параметром ``app`` (суффикс ключей, например ``2`` для ``GOOGLE_CLIENT_ID_2``).
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Admin, CurrentUser, DbSession
from app.connectors.base import AuthError, ConnectorError
from app.connectors.oauth import (
    PROVIDERS,
    OAuthApp,
    Provider,
    account_login,
    authorize_url,
    exchange_code,
)
from app.models import Credential
from app.security import encrypt_secret
from app.services.audit import audit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["oauth"])

#: Куда вернуть администратора после входа.
RETURN_PATH = "/credentials"


def _provider(name: str) -> Provider:
    provider = PROVIDERS.get(name)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Неизвестный провайдер")
    return provider


def _back(**params: str) -> RedirectResponse:
    return RedirectResponse(f"{RETURN_PATH}?{urlencode(params)}", status_code=303)


@router.get("/oauth/providers")
def providers(_: Admin) -> list[dict]:
    """Настроены ли OAuth-приложения и какие адреса возврата указать в их настройках."""
    result = []
    for p in PROVIDERS.values():
        apps = [{"key": app.key, "name": app.name} for app in p.apps()]
        result.append({"name": p.name, "title": p.title, "configured": bool(apps),
                       "apps": apps, "redirect_uri": p.redirect_uri(),
                       "systems": list(p.systems), "manual_code": p.manual_code})
    return result


def _app(provider: Provider, key: str | None) -> OAuthApp:
    try:
        return provider.app(key)
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/oauth/{provider_name}/start")
def start(provider_name: str, request: Request, _: Admin,
          app: str | None = Query(default=None, max_length=64)) -> RedirectResponse:
    """Перейти на страницу входа провайдера через выбранное OAuth-приложение."""
    provider = _provider(provider_name)
    try:
        oauth_app = provider.app(app)
    except ConnectorError as exc:
        return _back(oauth_error=str(exc))
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = {"state": state, "provider": provider.name,
                                      "app": oauth_app.key}
    return RedirectResponse(authorize_url(provider, oauth_app, state), status_code=303)


@router.get("/oauth/{provider_name}/callback")
def callback(provider_name: str, request: Request, user: Admin, db: DbSession,
             code: str | None = None, state: str | None = None,
             error: str | None = None) -> RedirectResponse:
    """Принять код от провайдера, получить токены и сохранить доступы."""
    provider = _provider(provider_name)
    expected = request.session.pop("oauth_state", None)
    if error:
        return _back(oauth_error=f"{provider.title}: вход отменён ({error})")
    if not expected or expected.get("state") != state or expected.get("provider") != provider.name:
        return _back(oauth_error="Сессия входа устарела — нажмите «Войти» ещё раз")
    if not code:
        return _back(oauth_error=f"{provider.title} не вернул код авторизации")
    try:
        login = connect_account(db, provider, provider.app(expected.get("app")), code, user)
    except ConnectorError as exc:
        logger.warning("OAuth %s: %s", provider.name, exc)
        return _back(oauth_error=str(exc))
    return _back(connected=login, provider=provider.title)


class VerificationCodeIn(BaseModel):
    """Код подтверждения со страницы провайдера (Яндекс)."""

    code: str = Field(min_length=4, max_length=200)
    #: Приложение, через которое открыта страница входа (код выдан только ему).
    app: str | None = Field(default=None, max_length=64)


@router.post("/oauth/{provider_name}/code")
def submit_code(provider_name: str, payload: VerificationCodeIn, user: Admin,
                db: DbSession) -> dict:
    """Подключить аккаунт по коду подтверждения, введённому вручную."""
    provider = _provider(provider_name)
    if not provider.manual_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{provider.title} возвращает код автоматически")
    oauth_app = _app(provider, payload.app)
    try:
        login = connect_account(db, provider, oauth_app, payload.code, user)
    except AuthError as exc:
        # invalid_grant при обмене кода — код неверный, уже использован или устарел.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Код не подошёл: он неверный, уже использован или устарел "
                            "(действует 10 минут) либо выдан другому приложению. Откройте "
                            "страницу входа ещё раз и вставьте новый код") from exc
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"login": login, "provider": provider.title}


def connect_account(db, provider: Provider, app: OAuthApp, code: str,
                    user: CurrentUser) -> str:
    """Обменять код на токены и создать или обновить доступы всех систем провайдера.

    Returns:
        Логин подключённого аккаунта.

    Raises:
        ConnectorError: Код неверный или устарел, провайдер не ответил.
    """
    secret = exchange_code(provider, app, code)
    login = account_login(provider, secret["access_token"])
    updated = False
    for system in provider.systems:
        credential = db.scalar(select(Credential).where(
            Credential.system_code == system, Credential.auth_type == "oauth",
            Credential.account_login == login))
        if credential is None:
            credential = Credential(system_code=system, label=login, account_login=login,
                                    auth_type="oauth", created_by_name=user.actor_name)
            db.add(credential)
        else:
            updated = True
        # У каждого доступа своя копия секрета: обновления токена сохраняются по отдельности.
        credential.secret_encrypted = encrypt_secret(dict(secret))
        credential.status, credential.status_message = "ok", "Вход выполнен"
        credential.last_checked_at = datetime.now(UTC)
    db.flush()
    audit(db, account_id=user.account_id, actor_name=user.actor_name,
          action="update" if updated else "create", entity="credential",
          changes={"auth_type": "oauth", "account_login": login, "system_code": provider.name,
                   "oauth_app": app.name or app.key or None})
    db.commit()
    return login
