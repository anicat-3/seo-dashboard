"""Общая логика коннекторов съёма позиций (Topvisor, SE Ranking).

Сводные показатели — средняя позиция, видимость и распределение по топам —
считаются дашбордом из позиций по запросам по единой формуле для обоих сервисов.
Поэтому видимость может немного отличаться от значения в интерфейсе самого
сервиса: у каждого своя формула, а здесь важна сопоставимость между проектами.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date

from app.connectors.base import DailyValue, KeywordState

#: Глубина, дальше которой позиция считается «не найдено».
MAX_DEPTH = 100

#: Доля кликов по позициям 1–10 (усреднённая кривая CTR выдачи); 11–20 — 1%.
_CTR_TOP10 = (0.28, 0.15, 0.11, 0.08, 0.07, 0.05, 0.04, 0.03, 0.03, 0.025)


def expected_ctr(position: int | None) -> float:
    """Ожидаемая доля кликов для позиции; вне ТОП-20 — ноль."""
    if position is None or position < 1:
        return 0.0
    if position <= len(_CTR_TOP10):
        return _CTR_TOP10[position - 1]
    return 0.01 if position <= 20 else 0.0


def visibility(positions: list[int | None]) -> float | None:
    """Видимость, %: ожидаемые клики относительно ситуации «все запросы на 1-м месте»."""
    if not positions:
        return None
    return round(sum(expected_ctr(p) for p in positions) / (len(positions) * _CTR_TOP10[0]) * 100,
                 2)


def normalize_position(value: object) -> int | None:
    """Позиция из ответа сервиса: число 1–100 или ``None`` («не найдено», «--», 0)."""
    try:
        position = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return position if 1 <= position <= MAX_DEPTH else None


def summarize(system: str, keywords: Iterable[KeywordState]) -> list[DailyValue]:
    """Сводные метрики по каждому сегменту (поисковик:регион) и дате съёма.

    Args:
        system: Префикс метрик — ``topvisor`` или ``seranking``.
        keywords: Запросы с позициями по датам.
    """
    by_point: dict[tuple[str, date], list[int | None]] = defaultdict(list)
    for keyword in keywords:
        segment = f"{keyword.search_engine}:{keyword.region}"
        for check_date, position, _ in keyword.positions:
            by_point[(segment, check_date)].append(position)

    values: list[DailyValue] = []
    for (segment, check_date), positions in sorted(by_point.items()):
        found = [p for p in positions if p is not None]
        values += [
            DailyValue(check_date, f"{system}.avg_position",
                       round(sum(found) / len(found), 2) if found else None, segment),
            DailyValue(check_date, f"{system}.visibility", visibility(positions), segment),
            DailyValue(check_date, f"{system}.top3", sum(p <= 3 for p in found), segment),
            DailyValue(check_date, f"{system}.top10", sum(p <= 10 for p in found), segment),
            DailyValue(check_date, f"{system}.top30", sum(p <= 30 for p in found), segment),
            DailyValue(check_date, f"{system}.top100", len(found), segment),
            DailyValue(check_date, f"{system}.keywords_total", len(positions), segment),
        ]
    return values


def keep_last_check(keywords: list[KeywordState]) -> list[KeywordState]:
    """Оставить у запросов только последний съём (загрузка истории при подключении)."""
    dates = [d for k in keywords for d, _, _ in k.positions]
    if not dates:
        return keywords
    last = max(dates)
    for keyword in keywords:
        keyword.positions = [p for p in keyword.positions if p[0] == last]
    return keywords


def engine_code(name: str) -> str:
    """Код поисковика из названия: «Google Belarus» → ``google``, «Яндекс» → ``yandex``."""
    lowered = name.strip().lower()
    for code, markers in (("yandex", ("yandex", "яндекс")), ("google", ("google",)),
                          ("bing", ("bing",)), ("yahoo", ("yahoo",))):
        if any(m in lowered for m in markers):
            return code
    return lowered.split(" ")[0] if lowered else "search"
