"""Import human DOCX reports as regression-only baselines."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

import yaml
from docx import Document


@dataclass(frozen=True)
class ManualBaselineRow:
    report_name: str
    package_name: str
    expected_rule_ids: frozenset[str]
    expected_timeline_paths: tuple[tuple[tuple[str, ...], ...], ...] = ()
    unresolved_statements: tuple[str, ...] = ()


_RULE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("RULE_EXT_SENSITIVE_MARK", ("敏感个人信息", "显著标识", "醒目标识")),
    ("RULE_EXT_LOGIN_DATA_PROTECTION", ("加密", "去标识化", "认证数据", "登录数据")),
    ("RULE_2_1_SDK", ("第三方sdk", "嵌入的sdk", "嵌入sdk", "第三方插件", "flutter框架")),
    ("RULE_6_5", ("投诉", "举报", "处理时限", "承诺时限", "查处时限")),
    ("RULE_6_3", ("未公布投诉", "未提供投诉", "投诉、举报方式", "投诉举报渠道")),
    ("RULE_6_1", ("注销账号", "删除个人信息", "注销账户", "删除、更正", "查询、更正、删除")),
    ("RULE_3_8", ("撤回个人信息", "撤回同意", "撤销同意", "撤回功能", "撤回个人信息权限")),
    ("RULE_3_4", ("默认勾选", "默认选中", "默认同意")),
    ("RULE_3_1", ("同意前", "未勾选同意", "未选择同意", "首次使用", "注册功能时")),
    ("RULE_3_2", ("超出用户授权", "未在隐私政策", "实际收集", "未向用户明示")),
    ("RULE_4_2", ("拒绝", "无法使用", "不能使用", "拒绝服务", "业务功能被阻断")),
    ("RULE_4_4", ("超频次", "频繁", "后台状态", "后台收集", "高频")),
    ("RULE_4_1", ("与业务无关", "无关的权限", "非必要权限", "提前申请", "无实际业务")),
    ("RULE_2_2", ("申请", "权限", "未同步告知", "目的不明确", "未告知目的")),
    ("RULE_2_1", ("目的、方式和范围", "目的、方式、范围", "未逐一列出", "未明示收集使用")),
    ("RULE_1_2_NOTICE", ("首次运行", "显著方式提示", "未提示阅读")),
    ("RULE_1_1", ("无隐私政策", "未公开隐私政策", "隐私政策不存在")),
)


def _document_text(path: Path) -> str:
    document = Document(path)
    values = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    values.extend(
        " | ".join(cell.text.strip() for cell in row.cells)
        for table in document.tables for row in table.rows
    )
    return "\n".join(values)


def _infer_rule_ids(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", str(text or "")).lower()
    inferred: set[str] = set()
    for rule_id, terms in _RULE_PATTERNS:
        # Multi-signal rules need all key concepts; broad disclosure rules need
        # one exact phrase. This is a regression import, never adjudication.
        if rule_id == "RULE_2_2":
            if "权限" in compact and any(term in compact for term in ("未同步告知", "目的不明确", "未告知目的")):
                inferred.add(rule_id)
        elif rule_id == "RULE_4_2":
            if "拒绝" in compact and any(term in compact for term in ("无法使用", "不能使用", "拒绝服务", "业务功能被阻断")):
                inferred.add(rule_id)
        elif rule_id == "RULE_6_5":
            if any(term in compact for term in ("投诉", "举报")) and any(term in compact for term in ("处理时限", "承诺时限", "查处时限")):
                inferred.add(rule_id)
        elif any(re.sub(r"\s+", "", term).lower() in compact for term in terms):
            inferred.add(rule_id)
    return inferred


def _known_rule_ids(config_path: Path) -> set[str]:
    rules_path = config_path.parent / "rules" / "identification_method_rules.yaml"
    payload = yaml.safe_load(rules_path.read_text("utf-8")) or {}
    return {str(row.get("rule_id")) for row in payload.get("rules", []) if row.get("rule_id")}


class ManualBaselineCatalog:
    def __init__(self, rows: list[ManualBaselineRow], *, known_rule_ids: set[str]) -> None:
        self.rows = tuple(rows)
        self._by_package = {row.package_name: row for row in rows}
        self.unknown_rule_ids = {
            rule_id for row in rows for rule_id in row.expected_rule_ids
            if rule_id not in known_rule_ids
        }

    @classmethod
    def load(cls, config_path: Path, *, report_dir: Path) -> "ManualBaselineCatalog":
        config_path = Path(config_path)
        report_dir = Path(report_dir)
        payload = yaml.safe_load(config_path.read_text("utf-8")) or {}
        overrides = {
            str(package): {str(rule) for rule in rules}
            for package, rules in dict(payload.get("overrides") or {}).items()
        }
        timelines = dict(payload.get("timeline_paths") or {})
        rows: list[ManualBaselineRow] = []
        for raw in payload.get("reports") or []:
            report_name = str(raw.get("report") or "")
            package_name = str(raw.get("package_name") or "")
            path = report_dir / report_name
            if not path.is_file():
                raise FileNotFoundError(f"manual baseline report missing: {report_name}")
            inferred = overrides.get(package_name) or _infer_rule_ids(_document_text(path))
            if not inferred:
                raise ValueError(f"manual report has no inferred rule baseline: {report_name}")
            raw_paths = timelines.get(package_name) or []
            timeline_paths = tuple(
                tuple(tuple(str(event) for event in alternatives) for alternatives in path_rows)
                for path_rows in raw_paths
            )
            rows.append(ManualBaselineRow(
                report_name=report_name,
                package_name=package_name,
                expected_rule_ids=frozenset(inferred),
                expected_timeline_paths=timeline_paths,
            ))
        return cls(rows, known_rule_ids=_known_rule_ids(config_path))

    def accounted_report_names(self) -> set[str]:
        return {row.report_name for row in self.rows}

    def baseline_for_package(self, package_name: str) -> dict | None:
        row = self._by_package.get(str(package_name or ""))
        if row is None:
            return None
        app_name = row.report_name.split("-App", 1)[0]
        return {
            "name": f"{app_name}人工检测基准",
            "expected_rule_ids": set(row.expected_rule_ids),
            "expected_timeline_paths": [
                [tuple(alternatives) for alternatives in path]
                for path in row.expected_timeline_paths
            ],
            "source_report": row.report_name,
            "unresolved_statements": list(row.unresolved_statements),
        }


@lru_cache(maxsize=1)
def default_manual_baseline_catalog() -> ManualBaselineCatalog:
    project_root = Path(__file__).resolve().parents[2]
    return ManualBaselineCatalog.load(
        project_root / "agent/config/manual_baselines.yaml",
        report_dir=project_root / "app人工检测报告",
    )
