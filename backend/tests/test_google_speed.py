"""Коннекторы PSI и CrUX на ответах в формате реальных API (сеть подменяется)."""

from datetime import date

import httpx
import pytest

from app.connectors.base import AuthError, IntegrationContext, QuotaError
from app.connectors.google_speed import CruxConnector, PsiConnector

SECRET = {"api_key": "test-key"}


def psi_response(score: float, lcp: int = 2100, cls: int = 5, fallback: bool = False) -> dict:
    """Фрагмент ответа runPagespeed v5 с нужными полями."""
    return {
        "id": "https://site.by/",
        "loadingExperience": {
            "overall_category": "AVERAGE",
            "origin_fallback": fallback,
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": lcp, "category": "FAST"},
                "INTERACTION_TO_NEXT_PAINT": {"percentile": 180, "category": "FAST"},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": cls, "category": "FAST"},
                "FIRST_CONTENTFUL_PAINT_MS": {"percentile": 1500, "category": "FAST"},
                "EXPERIMENTAL_TIME_TO_FIRST_BYTE": {"percentile": 600, "category": "FAST"},
            },
        },
        "lighthouseResult": {"categories": {"performance": {"score": score}},
                             "audits": {"huge": "x" * 1000}},
    }


def google_error(status: int, message: str, reason: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {
        "code": status, "message": message,
        "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}],
    }})


def psi_context(**settings) -> IntegrationContext:
    return IntegrationContext(integration_id=1, external_id="https://site.by/", domain="site.by",
                              settings=settings,
                              monitored_urls=[(10, "https://site.by/"),
                                              (11, "https://site.by/catalog/")])


def test_psi_collect_takes_median_of_runs_and_averages_urls():
    scores = iter([0.30, 0.50, 0.40] * 4)  # 2 URL × 2 устройства × 3 прогона

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "test-key"
        assert request.url.params["category"] == "performance"
        return httpx.Response(200, json=psi_response(next(scores)))

    connector = PsiConnector(SECRET, psi_context(), transport=httpx.MockTransport(handler))
    result = connector.collect(date(2026, 9, 25), date(2026, 9, 30))

    assert not result.partial
    assert len(result.psi) == 4  # по одной записи на URL и устройство
    assert {r.performance_score for r in result.psi} == {40}  # медиана 30/50/40
    first = result.psi[0]
    assert first.field_lcp == 2100 and first.field_cls == 0.05  # CLS приходит ×100
    assert {(d.metric_code, d.segment, d.date) for d in result.daily} == {
        ("psi.performance", "mobile", date(2026, 9, 30)),
        ("psi.performance", "desktop", date(2026, 9, 30)),
    }
    # Сырой ответ урезан: огромный раздел audits не хранится.
    assert "audits" not in result.raw[0].response["lighthouseResult"]


def test_psi_single_run_setting():
    calls = []

    def handler(request):
        calls.append(request.url.params["strategy"])
        return httpx.Response(200, json=psi_response(0.9))

    connector = PsiConnector(SECRET, psi_context(runs=1, devices=["mobile"]),
                             transport=httpx.MockTransport(handler))
    connector.collect(date(2026, 9, 30), date(2026, 9, 30))
    assert calls == ["mobile", "mobile"]  # 2 URL × 1 прогон, только мобильные


def test_psi_invalid_key_is_auth_error():
    transport = httpx.MockTransport(
        lambda r: google_error(400, "API key not valid. Please pass a valid API key.",
                               "API_KEY_INVALID"))
    connector = PsiConnector(SECRET, psi_context(runs=1), transport=transport)
    with pytest.raises(AuthError, match="недействителен"):
        connector.collect(date(2026, 9, 30), date(2026, 9, 30))


def test_psi_disabled_api_explains_what_to_do():
    transport = httpx.MockTransport(lambda r: google_error(
        403, "PageSpeed Insights API has not been used in project 123 before or it is disabled.",
        "SERVICE_DISABLED"))
    with pytest.raises(AuthError, match="не включён"):
        PsiConnector(SECRET, psi_context(), transport=transport).check_access()


def test_psi_partial_failure_keeps_successful_urls():
    def handler(request):
        if "catalog" in request.url.params["url"]:
            return httpx.Response(500, json={"error": {"code": 500, "message": "Lighthouse error"}})
        return httpx.Response(200, json=psi_response(0.8))

    connector = PsiConnector(SECRET, psi_context(runs=1), transport=httpx.MockTransport(handler))
    result = connector.collect(date(2026, 9, 30), date(2026, 9, 30))
    assert result.partial
    assert {r.monitored_url_id for r in result.psi} == {10}
    assert any("catalog" in m for m in result.messages)


