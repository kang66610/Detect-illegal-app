from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter

import yaml


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    package_name: str
    expected_rule_ids: set[str] = field(default_factory=set)
    forbidden_rule_ids: set[str] = field(default_factory=set)
    required_legal_keys: set[str] = field(default_factory=set)
    repeats: int = 3
    artifact_ref: str = ""
    execution_status: str = "executable"
    source_report: str = ""
    source_findings: tuple[str, ...] = ()

    @property
    def executable(self) -> bool:
        return self.execution_status == "executable"


def load_benchmark_cases(path: Path) -> list[BenchmarkCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [BenchmarkCase(
        case_id=str(item["case_id"]), package_name=str(item["package_name"]),
        expected_rule_ids=set(item.get("expected_rule_ids") or []),
        forbidden_rule_ids=set(item.get("forbidden_rule_ids") or []),
        required_legal_keys={str(key) for key in item.get("required_legal_keys") or []},
        repeats=max(1, int(item.get("repeats") or 3)), artifact_ref=str(item.get("artifact_ref") or ""),
        execution_status=str(item.get("execution_status") or "executable"),
        source_report=str(item.get("source_report") or ""),
        source_findings=tuple(str(value) for value in item.get("source_findings") or []),
    ) for item in raw.get("cases") or []]


def evaluate_case(case: BenchmarkCase, runs: list[dict]) -> dict:
    expected_total = len(case.expected_rule_ids) * len(runs)
    true_positive = sum(len(set(run.get("detected_rule_ids") or []) & case.expected_rule_ids) for run in runs)
    detected_total = sum(len(set(run.get("detected_rule_ids") or [])) for run in runs)
    forbidden_hits = sum(len(set(run.get("detected_rule_ids") or []) & case.forbidden_rule_ids) for run in runs)
    coverage_total = len(case.required_legal_keys) * len(runs)
    covered = sum(sum((run.get("adjudication") or {}).get(key) != "not_covered" for key in case.required_legal_keys) for run in runs)
    signatures = [tuple(sorted(run.get("detected_rule_ids") or [])) for run in runs]
    most_common = Counter(signatures).most_common(1)[0][1] if signatures else 0
    stability_rate = most_common / len(signatures) if signatures else 0.0
    return {
        "case_id": case.case_id, "runs": len(runs),
        "recall": true_positive / expected_total if expected_total else 1.0,
        "precision": true_positive / detected_total if detected_total else (1.0 if not case.expected_rule_ids else 0.0),
        "forbidden_hits": forbidden_hits, "stable": stability_rate == 1.0,
        "stability_rate": stability_rate,
        "required_coverage_rate": covered / coverage_total if coverage_total else 1.0,
        "missed_rule_ids": sorted(set().union(*(
            case.expected_rule_ids - set(run.get("detected_rule_ids") or []) for run in runs
        )) if runs else case.expected_rule_ids),
        "unexpected_rule_ids": sorted(set().union(*(
            set(run.get("detected_rule_ids") or []) - case.expected_rule_ids for run in runs
        )) if runs else set()),
    }


def evaluate_suite(cases: list[BenchmarkCase], run_results: dict[str, list[dict]]) -> dict:
    """Evaluate a persistent regression suite without hard-coding one App.

    ``run_results`` is deliberately an adapter boundary: CI, a real-device
    farm, or a manually captured run can provide the same compact evidence
    summary.  Cases without an APK artifact stay visible as labelled debt and
    do not fabricate executable results.
    """
    executable = [case for case in cases if case.executable]
    results = [evaluate_case(case, run_results.get(case.case_id, [])) for case in executable]
    regressions = [
        result["case_id"] for result in results
        if result["recall"] < 1.0 or result["forbidden_hits"] or not result["stable"]
    ]
    leave_one_out = leave_one_out_recalls(executable, run_results)
    return {
        "executable_cases": len(executable),
        "label_only_cases": len(cases) - len(executable),
        "results": results,
        "macro_recall": sum(result["recall"] for result in results) / len(results) if results else None,
        "macro_precision": sum(result["precision"] for result in results) / len(results) if results else None,
        "macro_required_coverage": sum(result["required_coverage_rate"] for result in results) / len(results) if results else None,
        "leave_one_out": leave_one_out,
        "minimum_held_out_recall": leave_one_out.get("minimum_held_out_recall"),
        "regressions": regressions,
    }


def leave_one_out_recalls(cases: list[BenchmarkCase], run_results: dict[str, list[dict]]) -> dict:
    """Hold out each executable App once and report its recall in isolation.

    Training folds are evaluated for visibility only; the gate cares about the
    minimum held-out recall so a single-App hard-coded patch cannot pass CI.
    """
    executable = [case for case in cases if case.executable]
    folds: list[dict] = []
    for held in executable:
        train = [case for case in executable if case.case_id != held.case_id]
        train_suite = evaluate_suite_without_loo(train, run_results)
        held_result = evaluate_case(held, run_results.get(held.case_id, []))
        folds.append({
            "held_out_case_id": held.case_id,
            "held_out_recall": held_result["recall"],
            "train_macro_recall": train_suite["macro_recall"],
            "train_executable_cases": train_suite["executable_cases"],
        })
    recalls = [fold["held_out_recall"] for fold in folds]
    return {
        "folds": folds,
        "minimum_held_out_recall": min(recalls) if recalls else None,
        "mean_held_out_recall": (sum(recalls) / len(recalls)) if recalls else None,
    }


def evaluate_suite_without_loo(cases: list[BenchmarkCase], run_results: dict[str, list[dict]]) -> dict:
    """Suite metrics without recursively computing leave-one-out folds."""
    executable = [case for case in cases if case.executable]
    results = [evaluate_case(case, run_results.get(case.case_id, [])) for case in executable]
    return {
        "executable_cases": len(executable),
        "label_only_cases": len(cases) - len(executable),
        "results": results,
        "macro_recall": sum(result["recall"] for result in results) / len(results) if results else None,
        "macro_precision": sum(result["precision"] for result in results) / len(results) if results else None,
        "macro_required_coverage": sum(result["required_coverage_rate"] for result in results) / len(results) if results else None,
        "regressions": [
            result["case_id"] for result in results
            if result["recall"] < 1.0 or result["forbidden_hits"] or not result["stable"]
        ],
    }
