"""Общий интерфейс коннекторов внешних систем.

Каждая система — отдельный модуль с классом-наследником :class:`Connector`.
Коннектор ничего не знает о БД: он получает расшифрованный секрет и параметры
подключения, обращается к API и возвращает :class:`CollectResult`.
Запись в БД (upsert) выполняет :mod:`app.services.writer`, поэтому новая система
добавляется без изменения схемы БД и без изменения кода записи.
"""

from __future__ import annotations

import functools
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, ClassVar

import httpx


class ConnectorError(Exception):
    """Ошибка обращения к внешней системе."""


class AuthError(ConnectorError):
    """Доступ отозван или недействителен: сбор по аккаунту невозможен до переподключения."""


class QuotaError(ConnectorError):
    """Превышена квота API; запрос стоит повторить позже."""


class NotSupportedError(ConnectorError):
    """Операция не поддерживается системой (например, итоги за период у GSC)."""


class NetworkError(ConnectorError):
    """Нет связи с внешней системой: адрес не найден, соединение не установлено, тайм-аут."""


def network_error_message(exc: httpx.TransportError) -> str:
    """Понятное описание сетевого сбоя вместо системного текста вроде «getaddrinfo failed»."""
    try:
        host = exc.request.url.host
    except RuntimeError:
        host = "сервиса"
    text = str(exc).lower()
    if isinstance(exc, httpx.TimeoutException):
        return f"{host} не ответил вовремя. Повторите попытку позже"
    if isinstance(exc, httpx.ConnectError) and any(
            marker in text for marker in ("getaddrinfo", "name or service", "nodename")):
        return (f"Нет связи с {host}: адрес не найден (DNS). Проверьте подключение "
                "к интернету или VPN")
    if isinstance(exc, httpx.ConnectError):
        return f"Нет связи с {host}: соединение не установлено. Проверьте интернет или VPN"
    return f"Сбой сети при обращении к {host}. Повторите попытку позже"


#: Методы коннектора, которые обращаются к сети.
NETWORK_METHODS = ("list_resources", "check_access", "list_goals", "test", "collect", "backfill",
                   "fetch_period_totals")


