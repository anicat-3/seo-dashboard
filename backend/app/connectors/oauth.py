"""OAuth 2.0 для Google (GSC, GA4) и Яндекса (Метрика, Вебмастер).

Поток «authorization code»:

* **Google** возвращает код на ``<PUBLIC_BASE_URL>/api/oauth/google/callback``
  автоматически.
* **Яндекс** использует штатную страницу ``https://oauth.yandex.ru/verification_code``:
  после входа Яндекс показывает код, администратор вставляет его в дашборд.
  Так не нужно регистрировать адрес дашборда в приложении Яндекса.

Приложение обменивает код на токены и сохраняет их в ``credentials`` (зашифрованно).

У провайдера может быть несколько OAuth-приложений (например, по одному на каждый
рабочий Google-аккаунт). Они задаются в ``.env`` нумерованными ключами::

    GOOGLE_CLIENT_ID_1=...      GOOGLE_CLIENT_SECRET_1=...      GOOGLE_APP_NAME_1=proweber.a
    GOOGLE_CLIENT_ID_2=...      GOOGLE_CLIENT_SECRET_2=...      GOOGLE_APP_NAME_2=proweber.b

Ключи без номера (``GOOGLE_CLIENT_ID``) тоже поддерживаются. Токены выдаются
конкретному приложению, поэтому секрет доступа хранит его client ID — по нему
токен потом обновляется.

Секрет OAuth-доступа::

    {"refresh_token": "...", "access_token": "...", "expires_at": "2026-10-01T12:00:00+00:00",
     "client_id": "..."}

Коннекторы получают действующий access-токен через :func:`access_token`; если он
истёк, токен обновляется по refresh-токену, а секрет помечается изменённым, чтобы
сборщик сохранил новое значение в БД.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from dotenv import dotenv_values

from app.config import REPO_ROOT, get_settings
from app.connectors.base import AuthError, ConnectorError

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
#: Обновлять токен заранее, чтобы он не истёк посреди сбора.
EXPIRY_MARGIN = timedelta(minutes=5)


def _env() -> dict[str, str]:
    """Переменные ``.env`` и окружения (окружение главнее), включая нумерованные ключи."""
    values = {k.upper(): v for k, v in dotenv_values(REPO_ROOT / ".env").items() if v}
    values.update({k.upper(): v for k, v in os.environ.items() if v})
    return values


def _natural(key: str) -> tuple:
    """Порядок «2» < «10»: числа сравниваются как числа."""
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", key))


@dataclass(frozen=True, slots=True)
class OAuthApp:
    """OAuth-приложение провайдера (client ID и secret из ``.env``)."""

    #: Суффикс ключей в ``.env`` в нижнем регистре: ``""`` для ``GOOGLE_CLIENT_ID``,
    #: ``"2"`` для ``GOOGLE_CLIENT_ID_2``.
    key: str
    #: Название для выбора аккаунта (``GOOGLE_APP_NAME_2``); по умолчанию — номер.
    name: str
    client_id: str
    client_secret: str


@dataclass(frozen=True, slots=True)
class Provider:
    """Параметры OAuth-провайдера."""

    name: str
    title: str
    auth_url: str
    token_url: str
    scopes: tuple[str, ...]
    #: Системы, доступ к которым даёт один вход (создаётся по доступу на каждую).
    systems: tuple[str, ...]
    #: Код подтверждения вводится вручную (страница провайдера вместо возврата в дашборд).
    manual_code: bool = False
    #: Фиксированный адрес возврата провайдера для ручного ввода кода.
    fixed_redirect_uri: str | None = None

    def apps(self) -> list[OAuthApp]:
        """Настроенные OAuth-приложения провайдера, в порядке номеров.

        Приложение без пары client ID + secret пропускается.
        """
        env = _env()
        prefix = self.name.upper()
        settings = get_settings()
        result: list[OAuthApp] = []
        seen: set[str] = set()
        base_id = getattr(settings, f"{self.name}_client_id")
        base_secret = getattr(settings, f"{self.name}_client_secret")
        if base_id and base_secret:
            result.append(OAuthApp("", env.get(f"{prefix}_APP_NAME", ""), base_id, base_secret))
            seen.add(base_id)
        pattern = re.compile(rf"^{prefix}_CLIENT_ID_([A-Z0-9_]+)$")
        suffixes = sorted((m.group(1) for k in env if (m := pattern.match(k))), key=_natural)
        for suffix in suffixes:
            client_id = env[f"{prefix}_CLIENT_ID_{suffix}"]
            client_secret = env.get(f"{prefix}_CLIENT_SECRET_{suffix}")
            if not client_secret or client_id in seen:
                continue
            seen.add(client_id)
            result.append(OAuthApp(suffix.lower(), env.get(f"{prefix}_APP_NAME_{suffix}", ""),
                                   client_id, client_secret))
        if len(result) > 1:
            # Безымянным приложениям — номер, чтобы их можно было различить в списке.
            result = [app if app.name else OAuthApp(app.key, f"приложение {app.key or 1}",
                                                    app.client_id, app.client_secret)
                      for app in result]
        return result

    def app(self, key: str | None = None) -> OAuthApp:
        """Приложение по суффиксу ключей; без суффикса — первое настроенное.

        Raises:
            ConnectorError: Приложение не настроено.
        """
        apps = self.apps()
        if not apps:
            env = self.name.upper()
            raise ConnectorError(f"Не настроено OAuth-приложение {self.title}: заполните "
                                 f"{env}_CLIENT_ID_1 и {env}_CLIENT_SECRET_1 в .env и "
                                 "перезапустите приложение")
        if key is None:
            return apps[0]
        for app in apps:
            if app.key == key.lower():
                return app
        raise ConnectorError(f"OAuth-приложение {self.title} «{key}» не найдено в .env")

    def app_for_secret(self, secret: dict[str, Any]) -> OAuthApp:
        """Приложение, которому выданы токены доступа.

        Доступы, подключённые до поддержки нескольких приложений, не хранят client ID —
        для них берётся первое приложение.

        Raises:
            AuthError: Приложение удалено из ``.env``.
        """
        client_id = secret.get("client_id")
        if not client_id:
            return self.app()
        for app in self.apps():
            if app.client_id == client_id:
                return app
        raise AuthError(f"{self.title}: OAuth-приложение, через которое подключён аккаунт, "
                        "больше не указано в .env. Верните его ключи или переподключите аккаунт")

    @property
    def configured(self) -> bool:
        """Есть ли хотя бы одно настроенное приложение."""
        return bool(self.apps())

    def redirect_uri(self) -> str:
        """Адрес возврата — его же нужно указать в настройках OAuth-приложения."""
        if self.fixed_redirect_uri:
            return self.fixed_redirect_uri
        base = get_settings().public_base_url.rstrip("/")
        return f"{base}/api/oauth/{self.name}/callback"


GOOGLE = Provider(
    name="google", title="Google",
    auth_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scopes=("openid", "email",
            "https://www.googleapis.com/auth/webmasters.readonly",
            "https://www.googleapis.com/auth/analytics.readonly"),
    systems=("gsc", "ga4"),
)
YANDEX = Provider(
    name="yandex", title="Яндекс",
    auth_url="https://oauth.yandex.ru/authorize",
    token_url="https://oauth.yandex.ru/token",
    # Права (Метрика, Вебмастер) задаются в настройках приложения на oauth.yandex.ru.
    scopes=(),
    systems=("metrika", "ywm"),
    manual_code=True,
    fixed_redirect_uri="https://oauth.yandex.ru/verification_code",
)
PROVIDERS = {GOOGLE.name: GOOGLE, YANDEX.name: YANDEX}
#: Провайдер по коду системы.
SYSTEM_PROVIDER = {system: p for p in PROVIDERS.values() for system in p.systems}


def authorize_url(provider: Provider, app: OAuthApp, state: str) -> str:
    """Адрес страницы входа провайдера для указанного приложения."""
    params: dict[str, str] = {"response_type": "code", "client_id": app.client_id,
                              "redirect_uri": provider.redirect_uri(), "state": state}
    if provider is GOOGLE:
        # offline + consent — чтобы Google выдал refresh-токен даже при повторном входе.
        params |= {"scope": " ".join(provider.scopes), "access_type": "offline",
                   "prompt": "consent select_account", "include_granted_scopes": "true"}
    else:
        params |= {"force_confirm": "yes"}
    return f"{provider.auth_url}?{urlencode(params)}"


def _token_request(provider: Provider, app: OAuthApp, data: dict[str, str],
                   transport: httpx.BaseTransport | None) -> dict[str, Any]:
    payload = {**data, "client_id": app.client_id, "client_secret": app.client_secret}
    with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
        response = client.post(provider.token_url, data=payload)
    try:
        body = response.json()
    except ValueError:
        body = {"error": response.text[:200]}
    if response.is_success and body.get("access_token"):
        return body
    error = body.get("error", "")
    description = body.get("error_description", "")
    if error in ("invalid_grant", "invalid_client", "unauthorized_client"):
        raise AuthError(f"{provider.title}: доступ отозван или истёк ({description or error}). "
                        "Переподключите аккаунт")
    raise ConnectorError(f"{provider.title}: не удалось получить токен ({description or error})")


def _expires_at(body: dict[str, Any]) -> str:
    seconds = int(body.get("expires_in") or 3600)
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def exchange_code(provider: Provider, app: OAuthApp, code: str,
                  transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Обменять код авторизации на токены; вернуть секрет для ``credentials``.

    Код действителен только для приложения, через которое выполнен вход.
    """
    data = {"grant_type": "authorization_code", "code": code.strip()}
    if not provider.manual_code:
        data["redirect_uri"] = provider.redirect_uri()
    body = _token_request(provider, app, data, transport)
    if not body.get("refresh_token"):
        raise ConnectorError(f"{provider.title} не выдал refresh-токен. Отзовите доступ "
                             "приложения в настройках аккаунта и войдите снова")
    return {"refresh_token": body["refresh_token"], "access_token": body["access_token"],
            "expires_at": _expires_at(body), "client_id": app.client_id}


