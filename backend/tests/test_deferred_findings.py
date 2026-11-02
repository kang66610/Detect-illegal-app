from types import SimpleNamespace

from agent.detection_engines.base import DetectionContext
from agent.rule_engine.deferred_findings import collect_deferred_findings, mismatched_permissions


def test_sms_permission_is_an_industry_mismatch_for_a_reader_app():
    hits = mismatched_permissions("阅读", ["android.permission.READ_SMS", "android.permission.INTERNET"])
    assert hits == ["android.permission.READ_SMS"]


def test_communications_industry_may_use_sms():
    assert mismatched_permissions("通讯", ["android.permission.READ_SMS"]) == []


def test_finance_alias_flags_location_but_not_camera():
    assert mismatched_permissions("金融理财", [
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.CAMERA",
        "android.permission.INTERNET",
    ]) == ["android.permission.ACCESS_FINE_LOCATION"]


def test_generic_industry_does_not_flag_location():
    assert mismatched_permissions("通用", ["android.permission.ACCESS_FINE_LOCATION"]) == []


def test_missing_policy_after_finished_traversal_emits_policy_missing(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用", mode="fast"),
        apk=SimpleNamespace(policy_raw=None, permissions=[]),
        cfg={}, data_dir=tmp_path,
        runtime={
            "seen_text": "首页 推荐",
            "traversal_termination": {"kind": "safe_frontier_exhausted"},
            "pages_covered": 12,
        },
    )
    findings, _completions = collect_deferred_findings(ctx)
    kinds = {item.kind for item in findings}
    assert "policy_missing" in kinds
    assert "policy_entry_not_found" in kinds


def test_identifier_collection_without_policy_disclosure_is_beyond_authorization(tmp_path):
    (tmp_path / "callstack").mkdir()
    (tmp_path / "callstack" / "frida-events.json").write_text(
        '{"events":[{"type":"api","data_type":"设备标识信息","api":"Settings$Secure.getString","time":1}]}',
        encoding="utf-8",
    )
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用"),
        apk=SimpleNamespace(policy_raw="我们收集账号用于登录。投诉请联系客服。", permissions=[]),
        cfg={}, data_dir=tmp_path,
        runtime={
            "privacy_policy_read_complete": True,
            "policy_document_read_complete": True,
            "policy_text": "我们收集账号用于登录。",
        },
    )
    findings, _completions = collect_deferred_findings(ctx)
    assert any(item.kind == "collected_beyond_authorization" for item in findings)


def test_deny_path_still_collecting_location_emits_refusal_finding(tmp_path):
    (tmp_path / "callstack").mkdir()
    (tmp_path / "callstack" / "frida-events.json").write_text(
        '{"events":[{"type":"api","data_type":"位置信息","api":"getLastKnownLocation","time":2000}]}',
        encoding="utf-8",
    )
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用"),
        apk=SimpleNamespace(policy_raw=None, permissions=[]),
        cfg={}, data_dir=tmp_path,
        runtime={"permission_denied_at_ms": 1000},
    )
    findings, _completions = collect_deferred_findings(ctx)
    assert any(item.kind == "api_called_after_permission_denial" for item in findings)


def test_incomplete_privacy_hub_does_not_emit_missing_withdraw_path(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用"),
        apk=SimpleNamespace(policy_raw="我们收集个人信息用于提供服务，范围包括账号。投诉可通过客服联系我们。", permissions=[]),
        cfg={}, data_dir=tmp_path,
        runtime={
            "seen_text": "设置 个人信息 隐私政策",
            "traversal_termination": {"kind": "safe_frontier_exhausted"},
            "pages_covered": 10,
            "privacy_hub_visited": True,
            "policy_document_read_complete": True,
            "policy_text": "我们收集个人信息用于提供服务，范围包括账号。投诉可通过客服联系我们。",
        },
    )
    findings, completions = collect_deferred_findings(ctx)
    assert not any(item.kind == "withdraw_consent_unavailable" for item in findings)
    assert "withdraw_consent_unavailable" not in completions


