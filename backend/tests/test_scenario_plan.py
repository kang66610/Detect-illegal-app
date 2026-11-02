from agent.rule_engine.scenario_plan import (
    ScenarioFrontier,
    device_scenario_plan,
    scenario_plan_for_probe,
)
from agent.rule_engine.recognition_coverage import ITEM_BY_KEY


def test_default_plan_covers_all_31_recognition_items_and_separates_server_facts():
    plan = device_scenario_plan()

    assert len(plan) == 31
    assert {row["item"] for row in plan} == {
        *(f"{category}.{index}" for category, size in ((1, 4), (2, 4), (3, 9), (4, 6), (5, 3), (6, 5)) for index in range(1, size + 1))
    }
    assert {row["executor"] for row in plan} == {"device", "server"}


def test_permission_purpose_and_complaint_processing_are_device_automated():
    assert ITEM_BY_KEY["2.3"].evidence_scope == "device"
    assert ITEM_BY_KEY["6.5"].evidence_scope == "device"


def test_scenario_frontier_records_blocked_reason_instead_of_silently_completing_rule():
    frontier = ScenarioFrontier([{"item": "1.1", "goal": "policy", "signals": ("隐私",)}])
    frontier.mark_attempted("privacy", ["1.1"])
    frontier.mark_blocked(["1.1"], "blocked_external", "外部浏览器没有加载正文")

    snapshot = frontier.snapshot()

    assert snapshot["completed"] == 0
    assert snapshot["remaining"] == 0
    assert snapshot["items"][0]["state"] == "blocked_external"
    assert "外部浏览器" in snapshot["items"][0]["reason"]


def test_completed_scenario_contains_evidence_state():
    frontier = ScenarioFrontier([{"item": "4.2", "goal": "deny", "signals": ("相机",)}])
    frontier.mark_completed(["4.2"], evidence_source="permission-denial-retry")

    row = frontier.snapshot()["items"][0]

    assert row["state"] == "evidence_observed"
    assert row["evidence_sources"] == ["permission-denial-retry"]


def test_frontier_does_not_let_detectorless_items_steal_later_clicks():
    frontier = ScenarioFrontier(device_scenario_plan())
    recommendation = frontier.recommend(
        [{"text": "个性化推荐", "content_desc": "", "resource_id": "feed", "clickable": True}],
        set(),
    )
    assert recommendation is None

    delete = frontier.recommend(
        [{"text": "账号注销", "content_desc": "", "resource_id": "delete", "clickable": True}],
        set(),
    )
    assert delete is not None
    assert "6.1" in delete["scenario_items"]


def test_frontier_does_not_recommend_the_same_semantic_target_forever():
    frontier = ScenarioFrontier([{"item": "1.1", "goal": "policy", "signals": ("隐私",)}])
    elements = [{"text": "隐私政策", "target": "privacy", "clickable": True}]

    for _ in range(2):
        recommendation = frontier.recommend(elements, set())
        assert recommendation and recommendation["target"] == "privacy"
        frontier.mark_attempted(recommendation["target"], recommendation["scenario_items"])

    assert frontier.recommend(elements, set()) is None


def test_allow_probe_plan_contains_only_permission_comparison_scenarios():
    deny_items = {row["item"] for row in scenario_plan_for_probe("deny")}
    allow_items = {row["item"] for row in scenario_plan_for_probe("allow")}

    assert deny_items == {row["item"] for row in device_scenario_plan()}
    assert {"2.3", "3.3", "3.9", "4.1", "4.4", "4.6", "5.1"} <= allow_items
    assert allow_items.isdisjoint({"1.1", "1.4", "3.2", "3.8", "6.1", "6.3", "6.5"})