def account_login(provider: Provider, access_token: str,
                  transport: httpx.BaseTransport | None = None) -> str:
    """Логин (e-mail) аккаунта, под которым выполнен вход."""
    url = ("https://openidconnect.googleapis.com/v1/userinfo" if provider is GOOGLE
           else "https://login.yandex.ru/info?format=json")
    scheme = "Bearer" if provider is GOOGLE else "OAuth"
    with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
        response = client.get(url, headers={"Authorization": f"{scheme} {access_token}"})
    if not response.is_success:
        raise ConnectorError(f"{provider.title}: не удалось получить данные аккаунта")
    data = response.json()
    return data.get("email") or data.get("default_email") or data.get("login") or "аккаунт"


def access_token(provider: Provider, secret: dict[str, Any],
                 transport: httpx.BaseTransport | None = None) -> tuple[str, bool]:
    """Действующий access-токен; при необходимости обновить его по refresh-токену.

    Args:
        provider: Провайдер.
        secret: Секрет доступа; при обновлении изменяется на месте.
        transport: Подмена сети для тестов.

    Returns:
        Токен и признак того, что секрет изменился и его нужно сохранить.

    Raises:
        AuthError: Нет refresh-токена, он отозван или приложение удалено из ``.env``.
    """
    token = secret.get("access_token")
    expires = secret.get("expires_at")
    if token and expires and datetime.fromisoformat(expires) - EXPIRY_MARGIN > datetime.now(UTC):
        return token, False
    refresh = secret.get("refresh_token")
    if not refresh:
        raise AuthError(f"{provider.title}: нет refresh-токена — переподключите аккаунт")
    app = provider.app_for_secret(secret)
    body = _token_request(provider, app,
                          {"grant_type": "refresh_token", "refresh_token": refresh}, transport)
    secret["access_token"] = body["access_token"]
    secret["expires_at"] = _expires_at(body)
    if body.get("refresh_token"):
        # Яндекс может выдать новый refresh-токен — старый тогда перестаёт работать.
        secret["refresh_token"] = body["refresh_token"]
    return secret["access_token"], True
