"""Коннекторы скорости загрузки Google: PageSpeed Insights API v5 и CrUX History API.

Обе системы работают по API-ключу из Google Cloud (без OAuth). Секрет доступа —
словарь ``{"api_key": "..."}``. Один и тот же ключ подходит для обеих систем,
если в проекте Google Cloud включены оба API.

Ресурс подключения — сайт проекта: для PSI — адрес главной страницы, для CrUX —
origin (``https://site.by``). Список ресурсов строится из домена проекта.

Документация:
    https://developers.google.com/speed/docs/insights/rest/v5/pagespeedapi/runpagespeed
    https://developer.chrome.com/docs/crux/history-api
"""

from __future__ import annotations

import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any, ClassVar

import httpx

from app.connectors.base import (
    AuthError,
    CollectResult,
    Connector,
    ConnectorError,
    CwvPoint,
    DailyValue,
    IntegrationContext,
    PsiResult,
    QuotaError,
    RawCall,
    Resource,
    TestResult,
)

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CRUX_HISTORY_ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"

#: Прогон Lighthouse занимает 10–40 секунд.
PSI_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
CRUX_TIMEOUT = httpx.Timeout(30.0, connect=15.0)

#: Сколько прогонов PSI делается на URL и устройство: лабораторная оценка скачет,
#: поэтому хранится медиана (рекомендация из архитектуры).
DEFAULT_PSI_RUNS = 3
#: Параллельные запросы к PSI: укладывается в квоту 400 запросов за 100 секунд.
PSI_PARALLEL = 6

DEVICES = ("mobile", "desktop")

#: Полевые метрики PSI (loadingExperience) → поля psi_runs.
PSI_FIELD_METRICS = {
    "LARGEST_CONTENTFUL_PAINT_MS": "field_lcp",
    "INTERACTION_TO_NEXT_PAINT": "field_inp",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "field_cls",
    "FIRST_CONTENTFUL_PAINT_MS": "field_fcp",
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "field_ttfb",
}

#: Метрики CrUX History API → коды в cwv_weekly.
CRUX_METRICS = {
    "largest_contentful_paint": "lcp",
    "interaction_to_next_paint": "inp",
    "cumulative_layout_shift": "cls",
    "first_contentful_paint": "fcp",
    "experimental_time_to_first_byte": "ttfb",
}
#: Устройства CrUX → коды в cwv_weekly (как в интерфейсе дашборда).
CRUX_FORM_FACTORS = {"PHONE": "phone", "DESKTOP": "desktop"}
CRUX_PERIODS = 40


def _api_key(secret: dict[str, Any]) -> str:
    key = (secret.get("api_key") or "").strip()
    if not key:
        raise AuthError("В доступе не указан API-ключ")
    return key


def raise_for_google_error(response: httpx.Response, service: str) -> None:
    """Перевести ответ Google API с ошибкой в исключение коннектора.

    Raises:
        AuthError: Ключ недействителен или API не включён в проекте Google Cloud.
        QuotaError: Превышена квота.
        ConnectorError: Прочие ошибки.
    """
    if response.is_success:
        return
    try:
        error = response.json().get("error", {})
        message = error.get("message", "")
        reasons = {d.get("reason") for d in error.get("details", []) if isinstance(d, dict)}
        reasons |= {e.get("reason") for e in error.get("errors", []) if isinstance(e, dict)}
    except ValueError:
        message, reasons = response.text[:300], set()
    status = response.status_code
    if status == 429 or "RATE_LIMIT_EXCEEDED" in reasons or "rateLimitExceeded" in reasons:
        raise QuotaError(f"{service}: превышена квота API ({message})")
    if "API_KEY_INVALID" in reasons or "API key not valid" in message:
        raise AuthError(f"{service}: API-ключ недействителен")
    if status == 403 and ("SERVICE_DISABLED" in reasons or "has not been used" in message
                          or "is disabled" in message):
        raise AuthError(f"{service}: API не включён в проекте Google Cloud — включите его "
                        "в разделе APIs & Services → Library")
    if status in (401, 403):
        raise AuthError(f"{service}: доступ запрещён ({message or status})")
    raise ConnectorError(f"{service}: ошибка {status} ({message or 'без описания'})")


