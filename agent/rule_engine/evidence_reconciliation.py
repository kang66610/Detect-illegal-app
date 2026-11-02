"""Reconcile UI, document, Frida, network and screenshot evidence by finding."""
from __future__ import annotations

from collections import defaultdict


_POSITIVE_FLAGS = {
    "verified", "base_service_blocked", "purpose_context_verified",
    "policy_document_complete", "time_correlated",
}


def _finding_kinds(item: dict) -> set[str]:
    meta = item.get("meta") or {}
    return {
        str(meta.get("finding_kind") or ""),
        *(str(value) for value in meta.get("finding_kinds") or []),
    } - {""}


def reconcile_evidence(findings: list, evidence_files: list[dict], adjudication: list[dict]) -> list[dict]:
    """Return one immutable, cross-source case object per candidate finding."""
    artifacts: dict[str, list[dict]] = defaultdict(list)
    for item in evidence_files:
        for kind in _finding_kinds(item):
            artifacts[kind].append(item)
    decisions = {str(row.get("finding_kind") or ""): dict(row) for row in adjudication}
    cases: list[dict] = []
    for finding in findings:
        kind = str(finding.kind)
        scoped = artifacts.get(kind, [])
        sources = sorted({str((item.get("meta") or {}).get("source") or item.get("type") or "unknown") for item in scoped})
        polarity: dict[str, set[bool]] = defaultdict(set)
        for item in scoped:
            meta = item.get("meta") or {}
            for flag in _POSITIVE_FLAGS:
                if flag in meta and isinstance(meta.get(flag), bool):
                    polarity[flag].add(bool(meta[flag]))
        conflicts = sorted(flag for flag, values in polarity.items() if len(values) > 1)
        admission = decisions.get(kind, {})
        if conflicts:
            status = "conflict"
            next_action = "保留全部原始证据，并安排针对冲突字段的恢复/补证任务"
        elif admission.get("status") == "downgraded":
            status = "supplement_required"
            next_action = "按缺失证据清单补采，不删除已经观察到的动态或页面证据"
        else:
            status = "observed"
            next_action = "无需补证"
        cases.append({
            "finding_kind": kind,
            "status": status,
            "sources": sources,
            "artifact_count": len(scoped),
            "conflicts": conflicts,
            "missing": list(admission.get("missing") or []),
            "next_action": next_action,
        })
    return cases
