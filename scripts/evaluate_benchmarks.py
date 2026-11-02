"""Evaluate exported benchmark run JSON files against the versioned quality gate."""
import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.evaluation.benchmark_suite import (
    DEFAULT_MIN_EXECUTABLE_CASES,
    evaluate_case,
    evaluate_suite,
    load_benchmark_cases,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="benchmarks/privacy_benchmark.yaml")
    parser.add_argument("--results", required=True, help="每个 case_id 目录中放置一次运行一个 JSON")
    parser.add_argument("--output", default="data/benchmark-summary.json")
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    gate = raw.get("quality_gate") or {}
    summaries, failures, skipped, evaluated_cases, run_results = [], [], [], [], {}
    for case in load_benchmark_cases(manifest_path):
        if not case.executable:
            skipped.append({
                "case_id": case.case_id,
                "execution_status": case.execution_status,
                "reason": "人工标签已入库，但缺少可重复执行的隔离 APK 制品",
            })
            continue
        files = sorted((Path(args.results) / case.case_id).glob("*.json"))
        runs = [json.loads(path.read_text(encoding="utf-8")) for path in files]
        if len(runs) < case.repeats:
            failures.append(f"{case.case_id}: 仅有 {len(runs)}/{case.repeats} 次运行")
            continue
        synthetic = [path.name for path, run in zip(files, runs) if run.get("source") != "real_task"]
        if synthetic:
            failures.append(
                f"{case.case_id}: 运行结果不是真实任务导出（缺少 source=real_task）：{', '.join(synthetic)}"
            )
            continue
        summary = evaluate_case(case, runs[:case.repeats]); summaries.append(summary)
        evaluated_cases.append(case); run_results[case.case_id] = runs[:case.repeats]
        if summary["recall"] < float(gate.get("minimum_recall", 0)):
            failures.append(f"{case.case_id}: recall={summary['recall']:.3f}")
        if summary["forbidden_hits"] > int(gate.get("maximum_forbidden_hits", 0)):
            failures.append(f"{case.case_id}: forbidden_hits={summary['forbidden_hits']}")
        if summary["stability_rate"] < float(gate.get("minimum_stability", 1.0)):
            failures.append(f"{case.case_id}: stability={summary['stability_rate']:.3f}")
        if summary["required_coverage_rate"] < float(gate.get("minimum_required_coverage", 0)):
            failures.append(f"{case.case_id}: required_coverage={summary['required_coverage_rate']:.3f}")
        if summary["precision"] < float(gate.get("minimum_precision", 0)):
            failures.append(f"{case.case_id}: precision={summary['precision']:.3f}")
    suite = evaluate_suite(
        evaluated_cases, run_results,
        minimum_executable_cases=int(
            gate.get("minimum_executable_cases", DEFAULT_MIN_EXECUTABLE_CASES)
        ),
    )
    if suite.get("macro_recall") is not None and suite["macro_recall"] < float(gate.get("minimum_macro_recall", 0)):
        failures.append(f"suite: macro_recall={suite['macro_recall']:.3f}")
    held_out = suite.get("minimum_held_out_recall")
    if held_out is not None and held_out < float(gate.get("minimum_held_out_recall", 0)):
        failures.append(f"suite: minimum_held_out_recall={held_out:.3f}")

    adequacy = suite.get("sample_adequacy") or {}
    if failures:
        verdict = "regression_detected"
    elif adequacy.get("adequate"):
        verdict = "passed"
    else:
        # 没发现退化 ≠ 质量达标：样本太少时只能说“没退步”。
        verdict = "insufficient_sample"
    conclusive = verdict in {"passed", "regression_detected"}

    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "cases": summaries, "suite": suite, "skipped": skipped, "failures": failures,
        "gate_passed": not failures,
        "verdict": verdict,
        "conclusive": conclusive,
        "sample_note": adequacy.get("note", ""),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if verdict == "insufficient_sample":
        print(f"[样本不足] {adequacy.get('note', '')}", file=sys.stderr)
        print("本次结果只证明“未发现退化”，不能作为质量达标结论对外引用。", file=sys.stderr)
    elif verdict == "regression_detected":
        print(f"[门禁未通过] {len(failures)} 项：{'；'.join(failures[:5])}", file=sys.stderr)
    else:
        print(f"[门禁通过] {adequacy.get('note', '')}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
