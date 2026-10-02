"""Коннекторы GSC, GA4, Метрики, Вебмастера, Bing и OAuth на ответах в формате их API."""

import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from app.connectors import oauth
from app.connectors.base import AuthError, IntegrationContext
from app.connectors.bing import BingConnector, parse_wcf_date
from app.connectors.google_apis import Ga4Connector, SearchConsoleConnector
from app.connectors.yandex_apis import MetrikaConnector, WebmasterConnector


def token_secret(expired: bool = False) -> dict:
    delta = timedelta(hours=-1) if expired else timedelta(hours=1)
    return {"refresh_token": "refresh-1", "access_token": "access-1",
            "expires_at": (datetime.now(UTC) + delta).isoformat()}


@pytest.fixture(autouse=True)
def oauth_apps(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    for name in ("google", "yandex"):
        monkeypatch.setattr(settings, f"{name}_client_id", f"{name}-id")
        monkeypatch.setattr(settings, f"{name}_client_secret", f"{name}-secret")
    # Настоящий .env разработчика в тестах не читается.
    monkeypatch.setattr(oauth, "_env", lambda: {})


# -------------------------------------------------------------------- OAuth
def test_authorize_url_asks_google_for_offline_access():
    url = oauth.authorize_url(oauth.GOOGLE, oauth.GOOGLE.app(), "state-1")
    params = parse_qs(url.split("?", 1)[1])
    assert params["access_type"] == ["offline"]
    assert "https://www.googleapis.com/auth/webmasters.readonly" in params["scope"][0]
    assert params["redirect_uri"][0].endswith("/api/oauth/google/callback")


def test_expired_token_is_refreshed_and_marked_for_saving():
    def handler(request):
        body = parse_qs(request.content.decode())
        assert body["grant_type"] == ["refresh_token"] and body["refresh_token"] == ["refresh-1"]
        return httpx.Response(200, json={"access_token": "access-2", "expires_in": 3600,
                                         "refresh_token": "refresh-2"})

    secret = token_secret(expired=True)
    token, updated = oauth.access_token(oauth.YANDEX, secret, httpx.MockTransport(handler))
    assert token == "access-2" and updated
    assert secret["refresh_token"] == "refresh-2"  # новый refresh-токен Яндекса сохранится


def test_valid_token_is_reused():
    token, updated = oauth.access_token(oauth.GOOGLE, token_secret())
    assert token == "access-1" and not updated


def test_revoked_refresh_token_is_auth_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(400, json={
        "error": "invalid_grant", "error_description": "Token has been expired or revoked."}))
    with pytest.raises(AuthError, match="Переподключите"):
        oauth.access_token(oauth.GOOGLE, token_secret(expired=True), transport)


def test_missing_oauth_app_settings(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "google_client_id", None)
    assert not oauth.GOOGLE.configured
    with pytest.raises(Exception, match="GOOGLE_CLIENT_ID"):
        oauth.GOOGLE.app()


def test_several_numbered_oauth_apps(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "google_client_id", None)
    monkeypatch.setattr(oauth, "_env", lambda: {
        "GOOGLE_CLIENT_ID_10": "id-10", "GOOGLE_CLIENT_SECRET_10": "s-10",
        "GOOGLE_CLIENT_ID_2": "id-2", "GOOGLE_CLIENT_SECRET_2": "s-2",
        "GOOGLE_APP_NAME_2": "proweber.b",
        "GOOGLE_CLIENT_ID_3": "id-3",  # без секрета — пропускается
    })
    apps = oauth.GOOGLE.apps()
    assert [(a.key, a.name, a.client_id) for a in apps] == [
        ("2", "proweber.b", "id-2"), ("10", "приложение 10", "id-10")]
    assert oauth.GOOGLE.app("10").client_secret == "s-10"
    assert oauth.GOOGLE.app().key == "2"
    url = oauth.authorize_url(oauth.GOOGLE, oauth.GOOGLE.app("10"), "s")
    assert parse_qs(url.split("?", 1)[1])["client_id"] == ["id-10"]


