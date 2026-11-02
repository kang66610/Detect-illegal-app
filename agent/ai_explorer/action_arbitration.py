"""Final Action arbitration with non-overridable safety constraints."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent.detection_engines.page_semantics import PageRole, PageSemantics


@dataclass(frozen=True)
class ActionProposal:
    action: str
    target: str = ""
    reason: str = ""
    source: str = "unknown"
    priority: int = 0
    reversible: bool = True
    scenario_items: tuple[str, ...] = ()
    token: str = ""

    @classmethod
    def from_decision(cls, decision: dict, *, source: str, priority: int = 0) -> "ActionProposal":
        return cls(
            action=str(decision.get("action") or "wait"),
            target=str(decision.get("target") or ""),
            reason=str(decision.get("reason") or ""),
            source=str(source or "unknown"),
            priority=int(priority),
        )

    def as_decision(self) -> dict:
        return {"action": self.action, "target": self.target, "reason": self.reason}


@dataclass(frozen=True)
class ArbitrationResult:
    proposal: ActionProposal
    overridden: bool = False
    safety_reason: str | None = None


class ActionArbiter:
    """Choose one proposal; safety filtering happens before priority ranking."""

    def arbitrate(
        self,
        proposals: list[ActionProposal],
        *,
        semantics: PageSemantics,
        is_root: bool,
    ) -> ArbitrationResult:
        if not proposals:
            return ArbitrationResult(ActionProposal("wait", reason="没有可执行候选动作", source="arbiter"))
        winner = sorted(enumerate(proposals), key=lambda row: (-row[1].priority, row[0]))[0][1]
        replacement = self._safety_replacement(winner, semantics=semantics, is_root=is_root)
        if replacement is None:
            return ArbitrationResult(winner)
        return ArbitrationResult(replacement, overridden=True, safety_reason=replacement.reason)

    @staticmethod
    def _safety_replacement(
        proposal: ActionProposal, *, semantics: PageSemantics, is_root: bool,
    ) -> ActionProposal | None:
        external_exit_roles = {
            PageRole.SYSTEM_OVERLAY, PageRole.SYSTEM_SETTINGS, PageRole.SYSTEM_CAMERA, PageRole.FOREIGN_APP,
        }
        if semantics.role in external_exit_roles and proposal.action not in {"back", "stop"}:
            return ActionProposal(
                "back", reason=f"{semantics.role.value} 只验证到达，不在外部/系统页面继续深度点击",
                source="safety_scope_exit", priority=10_000,
            )
        if semantics.role is PageRole.SYSTEM_LAUNCHER and proposal.action not in {"stop", "wait"}:
            return ActionProposal(
                "wait", reason="系统桌面由恢复流程重新拉起被测应用，不执行普通页面动作",
                source="safety_scope_exit", priority=10_000,
            )
        if semantics.role is PageRole.LOW_VALUE and proposal.action == "click":
            return ActionProposal(
                "stop" if is_root else "back",
                reason="低审计价值页面只观察一次并离开",
                source="safety_low_value_exit", priority=10_000,
            )
        return None


@dataclass(frozen=True)
class DecisionAudit:
    """Final attribution for a proposal after deterministic rewrites and safety."""

    record: dict
    source: str
    proposal_changed: bool

    @classmethod
    def finalize(
        cls,
        *,
        activity: str,
        decision: dict,
        decision_source: str,
        proposed: dict | None = None,
        proposal_source: str | None = None,
        context: dict | None = None,
    ) -> "DecisionAudit":
        source = str(decision_source or "unknown")
        changed = bool(proposed) and (
            proposed.get("action") != decision.get("action")
            or str(proposed.get("target") or "") != str(decision.get("target") or "")
        )
        if changed and source == str(proposal_source or ""):
            source = "deterministic_override"
        record = {
            "time": datetime.utcnow().isoformat(),
            "activity": activity,
            "decision_source": source,
            **decision,
        }
        if context:
            # Context is decided before proposals are solicited; action
            # sources may not overwrite role/layer attribution afterwards.
            record.update({
                str(key): value for key, value in context.items()
                if str(key) not in {"action", "target", "reason", "decision_source"}
            })
        if proposed:
            record.update({
                "proposed_by": proposal_source,
                "final_by": source,
                "llm_proposed_action": proposed.get("action"),
                "llm_proposed_target": proposed.get("target"),
                "llm_proposed_reason": str(proposed.get("reason") or "")[:300],
            })
        return cls(record=record, source=source, proposal_changed=changed)
