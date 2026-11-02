from pathlib import Path

from agent.evaluation.benchmark_suite import BenchmarkCase, evaluate_case, evaluate_suite, load_benchmark_cases


def test_benchmark_reports_precision_recall_and_tristate_coverage():
    case = BenchmarkCase(
        case_id="known-positive", package_name="com.demo", expected_rule_ids={"RULE_2_2", "RULE_3_1"},
        forbidden_rule_ids={"RULE_6_3"}, required_legal_keys={"2.3", "3.1"}, repeats=3,
    )

    result = evaluate_case(case, [
        {"detected_rule_ids": ["RULE_2_2"], "adjudication": {"2.3": "violation", "3.1": "not_covered"}},
        {"detected_rule_ids": ["RULE_2_2", "RULE_3_1"], "adjudication": {"2.3": "violation", "3.1": "violation"}},
        {"detected_rule_ids": ["RULE_2_2", "RULE_3_1"], "adjudication": {"2.3": "violation", "3.1": "violation"}},
    ])

    assert result["recall"] == 5 / 6
    assert result["precision"] == 1.0
    assert result["forbidden_hits"] == 0
    assert result["stable"] is False
    assert result["stability_rate"] == 2 / 3
    assert result["required_coverage_rate"] == 5 / 6


def test_benchmark_manifest_distinguishes_executable_and_label_only(tmp_path: Path):
    manifest = tmp_path / "benchmarks.yaml"
    manifest.write_text("""
cases:
  - case_id: executable
    package_name: com.example.one
    artifact_ref: apk-library://sha256/one
    execution_status: executable
    expected_rule_ids: [RULE_3_1]
    source_findings: [同意前收集信息]
  - case_id: labels-only
    package_name: ""
    execution_status: artifact_missing
    source_report: 人工报告.docx
""", encoding="utf-8")

    cases = load_benchmark_cases(manifest)

    assert cases[0].executable is True
    assert cases[0].source_findings == ("同意前收集信息",)
    assert cases[1].executable is False


def test_benchmark_suite_keeps_missing_artifacts_visible_without_running_them():
    executable = BenchmarkCase(case_id="run", package_name="com.demo", expected_rule_ids={"RULE_2_2"})
    label_only = BenchmarkCase(case_id="debt", package_name="", execution_status="artifact_missing")

    result = evaluate_suite([executable, label_only], {"run": [{"detected_rule_ids": ["RULE_2_2"]}]})

    assert result["executable_cases"] == 1
    assert result["label_only_cases"] == 1
    assert result["macro_recall"] == 1.0
    assert result["regressions"] == []


def test_repository_benchmark_example_keeps_fourth_article_rule_ids():
    """仓库提交的是脱敏示例清单；真实客户清单只保留在本地。"""
    manifest = Path(__file__).resolve().parents[2] / "benchmarks" / "privacy_benchmark.example.yaml"
    cases = list(load_benchmark_cases(manifest))

    assert cases, "示例基准清单不应为空"
    flat = set().union(*(case.expected_rule_ids for case in cases))
    assert "RULE_4_2" in flat
    assert "RULE_4_4" in flat
    # 4.3 属"新功能扩大收集范围"，只能靠服务端/人工核验，不得进入自动基准
    assert all("RULE_4_3" not in case.expected_rule_ids for case in cases)
