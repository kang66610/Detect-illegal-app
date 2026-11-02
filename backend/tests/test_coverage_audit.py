"""覆盖审计文档必须与代码同源，且不能漏登记法条或规则。

这份文档是对外回答"能测哪几条、什么情况判不了"的唯一依据，
所以它不能靠人记得更新——三条门禁都指向同一个事实：代码是唯一真相。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "agent" / "config" / "legal_catalog.yaml"
RULES = ROOT / "agent" / "config" / "rules" / "identification_method_rules.yaml"
GENERATOR = ROOT / "scripts" / "generate_coverage_audit.py"
AUDIT_DOC = ROOT / "docs" / "legal" / "认定方法-自动化覆盖审计.md"

# 《认定方法》官方六类共 31 项具体情形
OFFICIAL_CLAUSE_COUNT = 31
OFFICIAL_CATEGORIES = {1: 4, 2: 4, 3: 9, 4: 6, 5: 3, 6: 5}


def _catalog() -> list[dict]:
    return (yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}).get("clauses") or []


def _rules() -> list[dict]:
    return (yaml.safe_load(RULES.read_text(encoding="utf-8")) or {}).get("rules") or []


def test_coverage_audit_is_in_sync_with_code():
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )
    assert result.returncode == 0, (
        "覆盖审计文档与规则库/证据链不一致，请运行 "
        f"`python scripts/generate_coverage_audit.py` 重新生成。\n{result.stdout}{result.stderr}"
    )


def test_catalog_covers_all_official_clauses():
    clauses = _catalog()
    assert len(clauses) == OFFICIAL_CLAUSE_COUNT

    counts: dict[int, int] = {}
    for clause in clauses:
        counts[clause["category"]] = counts.get(clause["category"], 0) + 1
    assert counts == OFFICIAL_CATEGORIES, f"分类分布与官方不一致：{counts}"


def test_every_clause_is_covered_or_explains_its_gap():
    """没有自动规则的条款必须写清为什么不能自动定性，不能悄悄留空。"""
    clause_key_pattern = __import__("re").compile(r"第([一二三四五六])条(?:第（([一二三四五六七八九十]+)）点)?")
    cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}

    covered: set[str] = set()
    for rule in _rules():
        match = clause_key_pattern.search(str(rule.get("legal_basis") or ""))
        if not match:
            continue
        article = cn[match.group(1)]
        item = match.group(2)
        covered.add(str(article) if not item else f"{article}-{cn[item[0]]}")

    for clause in _catalog():
        if clause["key"] in covered:
            continue
        assert clause.get("gap"), (
            f"{clause['label']} 没有自动规则，也没有登记 gap 原因；"
            "请在 legal_catalog.yaml 补充缺口说明"
        )


def test_every_rule_is_either_mapped_to_a_clause_or_declared_extension():
    catalog_keys = {clause["key"] for clause in _catalog()}
    clause_key_pattern = __import__("re").compile(r"第([一二三四五六])条(?:第（([一二三四五六七八九十]+)）点)?")
    cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}

    orphans = []
    for rule in _rules():
        legal_basis = str(rule.get("legal_basis") or "")
        match = clause_key_pattern.search(legal_basis)
        if match:
            article = cn[match.group(1)]
            item = match.group(2)
            key = str(article) if not item else f"{article}-{cn[item[0]]}"
            if key not in catalog_keys:
                orphans.append((rule.get("rule_id"), key))
            continue
        # 扩展项必须在 legal_basis 里自己声明，不能被当成法条规则混进覆盖率
        if "扩展" not in legal_basis:
            orphans.append((rule.get("rule_id"), legal_basis[:40]))

    assert orphans == [], f"规则未挂到任何法条或未声明为扩展项：{orphans}"


def test_audit_document_states_the_real_coverage_numbers():
    """文档里的覆盖统计必须与规则库实际算出来的一致，防止手改数字。"""
    text = AUDIT_DOC.read_text(encoding="utf-8")
    rules = _rules()
    extensions = [r for r in rules if "扩展" in str(r.get("legal_basis") or "")]
    assert f"规则库共 {len(rules)} 条规则" in text
    assert f"{len(rules) - len(extensions)} 条对应法条" in text
    assert "请勿手工编辑" in text
