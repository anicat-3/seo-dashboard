"""Коннектор Topvisor (API v2).

Доступ — User ID и API-ключ из профиля Топвизора (Настройки → API).
Секрет доступа — ``{"user_id": "...", "api_key": "..."}``. Запросы — POST с JSON
на ``https://api.topvisor.com/v2/json/<операция>/<сервис>/<метод>`` с заголовками
``User-Id`` и ``Authorization: bearer <ключ>``. Ответ — ``{"result": ..., "errors": [...]}``.

Коннектор не запускает проверки позиций (метод ``edit/positions_2/checker/go``
платный), а читает историю уже выполненных съёмов (``get/positions_2/history``).
Поисковики и регионы берутся из настроек проекта в Топвизоре.

Документация: https://topvisor.com/api/v2/ и https://topvisor.com/api/v2-services/positions_2/
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

BASE_URL = "https://api.topvisor.com/v2/json"
TIMEOUT = httpx.Timeout(90.0, connect=15.0)
LAST_CHECK_LOOKBACK_DAYS = 35
#: Устройство региона в Топвизоре.
DEVICES = {0: "desktop", 1: "tablet", 2: "mobile"}
DEVICE_LABELS = {"tablet": "планшет", "mobile": "моб."}
#: Сколько запросов забирать за один вызов истории.
PAGE_SIZE = 1000


class TopvisorConnector(Connector):
    """Позиции по запросам и сводка по топам из Topvisor."""

    system_code: ClassVar[str] = "topvisor"
    history_days: ClassVar[int | None] = LAST_CHECK_LOOKBACK_DAYS

    def __init__(self, secret: dict[str, Any], context: IntegrationContext | None = None,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(secret, context)
        self._transport = transport

    # ------------------------------------------------------------- HTTP
    def _client(self) -> httpx.Client:
        user_id = str(self.secret.get("user_id") or "").strip()
        key = (self.secret.get("api_key") or "").strip()
        if not user_id or not key:
            raise AuthError("В доступе Топвизора нужны User ID и API-ключ")
        return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, transport=self._transport,
                            headers={"User-Id": user_id, "Authorization": f"bearer {key}",
                                     "Content-Type": "application/json"})

    @staticmethod
    def _call(client: httpx.Client, method: str, payload: dict[str, Any],
              raw: list[RawCall] | None = None) -> Any:
        """Вызвать метод API и вернуть ``result``; ошибки перевести в исключения коннектора."""
        response = client.post(f"/{method}", json=payload)
        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError(f"Topvisor: ответ не JSON (HTTP {response.status_code})") from exc
        errors = data.get("errors") or []
        if errors or not response.is_success:
            message = "; ".join(str(e.get("string") or e.get("message") or e) for e in errors) \
                or f"HTTP {response.status_code}"
            lowered = message.lower()
            if response.status_code == 429 or "limit" in lowered or "лимит" in lowered:
                raise QuotaError(f"Topvisor: превышен лимит ({message})")
            if response.status_code in (401, 403) or any(
                    w in lowered for w in ("auth", "автор", "ключ", "key", "user-id", "user id")):
                raise AuthError(f"Topvisor: ошибка авторизации ({message}). Проверьте User ID "
                                "и API-ключ")
            raise ConnectorError(f"Topvisor: {message}")
        if raw is not None:
            raw.append(RawCall(f"topvisor/{method}", payload, data.get("result")))
        return data.get("result")

    def _projects(self, client: httpx.Client) -> list[dict[str, Any]]:
        return self._call(client, "get/projects_2/projects",
                          {"show_searchers_and_regions": 1, "fields": ["id", "name", "site"]}) or []

    # -------------------------------------------------------- ресурсы
    def list_resources(self) -> list[Resource]:
        """Проекты аккаунта Топвизора с их поисковиками и регионами."""
        with self._client() as client:
            projects = self._projects(client)
        resources = []
        for project in projects:
            regions = [f"{s.get('name')} · {r.get('name')}" for s in project.get("searchers", [])
                       for r in s.get("regions", [])]
            resources.append(Resource(str(project["id"]),
                                      f"{project.get('name')} ({project.get('site')})",
                                      extra={"domain": project.get("site"), "regions": regions}))
        return resources

    def check_access(self) -> str:
        """Проверить User ID и ключ списком проектов."""
        return f"Проектов в Топвизоре: {len(self.list_resources())}"

    def test(self) -> TestResult:
        """Последний съём за неделю: число запросов и дата проверки."""
        yesterday = date.today() - timedelta(days=1)
        result = self.collect(yesterday - timedelta(days=7), yesterday)
        dates = sorted({d for k in result.keywords for d, _, _ in k.positions})
        if not dates:
            return TestResult(False, "За последнюю неделю съёмов позиций нет — проверьте "
                                     "расписание проверок в Топвизоре")
        return TestResult(True, "Позиции получены", {
            "Запросов": len({k.external_keyword_id for k in result.keywords}),
            "Поисковиков и регионов": len({(k.search_engine, k.region) for k in result.keywords}),
            "Последний съём": dates[-1].isoformat(),
        })

    # ------------------------------------------------------------ сбор
    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """Позиции всех запросов проекта по каждому региону за даты съёмов в окне."""
        project_id = int(self.ctx.external_id)
        result = CollectResult()
        with self._client() as client:
            project = next((p for p in self._projects(client) if int(p["id"]) == project_id),
                           None)
            if project is None:
                raise ConnectorError(f"Topvisor: проект {project_id} не найден в аккаунте")
            for searcher in project.get("searchers", []):
                engine = engine_code(str(searcher.get("name", "")))
                for region in searcher.get("regions", []):
                    device = DEVICES.get(int(region.get("device") or 0), "desktop")
                    name = str(region.get("name") or region.get("areaName") or region["index"])
                    if device != "desktop":
                        # Один регион может отслеживаться и на ПК, и на телефоне — это разные срезы.
                        name = f"{name} · {DEVICE_LABELS[device]}"
                    result.keywords += self._region_history(
                        client, project_id, int(region["index"]), engine, name, device,
                        date_from, date_to, result.raw)
        result.daily = summarize(self.system_code, result.keywords)
        if not result.keywords:
            result.messages.append("Новых съёмов позиций за период нет")
        return result

    def _region_history(self, client: httpx.Client, project_id: int, region_index: int,
                        engine: str, region: str, device: str, date_from: date, date_to: date,
                        raw: list[RawCall]) -> list[KeywordState]:
        """История позиций одного региона, постранично."""
        states: list[KeywordState] = []
        offset = 0
        while True:
            payload = {
                "project_id": project_id,
                "regions_indexes": [region_index],
                "date1": date_from.isoformat(),
                "date2": date_to.isoformat(),
                "type_range": 0,  # все съёмы в диапазоне date1–date2
                "positions_fields": ["position", "relevant_url"],
                "fields": ["name", "group_name"],
                "limit": PAGE_SIZE,
                "offset": offset,
            }
            result = self._call(client, "get/positions_2/history", payload, raw) or {}
            keywords = result.get("keywords") or []
            for item in keywords:
                state = KeywordState(external_keyword_id=str(item.get("id")),
                                     keyword=item.get("name") or f"#{item.get('id')}",
                                     search_engine=engine, region=region, device=device,
                                     group_name=item.get("group_name"))
                for key, data in (item.get("positionsData") or {}).items():
                    # Ключ — «дата:ID проекта:индекс региона».
                    parts = str(key).split(":")
                    if (len(parts) < 3 or not isinstance(data, dict)
                            or int(parts[2]) != region_index):
                        continue
                    position = normalize_position(data.get("position"))
                    state.positions.append((date.fromisoformat(parts[0]), position,
                                            data.get("relevant_url") if position else None))
                if state.positions:
                    state.positions.sort()
                    states.append(state)
            if len(keywords) < PAGE_SIZE:
                return states
            offset += PAGE_SIZE

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