def test_token_is_refreshed_by_the_app_that_issued_it(monkeypatch):
    monkeypatch.setattr(oauth, "_env", lambda: {
        "GOOGLE_CLIENT_ID_2": "id-2", "GOOGLE_CLIENT_SECRET_2": "s-2"})

    def handler(request):
        body = parse_qs(request.content.decode())
        assert body["client_id"] == ["id-2"] and body["client_secret"] == ["s-2"]
        return httpx.Response(200, json={"access_token": "access-2", "expires_in": 3600})

    secret = token_secret(expired=True) | {"client_id": "id-2"}
    token, _ = oauth.access_token(oauth.GOOGLE, secret, httpx.MockTransport(handler))
    assert token == "access-2"


def test_removed_oauth_app_is_auth_error():
    secret = token_secret(expired=True) | {"client_id": "deleted-app"}
    with pytest.raises(AuthError, match="больше не указано"):
        oauth.access_token(oauth.GOOGLE, secret)


def test_exchanged_secret_remembers_app():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        "access_token": "a", "refresh_token": "r", "expires_in": 3600}))
    secret = oauth.exchange_code(oauth.GOOGLE, oauth.GOOGLE.app(), "c", transport)
    assert secret["client_id"] == "google-id"


# ---------------------------------------------------------------------- GSC
def gsc_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer access-1"
    path = request.url.path
    if path == "/webmasters/v3/sites":
        return httpx.Response(200, json={"siteEntry": [
            {"siteUrl": "sc-domain:site.by", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://old.by/", "permissionLevel": "siteUnverifiedUser"}]})
    if path.endswith("/searchAnalytics/query"):
        body = json.loads(request.content)
        assert body["dimensions"] == ["date"] and body["dataState"] == "all"
        return httpx.Response(200, json={"rows": [
            {"keys": ["2026-09-27"], "clicks": 10, "impressions": 400, "ctr": 0.025,
             "position": 7.25}]})
    if path.endswith("/sitemaps"):
        return httpx.Response(200, json={"sitemap": [{
            "path": "https://site.by/sitemap.xml", "isPending": False, "isSitemapsIndex": True,
            "lastDownloaded": "2026-09-28T03:00:00.000Z", "warnings": "0", "errors": "2",
            "contents": [{"type": "web", "submitted": "350", "indexed": "0"}]}]})
    return httpx.Response(404, json={"error": {"code": 404, "message": "not found"}})


def test_gsc_resources_skip_unverified():
    connector = SearchConsoleConnector(token_secret(), transport=httpx.MockTransport(gsc_handler))
    assert [r.external_id for r in connector.list_resources()] == ["sc-domain:site.by"]


def test_gsc_collect():
    context = IntegrationContext(integration_id=1, external_id="sc-domain:site.by")
    result = SearchConsoleConnector(token_secret(), context,
                                    transport=httpx.MockTransport(gsc_handler)).collect(
        date(2026, 9, 24), date(2026, 9, 28))
    values = {v.metric_code: v.value for v in result.daily}
    assert values == {"gsc.clicks": 10, "gsc.impressions": 400, "gsc.ctr": 2.5,
                      "gsc.position": 7.25}
    (sitemap,) = result.sitemaps
    assert sitemap.status == "error" and sitemap.submitted_urls == 350 and sitemap.is_index


# ---------------------------------------------------------------------- GA4
def ga4_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/v1beta/accountSummaries":
        return httpx.Response(200, json={"accountSummaries": [{
            "displayName": "Компания", "propertySummaries": [
                {"property": "properties/111", "displayName": "site.by"}]}]})
    if path == "/v1beta/properties/111/keyEvents":
        return httpx.Response(200, json={"keyEvents": [{"eventName": "purchase"}]})
    if path == "/v1beta/properties/111:runReport":
        body = json.loads(request.content)
        organic = "dimensionFilter" in body and \
            body["dimensionFilter"]["filter"]["fieldName"] == "sessionDefaultChannelGroup"
        if any(d["name"] == "eventName" for d in body.get("dimensions", [])):
            return httpx.Response(200, json={"rows": [{
                "dimensionValues": [{"value": "20260927"}, {"value": "purchase"}],
                "metricValues": [{"value": "5"}]}]})
        if not body.get("dimensions"):  # итог за период
            return httpx.Response(200, json={"rows": [{"metricValues": [
                {"value": "900" if not organic else "400"}, {"value": "95.5"},
                {"value": "0.42"}]}]})
        return httpx.Response(200, json={"rows": [{
            "dimensionValues": [{"value": "20260927"}],
            "metricValues": [{"value": "120" if not organic else "60"}, {"value": "150"},
                             {"value": "88.4"}, {"value": "0.4512"}]}]})
    return httpx.Response(404, json={"error": {"code": 404, "message": "not found"}})


def ga4_context() -> IntegrationContext:
    return IntegrationContext(integration_id=1, external_id="properties/111",
                              goal_ids=["purchase"])


def test_ga4_resources_and_goals():
    connector = Ga4Connector(token_secret(), ga4_context(),
                             transport=httpx.MockTransport(ga4_handler))
    assert connector.list_resources()[0].external_id == "properties/111"
    assert [g.external_goal_id for g in connector.list_goals()] == ["purchase"]


def test_ga4_collect_and_period_totals():
    connector = Ga4Connector(token_secret(), ga4_context(),
                             transport=httpx.MockTransport(ga4_handler))
    result = connector.collect(date(2026, 9, 27), date(2026, 9, 27))
    values = {(v.metric_code, v.segment): v.value for v in result.daily}
    assert values[("ga4.users", "all")] == 120 and values[("ga4.users", "organic")] == 60
    assert values[("ga4.bounce_rate", "all")] == 45.12  # доля → проценты
    assert values[("ga4.goals", "purchase")] == 5
    totals = {(v.metric_code, v.segment): v.value
              for v in connector.fetch_period_totals(date(2026, 9, 1), date(2026, 9, 27),
                                                     ["all", "organic"])}
    assert totals[("ga4.users", "all")] == 900 and totals[("ga4.users", "organic")] == 400
    assert totals[("ga4.bounce_rate", "all")] == 42.0


# ------------------------------------------------------------------ Метрика
def metrika_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "OAuth access-1"
    path, params = request.url.path, request.url.params
    if path == "/management/v1/counters":
        return httpx.Response(200, json={"counters": [
            {"id": 555, "name": "Сайт", "site": "site.by", "time_zone_name": "Europe/Minsk"}]})
    if path == "/management/v1/counter/555/goals":
        return httpx.Response(200, json={"goals": [{"id": 77, "name": "Заявка"}]})
    if path == "/stat/v1/data":
        assert params["accuracy"] == "full"
        assert params["filters"].startswith("ym:s:isRobot=='No'")  # только люди
        organic = "lastTrafficSource" in params["filters"]
        if "ym:s:goal77reaches" in params["metrics"]:
            return httpx.Response(200, json={"data": [
                {"dimensions": [{"name": "2026-09-27"}], "metrics": [3]}]})
        if "dimensions" not in params:
            return httpx.Response(200, json={"data": [], "totals": [700 if not organic else 300,
                                                                    101.5, 33.3]})
        return httpx.Response(200, json={"data": [
            {"dimensions": [{"name": "2026-09-27"}],
             "metrics": [80 if not organic else 30, 95, 120.4, 31.5]}]})
    return httpx.Response(404, json={"errors": [{"error_type": "not_found", "message": "no"}]})


def test_metrika_collect_goals_and_totals():
    context = IntegrationContext(integration_id=1, external_id="555", goal_ids=["77"])
    connector = MetrikaConnector(token_secret(), context,
                                 transport=httpx.MockTransport(metrika_handler))
    assert connector.list_resources()[0].timezone == "Europe/Minsk"
    assert connector.list_goals()[0].name == "Заявка"
    values = {(v.metric_code, v.segment): v.value
              for v in connector.collect(date(2026, 9, 27), date(2026, 9, 27)).daily}
    assert values[("metrika.users", "organic")] == 30
    assert values[("metrika.goals", "77")] == 3
    totals = {(v.metric_code, v.segment): v.value
              for v in connector.fetch_period_totals(date(2026, 9, 1), date(2026, 9, 27),
                                                     ["all", "organic"])}
    assert totals[("metrika.users", "all")] == 700


# ---------------------------------------------------------------- Вебмастер
def webmaster_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/v4")
    host = "/user/9/hosts/https:site.by:443"
    if path == "/user":
        return httpx.Response(200, json={"user_id": 9})
    if path == "/user/9/hosts":
        return httpx.Response(200, json={"hosts": [
            {"host_id": "https:site.by:443", "unicode_host_url": "https://site.by",
             "verified": True},
            {"host_id": "http:x.by:80", "unicode_host_url": "http://x.by", "verified": False}]})
    if path == f"{host}/search-queries/all/history":
        assert request.url.params.get_list("query_indicator") == [
            "TOTAL_SHOWS", "TOTAL_CLICKS", "AVG_SHOW_POSITION"]
        return httpx.Response(200, json={"indicators": {
            "TOTAL_SHOWS": [{"date": "2026-09-27T00:00:00.000+03:00", "value": 1000.0}],
            "TOTAL_CLICKS": [{"date": "2026-09-27T00:00:00.000+03:00", "value": 50.0}],
            "AVG_SHOW_POSITION": [{"date": "2026-09-27T00:00:00.000+03:00", "value": 6.4}]}})
    if path == f"{host}/search-urls/in-search/history":
        return httpx.Response(200, json={"history": [
            {"date": "2026-09-27T00:00:00.000+03:00", "value": 1450}]})
    if path == f"{host}/summary":
        return httpx.Response(200, json={"searchable_pages_count": 1450,
                                         "excluded_pages_count": 300})
    if path == f"{host}/diagnostics":
        return httpx.Response(200, json={"problems": {
            "DOCUMENTS_MISSING_DESCRIPTION": {"severity": "RECOMMENDATION", "state": "PRESENT"},
            "DNS_ERROR": {"severity": "FATAL", "state": "ABSENT"}}})
    if path == f"{host}/sitemaps":
        return httpx.Response(200, json={"sitemaps": [{
            "sitemap_id": "1", "sitemap_url": "https://site.by/sitemap.xml",
            "last_access_date": "2026-09-27T10:00:00+03:00", "errors_count": 0,
            "urls_count": 1200, "children_count": 0, "sitemap_type": "SITEMAP"}]})
    return httpx.Response(404, json={"error_code": "NOT_FOUND", "error_message": path})


def test_webmaster_collect():
    secret = token_secret()
    context = IntegrationContext(integration_id=1, external_id="https:site.by:443")
    connector = WebmasterConnector(secret, context,
                                   transport=httpx.MockTransport(webmaster_handler))
    assert [r.external_id for r in connector.list_resources()] == ["https:site.by:443"]
    assert secret["user_id"] == "9" and connector.secret_updated  # user_id кэшируется
    result = connector.collect(date(2026, 9, 21), date(2026, 9, 27))
    values = {v.metric_code: v.value for v in result.daily}
    assert values["ywm.clicks"] == 50 and values["ywm.ctr"] == 5.0
    assert values["ywm.pages_in_search"] == 1450 and values["ywm.excluded_pages"] == 300
    assert values["ywm.open_issues"] == 1
    assert [i.title for i in result.issues] == ["Нет мета-описания у страниц"]
    assert result.sitemaps[0].submitted_urls == 1200


# --------------------------------------------------------------------- Bing
def test_wcf_date():
    moment = parse_wcf_date("/Date(1758956400000-0700)/")
    assert moment.date() == date(2025, 9, 27)


def bing_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.params["apikey"] == "bing-key"
    method = request.url.path.rsplit("/", 1)[-1]
    if method == "GetUserSites":
        return httpx.Response(200, json={"d": [{"Url": "https://site.by/", "IsVerified": True}]})
    if method == "GetRankAndTrafficStats":
        return httpx.Response(200, json={"d": [
            {"Date": "/Date(1758956400000-0700)/", "Clicks": 4, "Impressions": 200},
            {"Date": "/Date(1700000000000-0700)/", "Clicks": 1, "Impressions": 10}]})
    if method == "GetCrawlStats":
        return httpx.Response(200, json={"d": [{"Date": "/Date(1758956400000-0700)/",
                                                "Code4xx": 3, "Code5xx": 1,
                                                "BlockedByRobotsTxt": 0, "DnsFailures": 0,
                                                "ConnectionTimeout": 2}]})
    if method == "GetFeeds":
        return httpx.Response(200, json={"d": [{"Url": "https://site.by/sitemap.xml",
                                                "Status": "Success", "UrlCount": 90,
                                                "Type": "Sitemap",
                                                "LastCrawled": "/Date(1758956400000-0700)/"}]})
    return httpx.Response(400, json={"ErrorCode": 3, "Message": "ERROR!!! InvalidApiKey"})


def test_bing_collect_filters_window():
    context = IntegrationContext(integration_id=1, external_id="https://site.by/")
    connector = BingConnector({"api_key": "bing-key"}, context,
                              transport=httpx.MockTransport(bing_handler))
    result = connector.collect(date(2025, 9, 23), date(2025, 9, 27))
    values = {v.metric_code: v.value for v in result.daily}
    assert values["bing.clicks"] == 4 and values["bing.ctr"] == 2.0  # старая дата отброшена
    assert values["bing.crawl_4xx"] == 3 and values["bing.timeouts"] == 2
    assert result.sitemaps[0].status == "ok" and result.sitemaps[0].submitted_urls == 90


def test_bing_invalid_key_real_format():
    transport = httpx.MockTransport(lambda r: httpx.Response(
        400, json={"ErrorCode": 3, "Message": "ERROR!!! InvalidApiKey"}))
    with pytest.raises(AuthError):
        BingConnector({"api_key": "bad"}, transport=transport).check_access()


def test_yandex_uses_verification_code_page():
    url = oauth.authorize_url(oauth.YANDEX, oauth.YANDEX.app(), "s")
    params = parse_qs(url.split("?", 1)[1])
    assert params["redirect_uri"] == ["https://oauth.yandex.ru/verification_code"]
    assert oauth.YANDEX.manual_code and not oauth.GOOGLE.manual_code


def test_yandex_code_exchange_without_redirect_uri():
    def handler(request):
        body = parse_qs(request.content.decode())
        assert body["grant_type"] == ["authorization_code"] and body["code"] == ["1234567"]
        assert "redirect_uri" not in body  # Яндексу адрес возврата при обмене не нужен
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "r",
                                         "expires_in": 31536000})

    secret = oauth.exchange_code(oauth.YANDEX, oauth.YANDEX.app(), " 1234567 ",
                                 httpx.MockTransport(handler))
    assert secret["refresh_token"] == "r"


def test_wrong_yandex_code():
    transport = httpx.MockTransport(lambda r: httpx.Response(400, json={
        "error": "invalid_grant", "error_description": "Code has expired"}))
    with pytest.raises(AuthError, match="Code has expired"):
        oauth.exchange_code(oauth.YANDEX, oauth.YANDEX.app(), "0000000", transport)
