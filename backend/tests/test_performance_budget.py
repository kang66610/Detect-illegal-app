from agent.ai_explorer.exploration_completion import ExplorationCompletionGate
from agent.ai_explorer.performance_budget import PerformanceBudget


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def test_document_has_no_fixed_scroll_count_but_stuck_time_is_bounded():
    clock = Clock()
    budget = PerformanceBudget({"document_stuck_seconds": 9}, clock=clock)

    for _ in range(25):
        assert budget.allow_document_scroll("policy", moved=True) is True
    assert budget.allow_document_scroll("policy", moved=False) is True
    clock.advance(10)

    assert budget.allow_document_scroll("policy", moved=False) is False


def test_low_value_surface_is_observed_once():
    budget = PerformanceBudget({}, clock=Clock())

    assert budget.allow_low_value_observation("commercial:abc") is True
    assert budget.allow_low_value_observation("commercial:abc") is False


def test_no_effect_target_is_blocked_after_configured_attempts():
    budget = PerformanceBudget({"no_effect_attempts": 2}, clock=Clock())

    assert budget.record_action_effect("page::cache", effective=False) is False
    assert budget.record_action_effect("page::cache", effective=False) is True
    assert budget.target_blocked("page::cache") is True


def test_operation_metrics_capture_count_and_elapsed_time():
    clock = Clock()
    budget = PerformanceBudget({}, clock=clock)
    token = budget.begin("llm")
    clock.advance(1.25)
    budget.finish(token)

    assert budget.metrics()["llm"] == {"count": 1, "total_ms": 1250, "max_ms": 1250}


def test_total_timeout_reports_pending_scenario_as_gap():
    result = ExplorationCompletionGate().assess(
        proposed_termination={"kind": "budget_exhausted"},
        scenario_snapshot={"items": [{"item": "4.2", "state": "attempted"}]},
        coverage_gaps=[], navigation_frontier_exhausted=False,
        total_budget_exhausted=True,
    )

    assert result.coverage_complete is False
    assert "4.2" in result.unfinished_items
    assert any("总时间预算" in gap for gap in result.gaps)
