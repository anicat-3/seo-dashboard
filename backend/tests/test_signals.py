from types import SimpleNamespace

from app.services.dashboard import is_worse
from app.services.signals import effective_rules, evaluate, is_position_metric


def test_drop_of_threshold_is_worse_for_growth_metric():
    ev = evaluate(90, 100, 10, higher_is_better=True)
    assert ev.is_worse and ev.change_pct == -10


def test_small_drop_is_not_signal():
    assert not evaluate(95, 100, 10, higher_is_better=True).is_worse


def test_position_growth_is_worse():
    # Средняя позиция выросла с 10 до 12 — это ухудшение.
    assert evaluate(12, 10, 10, higher_is_better=False).is_worse
    assert not evaluate(8, 10, 10, higher_is_better=False).is_worse


def test_zero_baseline_never_signals():
    assert not evaluate(5, 0, 10, higher_is_better=True).is_worse


def _rule(rule_id, project_id, threshold, active=True):
    return SimpleNamespace(id=rule_id, project_id=project_id, metric_code="gsc.clicks",
                           segment="all", threshold_pct=threshold, is_active=active)


def test_project_rule_overrides_global():
    rules = [_rule(1, None, 10), _rule(2, 7, 25)]
    assert [r.id for r in effective_rules(rules, 7)] == [2]
    assert [r.id for r in effective_rules(rules, 8)] == [1]


def test_disabled_project_rule_switches_metric_off():
    rules = [_rule(1, None, 10), _rule(2, 7, 25, active=False)]
    assert effective_rules(rules, 7) == []


def test_card_highlight_only_when_change_is_bad():
    assert is_worse(-12.0, higher_is_better=True)
    assert not is_worse(+8.0, higher_is_better=True)  # клики выросли — рамки нет
    assert is_worse(+5.0, higher_is_better=False)  # позиция ухудшилась
    assert not is_worse(None, higher_is_better=True)


def test_position_metrics():
    assert is_position_metric("gsc.position")
    assert is_position_metric("topvisor.avg_position")
    assert not is_position_metric("gsc.clicks")
