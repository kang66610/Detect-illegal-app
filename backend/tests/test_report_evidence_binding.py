from types import SimpleNamespace

from agent.detection_engines.base import Finding
from agent.rule_engine.report_generator import evidence_for_match
from agent.rule_engine.evidence_chain import keep_only_evidence_bound_matches
from agent.rule_engine.rule_matcher import MatchedViolation


def test_report_binds_only_rule_scoped_evidence_to_matching_violation():
    matched = MatchedViolation(
        rule=SimpleNamespace(evidence_fields=["screenshot", "timeline"]),
        finding=Finding(kind="permission_purpose_not_informed", category=2),
        payload={},
    )
    evidence = [
        {"type": "screenshot", "path": "permission.png", "meta": {"finding_kind": "permission_purpose_not_informed"}},
        {"type": "timeline", "path": "permission.json", "meta": {"finding_kinds": ["permission_purpose_not_informed"]}},
        {"type": "screenshot", "path": "unrelated.png", "meta": {"finding_kind": "frequent_collection"}},
        {"type": "callstack", "path": "all-events.json", "meta": {"finding_kind": "permission_purpose_not_informed"}},
    ]

    selected = evidence_for_match(matched, evidence)

    assert [item["path"] for item in selected] == ["permission.png", "permission.json"]


def test_report_gate_downgrades_matches_with_no_rule_scoped_artifact():
    supported = MatchedViolation(
        rule=SimpleNamespace(rule_id="R-supported", rule_name="supported", evidence_fields=["timeline"]),
        finding=Finding(kind="permission_purpose_not_informed", category=2),
        payload={},
    )
    unsupported = MatchedViolation(
        rule=SimpleNamespace(rule_id="R-empty", rule_name="empty", evidence_fields=["screenshot"]),
        finding=Finding(kind="no_delete_entry", category=6),
        payload={},
    )
    evidence = [{
        "type": "timeline", "path": "permission.json",
        "meta": {"finding_kind": "permission_purpose_not_informed"},
    }]

    kept, downgraded = keep_only_evidence_bound_matches([supported, unsupported], evidence)

    assert kept == [supported]
    assert downgraded == [{
        "rule_id": "R-empty",
        "finding_kind": "no_delete_entry",
        "reason": "未形成该规则专属证据，已降级为待核验",
    }]


def test_permission_mismatch_uses_a_scoped_permission_list_artifact():
    matched = MatchedViolation(
        rule=SimpleNamespace(rule_id="RULE_4_1", rule_name="permission mismatch", evidence_fields=["permission_list"]),
        finding=Finding(kind="permission_industry_mismatch", category=4),
        payload={},
    )
    kept, downgraded = keep_only_evidence_bound_matches([matched], [{
        "type": "permission_list", "path": "behavior/permission-list.json",
        "meta": {"finding_kind": "permission_industry_mismatch"},
    }])
    assert kept == [matched]
    assert downgraded == []