def _site_url(domain: str) -> str:
    return f"https://{domain.strip().strip('/')}/"


# ---------------------------------------------------------------- PageSpeed
class PsiConnector(Connector):
    """PageSpeed Insights API v5: оценка производительности и полевые метрики URL.

    Снимок текущего состояния: каждый запуск проверяет все URL проекта для PSI
    на мобильных и ПК (по умолчанию 3 прогона, хранится медиана) и записывает
    результат на последнюю дату окна. Историю задним числом получить нельзя.
    """

    system_code: ClassVar[str] = "psi"
    history_days: ClassVar[int | None] = None

    def __init__(self, secret: dict[str, Any], context: IntegrationContext | None = None,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(secret, context)
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=PSI_TIMEOUT, transport=self._transport)

    def _run(self, client: httpx.Client, url: str, device: str) -> dict[str, Any]:
        response = client.get(PSI_ENDPOINT, params={
            "url": url, "strategy": device, "category": "performance",
            "key": _api_key(self.secret),
        })
        raise_for_google_error(response, "PageSpeed Insights")
        return response.json()

    def list_resources(self) -> list[Resource]:
        """Ресурс PSI — главная страница сайта проекта."""
        if self.context is None or not self.context.domain:
            return []
        return [Resource(_site_url(self.context.domain), f"Сайт {self.context.domain}")]

    def check_access(self) -> str:
        """Проверить ключ одним прогоном (занимает 10–30 секунд)."""
        with self._client() as client:
            self._run(client, "https://www.google.com/", "mobile")
        return "API-ключ работает"

    def test(self) -> TestResult:
        """Пробная проверка главной страницы (мобильные, один прогон)."""
        url = self.ctx.monitored_urls[0][1] if self.ctx.monitored_urls else self.ctx.external_id
        with self._client() as client:
            data = self._run(client, url, "mobile")
        result = _parse_psi(data, 0, "mobile", datetime.now(UTC))
        return TestResult(True, f"Проверка {url} прошла",
                          {"Производительность (моб.)": result.performance_score,
                           "LCP, мс": result.field_lcp})

    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """Проверить все URL проекта на обоих устройствах и записать снимок на ``date_to``."""
        result = CollectResult(snapshot_date=date_to)
        urls = self.ctx.monitored_urls
        if not urls:
            result.messages.append("Нет URL для проверки — добавьте их в настройках проекта")
            result.partial = True
            return result
        runs = int(self.ctx.settings.get("runs") or DEFAULT_PSI_RUNS)
        devices = [d for d in self.ctx.settings.get("devices", DEVICES) if d in DEVICES]
        now = datetime.now(UTC)
        jobs = [(url_id, url, device) for url_id, url in urls for device in devices
                for _ in range(runs)]
        with self._client() as client, ThreadPoolExecutor(PSI_PARALLEL) as pool:
            outcomes = list(pool.map(lambda job: self._safe_run(client, job), jobs))

        errors: list[str] = []
        scores_by_device: dict[str, list[float]] = {d: [] for d in devices}
        for url_id, url in urls:
            for device in devices:
                parsed = []
                for (job_url_id, _, job_device), outcome in zip(jobs, outcomes, strict=True):
                    if job_url_id != url_id or job_device != device:
                        continue
                    if isinstance(outcome, Exception):
                        errors.append(f"{url} ({device}): {outcome}")
                    else:
                        parsed.append(_parse_psi(outcome, url_id, device, now))
                if not parsed:
                    continue
                best = _median_run(parsed)
                result.psi.append(best)
                if best.performance_score is not None:
                    scores_by_device[device].append(best.performance_score)
                result.raw.append(RawCall("pagespeedonline/v5/runPagespeed",
                                          {"url": url, "strategy": device, "runs": len(parsed)},
                                          _trim_psi(outcomes[jobs.index((url_id, url, device))])))
        for device, scores in scores_by_device.items():
            if scores:
                result.daily.append(DailyValue(date_to, "psi.performance",
                                               round(sum(scores) / len(scores), 1), device))
        if errors:
            # Ошибка авторизации или квоты по всем прогонам — это ошибка запуска целиком.
            first = next(o for o in outcomes if isinstance(o, Exception))
            if not result.psi and isinstance(first, (AuthError, QuotaError)):
                raise first
            result.partial = True
            result.messages += errors[:5]
        return result

    def _safe_run(self, client: httpx.Client, job: tuple[int, str, str]) -> Any:
        _, url, device = job
        try:
            return self._run(client, url, device)
        except (ConnectorError, httpx.HTTPError) as exc:
            return exc if isinstance(exc, ConnectorError) else ConnectorError(str(exc))


