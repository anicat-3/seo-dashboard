"""Коннекторы Topvisor и SE Ranking на ответах в формате их API (сеть подменяется)."""

import json
from datetime import date

import httpx
import pytest

from app.connectors.base import AuthError, IntegrationContext, KeywordState, QuotaError
from app.connectors.rank_tracking import (
    engine_code,
    keep_last_check,
    normalize_position,
    summarize,
    visibility,
)
from app.connectors.seranking import SeRankingConnector
from app.connectors.topvisor import TopvisorConnector


# ------------------------------------------------------------- общая логика
def test_normalize_position():
    assert normalize_position("5") == 5
    assert normalize_position(7) == 7
    assert normalize_position("--") is None
    assert normalize_position(0) is None
    assert normalize_position(None) is None
    assert normalize_position(150) is None


def test_visibility_and_summary():
    assert visibility([1, 1]) == 100.0
    assert visibility([None, None]) == 0.0
    keyword = KeywordState("1", "kw", "google", "Минск",
                           positions=[(date(2026, 9, 28), 2, None)])
    other = KeywordState("2", "kw2", "google", "Минск",
                         positions=[(date(2026, 9, 28), None, None)])
    values = {v.metric_code: v.value for v in summarize("topvisor", [keyword, other])}
    assert values["topvisor.avg_position"] == 2
    assert values["topvisor.top3"] == 1 and values["topvisor.top100"] == 1
    assert values["topvisor.keywords_total"] == 2


def test_keep_last_check():
    kw = KeywordState("1", "kw", "google", "Минск",
                      positions=[(date(2026, 9, 21), 5, None), (date(2026, 9, 28), 4, None)])
    assert keep_last_check([kw])[0].positions == [(date(2026, 9, 28), 4, None)]


def test_engine_code():
    assert engine_code("Google Belarus") == "google"
    assert engine_code("Яндекс") == "yandex"


# --------------------------------------------------------------- SE Ranking
SR_SECRET = {"api_key": "sr-token"}


def seranking_handler(request: httpx.Request) -> httpx.Response:
    """Ответы в формате документации SE Ranking Project API."""
    assert request.headers["Authorization"] == "Token sr-token"
    path = request.url.path.removeprefix("/v1/project-management")
    if path == "/sites":
        return httpx.Response(200, json=[{"id": 123, "title": "Мой сайт", "name": "site.by",
                                          "keyword_count": 2}])
    if path == "/sites/search-engines":
        return httpx.Response(200, json=[
            {"site_engine_id": 1, "search_engine_id": 339, "region_id": 0, "region_name": None},
            {"site_engine_id": 2, "search_engine_id": 500, "region_id": 0,
             "region_name": "Minsk, Minsk, Belarus"},
        ])
    if path == "/system/search-engines":
        return httpx.Response(200, json=[{"id": "339", "name": "Google Belarus", "regionid": "21"},
                                         {"id": "500", "name": "Yandex", "regionid": "21"}])
    if path == "/keywords":
        return httpx.Response(200, json=[{"id": "12", "name": "купить ноутбук", "group_id": "7"},
                                         {"id": "13", "name": "ноутбук цена", "group_id": "7"}])
    if path == "/keywords/groups":
        return httpx.Response(200, json=[{"id": "7", "name": "Ноутбуки"}])
    if path == "/sites/positions":
        assert request.url.params["site_id"] == "123"
        return httpx.Response(200, json=[
            {"site_engine_id": 1, "keywords": [
                {"id": "12", "positions": [
                    {"date": "2026-09-21", "pos": 8, "change": 0},
                    {"date": "2026-09-28", "pos": 5, "change": 3}],
                 "landing_pages": [{"date": "2026-09-28", "url": "https://site.by/notebooks/"}]},
                {"id": "13", "positions": [
                    {"date": "2026-09-21", "pos": 0, "change": 0},
                    {"date": "2026-09-28", "pos": 0, "change": 0}]},
            ]},
            {"site_engine_id": 2, "keywords": [
                {"id": "12", "positions": [{"date": "2026-09-28", "pos": 2, "change": 0}]}]},
        ])
    return httpx.Response(404, json={"message": "Not Found"})


