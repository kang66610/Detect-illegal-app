"""Stable, reportable quality metrics for one automatic detection run."""
from __future__ import annotations


def _has_scoped_evidence(match, evidence_files: list[dict]) -> bool:
    allowed = set(match.rule.evidence_fields)
    for evidence in evidence_files:
        if evidence.get("type") not in allowed:
            continue
        meta = evidence.get("meta") or {}
        kinds = {str(meta.get("finding_kind") or ""), *(str(item) for item in meta.get("finding_kinds") or [])}
        if match.finding.kind in kinds:
            return True
    return False


def build_quality_metrics(matched, evidence_files: list[dict], runtime: dict, baseline: dict | None = None) -> dict:
    total = len(matched)
    evidence_complete = sum(_has_scoped_evidence(match, evidence_files) for match in matched)
    scenarios = runtime.get("scenario_coverage") or {}
    planned = int(scenarios.get("planned") or 0)
    attempted = int(scenarios.get("attempted") or 0)
    ledger = next((item.get("meta") or {} for item in evidence_files if item.get("type") == "behavior_ledger"), {})
    return {
        "evidence_chain_completeness": evidence_complete / total if total else None,
        "evidence_bound_findings": evidence_complete,
        "finding_count": total,
        "scenario_attempt_rate": attempted / planned if planned else None,
        "scenarios_planned": planned,
        "scenarios_attempted": attempted,
        "scenarios_remaining": int(scenarios.get("remaining") or 0),
        "dynamic_events": int(ledger.get("event_count") or 0),
        "time_correlated_events": int(ledger.get("correlated_count") or 0),
        "manual_baseline_recall": baseline.get("recall") if baseline else None,
        "manual_baseline_false_negatives": list(baseline.get("false_negative") or []) if baseline else [],
        "evidence_candidates": len(runtime.get("evidence_chain_adjudication") or []),
        "evidence_candidates_downgraded": sum(
            row.get("status") == "downgraded" for row in (runtime.get("evidence_chain_adjudication") or [])
        ),
    }
