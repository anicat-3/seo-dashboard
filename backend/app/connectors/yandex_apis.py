"""Коннекторы Яндекса по OAuth: Яндекс.Метрика и Яндекс.Вебмастер.

Один вход в Яндекс ID даёт доступ к обеим системам — права задаются
в настройках OAuth-приложения на oauth.yandex.ru. Токен передаётся заголовком
``Authorization: OAuth <токен>``.

Документация:
    https://yandex.ru/dev/metrika/ru/stat/openapi/data
    https://yandex.ru/dev/metrika/ru/management/openapi/counter/counters
    https://yandex.ru/dev/webmaster/doc/ru/
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, ClassVar

import httpx

from app.connectors.base import (
    AuthError,
    CollectResult,
    Connector,
    ConnectorError,
    DailyValue,
    Goal,
    IntegrationContext,
    IssueState,
    PeriodValue,
    QuotaError,
    RawCall,
    Resource,
    SitemapState,
    TestResult,
)
from app.connectors.oauth import YANDEX, access_token

TIMEOUT = httpx.Timeout(60.0, connect=15.0)
METRIKA_BASE = "https://api-metrika.yandex.net"
WEBMASTER_BASE = "https://api.webmaster.yandex.net/v4"
HISTORY_DAYS = 480
#: Метрика принимает не больше 20 метрик в одном запросе.
METRIKA_MAX_METRICS = 20
#: Коды ошибок API Яндекса, означающие проблему с токеном или правами.
AUTH_ERROR_CODES = ("invalid_token", "access_denied", "INVALID_OAUTH_TOKEN", "ACCESS_FORBIDDEN")


class _YandexConnector(Connector):
    """Общая часть: OAuth-токен, HTTP-клиент и разбор ошибок API Яндекса."""

    service: ClassVar[str] = "Яндекс"

    def __init__(self, secret: dict[str, Any], context: IntegrationContext | None = None,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(secret, context)
        self._transport = transport

    def _client(self, base_url: str) -> httpx.Client:
        token, updated = access_token(YANDEX, self.secret, self._transport)
        self.secret_updated = self.secret_updated or updated
        return httpx.Client(base_url=base_url, timeout=TIMEOUT, transport=self._transport,
                            headers={"Authorization": f"OAuth {token}"})

    def _json(self, response: httpx.Response) -> Any:
        if response.is_success:
            return response.json()
        try:
            body = response.json()
        except ValueError:
            body = {}
        errors = body.get("errors") or []
        message = (body.get("message") or body.get("error_message")
                   or "; ".join(e.get("message", "") for e in errors if isinstance(e, dict))
                   or f"HTTP {response.status_code}")
        code = body.get("error_code") or next(
            (e.get("error_type") for e in errors if isinstance(e, dict)), "")
        if response.status_code == 429 or code in ("quota", "TOO_MANY_REQUESTS_ERROR"):
            raise QuotaError(f"{self.service}: превышена квота ({message})")
        if response.status_code in (401, 403) or code in AUTH_ERROR_CODES:
            raise AuthError(f"{self.service}: нет доступа ({message}). Проверьте права "
                            "OAuth-приложения и доступ аккаунта к ресурсу")
        raise ConnectorError(f"{self.service}: ошибка {response.status_code} ({message})")


# ------------------------------------------------------------------ Метрика
class MetrikaConnector(_YandexConnector):
    """Пользователи (все и органика), визиты, длительность, отказы и цели Метрики.

    Все запросы — с ``accuracy=full`` (без семплирования, иначе на больших сайтах
    цифры будут приблизительными) и без визитов роботов: как «Роботность — Только люди»
    в интерфейсе Метрики.
    """

    system_code: ClassVar[str] = "metrika"
    service: ClassVar[str] = "Яндекс.Метрика"
    history_days: ClassVar[int | None] = HISTORY_DAYS
    supports_period_totals: ClassVar[bool] = True

    #: Метрики Метрики → коды дашборда.
    METRICS: ClassVar[dict[str, str]] = {
        "ym:s:users": "metrika.users",
        "ym:s:visits": "metrika.sessions",
        "ym:s:avgVisitDurationSeconds": "metrika.avg_session_duration",
        "ym:s:bounceRate": "metrika.bounce_rate",
    }
    HUMANS_FILTER: ClassVar[str] = "ym:s:isRobot=='No'"
    ORGANIC_FILTER: ClassVar[str] = "ym:s:lastTrafficSource=='organic'"

    def list_resources(self) -> list[Resource]:
        """Счётчики, доступные аккаунту (свои и гостевые)."""
        resources: list[Resource] = []
        offset = 1
        with self._client(METRIKA_BASE) as client:
            while True:
                data = self._json(client.get("/management/v1/counters",
                                             params={"per_page": 1000, "offset": offset}))
                counters = data.get("counters", [])
                for counter in counters:
                    resources.append(Resource(
                        str(counter["id"]),
                        f"{counter.get('name') or counter.get('site')} ({counter.get('site')})",
                        counter.get("time_zone_name") or "Europe/Moscow",
                        {"domain": counter.get("site")}))
                if len(counters) < 1000:
                    return sorted(resources, key=lambda r: r.name.lower())
                offset += 1000

    def check_access(self) -> str:
        """Число доступных счётчиков."""
        return f"Счётчиков Метрики: {len(self.list_resources())}"

    def list_goals(self) -> list[Goal]:
        """Цели счётчика."""
        with self._client(METRIKA_BASE) as client:
            data = self._json(client.get(f"/management/v1/counter/{self.ctx.external_id}/goals"))
        return [Goal(str(g["id"]), g.get("name") or str(g["id"])) for g in data.get("goals", [])]

    def _data(self, client: httpx.Client, params: dict[str, Any],
              raw: list[RawCall] | None = None) -> dict[str, Any]:
        params = dict(params)
        filters = " AND ".join(f for f in (self.HUMANS_FILTER, params.pop("filters", None)) if f)
        query = {"ids": self.ctx.external_id, "accuracy": "full", "limit": 100000,
                 "filters": filters, **params}
        data = self._json(client.get("/stat/v1/data", params=query))
        if raw is not None:
            raw.append(RawCall("metrika/stat/v1/data", query, data))
        return data

    def test(self) -> TestResult:
        """Пользователи за вчера."""
        yesterday = date.today() - timedelta(days=1)
        result = self.collect(yesterday, yesterday)
        users = next((v.value for v in result.daily
                      if v.metric_code == "metrika.users" and v.segment == "all"), 0)
        return TestResult(True, "Данные Метрики получены", {"Пользователей за вчера": users})

    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """Дневные метрики всего трафика и органики, достижения избранных целей по дням."""
        result = CollectResult()
        period = {"date1": date_from.isoformat(), "date2": date_to.isoformat(),
                  "dimensions": "ym:s:date"}
        with self._client(METRIKA_BASE) as client:
            for segment, extra in (("all", {}), ("organic", {"filters": self.ORGANIC_FILTER})):
                data = self._data(client, {**period, "metrics": ",".join(self.METRICS), **extra},
                                  result.raw)
                for row in data.get("data", []):
                    day = date.fromisoformat(row["dimensions"][0]["name"])
                    for name, value in zip(self.METRICS, row["metrics"], strict=True):
                        result.daily.append(DailyValue(day, self.METRICS[name], value, segment))
            goals = self.ctx.goal_ids
            for start in range(0, len(goals), METRIKA_MAX_METRICS):
                chunk = goals[start:start + METRIKA_MAX_METRICS]
                data = self._data(client, {**period, "metrics": ",".join(
                    f"ym:s:goal{g}reaches" for g in chunk)}, result.raw)
                for row in data.get("data", []):
                    day = date.fromisoformat(row["dimensions"][0]["name"])
                    for goal_id, value in zip(chunk, row["metrics"], strict=True):
                        result.daily.append(DailyValue(day, "metrika.goals", value, goal_id))
        return result

    def fetch_period_totals(self, date_from: date, date_to: date,
                            segments: list[str]) -> list[PeriodValue]:
        """Итоги за точный период: пользователи не суммируются по дням."""
        names = ["ym:s:users", "ym:s:avgVisitDurationSeconds", "ym:s:bounceRate"]
        values: list[PeriodValue] = []
        with self._client(METRIKA_BASE) as client:
            for segment in segments:
                if segment not in ("all", "organic"):
                    continue
                extra = {"filters": self.ORGANIC_FILTER} if segment == "organic" else {}
                data = self._data(client, {"date1": date_from.isoformat(),
                                           "date2": date_to.isoformat(),
                                           "metrics": ",".join(names), **extra})
                totals = data.get("totals") or [0] * len(names)
                for name, value in zip(names, totals, strict=True):
                    values.append(PeriodValue(self.METRICS[name], date_from, date_to, value,
                                              segment))
        return values


# ---------------------------------------------------------------- Вебмастер
#: Названия частых проблем диагностики Вебмастера (остальные показываются кодом).
DIAGNOSTIC_TITLES = {
    "DOCUMENTS_MISSING_TITLE": "Нет тега title у страниц",
    "DOCUMENTS_MISSING_DESCRIPTION": "Нет мета-описания у страниц",
    "DUPLICATE_PAGES": "Дубли страниц",
    "DUPLICATE_CONTENT_ATTRS": "Дубли title и description",
    "NO_SITEMAPS": "Не найдены карты сайта",
    "NO_SITEMAP_MODIFICATIONS": "Карты сайта давно не обновлялись",
    "ERRORS_IN_SITEMAPS": "Ошибки в картах сайта",
    "ERROR_IN_ROBOTS_TXT": "Ошибки в robots.txt",
    "NO_ROBOTS_TXT": "Нет файла robots.txt",
    "DISALLOWED_IN_ROBOTS": "Сайт закрыт в robots.txt",
    "CONNECT_FAILED": "Не удалось подключиться к серверу",
    "DNS_ERROR": "Ошибка DNS",
    "MAIN_PAGE_ERROR": "Главная страница возвращает ошибку",
    "MAIN_PAGE_REDIRECTS": "Главная страница перенаправляет на другой сайт",
    "SSL_CERTIFICATE_ERROR": "Ошибка SSL-сертификата",
    "SLOW_AVG_RESPONSE_TIME": "Долгий ответ сервера",
    "NOT_MOBILE_FRIENDLY": "Страницы не оптимизированы для мобильных",
    "NO_METRIKA_COUNTER_BINDING": "Сайт не связан со счётчиком Метрики",
    "NO_METRIKA_COUNTER_CRAWL_ENABLED": "Не включён обход по счётчику Метрики",
    "NO_REGIONS": "Не указан регион сайта",
    "THREATS": "Обнаружены угрозы безопасности",
    "BIG_FAVICON_ABSENT": "Нет фавиконки большого размера",
    "FAVICON_ERROR": "Ошибка фавиконки",
    "INSIGNIFICANT_CGI_PARAMETER": "Незначащие GET-параметры в URL",
    "URL_ALERT_4XX": "Страницы с кодом ответа 4xx",
    "URL_ALERT_5XX": "Страницы с кодом ответа 5xx",
}


def _wm_date(value: date) -> str:
    return f"{value.isoformat()}T00:00:00.000+03:00"


def _wm_day(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


class WebmasterConnector(_YandexConnector):
    """Клики, показы, позиция, страницы в поиске, ошибки диагностики и карты сайта Вебмастера.

    История поисковых запросов в Вебмастере хранится ограниченное время, поэтому
    её важно копить в дашборде с первого дня.
    """

    system_code: ClassVar[str] = "ywm"
    service: ClassVar[str] = "Яндекс.Вебмастер"
    history_days: ClassVar[int | None] = 180

    def _user_id(self, client: httpx.Client) -> str:
        if "user_id" not in self.secret:
            self.secret["user_id"] = str(self._json(client.get("/user"))["user_id"])
            self.secret_updated = True
        return self.secret["user_id"]

    def list_resources(self) -> list[Resource]:
        """Подтверждённые сайты аккаунта."""
        with self._client(WEBMASTER_BASE) as client:
            uid = self._user_id(client)
            data = self._json(client.get(f"/user/{uid}/hosts"))
        hosts = [h for h in data.get("hosts", []) if h.get("verified")]
        return [Resource(h["host_id"], h.get("unicode_host_url") or h.get("ascii_host_url"),
                         "Europe/Moscow", {"domain": h.get("ascii_host_url")})
                for h in sorted(hosts, key=lambda h: h.get("unicode_host_url", ""))]

    def check_access(self) -> str:
        """Число подтверждённых сайтов."""
        return f"Сайтов в Вебмастере: {len(self.list_resources())}"

    def test(self) -> TestResult:
        """Последняя неделя запросов и сводка по сайту."""
        yesterday = date.today() - timedelta(days=1)
        result = self.collect(yesterday - timedelta(days=6), yesterday)
        pages = next((v.value for v in result.daily if v.metric_code == "ywm.pages_in_search"),
                     None)
        clicks = sum(v.value or 0 for v in result.daily if v.metric_code == "ywm.clicks")
        return TestResult(True, "Данные Вебмастера получены", {
            "Кликов за неделю": int(clicks), "Страниц в поиске": pages,
            "Открытых ошибок": len(result.issues or [])})

    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """История запросов и страниц в поиске за окно, текущие ошибки и карты сайта."""
        result = CollectResult(snapshot_date=date_to)
        window = {"date_from": _wm_date(date_from), "date_to": _wm_date(date_to)}
        with self._client(WEBMASTER_BASE) as client:
            host = f"/user/{self._user_id(client)}/hosts/{self.ctx.external_id}"

            queries = self._json(client.get(f"{host}/search-queries/all/history", params=[
                ("query_indicator", "TOTAL_SHOWS"), ("query_indicator", "TOTAL_CLICKS"),
                ("query_indicator", "AVG_SHOW_POSITION"), *window.items()]))
            result.raw.append(RawCall("ywm/search-queries/all/history", window, queries))
            indicators = queries.get("indicators", {})
            by_day: dict[date, dict[str, float]] = {}
            for indicator, points in indicators.items():
                for point in points:
                    by_day.setdefault(_wm_day(point["date"]), {})[indicator] = point.get("value")
            for day, values in sorted(by_day.items()):
                shows, clicks = values.get("TOTAL_SHOWS"), values.get("TOTAL_CLICKS")
                result.daily += [
                    DailyValue(day, "ywm.impressions", shows),
                    DailyValue(day, "ywm.clicks", clicks),
                    DailyValue(day, "ywm.ctr",
                               round(clicks / shows * 100, 4) if shows and clicks is not None
                               else None),
                    DailyValue(day, "ywm.position", values.get("AVG_SHOW_POSITION")),
                ]

            history = self._json(client.get(f"{host}/search-urls/in-search/history",
                                            params=window))
            result.raw.append(RawCall("ywm/search-urls/in-search/history", window, history))
            for point in history.get("history", []):
                result.daily.append(DailyValue(_wm_day(point["date"]), "ywm.pages_in_search",
                                               point.get("value")))

            summary = self._json(client.get(f"{host}/summary"))
            result.raw.append(RawCall("ywm/summary", {}, summary))
            if summary.get("excluded_pages_count") is not None:
                result.daily.append(DailyValue(date_to, "ywm.excluded_pages",
                                               summary["excluded_pages_count"]))

            diagnostics = self._json(client.get(f"{host}/diagnostics"))
            result.raw.append(RawCall("ywm/diagnostics", {}, diagnostics))
            result.issues = [
                IssueState(code, DIAGNOSTIC_TITLES.get(code, code.replace("_", " ").capitalize()),
                           info.get("severity", "RECOMMENDATION"),
                           details={"last_state_update": info.get("last_state_update")})
                for code, info in (diagnostics.get("problems") or {}).items()
                if info.get("state") == "PRESENT"
            ]
            result.daily.append(DailyValue(date_to, "ywm.open_issues", len(result.issues)))

            sitemaps = self._json(client.get(f"{host}/sitemaps"))
            result.raw.append(RawCall("ywm/sitemaps", {}, sitemaps))
        result.sitemaps = [_wm_sitemap(s) for s in sitemaps.get("sitemaps", [])]
        return result


def _wm_sitemap(item: dict[str, Any]) -> SitemapState:
    errors = int(item.get("errors_count") or 0)
    accessed = item.get("last_access_date")
    return SitemapState(
        sitemap_url=item.get("sitemap_url", ""), status="error" if errors else "ok",
        submitted_urls=item.get("urls_count"), errors=errors,
        is_index=item.get("sitemap_type") == "INDEX_SITEMAP" or bool(item.get("children_count")),
        raw_status=item.get("sitemap_type"),
        last_downloaded_at=datetime.fromisoformat(accessed.replace("Z", "+00:00"))
        if accessed else None,
    )
