from types import SimpleNamespace

from agent.rule_engine.capability_status import automatic_capability_status
from agent.rule_engine.evidence_reconciliation import reconcile_evidence
from agent.rule_engine.manual_baseline import compare_manual_baseline, compare_timeline_baseline


def test_reconciliation_preserves_conflicting_cross_source_evidence():
    finding = SimpleNamespace(kind="permission_denial_blocks_function")
    evidence = [
        {"type": "timeline", "meta": {"finding_kind": finding.kind, "source": "appium", "verified": True}},
        {"type": "screenshot", "meta": {"finding_kind": finding.kind, "source": "screenshot", "verified": False}},
    ]
    cases = reconcile_evidence(
        [finding], evidence,
        [{"finding_kind": finding.kind, "status": "admissible", "missing": []}],
    )

    assert cases[0]["status"] == "conflict"
    assert cases[0]["artifact_count"] == 2
    assert cases[0]["conflicts"] == ["verified"]


def test_unavailable_visual_and_login_probes_are_explicitly_not_executed():
    status = automatic_capability_status(
        {"policy_document_read_complete": True, "policy_preserved_html": False}, [], [],
    )

    assert status["sensitive_information_emphasis"]["status"] == "not_executed"
    assert status["login_data_protection"]["status"] == "not_executed"


def test_lanhua_manual_and_timeline_baselines_are_registered():
    rules = compare_manual_baseline("com.example.flowers", {"RULE_2_1_SDK"})
    timeline = compare_timeline_baseline("com.example.flowers", [
        {"meta": {"event_type": "external_document_read_complete"}},
        {"meta": {"event_type": "privacy_hub_entered"}},
        {"meta": {"event_type": "awaiting_manual_login"}},
        {"meta": {"event_type": "permission_prompt_without_purpose"}},
    ])

    assert set(rules["false_negative"]) == {
        "RULE_EXT_SENSITIVE_MARK", "RULE_EXT_LOGIN_DATA_PROTECTION",
    }
    assert timeline["passed"] is True