def sr_context() -> IntegrationContext:
    return IntegrationContext(integration_id=1, external_id="123", domain="site.by")


def test_seranking_resources():
    connector = SeRankingConnector(SR_SECRET, transport=httpx.MockTransport(seranking_handler))
    (resource,) = connector.list_resources()
    assert resource.external_id == "123" and "site.by" in resource.name


def test_seranking_collect():
    connector = SeRankingConnector(SR_SECRET, sr_context(),
                                   transport=httpx.MockTransport(seranking_handler))
    result = connector.collect(date(2026, 9, 21), date(2026, 9, 30))
    by_key = {(k.external_keyword_id, k.search_engine, k.region): k for k in result.keywords}
    google = by_key[("12", "google", "Belarus")]
    assert google.keyword == "купить ноутбук" and google.group_name == "Ноутбуки"
    assert google.positions == [(date(2026, 9, 21), 8, None),
                                (date(2026, 9, 28), 5, "https://site.by/notebooks/")]
    assert by_key[("13", "google", "Belarus")].positions[-1][1] is None  # pos 0 — не найдено
    assert ("12", "yandex", "Minsk, Minsk, Belarus") in by_key
    top10 = [v for v in result.daily if v.metric_code == "seranking.top10"
             and v.segment == "google:Belarus" and v.date == date(2026, 9, 28)]
    assert top10[0].value == 1


def test_seranking_backfill_keeps_last_check():
    connector = SeRankingConnector(SR_SECRET, sr_context(),
                                   transport=httpx.MockTransport(seranking_handler))
    result = connector.backfill(date(2026, 8, 1), date(2026, 9, 30))
    assert {d for k in result.keywords for d, _, _ in k.positions} == {date(2026, 9, 28)}


def test_seranking_errors():
    bad_token = httpx.MockTransport(
        lambda r: httpx.Response(403, json={"message": "Incorrect token"}))
    with pytest.raises(AuthError, match="недействителен"):
        SeRankingConnector(SR_SECRET, transport=bad_token).check_access()
    # Фактический ответ API на неверный ключ (проверено на api.seranking.com).
    real_401 = httpx.MockTransport(lambda r: httpx.Response(401, json={
        "error_description": "Authentication failed. Please ensure you have a valid, "
                             "enabled API key."}))
    with pytest.raises(AuthError, match="недействителен"):
        SeRankingConnector(SR_SECRET, transport=real_401).check_access()
    no_plan = httpx.MockTransport(lambda r: httpx.Response(403, json={"message": "No access"}))
    with pytest.raises(AuthError, match="тариф"):
        SeRankingConnector(SR_SECRET, transport=no_plan).check_access()
    too_fast = httpx.MockTransport(lambda r: httpx.Response(429, json={"message": "Too Many"}))
    with pytest.raises(QuotaError):
        SeRankingConnector(SR_SECRET, transport=too_fast).check_access()


# ------------------------------------------------------------------ Topvisor
TV_SECRET = {"user_id": "42", "api_key": "tv-key"}
TV_PROJECTS = [{
    "id": 777, "name": "Мой сайт", "site": "site.by",
    "searchers": [
        {"id": 1, "key": 0, "name": "Yandex", "regions": [
            {"id": 11, "key": 157, "index": 1, "name": "Минск", "device": 0},
            {"id": 12, "key": 157, "index": 2, "name": "Минск", "device": 2}]},
        {"id": 2, "key": 1, "name": "Google", "regions": [
            {"id": 21, "key": 1001493, "index": 3, "name": "Минск", "device": 0}]},
    ],
}]