def test_psi_without_urls_asks_to_add_them():
    context = IntegrationContext(integration_id=1, external_id="https://site.by/", domain="site.by")
    result = PsiConnector(SECRET, context).collect(date(2026, 9, 30), date(2026, 9, 30))
    assert result.partial and "добавьте" in result.messages[0].lower()


def test_resources_come_from_project_domain():
    context = IntegrationContext(integration_id=0, external_id="", domain="www.site.by")
    assert [r.external_id for r in PsiConnector(SECRET, context).list_resources()] == [
        "https://www.site.by/"]
    assert [r.external_id for r in CruxConnector(SECRET, context).list_resources()] == [
        "https://site.by", "https://www.site.by"]


# --------------------------------------------------------------------- CrUX
def crux_response() -> dict:
    """Фрагмент ответа queryHistoryRecord: две недели, вторая без данных INP."""
    periods = [
        {"firstDate": {"year": 2026, "month": 8, "day": 31},
         "lastDate": {"year": 2026, "month": 9, "day": 27}},
        {"firstDate": {"year": 2026, "month": 9, "day": 7},
         "lastDate": {"year": 2026, "month": 10, "day": 4}},
    ]
    return {"record": {
        "key": {"origin": "https://site.by", "formFactor": "PHONE"},
        "collectionPeriods": periods,
        "metrics": {
            "largest_contentful_paint": {
                "histogramTimeseries": [
                    {"start": 0, "end": 2500, "densities": [0.71, 0.74]},
                    {"start": 2500, "end": 4000, "densities": [0.2, 0.18]},
                    {"start": 4000, "densities": [0.09, 0.08]},
                ],
                "percentilesTimeseries": {"p75s": [2650, 2480]},
            },
            "cumulative_layout_shift": {
                "histogramTimeseries": [
                    {"start": "0.00", "end": "0.10", "densities": [0.9, 0.91]},
                    {"start": "0.10", "end": "0.25", "densities": [0.06, 0.05]},
                    {"start": "0.25", "densities": [0.04, 0.04]},
                ],
                "percentilesTimeseries": {"p75s": ["0.05", "0.04"]},
            },
            "interaction_to_next_paint": {
                "histogramTimeseries": [
                    {"start": 0, "end": 200, "densities": [0.8, "NaN"]},
                    {"start": 200, "end": 500, "densities": [0.15, "NaN"]},
                    {"start": 500, "densities": [0.05, "NaN"]},
                ],
                "percentilesTimeseries": {"p75s": [190, None]},
            },
        },
    }}


def crux_context() -> IntegrationContext:
    return IntegrationContext(integration_id=2, external_id="https://site.by", domain="site.by")


def test_crux_collect_parses_weeks_for_both_devices():
    seen = []

    def handler(request):
        body = request.read().decode()
        seen.append("PHONE" if "PHONE" in body else "DESKTOP")
        return httpx.Response(200, json=crux_response())

    result = CruxConnector(SECRET, crux_context(),
                           transport=httpx.MockTransport(handler)).collect(date(2026, 9, 1),
                                                                           date(2026, 10, 4))
    assert seen == ["PHONE", "DESKTOP"]
    phone = [p for p in result.cwv if p.device == "phone"]
    lcp = sorted((p for p in phone if p.metric == "lcp"), key=lambda p: p.period_end)
    assert [p.period_end for p in lcp] == [date(2026, 9, 27), date(2026, 10, 4)]
    assert lcp[0].p75 == 2650 and lcp[0].good_pct == 71.0 and lcp[0].poor_pct == 9.0
    cls = next(p for p in phone if p.metric == "cls")
    assert cls.p75 == 0.05  # строка «0.05» превращается в число
    inp = [p for p in phone if p.metric == "inp"]
    assert len(inp) == 1  # неделя с NaN пропущена


def test_crux_no_data_is_not_an_error():
    not_found = {"error": {"code": 404, "message": "chrome ux report data not found"}}
    connector = CruxConnector(SECRET, crux_context(), transport=httpx.MockTransport(
        lambda r: httpx.Response(404, json=not_found)))
    result = connector.collect(date(2026, 9, 1), date(2026, 9, 30))
    assert result.cwv == [] and len(result.messages) == 2
    assert not connector.test().ok


def test_crux_quota():
    transport = httpx.MockTransport(
        lambda r: google_error(429, "Quota exceeded", "RATE_LIMIT_EXCEEDED"))
    with pytest.raises(QuotaError):
        CruxConnector(SECRET, crux_context(), transport=transport).collect(date(2026, 9, 1),
                                                                           date(2026, 9, 30))


def test_missing_key():
    with pytest.raises(AuthError):
        CruxConnector({}, crux_context()).check_access()
