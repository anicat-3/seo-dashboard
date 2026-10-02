"""Коннекторы Google по OAuth: Search Console и Google Analytics 4.

Один вход в Google-аккаунт даёт доступ к обеим системам (права
``webmasters.readonly`` и ``analytics.readonly``); для каждой создаётся свой доступ.

Документация:
    https://developers.google.com/webmaster-tools/v1/searchanalytics/query
    https://developers.google.com/webmaster-tools/v1/sitemaps/list
    https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport
    https://developers.google.com/analytics/devguides/config/admin/v1/rest/v1beta/accountSummaries/list
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.connectors.base import (
    CollectResult,
    Connector,
    DailyValue,
    Goal,
    IntegrationContext,
    PeriodValue,
    RawCall,
    Resource,
    SitemapState,
    TestResult,
)
from app.connectors.google_speed import raise_for_google_error
from app.connectors.oauth import GOOGLE, access_token

TIMEOUT = httpx.Timeout(60.0, connect=15.0)
GSC_BASE = "https://www.googleapis.com/webmasters/v3"
GA_DATA_BASE = "https://analyticsdata.googleapis.com/v1beta"
GA_ADMIN_BASE = "https://analyticsadmin.googleapis.com/v1beta"
#: GSC хранит историю 16 месяцев.
GSC_HISTORY_DAYS = 480
#: Строк в одном ответе GSC.
GSC_ROW_LIMIT = 25000


class _GoogleConnector(Connector):
    """Общая часть: OAuth-токен и HTTP-клиент."""

    service: ClassVar[str] = "Google"

    def __init__(self, secret: dict[str, Any], context: IntegrationContext | None = None,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(secret, context)
        self._transport = transport

    def _client(self) -> httpx.Client:
        token, updated = access_token(GOOGLE, self.secret, self._transport)
        self.secret_updated = self.secret_updated or updated
        return httpx.Client(timeout=TIMEOUT, transport=self._transport,
                            headers={"Authorization": f"Bearer {token}"})

    def _json(self, response: httpx.Response) -> Any:
        raise_for_google_error(response, self.service)
        return response.json()


def _parse_date(value: str) -> date:
    """Дата из ответа Google: «2026-09-28» (GSC) или «20260928» (GA4)."""
    value = value.strip()
    return date.fromisoformat(value if "-" in value else f"{value[:4]}-{value[4:6]}-{value[6:]}")


# ------------------------------------------------------------ Search Console
class SearchConsoleConnector(_GoogleConnector):
    """Клики, показы, CTR, средняя позиция по дням и карты сайта из Search Console.

    Даты в GSC — по тихоокеанскому времени; данные за последние 2–3 дня уточняются,
    поэтому каждый запуск перезабирает окно в 5 дней.
    """

    system_code: ClassVar[str] = "gsc"
    service: ClassVar[str] = "Search Console"
    history_days: ClassVar[int | None] = GSC_HISTORY_DAYS

    def list_resources(self) -> list[Resource]:
        """Ресурсы Search Console, к которым у аккаунта есть доступ."""
        with self._client() as client:
            data = self._json(client.get(f"{GSC_BASE}/sites"))
        sites = [s for s in data.get("siteEntry", [])
                 if s.get("permissionLevel") != "siteUnverifiedUser"]
        return [Resource(s["siteUrl"], s["siteUrl"], "America/Los_Angeles",
                         {"permission": s.get("permissionLevel")})
                for s in sorted(sites, key=lambda s: s["siteUrl"])]

    def check_access(self) -> str:
        """Число доступных ресурсов."""
        return f"Ресурсов Search Console: {len(self.list_resources())}"

    def _site_path(self) -> str:
        return f"{GSC_BASE}/sites/{quote(self.ctx.external_id, safe='')}"

    def test(self) -> TestResult:
        """Данные за последнюю неделю (за вчера GSC часто ещё пуст)."""
        yesterday = date.today() - timedelta(days=1)
        result = self.collect(yesterday - timedelta(days=6), yesterday)
        clicks = sum(v.value or 0 for v in result.daily if v.metric_code == "gsc.clicks")
        days = len({v.date for v in result.daily})
        return TestResult(True, "Данные Search Console получены",
                          {"Дней с данными": days, "Кликов за неделю": int(clicks),
                           "Карт сайта": len(result.sitemaps or [])})

    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """Показатели по дням за окно и текущее состояние карт сайта."""
        result = CollectResult(snapshot_date=date_to)
        body = {"startDate": date_from.isoformat(), "endDate": date_to.isoformat(),
                "dimensions": ["date"], "rowLimit": GSC_ROW_LIMIT,
                # «all» включает свежие неокончательные данные — их уточнит окно перезаписи.
                "dataState": "all"}
        with self._client() as client:
            data = self._json(client.post(f"{self._site_path()}/searchAnalytics/query",
                                          json=body))
            result.raw.append(RawCall("gsc/searchAnalytics/query", body, data))
            for row in data.get("rows", []):
                day = _parse_date(row["keys"][0])
                result.daily += [
                    DailyValue(day, "gsc.clicks", row.get("clicks")),
                    DailyValue(day, "gsc.impressions", row.get("impressions")),
                    DailyValue(day, "gsc.ctr", round(row.get("ctr", 0) * 100, 4)),
                    DailyValue(day, "gsc.position", round(row.get("position", 0), 2)),
                ]
            sitemaps = self._json(client.get(f"{self._site_path()}/sitemaps"))
            result.raw.append(RawCall("gsc/sitemaps", {}, sitemaps))
        result.sitemaps = [_gsc_sitemap(s) for s in sitemaps.get("sitemap", [])]
        return result


def _gsc_sitemap(item: dict[str, Any]) -> SitemapState:
    errors = int(item.get("errors") or 0)
    warnings = int(item.get("warnings") or 0)
    submitted = sum(int(c.get("submitted") or 0) for c in item.get("contents", [])) or None
    status = ("pending" if item.get("isPending") else "error" if errors
              else "warning" if warnings else "ok")
    downloaded = item.get("lastDownloaded")
    return SitemapState(
        sitemap_url=item["path"], status=status, submitted_urls=submitted, errors=errors,
        warnings=warnings, is_index=bool(item.get("isSitemapsIndex")),
        raw_status="pending" if item.get("isPending") else "processed",
        last_downloaded_at=datetime.fromisoformat(downloaded.replace("Z", "+00:00"))
        if downloaded else None,
    )


# --------------------------------------------------------------------- GA4
#: Метрики GA4 → коды дашборда.
GA4_METRICS = {
    "activeUsers": "ga4.users",
    "sessions": "ga4.sessions",
    "averageSessionDuration": "ga4.avg_session_duration",
    "bounceRate": "ga4.bounce_rate",
}
ORGANIC_FILTER = {"filter": {"fieldName": "sessionDefaultChannelGroup",
                             "stringFilter": {"matchType": "EXACT", "value": "Organic Search"}}}
GA4_HISTORY_DAYS = 480


class Ga4Connector(_GoogleConnector):
    """Пользователи (все и органика), сеансы, длительность, отказы и ключевые события GA4.

    Ресурс — свойство GA4 (``properties/123456``). Избранные цели — ключевые
    события (key events) свойства; список берётся из Admin API.
    """

    system_code: ClassVar[str] = "ga4"
    service: ClassVar[str] = "Google Analytics"
    history_days: ClassVar[int | None] = GA4_HISTORY_DAYS
    supports_period_totals: ClassVar[bool] = True

    def list_resources(self) -> list[Resource]:
        """Свойства GA4 всех аккаунтов, доступных пользователю."""
        tz = get_settings().app_timezone
        resources: list[Resource] = []
        page_token = None
        with self._client() as client:
            while True:
                params = {"pageSize": 200, **({"pageToken": page_token} if page_token else {})}
                data = self._json(client.get(f"{GA_ADMIN_BASE}/accountSummaries", params=params))
                for account in data.get("accountSummaries", []):
                    for prop in account.get("propertySummaries", []):
                        resources.append(Resource(
                            prop["property"],
                            f"{prop.get('displayName')} — {account.get('displayName')}", tz,
                            {"account": account.get("displayName")}))
                page_token = data.get("nextPageToken")
                if not page_token:
                    return sorted(resources, key=lambda r: r.name.lower())

    def check_access(self) -> str:
        """Число доступных свойств."""
        return f"Свойств GA4: {len(self.list_resources())}"

    def list_goals(self) -> list[Goal]:
        """Ключевые события свойства."""
        with self._client() as client:
            data = self._json(client.get(f"{GA_ADMIN_BASE}/{self.ctx.external_id}/keyEvents",
                                         params={"pageSize": 200}))
        return [Goal(e["eventName"], e["eventName"]) for e in data.get("keyEvents", [])]

    def _report(self, client: httpx.Client, body: dict[str, Any],
                raw: list[RawCall] | None = None) -> dict[str, Any]:
        data = self._json(client.post(f"{GA_DATA_BASE}/{self.ctx.external_id}:runReport",
                                      json={"limit": 100000, **body}))
        if raw is not None:
            raw.append(RawCall("ga4/runReport", body, data))
        return data

    def test(self) -> TestResult:
        """Пользователи за вчера."""
        yesterday = date.today() - timedelta(days=1)
        result = self.collect(yesterday, yesterday)
        users = next((v.value for v in result.daily
                      if v.metric_code == "ga4.users" and v.segment == "all"), 0)
        return TestResult(True, "Данные GA4 получены", {"Пользователей за вчера": users})

    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """Дневные метрики всего трафика и органики, ключевые события по дням."""
        result = CollectResult()
        date_range = [{"startDate": date_from.isoformat(), "endDate": date_to.isoformat()}]
        metrics = [{"name": m} for m in GA4_METRICS]
        with self._client() as client:
            for segment, extra in (("all", {}), ("organic", {"dimensionFilter": ORGANIC_FILTER})):
                data = self._report(client, {"dateRanges": date_range,
                                             "dimensions": [{"name": "date"}],
                                             "metrics": metrics, **extra}, result.raw)
                for row in data.get("rows", []):
                    day = _parse_date(row["dimensionValues"][0]["value"])
                    for name, cell in zip(GA4_METRICS, row["metricValues"], strict=True):
                        result.daily.append(DailyValue(day, GA4_METRICS[name],
                                                       _ga_value(name, cell["value"]), segment))
            if self.ctx.goal_ids:
                data = self._report(client, {
                    "dateRanges": date_range,
                    "dimensions": [{"name": "date"}, {"name": "eventName"}],
                    "metrics": [{"name": "keyEvents"}],
                    "dimensionFilter": {"filter": {"fieldName": "eventName", "inListFilter": {
                        "values": self.ctx.goal_ids}}},
                }, result.raw)
                for row in data.get("rows", []):
                    day = _parse_date(row["dimensionValues"][0]["value"])
                    result.daily.append(DailyValue(day, "ga4.goals",
                                                   float(row["metricValues"][0]["value"]),
                                                   row["dimensionValues"][1]["value"]))
        return result

    def fetch_period_totals(self, date_from: date, date_to: date,
                            segments: list[str]) -> list[PeriodValue]:
        """Итоги за точный период: пользователи не суммируются по дням."""
        names = ["activeUsers", "averageSessionDuration", "bounceRate"]
        values: list[PeriodValue] = []
        with self._client() as client:
            for segment in segments:
                if segment not in ("all", "organic"):
                    continue
                extra = {"dimensionFilter": ORGANIC_FILTER} if segment == "organic" else {}
                data = self._report(client, {
                    "dateRanges": [{"startDate": date_from.isoformat(),
                                    "endDate": date_to.isoformat()}],
                    "metrics": [{"name": n} for n in names], **extra})
                row = (data.get("rows") or [{"metricValues": [{"value": "0"}] * len(names)}])[0]
                for name, cell in zip(names, row["metricValues"], strict=True):
                    values.append(PeriodValue(GA4_METRICS[name], date_from, date_to,
                                              _ga_value(name, cell["value"]), segment))
        return values


def _ga_value(metric: str, raw: str) -> float:
    value = float(raw)
    # bounceRate в API — доля (0.45), в дашборде — проценты.
    return round(value * 100, 2) if metric == "bounceRate" else value

