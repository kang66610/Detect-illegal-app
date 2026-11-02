"""Deterministic permission-rationale and media-source decisions."""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.ai_explorer.action_executor import ActionExecutionResult
from agent.ai_explorer.decision_directive import DecisionDirective


@dataclass(frozen=True)
class PermissionDecisionInput:
    rationale_target: str = ""
    rationale_decision: dict | None = None
    capture_target: str = ""
    album_target: str = ""
    prior_capture_target: str = ""
    prior_capture_visited: bool = False
    consent_dialog: bool = False
    launch_gate: bool = False
    permission_scenarios_pending: bool = False
    media_family: str = ""


@dataclass(frozen=True)
class PermissionActionResult:
    rationale_continued: bool = False
    media_probe_executed: bool = False
    business_trigger_record: dict = field(default_factory=dict)


class PermissionDecisionModule:
    """Own the ordering rationale → camera → album for a Permission probe."""

    def observe_action_result(
        self, result: ActionExecutionResult, *, rationale_source: bool = False,
        media_source: bool = False, business_action: bool = False,
        business_target: str = "", activity: str = "", sequence: int = 0,
    ) -> PermissionActionResult:
        """Consume one executed action and derive the permission-domain view.

        The business trigger record feeds the denial probe binding; the
        rationale/media flags only confirm which probe path executed.
        """
        executed = result.succeeded and result.action == "click"
        record = {}
        if executed and business_action and business_target:
            record = {
                "action": result.action,
                "target": business_target,
                "is_business_action": True,
                "activity": activity,
                "sequence": sequence,
            }
        return PermissionActionResult(
            rationale_continued=bool(executed and rationale_source),
            media_probe_executed=bool(executed and media_source),
            business_trigger_record=record,
        )

    def propose(self, facts: PermissionDecisionInput) -> DecisionDirective | None:
        if facts.rationale_target and facts.rationale_decision and not facts.consent_dialog:
            proposal = facts.rationale_decision
            return DecisionDirective(
                str(proposal.get("action") or "click"), facts.rationale_target,
                str(proposal.get("reason") or "继续应用内权限说明"),
                "deterministic_permission_rationale",
                "in_app_permission_rationale_continued",
                {"action": proposal.get("action"), "reason": proposal.get("reason")},
                effects=("remember_permission_rationale",),
            )
        chooser_allowed = (
            facts.permission_scenarios_pending and not facts.consent_dialog and not facts.launch_gate
        )
        if chooser_allowed and facts.capture_target:
            return DecisionDirective(
                "click", facts.capture_target,
                "媒体来源选择页优先拍照，核验权限申请是否同步告知目的",
                "deterministic_media_capture", "media_capture_chooser_prioritized",
                {"media_family": facts.media_family}, effects=("revoke_media_permissions",),
            )
        if chooser_allowed and facts.album_target and (
            not facts.prior_capture_target or facts.prior_capture_visited
        ):
            return DecisionDirective(
                "click", facts.album_target,
                "拍照路径已尝试或不可用，改走相册核验存储权限与拒权后果",
                "deterministic_media_album", "media_album_chooser_prioritized",
                {"media_family": facts.media_family}, effects=("revoke_media_permissions",),
            )
        return None

