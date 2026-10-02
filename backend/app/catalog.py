"""Справочные данные: системы, каталог метрик, правила подсветки по умолчанию.

Справочники загружаются в БД командой ``seo-dashboard setup`` (идемпотентно),
поэтому добавление метрики не требует изменения схемы БД.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.metrics import AGG_LAST, AGG_PERIOD_ONLY, AGG_SUM, AGG_WEIGHTED_AVG


@dataclass(frozen=True, slots=True)
class SystemDef:
    """Описание внешней системы."""

    code: str
    name: str
    auth_type: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class MetricDef:
    """Описание метрики для ``metric_catalog``."""

    code: str
    system_code: str
    name_ru: str
    unit: str
    aggregation: str
    weight_metric_code: str | None = None
    higher_is_better: bool = True


SYSTEMS: tuple[SystemDef, ...] = (
    SystemDef("ga4", "Google Analytics 4", "oauth", 10),
    SystemDef("metrika", "Яндекс.Метрика", "oauth", 20),
    SystemDef("gsc", "Google Search Console", "oauth", 30),
    SystemDef("crux", "Core Web Vitals (CrUX)", "api_key", 35),
    SystemDef("ywm", "Яндекс.Вебмастер", "oauth", 40),
    SystemDef("topvisor", "Topvisor", "api_key", 50),
    SystemDef("seranking", "SE Ranking", "api_key", 60),
    SystemDef("bing", "Bing Webmaster", "api_key", 70),
    SystemDef("psi", "PageSpeed Insights", "api_key", 80),
)

SYSTEM_NAMES: dict[str, str] = {s.code: s.name for s in SYSTEMS}


def _analytics_metrics(system: str, sessions_name: str, duration_name: str,
                       goals_name: str) -> list[MetricDef]:
    """Одинаковый набор метрик GA4 и Метрики (отличаются только названиями)."""
    return [
        MetricDef(f"{system}.users", system, "Пользователи", "", AGG_PERIOD_ONLY),
        MetricDef(f"{system}.sessions", system, sessions_name, "", AGG_SUM),
        MetricDef(
            f"{system}.avg_session_duration", system, duration_name, "s", AGG_PERIOD_ONLY,
            weight_metric_code=f"{system}.sessions",
        ),
        MetricDef(
            f"{system}.bounce_rate", system, "Отказы", "%", AGG_PERIOD_ONLY,
            weight_metric_code=f"{system}.sessions", higher_is_better=False,
        ),
        MetricDef(f"{system}.goals", system, goals_name, "", AGG_SUM),
    ]


def _search_metrics(system: str) -> list[MetricDef]:
    """Клики, показы, CTR и средняя позиция поисковой консоли."""
    return [
        MetricDef(f"{system}.clicks", system, "Клики", "", AGG_SUM),
        MetricDef(f"{system}.impressions", system, "Показы", "", AGG_SUM),
        MetricDef(
            f"{system}.ctr", system, "CTR", "%", AGG_WEIGHTED_AVG,
            weight_metric_code=f"{system}.impressions",
        ),
        MetricDef(
            f"{system}.position", system, "Средняя позиция", "", AGG_WEIGHTED_AVG,
            weight_metric_code=f"{system}.impressions", higher_is_better=False,
        ),
    ]


def _rank_tracker_metrics(system: str) -> list[MetricDef]:
    """Сводка съёма позиций: средняя позиция, видимость и распределение по топам."""
    return [
        MetricDef(f"{system}.avg_position", system, "Средняя позиция", "", AGG_LAST,
                  higher_is_better=False),
        MetricDef(f"{system}.visibility", system, "Видимость", "%", AGG_LAST),
        MetricDef(f"{system}.top3", system, "ТОП-3", "", AGG_LAST),
        MetricDef(f"{system}.top10", system, "ТОП-10", "", AGG_LAST),
        MetricDef(f"{system}.top30", system, "ТОП-30", "", AGG_LAST),
        MetricDef(f"{system}.top100", system, "ТОП-100", "", AGG_LAST),
        MetricDef(f"{system}.keywords_total", system, "Запросов в проверке", "", AGG_LAST),
    ]


METRICS: tuple[MetricDef, ...] = (
    *_analytics_metrics("ga4", "Сеансы", "Длительность сеанса", "Ключевые события"),
    *_analytics_metrics("metrika", "Визиты", "Длительность визита", "Достижения целей"),
    *_search_metrics("gsc"),
    *_search_metrics("ywm"),
    MetricDef("ywm.pages_in_search", "ywm", "Страниц в поиске", "", AGG_LAST),
    MetricDef("ywm.excluded_pages", "ywm", "Исключённых страниц", "", AGG_LAST,
              higher_is_better=False),
    MetricDef("ywm.open_issues", "ywm", "Открытых ошибок диагностики", "", AGG_LAST,
              higher_is_better=False),
    *_search_metrics("bing"),
    MetricDef("bing.crawl_4xx", "bing", "Ошибки обхода 4xx", "", AGG_SUM, higher_is_better=False),
    MetricDef("bing.crawl_5xx", "bing", "Ошибки обхода 5xx", "", AGG_SUM, higher_is_better=False),
    MetricDef("bing.robots_blocked", "bing", "Заблокировано robots.txt", "", AGG_SUM,
              higher_is_better=False),
    MetricDef("bing.dns_failures", "bing", "Ошибки DNS", "", AGG_SUM, higher_is_better=False),
    MetricDef("bing.timeouts", "bing", "Таймауты", "", AGG_SUM, higher_is_better=False),
    *_rank_tracker_metrics("topvisor"),
    *_rank_tracker_metrics("seranking"),
    MetricDef("psi.performance", "psi", "Производительность", "", AGG_LAST),
)

METRICS_BY_CODE: dict[str, MetricDef] = {m.code: m for m in METRICS}

#: Правила подсветки по умолчанию (для всех проектов): (metric_code, segment, comparison).
DEFAULT_SIGNAL_RULES: tuple[tuple[str, str, str], ...] = (
    ("ga4.users", "organic", "wow"),
    ("metrika.users", "organic", "wow"),
    ("gsc.clicks", "all", "wow"),
    ("gsc.impressions", "all", "wow"),
    ("ywm.clicks", "all", "wow"),
    ("ywm.pages_in_search", "all", "wow"),
    ("bing.clicks", "all", "wow"),
    ("topvisor.visibility", "*", "wow"),
    ("topvisor.avg_position", "*", "wow"),
    ("seranking.visibility", "*", "wow"),
    ("seranking.avg_position", "*", "wow"),
    ("psi.performance", "mobile", "wow"),
)

#: Сегмент-шаблон «любой сегмент метрики» в правилах (для позиций по поисковикам/регионам).
ANY_SEGMENT = "*"
