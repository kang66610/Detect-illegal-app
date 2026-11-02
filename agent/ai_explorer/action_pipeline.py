"""Single immutable arbitration path for one Appium observation cycle."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent.ai_explorer.action_arbitration import ActionArbiter, ActionProposal
from agent.detection_engines.page_semantics import PageSemantics


_SOURCE_RANK = {
    "recovery": 600,
    "scenario": 500,
    "document": 400,
    "deterministic": 300,
    "dfs": 200,
    "llm": 100,
}


@dataclass(frozen=True)
class FinalAction:
    action: str
    target: str
    reason: str
    source: str
    scenario_items: tuple[str, ...] = ()
    rejected: tuple[ActionProposal, ...] = ()
    duplicate_sources: tuple[str, ...] = ()
    safety_reason: str | None = None
    token: str = ""

    def as_decision(self) -> dict:
        return {"action": self.action, "target": self.target, "reason": self.reason}


class ActionPipeline:
    """Choose exactly one action; callers execute the returned value unchanged."""

    def __init__(self, arbiter: ActionArbiter | None = None) -> None:
        self._arbiter = arbiter or ActionArbiter()

    @staticmethod
    def _rank(proposal: ActionProposal, position: int) -> tuple[int, int, int]:
        source_rank = _SOURCE_RANK.get(proposal.source, 250)
        return source_rank, int(proposal.priority), -position

    def choose(
        self,
        proposals: list[ActionProposal],
        *,
        semantics: PageSemantics,
        is_root: bool,
        safety_validator: Callable[[ActionProposal], ActionProposal | None] | None = None,
    ) -> FinalAction:
        if not proposals:
            proposals = [ActionProposal("wait", reason="没有可执行候选动作", source="arbiter")]

        unique: list[ActionProposal] = []
        duplicates: dict[tuple[str, str], list[str]] = {}
        indexes: dict[tuple[str, str], int] = {}
        for proposal in proposals:
            key = (proposal.action, proposal.target)
            if key not in indexes:
                indexes[key] = len(unique)
                unique.append(proposal)
                duplicates[key] = []
                continue
            current_index = indexes[key]
            current = unique[current_index]
            if self._rank(proposal, current_index) > self._rank(current, current_index):
                duplicates[key].append(current.source)
                unique[current_index] = proposal
            else:
                duplicates[key].append(proposal.source)

        winner_index, winner = max(
            enumerate(unique), key=lambda row: self._rank(row[1], row[0]),
        )
        safety = self._arbiter.arbitrate([winner], semantics=semantics, is_root=is_root)
        selected = safety.proposal
        extra_safety_reason = None
        if not safety.overridden and safety_validator is not None:
            replacement = safety_validator(selected)
            if replacement is not None:
                selected = replacement
                safety = type(safety)(
                    proposal=replacement, overridden=True, safety_reason=replacement.reason,
                )
                extra_safety_reason = replacement.reason
        if safety.overridden:
            rejected = tuple(unique)
            duplicate_sources: tuple[str, ...] = ()
        else:
            rejected = tuple(item for index, item in enumerate(unique) if index != winner_index)
            duplicate_sources = tuple(duplicates[(winner.action, winner.target)])
        return FinalAction(
            action=selected.action,
            target=selected.target,
            reason=selected.reason,
            source=selected.source,
            scenario_items=selected.scenario_items,
            rejected=rejected,
            duplicate_sources=duplicate_sources,
            safety_reason=extra_safety_reason or safety.safety_reason,
            token=selected.token,
        )
