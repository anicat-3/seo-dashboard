"""Коннектор Bing Webmaster Tools API (по API-ключу).

Секрет доступа — ``{"api_key": "..."}`` (Bing Webmaster → Settings → API access).
Методы вызываются как ``GET https://ssl.bing.com/webmaster/api.svc/json/<Метод>?apikey=…``,
ответ — ``{"d": ...}``; даты приходят в формате WCF ``/Date(1695884400000-0700)/``.

Bing не отдаёт среднюю позицию по сайту в целом и список URL с ошибками
(``GetCrawlIssues`` возвращает пустой ответ), поэтому собираются клики, показы,
карты сайта и счётчики ошибок обхода.

Документация: https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, ClassVar

import httpx

from app.connectors.base import (
    AuthError,
    CollectResult,
    Connector,
    ConnectorError,
    DailyValue,
    IntegrationContext,
    QuotaError,
    RawCall,
    Resource,
    SitemapState,
    TestResult,
)

BASE_URL = "https://ssl.bing.com/webmaster/api.svc/json"
TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_WCF_DATE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")

#: Поля GetCrawlStats → метрики дашборда.
CRAWL_FIELDS = {
    "Code4xx": "bing.crawl_4xx",
    "Code5xx": "bing.crawl_5xx",
    "BlockedByRobotsTxt": "bing.robots_blocked",
    "DnsFailures": "bing.dns_failures",
    "ConnectionTimeout": "bing.timeouts",
}


def parse_wcf_date(value: str | None) -> datetime | None:
    """Дата WCF «/Date(1695884400000-0700)/» → datetime с часовым поясом."""
    if not value:
        return None
    match = _WCF_DATE.match(value)
    if not match:
        return None
    moment = datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC)
    offset = match.group(2)
    if offset:
        sign = 1 if offset[0] == "+" else -1
        tz = timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5])))
        return moment.astimezone(tz)
    return moment


class BingConnector(Connector):
    """Клики и показы по дням, карты сайта и ошибки обхода из Bing Webmaster."""

    system_code: ClassVar[str] = "bing"
    history_days: ClassVar[int | None] = 180

    def __init__(self, secret: dict[str, Any], context: IntegrationContext | None = None,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(secret, context)
        self._transport = transport

    def _call(self, client: httpx.Client, method: str, raw: list[RawCall] | None = None,
              **params: Any) -> Any:
        key = (self.secret.get("api_key") or "").strip()
        if not key:
            raise AuthError("В доступе не указан API-ключ Bing")
        response = client.get(f"{BASE_URL}/{method}", params={"apikey": key, **params})
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not response.is_success:
            message = body.get("Message") or body.get("message") or response.text[:200]
            code = body.get("ErrorCode")
            if response.status_code == 429 or "ThrottleUser" in str(message):
                raise QuotaError(f"Bing: превышена квота ({message})")
            if response.status_code in (401, 403) or "InvalidApiKey" in str(message) \
                    or code in (3, 14):
                raise AuthError(f"Bing: API-ключ недействителен или нет доступа к сайту "
                                f"({message})")
            raise ConnectorError(f"Bing: ошибка {response.status_code} ({message})")
        if raw is not None:
            raw.append(RawCall(f"bing/{method}", params, body))
        return body.get("d")

    def list_resources(self) -> list[Resource]:
        """Подтверждённые сайты аккаунта Bing Webmaster."""
        with httpx.Client(timeout=TIMEOUT, transport=self._transport) as client:
            sites = self._call(client, "GetUserSites") or []
        return [Resource(s["Url"], s["Url"], "UTC") for s in sites if s.get("IsVerified", True)]

    def check_access(self) -> str:
        """Число сайтов в аккаунте."""
        return f"Сайтов в Bing Webmaster: {len(self.list_resources())}"

    def test(self) -> TestResult:
        """Клики за последние 2 недели."""
        yesterday = date.today() - timedelta(days=1)
        result = self.collect(yesterday - timedelta(days=13), yesterday)
        clicks = sum(v.value or 0 for v in result.daily if v.metric_code == "bing.clicks")
        return TestResult(True, "Данные Bing получены",
                          {"Кликов за 2 недели": int(clicks),
                           "Карт сайта": len(result.sitemaps or [])})

    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """Клики, показы и ошибки обхода по дням за окно; текущее состояние карт сайта."""
        result = CollectResult(snapshot_date=date_to)
        site = self.ctx.external_id
        with httpx.Client(timeout=TIMEOUT, transport=self._transport) as client:
            traffic = self._call(client, "GetRankAndTrafficStats", result.raw, siteUrl=site) or []
            crawl = self._call(client, "GetCrawlStats", result.raw, siteUrl=site) or []
            feeds = self._call(client, "GetFeeds", result.raw, siteUrl=site) or []

        for row in traffic:
            moment = parse_wcf_date(row.get("Date"))
            if moment is None or not date_from <= moment.date() <= date_to:
                continue
            day, clicks, shows = moment.date(), row.get("Clicks"), row.get("Impressions")
            result.daily += [
                DailyValue(day, "bing.clicks", clicks),
                DailyValue(day, "bing.impressions", shows),
                DailyValue(day, "bing.ctr",
                           round(clicks / shows * 100, 4) if shows and clicks is not None
                           else None),
            ]
        for row in crawl:
            moment = parse_wcf_date(row.get("Date"))
            if moment is None or not date_from <= moment.date() <= date_to:
                continue
            for field, metric in CRAWL_FIELDS.items():
                result.daily.append(DailyValue(moment.date(), metric, row.get(field)))
        result.sitemaps = [_bing_feed(f) for f in feeds]
        return result


def _bing_feed(feed: dict[str, Any]) -> SitemapState:
    status_text = str(feed.get("Status") or "")
    lowered = status_text.lower()
    status = ("ok" if lowered in ("success", "ok", "") else "pending"
              if "pending" in lowered or "processing" in lowered else "error")
    return SitemapState(sitemap_url=feed.get("Url", ""), status=status,
                        submitted_urls=feed.get("UrlCount"),
                        is_index=str(feed.get("Type", "")).lower() == "sitemapindex",
                        raw_status=status_text or None,
                        last_downloaded_at=parse_wcf_date(feed.get("LastCrawled")))