def _parse_psi(data: dict[str, Any], url_id: int, device: str, run_at: datetime) -> PsiResult:
    """Извлечь оценку производительности и полевые метрики из ответа PSI."""
    score = (data.get("lighthouseResult", {}).get("categories", {})
             .get("performance", {}).get("score"))
    experience = data.get("loadingExperience") or {}
    metrics = experience.get("metrics") or {}
    fields: dict[str, float | None] = {}
    for api_name, field in PSI_FIELD_METRICS.items():
        percentile = (metrics.get(api_name) or {}).get("percentile")
        if percentile is not None and api_name == "CUMULATIVE_LAYOUT_SHIFT_SCORE":
            percentile = percentile / 100  # API отдаёт CLS, умноженный на 100
        fields[field] = percentile
    return PsiResult(
        monitored_url_id=url_id, device=device, run_at=run_at,
        performance_score=round(score * 100) if score is not None else None,
        field_category=experience.get("overall_category"),
        is_origin_fallback=bool(experience.get("origin_fallback")),
        **fields,
    )


def _median_run(runs: list[PsiResult]) -> PsiResult:
    """Прогон с медианной оценкой производительности (полевые данные одинаковы у всех)."""
    scored = [r for r in runs if r.performance_score is not None]
    if not scored:
        return runs[0]
    median = statistics.median_low([r.performance_score for r in scored])
    return next(r for r in scored if r.performance_score == median)


def _trim_psi(data: Any) -> Any:
    """Оставить в сыром ответе PSI только нужные разделы (полный отчёт весит мегабайты)."""
    if not isinstance(data, dict):
        return {"error": str(data)}
    lighthouse = data.get("lighthouseResult", {})
    return {
        "id": data.get("id"),
        "analysisUTCTimestamp": data.get("analysisUTCTimestamp"),
        "loadingExperience": data.get("loadingExperience"),
        "originLoadingExperience": data.get("originLoadingExperience"),
        "lighthouseResult": {
            "categories": lighthouse.get("categories"),
            "lighthouseVersion": lighthouse.get("lighthouseVersion"),
        },
    }


