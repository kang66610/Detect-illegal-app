"""One tri-state adjudication contract for all 31 recognition items."""
from __future__ import annotations

from agent.rule_engine.recognition_contract import RULE_LEGAL_KEYS
from agent.rule_engine.recognition_coverage import RECOGNITION_ITEMS


def build_adjudication_matrix(
    matched, runtime: dict, review_states: dict | None = None, *, attempted_as_covered: bool = False,
) -> list[dict]:
    """Build the tri-state matrix for all 31 recognition items.

    ``attempted_as_covered`` lowers the coverage bar: a device scenario that
    was actually attempted (a visible, safe target was selected and explored)
    but produced no violation evidence is reported as ``no_violation_evidence``
    instead of ``not_covered``.  Blocked, login-gated and server-only items
    always remain ``not_covered`` — an unexecuted scenario is never reported
    as checked.
    """
    violated = {
        legal_key
        for match in matched
        for legal_key in RULE_LEGAL_KEYS.get(match.rule.rule_id, set())
    }
    completed = set(runtime.get("scenario_completed_items") or [])
    queue_rows = {
        str(row.get("item")): row
        for row in (runtime.get("scenario_coverage") or {}).get("items") or []
    }
    reviews = review_states or {}
    rows = []
    for item in RECOGNITION_ITEMS:
        state, reason = "not_covered", "本次未取得足以判定该条款的证据"
        if item.key in violated:
            state, reason = "violation", "自动规则已形成完整证据链"
        elif reviews.get(item.key) == "violation":
            state, reason = "violation", "人工或服务端核验已确认"
        elif reviews.get(item.key) in {"no_evidence_found", "not_applicable"}:
            state, reason = "no_violation_evidence", "人工或服务端核验未形成违规证据"
        elif item.key in queue_rows and str((queue_rows[item.key] or {}).get("state") or "") == "requires_server_audit":
            # Server-only items start terminal in the scenario queue; do not
            # present them as a stuck device-side ``pending``.
            state, reason = "not_covered", "该条款需服务端审计，设备侧已标明待服务端处理（非遍历遗漏）"
        elif item.evidence_scope == "device" and item.key in completed:
            state, reason = "no_violation_evidence", "对应自动场景已执行，但未形成违规证据"
        elif item.evidence_scope == "device" and item.key in queue_rows:
            queue_row = queue_rows[item.key]
            queue_state = str(queue_row.get("state") or "pending")
            if queue_state == "evidence_observed":
                state, reason = "no_violation_evidence", "对应自动场景已执行，但未形成违规证据"
            elif queue_state == "attempted" and attempted_as_covered:
                state, reason = "no_violation_evidence", "对应自动场景已尝试执行，但未形成违规证据"
            elif queue_state != "pending":
                reason = str(queue_row.get("reason") or "对应自动场景尚未形成可判定证据")
        rows.append({
            "legal_key": item.key, "title": item.title, "category": item.category,
            "evidence_scope": item.evidence_scope, "state": state, "reason": reason,
            "scenario_state": (queue_rows.get(item.key) or {}).get("state"),
            "execution_status": (
                "executed" if state in {"violation", "no_violation_evidence"} else "not_executed"
            ),
        })
    return rows


def adjudication_counts(rows: list[dict]) -> dict:
    return {state: sum(row["state"] == state for row in rows) for state in (
        "violation", "no_violation_evidence", "not_covered",
    )}
