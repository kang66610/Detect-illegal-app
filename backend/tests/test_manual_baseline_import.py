from pathlib import Path

import pytest

from agent.rule_engine.manual_baseline import compare_manual_baseline
from agent.rule_engine.manual_baseline_import import ManualBaselineCatalog


ROOT = Path(__file__).resolve().parents[2]
BASELINE_CONFIG = ROOT / "agent/config/manual_baselines.yaml"
REPORT_DIR = ROOT / "app人工检测报告"

# 真实人工复核清单与客户报告只保留在本地（见 .gitignore）；干净 clone 里只有
# manual_baselines.example.yaml，此时跳过全量核对而不是报假失败。
requires_local_baselines = pytest.mark.skipif(
    not BASELINE_CONFIG.is_file() or not REPORT_DIR.is_dir(),
    reason="本地人工复核数据不在仓库中（客户信息），跳过全量核对",
)


@requires_local_baselines
def test_all_manual_reports_are_accounted_for_and_have_package_mapping():
    catalog = ManualBaselineCatalog.load(BASELINE_CONFIG, report_dir=REPORT_DIR)
    report_names = {path.name for path in REPORT_DIR.glob("*.docx")}

    assert catalog.accounted_report_names() == report_names
    assert all(row.package_name for row in catalog.rows)
    assert all(row.expected_rule_ids for row in catalog.rows)


@requires_local_baselines
def test_imported_rule_ids_are_known_to_rule_catalog():
    catalog = ManualBaselineCatalog.load(BASELINE_CONFIG, report_dir=REPORT_DIR)

    assert catalog.unknown_rule_ids == set()


def test_baseline_comparison_never_adds_a_finding():
    class Catalog:
        def baseline_for_package(self, _package):
            return {
                "name": "fixture", "expected_rule_ids": {"RULE_4_2"},
                "expected_timeline_paths": [],
            }

    result = compare_manual_baseline("pkg", set(), catalog=Catalog())

    assert result["false_negative"] == ["RULE_4_2"]
    assert result["detected"] == []
