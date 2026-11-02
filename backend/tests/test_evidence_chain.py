from agent.detection_engines.base import Finding
from agent.rule_engine.evidence_chain import assess_evidence_chain, keep_only_complete_evidence_chains


def _evidence(kind, evidence_type, index):
    return {"type": evidence_type, "path": f"{index}.{evidence_type}", "meta": {"finding_kind": kind}}


def test_ui_finding_with_one_screenshot_and_timeline_is_admissible():
    finding = Finding(kind="permission_denial_blocks_function", category=4, payload={
        "permission_message_matched": True, "business_action": "upload-avatar",
        "base_service_blocked": True, "permission_intrinsic_to_action": False,
    })
    evidence = [_evidence(finding.kind, "screenshot", 1), _evidence(finding.kind, "timeline", 2)]

    kept, gaps = keep_only_complete_evidence_chains([finding], evidence)

    assert kept == [finding]
    assert gaps == []


def test_ui_finding_also_survives_with_matching_before_after_screens_and_timeline():
    finding = Finding(kind="permission_denial_blocks_function", category=4, payload={
        "permission_message_matched": True, "business_action": "upload-avatar",
        "base_service_blocked": True, "permission_intrinsic_to_action": False,
    })
    evidence = [
        _evidence(finding.kind, "screenshot", 1), _evidence(finding.kind, "screenshot", 2),
        _evidence(finding.kind, "timeline", 3),
    ]

    kept, gaps = keep_only_complete_evidence_chains([finding], evidence)

    assert kept == [finding]
    assert gaps == []


def test_permission_purpose_finding_survives_with_one_prompt_screenshot_and_timeline():
    finding = Finding(kind="permission_purpose_not_informed", category=2, payload={
        "purpose_context_verified": True, "purpose_explained_before_prompt": False,
    })
    evidence = [_evidence(finding.kind, "screenshot", 1), _evidence(finding.kind, "timeline", 2)]

    kept, gaps = keep_only_complete_evidence_chains([finding], evidence)

    assert kept == [finding]
    assert gaps == []


def test_dynamic_finding_requires_a_time_correlated_behavior_ledger():
    finding = Finding(kind="api_called_before_consent", category=3, payload={})
    evidence = [
        {"type": "timeline", "path": "page.json", "meta": {"event_type": "page_observed"}},
        {"type": "callstack", "path": "calls.json", "meta": {"finding_kinds": [finding.kind]}},
    ]

    kept, gaps = keep_only_complete_evidence_chains([finding], evidence)

    assert kept == []
    assert "时间关联" in gaps[0]


def test_evidence_chain_exposes_the_missing_artifacts_for_a_downgraded_candidate():
    finding = Finding(kind="permission_denial_blocks_function", category=4, payload={
        "permission_message_matched": True, "business_action": "upload-avatar",
        "base_service_blocked": True, "permission_intrinsic_to_action": False,
    })

    decision = assess_evidence_chain(finding, [_evidence(finding.kind, "timeline", 1)])

    assert decision["status"] == "downgraded"
    assert "screenshot×1" in decision["missing"]


def test_lenient_ui_finding_is_admissible_with_a_single_screenshot_only():
    finding = Finding(kind="permission_denial_blocks_function", category=4, payload={
        "permission_message_matched": True, "business_action": "upload-avatar",
        "base_service_blocked": True, "permission_intrinsic_to_action": False,
    })
    evidence = [_evidence(finding.kind, "screenshot", 1)]

    kept, gaps = keep_only_complete_evidence_chains([finding], evidence, mode="lenient")

    assert kept == [finding]
    assert gaps == []


def test_lenient_ui_finding_without_any_artifact_is_still_downgraded():
    finding = Finding(kind="permission_denial_blocks_function", category=4, payload={
        "permission_message_matched": True, "business_action": "upload-avatar",
        "base_service_blocked": True, "permission_intrinsic_to_action": False,
    })

    decision = assess_evidence_chain(finding, [], mode="lenient")

    assert decision["status"] == "downgraded"
    assert "screenshot或timeline×1" in decision["missing"]


def test_lenient_mode_still_requires_the_rule_semantic_condition():
    finding = Finding(kind="permission_denial_blocks_function", category=4, payload={
        "permission_message_matched": False, "business_action": "upload-avatar",
        "base_service_blocked": True, "permission_intrinsic_to_action": False,
    })
    evidence = [_evidence(finding.kind, "screenshot", 1), _evidence(finding.kind, "timeline", 2)]

    kept, gaps = keep_only_complete_evidence_chains([finding], evidence, mode="lenient")

    assert kept == []
    assert gaps


def test_lenient_dynamic_finding_is_admissible_with_callstack_only():
    finding = Finding(kind="api_called_before_consent", category=3, payload={})
    evidence = [
        {"type": "callstack", "path": "calls.json", "meta": {"finding_kinds": [finding.kind]}},
    ]

    kept, gaps = keep_only_complete_evidence_chains([finding], evidence, mode="lenient")

    assert kept == [finding]
    assert gaps == []


def test_lenient_dynamic_finding_without_any_trace_is_still_downgraded():
    finding = Finding(kind="api_called_before_consent", category=3, payload={})
    evidence = [{"type": "timeline", "path": "page.json", "meta": {"event_type": "page_observed"}}]

    kept, gaps = keep_only_complete_evidence_chains([finding], evidence, mode="lenient")

    assert kept == []
    assert gaps


def test_lenient_sdk_collection_admits_callstack_without_consistency_matrix():
    """生产宽松模式：SDK 未披露有调用栈即可准入，矩阵缺失只作 notes。"""
    finding = Finding(kind="sdk_collection_not_disclosed", category=2, payload={})
    callstack = {
        "type": "callstack", "path": "calls.json",
        "meta": {"finding_kinds": [finding.kind]},
    }

    kept, gaps = keep_only_complete_evidence_chains([finding], [callstack], mode="lenient")
    assert kept == [finding]
    assert gaps == []

    decision = assess_evidence_chain(finding, [callstack], mode="lenient")
    assert decision["status"] == "admissible"
    assert decision["requirements"].get("consistency_matrix") is False
    assert any("一致性矩阵" in note for note in decision.get("notes") or [])


def test_lenient_non_sdk_dynamic_finding_still_admits_callstack_only():
    finding = Finding(kind="frequent_collection", category=4, payload={})
    evidence = [
        {"type": "callstack", "path": "calls.json", "meta": {"finding_kinds": [finding.kind]}},
    ]
    kept, gaps = keep_only_complete_evidence_chains([finding], evidence, mode="lenient")
    assert kept == [finding]
    assert gaps == []
