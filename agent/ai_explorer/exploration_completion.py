"""Truthful completion gate for one Appium exploration run."""
from __future__ import annotations

from dataclasses import dataclass


_TERMINAL_SCENARIO_STATES = {
    "evidence_observed", "not_applicable", "requires_server_audit",
}
_BLOCKED_SCENARIO_STATES = {"blocked_external", "requires_login"}


@dataclass(frozen=True)
class CompletionAssessment:
    termination: dict
    coverage_complete: bool
    gaps: list[str]
    unfinished_items: list[str]


class ExplorationCompletionGate:
    """Prevent local no-progress exits from masquerading as run completion."""

    def assess(
        self,
        *,
        proposed_termination: dict | None,
        scenario_snapshot: dict,
        coverage_gaps: list[str],
        active_document: bool = False,
        active_permission_probe: bool = False,
        pending_action_validation: bool = False,
        navigation_frontier_exhausted: bool = False,
        total_budget_exhausted: bool = False,
    ) -> CompletionAssessment:
        rows = [dict(row) for row in scenario_snapshot.get("items") or []]
        unfinished = [
            str(row.get("item")) for row in rows
            if str(row.get("state") or "pending") not in _TERMINAL_SCENARIO_STATES
        ]
        blocked = [
            str(row.get("item")) for row in rows
            if str(row.get("state") or "") in _BLOCKED_SCENARIO_STATES
        ]
        gaps = list(dict.fromkeys(str(gap) for gap in coverage_gaps if gap))
        for item in blocked:
            gap = f"场景 {item} 受外部条件限制，未执行完成"
            if gap not in gaps:
                gaps.append(gap)
        active_reasons = []
        if active_document:
            active_reasons.append("文档阅读会话尚未完成")
        if active_permission_probe:
            active_reasons.append("权限拒绝业务探针尚未形成终态")
        if pending_action_validation:
            active_reasons.append("最后一次动作效果尚未验证")
        if total_budget_exhausted:
            active_reasons.append("总时间预算已耗尽，未完成场景保留为覆盖缺口")
        gaps.extend(reason for reason in active_reasons if reason not in gaps)

        termination = dict(proposed_termination or {})
        kind = str(termination.get("kind") or "safe_frontier_exhausted")
        safe_claim = kind == "safe_frontier_exhausted"
        # Navigation exhaustion and rule coverage are deliberately different truths.
        # A traversal may have exhausted every safe UI edge while some legal
        # scenarios remain unavailable (for example, no login account).  In that
        # case the traversal termination is truthful, but coverage_complete must
        # remain false and the unfinished scenarios stay visible in the report.
        truly_exhausted = navigation_frontier_exhausted and not active_reasons
        if safe_claim and not truly_exhausted:
            termination = {
                "kind": "frontier_incomplete",
                "reason": "当前路径无进展，但仍有未完成场景或待验证状态",
                "remaining_items": unfinished,
            }
        coverage_complete = not gaps and not unfinished and not active_reasons
        return CompletionAssessment(termination, coverage_complete, gaps, unfinished)
