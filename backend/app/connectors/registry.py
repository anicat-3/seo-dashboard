"""Реестр коннекторов: выбор реализации по системе и типу доступа."""

from __future__ import annotations

from typing import Any

from app.connectors.base import Connector, ConnectorError, IntegrationContext
from app.connectors.bing import BingConnector
from app.connectors.google_apis import Ga4Connector, SearchConsoleConnector
from app.connectors.google_speed import CruxConnector, PsiConnector
from app.connectors.seranking import SeRankingConnector
from app.connectors.topvisor import TopvisorConnector
from app.connectors.yandex_apis import MetrikaConnector, WebmasterConnector

#: Коннекторы по кодам систем.
REAL_CONNECTORS: dict[str, type[Connector]] = {
    "gsc": SearchConsoleConnector,
    "ga4": Ga4Connector,
    "metrika": MetrikaConnector,
    "ywm": WebmasterConnector,
    "bing": BingConnector,
    "psi": PsiConnector,
    "crux": CruxConnector,
    "topvisor": TopvisorConnector,
    "seranking": SeRankingConnector,
}


class ConnectorUnavailableError(ConnectorError):
    """Для системы нет коннектора."""


def get_connector(system_code: str, auth_type: str, secret: dict[str, Any],
                  context: IntegrationContext | None = None) -> Connector:
    """Создать коннектор для системы.

    Args:
        system_code: Код системы (``gsc``, ``ga4`` …).
        auth_type: Тип доступа из ``credentials.auth_type``.
        secret: Расшифрованный секрет доступа.
        context: Параметры подключения (не нужен для списка ресурсов).

    Raises:
        ConnectorUnavailableError: Неизвестная система.
    """
    connector_cls = REAL_CONNECTORS.get(system_code)
    if connector_cls is None:
        raise ConnectorUnavailableError(
            f"Нет коннектора для системы «{system_code}»")
    return connector_cls(secret, context)
