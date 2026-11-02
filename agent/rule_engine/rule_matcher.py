from dataclasses import dataclass

from agent.common.exceptions import RuleConfigError
from agent.detection_engines.base import Finding
from agent.rule_engine.rule_loader import Rule

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "contains": lambda a, b: b in a if a is not None else False,
    "not_exists": lambda a, b: a is None,
}


@dataclass
class MatchedViolation:
    rule: Rule
    finding: Finding
    payload: dict


def _eval_condition(cond: dict, payload: dict) -> bool:
    op = _OPS.get(cond["op"])
    if op is None:
        raise RuleConfigError(f"不支持的操作符：{cond['op']}")
    try:
        return op(payload.get(cond["field"]), cond["value"])
    except TypeError:
        return False


def _findings_as_payloads(findings: list[Finding]) -> list[dict]:
    """展开：payload 平铺为顶层键 + kind 标记，供条件引用（如 frequent_collection_count）。"""
    out = []
    for f in findings:
        p = dict(f.payload)
        p.setdefault(f.kind, True)
        out.append(p)
    return out


def match_rules(rules: list[Rule], findings: list[Finding]) -> list[MatchedViolation]:
    payloads = _findings_as_payloads(findings)
    matched = []
    for rule in rules:
        for finding, p in zip(findings, payloads):
            if all(_eval_condition(c.model_dump(), p) for c in rule.conditions):
                matched.append(MatchedViolation(rule=rule, finding=finding, payload=p))
                break  # 一条规则命中一次即可
    return matched
