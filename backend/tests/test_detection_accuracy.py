from types import SimpleNamespace

from agent.detection_engines.base import Finding
from agent.rule_engine.manual_baseline import compare_manual_baseline
from agent.rule_engine.scenario_plan import ScenarioFrontier, device_scenario_plan
from agent.rule_engine.quality_metrics import build_quality_metrics


def test_device_plan_requires_deterministic_permission_and_account_scenarios():
    plan = {item["item"] for item in device_scenario_plan()}
    assert {"2.3", "3.1", "4.1", "6.2"} <= plan


def test_case_baseline_exposes_missing_manual_finding_without_inventing_it():
    result = compare_manual_baseline("com.example.travel", {"RULE_2_2", "RULE_4_1_CONSENT"})
    assert result["false_negative"] == ["RULE_2_1_SDK", "RULE_4_2"]
    assert result["recall"] == 0.5


def test_qiandu_baseline_tracks_manual_rules_without_inventing_them():
    result = compare_manual_baseline("com.example.reader", {"RULE_4_2"})
    assert result["false_negative"] == ["RULE_2_1_SDK", "RULE_3_8"]
    assert result["recall"] == 1 / 3


def test_rule_guided_frontier_prefers_outstanding_visible_privacy_target():
    frontier = ScenarioFrontier()
    elements = [
        {"clickable": True, "resource_id": "settings", "text": "设置", "content_desc": ""},
        {"clickable": True, "resource_id": "privacy", "text": "隐私政策", "content_desc": ""},
    ]

    recommendation = frontier.recommend(elements, set())

    assert recommendation["target"] == "privacy"
    assert "1.1" in recommendation["scenario_items"]
    frontier.mark_attempted(recommendation["target"], recommendation["scenario_items"])
    assert frontier.snapshot()["attempted"] >= 1


def test_quality_metrics_expose_baseline_recall_scenario_coverage_and_evidence_completeness():
    matched = [SimpleNamespace(
        finding=Finding(kind="sdk_collection_not_disclosed", category=2),
        rule=SimpleNamespace(rule_id="RULE_2_1_SDK", evidence_fields=["callstack"]),
    )]
    evidence = [{"type": "callstack", "path": "x", "meta": {"finding_kinds": ["sdk_collection_not_disclosed"]}}]
    runtime = {"scenario_coverage": {"planned": 9, "attempted": 4, "remaining": 5}}
    baseline = {"recall": 0.25, "false_negative": ["RULE_2_2"]}

    metrics = build_quality_metrics(matched, evidence, runtime, baseline)

    assert metrics["evidence_chain_completeness"] == 1.0
    assert metrics["scenario_attempt_rate"] == 4 / 9
    assert metrics["manual_baseline_recall"] == 0.25
