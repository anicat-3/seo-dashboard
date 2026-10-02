"""Коннектор SE Ranking (Project API).

Доступ — API-ключ из личного кабинета (API → Dashboard), передаётся заголовком
``Authorization: Token <ключ>``. Секрет доступа — ``{"api_key": "..."}``.
Ограничение API — не больше 5 запросов в секунду; коннектор делает 5–6
последовательных запросов на проект.

Коннектор не запускает проверки позиций, а читает уже снятые сервисом
(``GET /sites/positions``). Поисковики и регионы берутся из настроек проекта
в SE Ranking.

Документация: https://seranking.com/api/project/project-management/
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, ClassVar

import httpx

from app.connectors.base import (
    AuthError,
    CollectResult,
    Connector,
    ConnectorError,
    IntegrationContext,
    KeywordState,
    QuotaError,
    RawCall,
    Resource,
    TestResult,
)
from app.connectors.rank_tracking import (
    engine_code,
    keep_last_check,
    normalize_position,
    summarize,
)

BASE_URL = "https://api.seranking.com/v1/project-management"
TIMEOUT = httpx.Timeout(60.0, connect=15.0)
#: За сколько дней искать последний съём при загрузке истории.
LAST_CHECK_LOOKBACK_DAYS = 35


class SeRankingConnector(Connector):
    """Позиции по запросам и сводка по топам из SE Ranking."""

    system_code: ClassVar[str] = "seranking"
    history_days: ClassVar[int | None] = LAST_CHECK_LOOKBACK_DAYS

    def __init__(self, secret: dict[str, Any], context: IntegrationContext | None = None,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(secret, context)
        self._transport = transport

    # ------------------------------------------------------------- HTTP
    def _client(self) -> httpx.Client:
        key = (self.secret.get("api_key") or "").strip()
        if not key:
            raise AuthError("В доступе не указан API-токен SE Ranking")
        return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, transport=self._transport,
                            headers={"Authorization": f"Token {key}"})

    @staticmethod
    def _get(client: httpx.Client, path: str, raw: list[RawCall] | None = None,
             **params: Any) -> Any:
        response = client.get(path, params=params)
        if not response.is_success:
            try:
                body = response.json()
                # Документация описывает поле message; фактически при неверном ключе
                # API отвечает 401 с полем error_description.
                message = body.get("message") or body.get("error_description") or ""
            except ValueError:
                message = response.text[:200]
            if response.status_code == 429:
                raise QuotaError(f"SE Ranking: превышен лимит запросов ({message})")
            if response.status_code == 401 or (
                    response.status_code == 403 and message in ("No token", "Incorrect token")):
                raise AuthError("SE Ranking: API-токен недействителен")
            if response.status_code == 403:
                raise AuthError(f"SE Ranking: нет доступа ({message}). Проверьте, что тариф "
                                "включает Project API")
            raise ConnectorError(f"SE Ranking: ошибка {response.status_code} ({message})")
        data = response.json()
        if raw is not None:
            raw.append(RawCall(f"seranking{path}", params, data))
        return data

    # -------------------------------------------------------- ресурсы
    def list_resources(self) -> list[Resource]:
        """Проекты аккаунта SE Ranking."""
        with self._client() as client:
            sites = self._get(client, "/sites")
        return [Resource(str(site["id"]), f"{site.get('title') or site.get('name')} "
                                          f"({site.get('name')})",
                         extra={"domain": site.get("name"), "keywords": site.get("keyword_count")})
                for site in sites]

    def check_access(self) -> str:
        """Проверить токен списком проектов."""
        return f"Проектов в SE Ranking: {len(self.list_resources())}"

    def test(self) -> TestResult:
        """Последний съём за неделю: число запросов и дата проверки."""
        yesterday = date.today() - timedelta(days=1)
        result = self.collect(yesterday - timedelta(days=7), yesterday)
        dates = sorted({d for k in result.keywords for d, _, _ in k.positions})
        if not dates:
            return TestResult(False, "За последнюю неделю съёмов позиций нет — проверьте "
                                     "расписание проверок в SE Ranking")
        return TestResult(True, "Позиции получены", {
            "Запросов": len({k.external_keyword_id for k in result.keywords}),
            "Поисковиков и регионов": len({(k.search_engine, k.region) for k in result.keywords}),
            "Последний съём": dates[-1].isoformat(),
        })

    # ------------------------------------------------------------ сбор
    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """Позиции всех запросов проекта по датам съёмов в окне."""
        site_id = self.ctx.external_id
        result = CollectResult()
        with self._client() as client:
            engines = self._get(client, "/sites/search-engines", result.raw, site_id=site_id)
            catalog = {str(e["id"]): e.get("name", "") for e in
                       self._get(client, "/system/search-engines")}
            keywords = {str(k["id"]): k for k in
                        self._get(client, "/keywords", result.raw, site_id=site_id)}
            groups = {str(g["id"]): g.get("name") for g in
                      self._get(client, "/keywords/groups", site_id=site_id)}
            stats = self._get(client, "/sites/positions", result.raw, site_id=site_id,
                              date_from=date_from.isoformat(), date_to=date_to.isoformat(),
                              with_landing_pages=1)

        targets = {}
        for engine in engines:
            name = catalog.get(str(engine.get("search_engine_id")), "")
            region = engine.get("region_name") or _country(name) or "—"
            targets[engine["site_engine_id"]] = (engine_code(name), region)

        for block in stats:
            engine, region = targets.get(block.get("site_engine_id"), ("search", "—"))
            for item in block.get("keywords", []):
                info = keywords.get(str(item.get("id")), {})
                urls = {p.get("date"): p.get("url") for p in item.get("landing_pages") or []}
                state = KeywordState(
                    external_keyword_id=str(item.get("id")),
                    keyword=info.get("name") or f"#{item.get('id')}",
                    search_engine=engine, region=region,
                    group_name=groups.get(str(info.get("group_id"))),
                )
                for point in item.get("positions", []):
                    check_date = date.fromisoformat(point["date"])
                    position = normalize_position(point.get("pos"))
                    state.positions.append((check_date, position,
                                            urls.get(point["date"]) if position else None))
                if state.positions:
                    result.keywords.append(state)
        result.daily = summarize(self.system_code, result.keywords)
        if not result.keywords:
            result.messages.append("Новых съёмов позиций за период нет")
        return result

    def _history_days(self) -> int:
        """Сколько дней истории загрузить при подключении (0 — только последний съём)."""
        return int(self.ctx.settings.get("history_days") or 0)

    def backfill_in_one_call(self) -> bool:
        """Последний съём берётся одним вызовом; историю можно грузить по месяцам."""
        return self._history_days() == 0

    def backfill(self, date_from: date, date_to: date) -> CollectResult:
        """Загрузка при подключении: история за выбранный период или только последний съём."""
        if self._history_days():
            return self.collect(date_from, date_to)
        result = self.collect(max(date_from, date_to - timedelta(days=LAST_CHECK_LOOKBACK_DAYS)),
                              date_to)
        result.keywords = keep_last_check(result.keywords)
        result.daily = summarize(self.system_code, result.keywords)
        return result


def _country(engine_name: str) -> str:
    """«Google Belarus» → «Belarus»: регион по умолчанию для поисковика без города."""
    parts = engine_name.split(" ", 1)
    return parts[1] if len(parts) == 2 else ""