def topvisor_handler(request: httpx.Request) -> httpx.Response:
    """Ответы в формате API v2: {"result": ..., "errors": ...}."""
    assert request.headers["User-Id"] == "42"
    assert request.headers["Authorization"] == "bearer tv-key"
    body = json.loads(request.content or b"{}")
    path = request.url.path
    if path.endswith("/get/projects_2/projects"):
        assert body["show_searchers_and_regions"] == 1
        return httpx.Response(200, json={"result": TV_PROJECTS})
    if path.endswith("/get/positions_2/history"):
        index = body["regions_indexes"][0]
        return httpx.Response(200, json={"result": {
            "headers": {"dates": ["2026-09-21", "2026-09-28"]},
            "keywords": [
                {"id": 501, "name": "купить ноутбук", "group_name": "Ноутбуки", "positionsData": {
                    f"2026-09-21:777:{index}": {"position": "9", "relevant_url": "https://site.by/a"},
                    f"2026-09-28:777:{index}": {"position": str(index + 1),
                                                "relevant_url": "https://site.by/b"},
                }},
                {"id": 502, "name": "ноутбук цена", "group_name": "Ноутбуки", "positionsData": {
                    f"2026-09-28:777:{index}": {"position": "--"},
                }},
            ],
        }})
    return httpx.Response(404, json={"errors": [{"code": 404, "string": "unknown method"}]})


def tv_context() -> IntegrationContext:
    return IntegrationContext(integration_id=2, external_id="777", domain="site.by")


def test_topvisor_resources_show_regions():
    connector = TopvisorConnector(TV_SECRET, transport=httpx.MockTransport(topvisor_handler))
    (resource,) = connector.list_resources()
    assert resource.external_id == "777"
    assert resource.extra["regions"] == ["Yandex · Минск", "Yandex · Минск", "Google · Минск"]


def test_topvisor_collect_all_regions():
    connector = TopvisorConnector(TV_SECRET, tv_context(),
                                  transport=httpx.MockTransport(topvisor_handler))
    result = connector.collect(date(2026, 9, 21), date(2026, 9, 30))
    segments = {f"{k.search_engine}:{k.region}" for k in result.keywords}
    assert segments == {"yandex:Минск", "yandex:Минск · моб.", "google:Минск"}
    yandex = next(k for k in result.keywords if k.external_keyword_id == "501"
                  and k.region == "Минск" and k.search_engine == "yandex")
    assert yandex.positions == [(date(2026, 9, 21), 9, "https://site.by/a"),
                                (date(2026, 9, 28), 2, "https://site.by/b")]
    assert yandex.device == "desktop" and yandex.group_name == "Ноутбуки"
    missing = next(k for k in result.keywords if k.external_keyword_id == "502")
    assert missing.positions[0][1] is None  # «--» — нет в отслеживаемой глубине
    avg = [v for v in result.daily if v.metric_code == "topvisor.avg_position"
           and v.segment == "google:Минск" and v.date == date(2026, 9, 28)]
    assert avg[0].value == 4  # позиция 4 у единственного найденного запроса


def test_topvisor_unknown_project():
    context = IntegrationContext(integration_id=2, external_id="999", domain="site.by")
    connector = TopvisorConnector(TV_SECRET, context,
                                  transport=httpx.MockTransport(topvisor_handler))
    with pytest.raises(Exception, match="не найден"):
        connector.collect(date(2026, 9, 21), date(2026, 9, 30))


def test_topvisor_auth_error_and_missing_secret():
    transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"errors": [{"code": 53, "string": "Ошибка авторизации"}]}))
    with pytest.raises(AuthError):
        TopvisorConnector(TV_SECRET, transport=transport).check_access()
    with pytest.raises(AuthError, match="User ID"):
        TopvisorConnector({"api_key": "x"}).check_access()


def test_history_mode_loads_all_checks():
    context = IntegrationContext(integration_id=1, external_id="123", domain="site.by",
                                 settings={"history_days": 90})
    connector = SeRankingConnector(SR_SECRET, context,
                                   transport=httpx.MockTransport(seranking_handler))
    assert not connector.backfill_in_one_call()
    result = connector.backfill(date(2026, 7, 1), date(2026, 9, 30))
    assert {d for k in result.keywords for d, _, _ in k.positions} == {date(2026, 9, 21),
                                                                         date(2026, 9, 28)}