def _translate_network_errors(method: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except httpx.TransportError as exc:
            raise NetworkError(network_error_message(exc)) from exc

    wrapper.translates_network_errors = True  # type: ignore[attr-defined]
    return wrapper


@dataclass(slots=True)
class Resource:
    """Ресурс внешней системы, который можно подключить к проекту."""

    external_id: str
    name: str
    timezone: str = "UTC"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Goal:
    """Цель GA4 (key event) или Метрики."""

    external_goal_id: str
    name: str


@dataclass(slots=True)
class IntegrationContext:
    """Параметры подключения, передаваемые коннектору.

    Attributes:
        integration_id: ID подключения в БД.
        external_id: Идентификатор ресурса во внешней системе.
        timezone: Часовой пояс источника.
        settings: Специфичные настройки (фильтр органики, поисковики и регионы и т. п.).
        goal_ids: ID избранных целей.
        monitored_urls: Пары ``(monitored_url_id, url)`` для PSI.
        domain: Домен проекта.
    """

    integration_id: int
    external_id: str
    timezone: str = "UTC"
    settings: dict[str, Any] = field(default_factory=dict)
    goal_ids: list[str] = field(default_factory=list)
    monitored_urls: list[tuple[int, str]] = field(default_factory=list)
    domain: str = ""


@dataclass(slots=True)
class DailyValue:
    """Дневное значение метрики."""

    date: date
    metric_code: str
    value: float | None
    segment: str = "all"


@dataclass(slots=True)
class PeriodValue:
    """Итог несуммируемой метрики за точный период."""

    metric_code: str
    date_from: date
    date_to: date
    value: float | None
    segment: str = "all"


@dataclass(slots=True)
class SitemapState:
    """Состояние карты сайта на момент сбора."""

    sitemap_url: str
    status: str
    submitted_urls: int | None = None
    errors: int = 0
    warnings: int = 0
    is_index: bool = False
    raw_status: str | None = None
    last_downloaded_at: datetime | None = None


@dataclass(slots=True)
class IssueState:
    """Открытая ошибка диагностики на момент сбора."""

    issue_code: str
    title: str
    severity: str
    affected_count: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CwvPoint:
    """Недельная точка CrUX History API."""

    period_end: date
    device: str
    metric: str
    p75: float | None
    good_pct: float | None
    ni_pct: float | None
    poor_pct: float | None
    scope: str = "origin"
    url: str = ""


@dataclass(slots=True)
class PsiResult:
    """Результат PageSpeed Insights для URL и устройства (медиана прогонов)."""

    monitored_url_id: int
    device: str
    run_at: datetime
    performance_score: float | None
    field_lcp: float | None = None
    field_inp: float | None = None
    field_cls: float | None = None
    field_fcp: float | None = None
    field_ttfb: float | None = None
    field_category: str | None = None
    is_origin_fallback: bool = False


@dataclass(slots=True)
class KeywordState:
    """Запрос из системы съёма позиций и его позиции по датам проверок."""

    external_keyword_id: str
    keyword: str
    search_engine: str
    region: str
    device: str = "desktop"
    group_name: str | None = None
    positions: list[tuple[date, int | None, str | None]] = field(default_factory=list)


@dataclass(slots=True)
class RawCall:
    """Сырой ответ API для таблицы ``raw_responses``."""

    endpoint: str
    request_params: dict[str, Any]
    response: Any


@dataclass(slots=True)
class CollectResult:
    """Всё, что коннектор получил за один запуск.

    ``snapshot_date`` задаётся для снимков текущего состояния (карты сайта, ошибки):
    они относятся к дню сбора и задним числом не восстанавливаются.
    ``partial`` выставляется, если часть данных не получена (например, из-за квоты).
    """

    daily: list[DailyValue] = field(default_factory=list)
    period: list[PeriodValue] = field(default_factory=list)
    sitemaps: list[SitemapState] | None = None
    issues: list[IssueState] | None = None
    cwv: list[CwvPoint] = field(default_factory=list)
    psi: list[PsiResult] = field(default_factory=list)
    keywords: list[KeywordState] = field(default_factory=list)
    raw: list[RawCall] = field(default_factory=list)
    snapshot_date: date | None = None
    partial: bool = False
    messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TestResult:
    """Результат пробного запроса за вчерашний день."""

    ok: bool
    message: str
    sample: dict[str, Any] = field(default_factory=dict)


class Connector(ABC):
    """Базовый класс коннектора.

    Attributes:
        system_code: Код системы из справочника ``systems``.
        history_days: Сколько дней истории отдаёт API при первичной загрузке
            (``None`` — история не загружается, только текущее состояние).
        supports_period_totals: Умеет ли система отдавать итоги за точный период
            (пользователи GA4 и Метрики).
    """

    system_code: ClassVar[str]
    history_days: ClassVar[int | None] = None
    supports_period_totals: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Сетевые сбои в методах наследника превращаются в :class:`NetworkError`.

        Так обработчики, которые ловят :class:`ConnectorError`, показывают понятное
        сообщение, а не ошибку сервера.
        """
        super().__init_subclass__(**kwargs)
        for name in NETWORK_METHODS:
            method = cls.__dict__.get(name)
            if method is not None and not getattr(method, "translates_network_errors", False):
                setattr(cls, name, _translate_network_errors(method))

    def __init__(self, secret: dict[str, Any], context: IntegrationContext | None = None):
        self.secret = secret
        self.context = context
        #: Секрет изменён в ходе работы (обновлён OAuth-токен) — его нужно сохранить в БД.
        self.secret_updated = False

    @property
    def ctx(self) -> IntegrationContext:
        """Контекст подключения; обязателен для всех операций, кроме списка ресурсов."""
        if self.context is None:
            raise RuntimeError("Коннектор создан без контекста подключения")
        return self.context

    @abstractmethod
    def list_resources(self) -> list[Resource]:
        """Вернуть ресурсы аккаунта, доступные для подключения к проекту."""

    def check_access(self) -> str:
        """Проверить, что доступ работает; вернуть короткое описание для интерфейса.

        По умолчанию запрашивает список ресурсов аккаунта. Системы по API-ключу,
        у которых нет списка ресурсов, переопределяют метод.
        """
        return f"Доступно ресурсов: {len(self.list_resources())}"

    def list_goals(self) -> list[Goal]:
        """Вернуть цели ресурса (для GA4 и Метрики). По умолчанию целей нет."""
        return []

    @abstractmethod
    def test(self) -> TestResult:
        """Выполнить пробный запрос за вчерашний день."""

    @abstractmethod
    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """Забрать данные за диапазон дат и снимки текущего состояния.

        Args:
            date_from: Первая дата окна (включительно), в часовом поясе источника.
            date_to: Последняя дата окна (включительно).
        """

    def backfill_in_one_call(self) -> bool:
        """Загружать историю одним вызовом, а не частями по месяцу.

        Нужно системам позиций в режиме «только последний съём»: дробление окна
        на месяцы дало бы по съёму на каждый месяц.
        """
        return False

    def backfill(self, date_from: date, date_to: date) -> CollectResult:
        """Загрузить доступную историю после подключения.

        По умолчанию совпадает с :meth:`collect`; системы позиций переопределяют
        метод и забирают только последний съём.
        """
        return self.collect(date_from, date_to)

    def fetch_period_totals(self, date_from: date, date_to: date,
                            segments: list[str]) -> list[PeriodValue]:
        """Запросить у API итоги несуммируемых метрик за точный период.

        Raises:
            NotSupportedError: Система не отдаёт итоги за период.
        """
        raise NotSupportedError(f"{self.system_code}: итоги за период не поддерживаются")
