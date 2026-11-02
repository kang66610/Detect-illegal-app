import pytest

from agent.common.exceptions import RuleConfigError
from agent.detection_engines.base import Finding
from agent.rule_engine.rule_loader import load_rules
from agent.rule_engine.rule_matcher import match_rules


# 官方六大类 ↔ 《认定方法》第一至第六条。
CATEGORY_TO_ARTICLE = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}

# Appium/Frida findings must stay connected to the legal rule that turns
# them into a reportable violation.
REAL_DEVICE_KIND_TO_RULE = {
    "policy_entry_exceeds_four_clicks": ("RULE_1_3", {"click_count": 5}),
    "consent_checkbox_prechecked": ("RULE_3_4", {}),
    "permission_requested_immediately_after_consent": ("RULE_4_1_CONSENT", {"after_consent_ms": 1}),
    "permission_denial_blocks_function": ("RULE_4_2", {"probe_action": "deny"}),
    "multiple_permissions_requested_after_consent": ("RULE_4_6", {"count": 2}),
    "delete_obstacle": ("RULE_6_2", {}),
    "api_called_after_permission_denial": ("RULE_3_REFUSE", {}),
    "no_delete_entry": ("RULE_6_1", {}),
    "withdraw_consent_unavailable": ("RULE_3_8", {}),
    "first_run_notice_missing": ("RULE_1_2_NOTICE", {}),
    "targeted_push_no_opt_out": ("RULE_3_6", {}),
    "misleading_consent_copy": ("RULE_3_7", {}),
    "forced_consent_for_service_improvement": ("RULE_4_5", {}),
    "collected_beyond_authorization": ("RULE_3_2", {}),
}


def test_loads_20_rules_covering_official_six_categories():
    rules = load_rules()
    official = [r for r in rules if not r.rule_id.startswith("RULE_EXT_")]
    assert len(official) == 28
    assert {r.category for r in official} == {1, 2, 3, 4, 5, 6}
    for r in official:
        assert r.rule_id and r.legal_basis and r.risk_level in ("高", "中", "低") and r.weight > 0
        assert r.category_name  # 每类必须有类别名称，违规输出显式标注「第N类」
        assert f"第{CATEGORY_TO_ARTICLE[r.category]}条" in r.legal_basis  # 法规条款须具体到正确的第几条
        assert "第（" in r.legal_basis and "）点" in r.legal_basis  # 须具体到第（X）点
    assert {r.rule_id for r in rules if r.rule_id.startswith("RULE_EXT_")} == {
        "RULE_EXT_ASSOC_START", "RULE_EXT_KEEPALIVE", "RULE_EXT_SENSITIVE_MARK",
        "RULE_EXT_LOGIN_DATA_PROTECTION",
    }


def test_fourth_article_rule_ids_match_their_legal_point_numbers():
    rules = {rule.rule_id: rule for rule in load_rules()}
    assert "第四条第（二）点" in rules["RULE_4_2"].legal_basis
    assert rules["RULE_4_2"].rule_name == "用户拒绝非必要权限后业务功能被阻断"
    assert "第四条第（四）点" in rules["RULE_4_4"].legal_basis
    assert rules["RULE_4_4"].rule_name == "超频次收集个人信息"


def test_invalid_policy_contact_can_be_proved_by_policy_text_without_screenshot():
    rules = {rule.rule_id: rule for rule in load_rules()}
    assert "policy" in rules["RULE_6_4"].evidence_fields


def test_rule_fires_on_matching_finding():
    rules = load_rules()
    f = Finding(kind="policy_missing", category=1, payload={})
    matched = match_rules(rules, [f])
    assert len(matched) == 1
    assert matched[0].rule.rule_id == "RULE_1_1"


def test_rule_requires_all_conditions():
    rules = load_rules()
    f = Finding(kind="frequent_collection", category=3,
                payload={"count": 2, "window_minutes": 1})  # 未超阈值
    assert match_rules(rules, [f]) == []


def test_unknown_operator_raises():
    from agent.rule_engine.rule_matcher import _eval_condition
    with pytest.raises(RuleConfigError):
        _eval_condition({"field": "x", "op": "explode", "value": 1}, {"x": 1})


def test_real_device_findings_map_to_report_rules():
    rules = load_rules()
    findings = [
        Finding(kind=kind, category=1, payload=payload)
        for kind, (_rule_id, payload) in REAL_DEVICE_KIND_TO_RULE.items()
    ]

    matched = match_rules(rules, findings)

    assert {item.rule.rule_id for item in matched} == {
        rule_id for rule_id, _payload in REAL_DEVICE_KIND_TO_RULE.values()
    }
