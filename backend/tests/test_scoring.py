from agent.detection_engines.base import Finding
from agent.rule_engine.rule_loader import load_rules
from agent.rule_engine.rule_matcher import match_rules
from agent.rule_engine.scoring import compute_score


def test_clean_app_scores_100():
    rules = load_rules()
    score, breakdown = compute_score([], rules)
    assert score == 100
    assert breakdown["total_deduction"] == 0


def test_score_deduction_and_floor():
    rules = load_rules()
    # 注：brief 原文用 r.conditions[0]["field"]，pydantic v2 模型不支持下标访问，改为属性访问（断言语义不变）
    findings = [Finding(kind=r.conditions[0].field, category=r.category,
                        payload=_payload_for(r)) for r in rules]
    matched = match_rules(rules, findings)
    score, breakdown = compute_score(matched, rules)
    assert score < 100
    assert breakdown["total_deduction"] == sum(m.rule.weight for m in matched)
    # 全部违规扣到 0
    assert compute_score(matched, rules, base=10)[0] == 0


def _payload_for(rule):
    return {c.field: c.value for c in rule.conditions}
