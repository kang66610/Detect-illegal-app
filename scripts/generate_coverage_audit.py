"""由代码生成《认定方法》逐项自动化覆盖审计表。

手写这份表必然过期：规则库一改、证据链一改，文档就变成错的，
而它恰恰是回答"你们到底能测哪几条、什么情况判不了"的唯一依据。

数据来源（全部是代码，不是第二份手抄）：
- ``agent/config/legal_catalog.yaml``  31 项法条目录 + 无规则条款的缺口原因
- ``agent/config/rules/identification_method_rules.yaml``  规则、法依据、证据要求
- ``agent/rule_engine/evidence_chain.py``  证据链准入要求
- ``agent/rule_engine/capability_status.py``  明确 not_executed 的能力

用法：
    python scripts/generate_coverage_audit.py            # 重新生成文档
    python scripts/generate_coverage_audit.py --check     # 只校验是否与代码一致
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import OrderedDict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.rule_engine.evidence_chain import (  # noqa: E402
    _DYNAMIC_KINDS,
    _UI_CHAIN_REQUIREMENTS,
)

CATALOG = ROOT / "agent" / "config" / "legal_catalog.yaml"
RULES = ROOT / "agent" / "config" / "rules" / "identification_method_rules.yaml"
TARGET = ROOT / "docs" / "legal" / "认定方法-自动化覆盖审计.md"

ARTICLE_RE = re.compile(r"第([一二三四五六])条(?:第（([一二三四五六七八九十]+)）点)?")
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}

EVIDENCE_LABELS = {
    "policy": "隐私政策原文",
    "screenshot": "页面截图",
    "timeline": "操作时间线",
    "callstack": "敏感 API 调用栈",
    "behavior_ledger": "行为台账",
    "consistency_matrix": "声明-实际一致性矩阵",
    "traffic": "网络流量",
    "permission_list": "权限清单",
    "sdk_list": "SDK 清单",
}


def clause_key(legal_basis: str) -> str | None:
    """把「第一条第（三）点」解析成 "1-3"；扩展项返回 None。"""
    match = ARTICLE_RE.search(str(legal_basis or ""))
    if not match:
        return None
    article = CN_NUM[match.group(1)]
    item = match.group(2)
    if not item:
        return str(article)
    return f"{article}-{CN_NUM.get(item[0], item)}"


def load_inputs() -> tuple[list[dict], list[dict]]:
    catalog = (yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {})
    rules = (yaml.safe_load(RULES.read_text(encoding="utf-8")) or {}).get("rules") or []
    return list(catalog.get("clauses") or []), list(rules)


def build_report() -> str:
    clauses, rules = load_inputs()

    by_clause: dict[str, list[dict]] = {}
    extensions: list[dict] = []
    for rule in rules:
        key = clause_key(rule.get("legal_basis") or "")
        if key is None:
            extensions.append(rule)
        else:
            by_clause.setdefault(key, []).append(rule)

    covered = [c for c in clauses if by_clause.get(c["key"])]
    uncovered = [c for c in clauses if not by_clause.get(c["key"])]

    out: list[str] = []
    out.append("# 《认定方法》逐项自动化覆盖审计")
    out.append("")
    out.append("> **本文件由 `scripts/generate_coverage_audit.py` 从代码生成，请勿手工编辑。**")
    out.append("> 规则库、证据链或法条目录一变，重新运行脚本即可同步；")
    out.append("> `pytest` 中的 `test_coverage_audit_is_in_sync_with_code` 会拦住忘记更新的情况。")
    out.append("")
    out.append(f"依据：[认定方法全文](认定方法-国信办秘字〔2019〕191号-全文.md)。"
               f"官方六大类共 {len(clauses)} 个具体认定情形，规则库共 {len(rules)} 条规则"
               f"（其中 {len(rules) - len(extensions)} 条对应法条，{len(extensions)} 条为扩展检测项）。")
    out.append("")
    out.append("状态含义：")
    out.append("")
    out.append("- **可自动判定（证据型）**：已有规则，且证据要求可在真实检测管线中采集；")
    out.append("  未采集到证据不等同于“App 合规”，只表示本次未形成违规证据。")
    out.append("- **未覆盖**：当前没有自动规则，判定需人工复核或服务端证据，**不得据此输出合规结论**。")
    out.append("")
    out.append(f"覆盖情况：**{len(covered)} / {len(clauses)}** 项可自动判定，"
               f"{len(uncovered)} 项未覆盖。")
    out.append("")

    out.append("## 一、逐项覆盖")
    out.append("")
    out.append("| 条款 | 具体情形 | 规则 | 证据要求 | 状态 |")
    out.append("|---|---|---|---|---|")
    for clause in clauses:
        matched = by_clause.get(clause["key"]) or []
        if matched:
            rule_ids = "<br>".join(str(r.get("rule_id")) for r in matched)
            fields: list[str] = []
            for rule in matched:
                for field in rule.get("evidence_fields") or []:
                    label = EVIDENCE_LABELS.get(str(field), str(field))
                    if label not in fields:
                        fields.append(label)
            evidence = "、".join(fields)
            status = "可自动判定（证据型）"
        else:
            rule_ids = "—"
            evidence = clause.get("gap") or "无自动规则"
            status = "未覆盖"
        out.append(f"| {clause['label']} | {clause['title']} | {rule_ids} | {evidence} | {status} |")
    out.append("")

    out.append("## 二、扩展检测项")
    out.append("")
    out.append("以下规则不属于《认定方法》31 项情形，用于补充数据安全与体验类风险，"
               "报告中标为扩展项，不参与法条覆盖率统计。")
    out.append("")
    out.append("| 规则 | 名称 | 法依据 |")
    out.append("|---|---|---|")
    for rule in extensions:
        out.append(f"| {rule.get('rule_id')} | {rule.get('rule_name')} | {rule.get('legal_basis')} |")
    out.append("")

    out.append("## 三、证据链准入要求")
    out.append("")
    out.append("违规认定前必须先过证据链门禁，缺证据的发现会降级为提示而不是直接入报告。"
               "默认 `evidence_chain_mode=strict`（`backend/app/config.py`），"
               "只有显式设置 `PRIVACY_EVIDENCE_CHAIN_MODE=lenient` 才会放宽。")
    out.append("")
    out.append("**动态数据类（需要跨源关联）：**")
    out.append("")
    for kind in sorted(_DYNAMIC_KINDS):
        out.append(f"- `{kind}`")
    out.append("")
    out.append("**UI 交互类（截图 + 时间线 + 语义条件）：**")
    out.append("")
    out.append("| finding kind | 截图 | 时间线条目 |")
    out.append("|---|---|---|")
    for kind, requirement in sorted(_UI_CHAIN_REQUIREMENTS.items()):
        out.append(f"| `{kind}` | {requirement.get('screenshot', 0)} | {requirement.get('timeline', 0)} |")
    out.append("")

    out.append("## 四、自动化能力限制")
    out.append("")
    out.append("有两项检测即使跑完也可能不产生结论，报告中必须显示为“未执行”而非“无问题”：")
    out.append("")
    out.append("| 能力 | 触发未执行的条件 |")
    out.append("|---|---|")
    out.append("| 敏感个人信息显著标识 | 未取得可解析的 DOM/CSS 样式时，不能从纯文本推断显著标识 |")
    out.append("| 登录数据传输保护 | 未使用安全测试账号触发认证请求时，不能推断登录数据已加密 |")
    out.append("")
    out.append("这两项由 `agent/rule_engine/capability_status.py` 在运行期判定，"
               "状态为 `not_executed` 时报告不得给出合规结论。")
    out.append("")

    out.append("## 五、未覆盖清单")
    out.append("")
    if uncovered:
        for clause in uncovered:
            out.append(f"- **{clause['label']} {clause['title']}**：{clause.get('gap') or '无自动规则'}")
    else:
        out.append("无。")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只校验文档是否与代码一致")
    args = parser.parse_args()

    generated = build_report()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current.strip() != generated.strip():
            print(f"{TARGET.relative_to(ROOT)} 与代码不一致，请运行 "
                  f"`python scripts/generate_coverage_audit.py` 重新生成", file=sys.stderr)
            return 1
        print("覆盖审计文档与代码一致")
        return 0

    TARGET.write_text(generated, encoding="utf-8")
    print(f"已生成 {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