# --------------------------------------------------------------------- CrUX
class CruxConnector(Connector):
    """CrUX History API: недельная динамика Core Web Vitals сайта за ~40 недель.

    Каждый запрос возвращает всю доступную историю, поэтому загрузка истории
    и ежедневный сбор выполняются одним вызовом на устройство.
    """

    system_code: ClassVar[str] = "crux"
    history_days: ClassVar[int | None] = None

    def __init__(self, secret: dict[str, Any], context: IntegrationContext | None = None,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(secret, context)
        self._transport = transport

    def _query(self, client: httpx.Client, origin: str, form_factor: str) -> dict[str, Any] | None:
        response = client.post(
            CRUX_HISTORY_ENDPOINT, params={"key": _api_key(self.secret)},
            json={"origin": origin, "formFactor": form_factor,
                  "metrics": list(CRUX_METRICS), "collectionPeriodCount": CRUX_PERIODS},
        )
        if response.status_code == 404:
            return None  # у сайта недостаточно трафика из Chrome для отчёта
        raise_for_google_error(response, "CrUX")
        return response.json()

    def list_resources(self) -> list[Resource]:
        """Ресурсы CrUX — origin сайта с www и без."""
        if self.context is None or not self.context.domain:
            return []
        domain = self.context.domain.strip().strip("/")
        bare = domain.removeprefix("www.")
        return [Resource(f"https://{bare}", f"https://{bare}"),
                Resource(f"https://www.{bare}", f"https://www.{bare}")]

    def check_access(self) -> str:
        """Проверить ключ запросом к заведомо известному сайту."""
        with httpx.Client(timeout=CRUX_TIMEOUT, transport=self._transport) as client:
            self._query(client, "https://www.google.com", "PHONE")
        return "API-ключ работает"

    def test(self) -> TestResult:
        """Пробный запрос по мобильным устройствам."""
        with httpx.Client(timeout=CRUX_TIMEOUT, transport=self._transport) as client:
            data = self._query(client, self.ctx.external_id, "PHONE")
        if data is None:
            return TestResult(False, f"В CrUX нет данных по {self.ctx.external_id}: у сайта мало "
                                     "посещений из Chrome. Попробуйте вариант с www или без.")
        points = _parse_crux(data, "phone")
        latest = max((p for p in points if p.metric == "lcp"), key=lambda p: p.period_end,
                     default=None)
        sample = {"Недель истории": len({p.period_end for p in points})}
        if latest is not None:
            sample["LCP p75, мс (последняя неделя)"] = latest.p75
        return TestResult(True, "Данные CrUX получены", sample)

    def collect(self, date_from: date, date_to: date) -> CollectResult:
        """Забрать всю доступную историю по мобильным и ПК (окно дат не влияет на ответ)."""
        result = CollectResult()
        with httpx.Client(timeout=CRUX_TIMEOUT, transport=self._transport) as client:
            for form_factor, device in CRUX_FORM_FACTORS.items():
                data = self._query(client, self.ctx.external_id, form_factor)
                result.raw.append(RawCall("crux/queryHistoryRecord",
                                          {"origin": self.ctx.external_id,
                                           "formFactor": form_factor}, data))
                if data is None:
                    result.messages.append(f"CrUX: нет данных для {device}")
                    continue
                result.cwv += _parse_crux(data, device)
        return result


def _crux_date(value: dict[str, int]) -> date:
    return date(value["year"], value["month"], value["day"])


def _number(value: Any) -> float | None:
    """CrUX отдаёт числа и строками («0.05»), и «NaN» для пустых недель."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN


def _parse_crux(data: dict[str, Any], device: str) -> list[CwvPoint]:
    """Разобрать ответ History API в недельные точки по каждой метрике."""
    record = data.get("record", {})
    periods = [_crux_date(p["lastDate"]) for p in record.get("collectionPeriods", [])]
    points: list[CwvPoint] = []
    for api_name, metric in CRUX_METRICS.items():
        info = record.get("metrics", {}).get(api_name)
        if not info:
            continue
        p75s = info.get("percentilesTimeseries", {}).get("p75s", [])
        histogram = info.get("histogramTimeseries", [])
        for index, period_end in enumerate(periods):
            p75 = _number(p75s[index]) if index < len(p75s) else None
            densities = [
                _number(bin_.get("densities", [None] * len(periods))[index])
                for bin_ in histogram[:3]
            ] if len(histogram) >= 3 else [None, None, None]
            if p75 is None and all(d is None for d in densities):
                continue
            good, ni, poor = (round(d * 100, 1) if d is not None else None for d in densities)
            points.append(CwvPoint(period_end=period_end, device=device, metric=metric, p75=p75,
                                   good_pct=good, ni_pct=ni, poor_pct=poor))
    return points
