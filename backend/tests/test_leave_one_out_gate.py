from pathlib import Path

from agent.evaluation.benchmark_suite import BenchmarkCase, evaluate_suite, leave_one_out_recalls


def test_leave_one_out_reports_held_out_recall():
    cases = [
        BenchmarkCase(case_id="a", package_name="com.a", expected_rule_ids={"RULE_1"}),
        BenchmarkCase(case_id="b", package_name="com.b", expected_rule_ids={"RULE_2"}),
    ]
    runs = {
        "a": [{"detected_rule_ids": ["RULE_1"]}],
        "b": [{"detected_rule_ids": []}],
    }
    loo = leave_one_out_recalls(cases, runs)
    assert loo["minimum_held_out_recall"] == 0.0
    assert {fold["held_out_case_id"] for fold in loo["folds"]} == {"a", "b"}

    suite = evaluate_suite(cases, runs)
    assert suite["minimum_held_out_recall"] == 0.0
    assert suite["macro_recall"] == 0.5


def test_detector_modules_do_not_hardcode_benchmark_packages():
    """Package names belong in baselines/benchmarks/tests, not detector logic."""
    forbidden = (
        "com.example.reader",
        "com.example.travel",
        "com.example.socialsecurity",
    )
    roots = [
        Path("agent/detection_engines"),
        Path("agent/ai_explorer"),
        Path("agent/rule_engine"),
    ]
    allow_names = {"manual_baseline.py"}
    offenders: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if path.name in allow_names:
                continue
            text = path.read_text(encoding="utf-8")
            for package in forbidden:
                if package in text:
                    offenders.append(f"{path.as_posix()}: {package}")
    assert offenders == []