def test_missing_withdraw_entry_survives_unrelated_incomplete_frontier(tmp_path):
    """A completed hub audit is enough for 3.8 even if another branch fails."""
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用"),
        apk=SimpleNamespace(policy_raw="完整隐私政策正文。", permissions=[]),
        cfg={}, data_dir=tmp_path,
        runtime={
            "seen_text": "设置 个人信息 注销账号 隐私政策",
            "traversal_termination": {"kind": "frontier_incomplete", "reason": "foreign_app_launch"},
            "pages_covered": 23,
            "privacy_hub_visited": True,
            "privacy_hub_audit_complete": True,
            "policy_document_read_complete": True,
            "policy_text": "完整隐私政策正文。",
        },
    )
    findings, completions = collect_deferred_findings(ctx)
    assert any(item.kind == "withdraw_consent_unavailable" for item in findings)
    assert "withdraw_consent_unavailable" in completions


def test_finished_run_without_first_run_notice_is_a_1_2_finding(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用"),
        apk=SimpleNamespace(policy_raw=None, permissions=[]),
        cfg={}, data_dir=tmp_path,
        runtime={
            "seen_text": "首页 推荐",
            "traversal_termination": {"kind": "safe_frontier_exhausted"},
            "pages_covered": 8,
        },
    )
    findings, completions = collect_deferred_findings(ctx)
    assert any(item.kind == "first_run_notice_missing" for item in findings)
    assert "first_run_notice_missing" in completions


def test_visible_withdraw_entry_does_not_emit_missing_path(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用"),
        apk=SimpleNamespace(policy_raw="用户可在设置中撤回同意授权。投诉可通过客服联系我们。", permissions=[]),
        cfg={}, data_dir=tmp_path,
        runtime={
            "seen_text": "设置 授权管理 撤回同意",
            "traversal_termination": {"kind": "safe_frontier_exhausted"},
            "pages_covered": 10,
            "privacy_hub_visited": True,
            "withdraw_paths_observed": {"授权管理"},
        },
    )
    findings, completions = collect_deferred_findings(ctx)
    assert not any(item.kind == "withdraw_consent_unavailable" for item in findings)
    assert "withdraw_entry_found" in completions


def test_static_known_sdk_without_runtime_collection_is_only_a_coverage_gap(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用", mode="deep"),
        apk=SimpleNamespace(
            policy_raw="本应用使用阿里云用户反馈SDK提供意见反馈服务，不说明IMSI。",
            permissions=[],
            sdk_list=[{
                "name": "阿里云用户反馈",
                "collected": ["IMSI", "设备标识信息"],
                "matched_by": ["DEX:com.alibaba.sdk.android.feedback"],
            }],
            meta={},
        ),
        cfg={}, data_dir=tmp_path,
        runtime={
            "policy_document_read_complete": True,
            "policy_text": "本应用使用阿里云用户反馈SDK提供意见反馈服务，不说明IMSI。",
            "traversal_termination": {"kind": "safe_frontier_exhausted"},
            "pages_covered": 10,
        },
    )
    findings, completions = collect_deferred_findings(ctx)
    assert not any(item.kind == "sdk_collection_not_disclosed" for item in findings)
    assert "sdk_collection_not_disclosed" not in completions
    assert any("RULE_2_1_SDK" in gap for gap in ctx.runtime.get("coverage_gaps", []))


def test_permission_only_sdk_match_does_not_emit_static_sdk_gap(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用", mode="deep"),
        apk=SimpleNamespace(
            policy_raw="完整隐私政策正文，含目的方式范围个人信息。",
            permissions=[],
            sdk_list=[{
                "name": "声网 Agora",
                "collected": ["音视频数据"],
                "matched_by": ["权限:android.permission.RECORD_AUDIO,android.permission.CAMERA"],
            }],
            meta={},
        ),
        cfg={}, data_dir=tmp_path,
        runtime={
            "policy_document_read_complete": True,
            "policy_text": "完整隐私政策正文，含目的方式范围个人信息。",
            "traversal_termination": {"kind": "safe_frontier_exhausted"},
            "pages_covered": 10,
        },
    )
    findings, _ = collect_deferred_findings(ctx)
    assert not any(item.kind == "sdk_collection_not_disclosed" for item in findings)
