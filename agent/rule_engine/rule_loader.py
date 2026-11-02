from pathlib import Path

import yaml
from pydantic import BaseModel

from agent.common.exceptions import RuleConfigError
from agent.common.settings import PROJECT_ROOT

_RULES_PATH = PROJECT_ROOT / "agent" / "config" / "rules" / "identification_method_rules.yaml"


class Condition(BaseModel):
    field: str
    op: str
    value: object


class Rule(BaseModel):
    rule_id: str
    rule_name: str
    category: int
    category_name: str = ""  # 由 load_rules 从 category_names 映射填充
    legal_basis: str
    risk_level: str
    weight: int
    conditions: list[Condition]
    evidence_fields: list[str]
    suggestion: str


class RuleSet(BaseModel):
    score_base: int = 100
    category_names: dict[int, str] = {}
    rules: list[Rule]


_CATEGORY_NAMES = {
    1: "未公开收集使用规则",
    2: "未明示收集使用个人信息的目的、方式和范围",
    3: "未经用户同意收集使用个人信息",
    4: "违反必要原则，收集与其提供的服务无关的个人信息",
    5: "未经同意向他人提供个人信息",
    6: "未按法律规定提供删除或更正个人信息功能，或未公布投诉、举报方式等信息",
}


def load_rules(path: Path | None = None) -> list[Rule]:
    p = path or _RULES_PATH
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    try:
        ruleset = RuleSet.model_validate(data)
    except Exception as e:
        raise RuleConfigError(f"规则配置解析失败：{e}") from e
    # 类别名称：优先 YAML 内 category_names，缺省用官方六大类映射兜底。
    names = {int(k): v for k, v in ruleset.category_names.items()} or _CATEGORY_NAMES
    for rule in ruleset.rules:
        rule.category_name = names.get(rule.category, f"第{rule.category}类")
    return ruleset.rules
