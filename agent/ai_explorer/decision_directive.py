"""Common interface returned by deterministic exploration decision modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agent.ai_explorer.action_arbitration import ActionProposal


@dataclass(frozen=True)
class DecisionDirective:
    """One final deterministic proposal plus its auditable state changes."""

    action: str
    target: str
    reason: str
    source: str
    event_type: str = ""
    event_meta: dict = field(default_factory=dict)
    runtime_updates: dict = field(default_factory=dict)
    runtime_increments: dict = field(default_factory=dict)
    completed_scenarios: tuple[str, ...] = ()
    completion_source: str = ""
    effects: tuple[str, ...] = ()
    priority: int = 0

    def decision(self) -> dict:
        return {"action": self.action, "target": self.target, "reason": self.reason}


class DecisionDirectiveApplier:
    """Apply directive bookkeeping once so decision modules cannot diverge."""

    def __init__(
        self, *, runtime: dict, emit: Callable[..., None],
        mark_completed: Callable[..., None],
    ) -> None:
        self.runtime = runtime
        self.emit = emit
        self.mark_completed = mark_completed
        self._pending: dict[str, DecisionDirective] = {}
        self._next_token = 0

    def to_proposal(self, directive: DecisionDirective) -> ActionProposal:
        """Convert deterministically without applying any directive side effect."""
        self._next_token += 1
        token = f"directive-{self._next_token}"
        self._pending[token] = directive
        return ActionProposal(
            action=directive.action, target=directive.target, reason=directive.reason,
            source=directive.source, priority=directive.priority, token=token,
        )

    def commit_selected(self, token: str, *, activity: str) -> tuple[dict, str, tuple[str, ...]]:
        directive = self._pending.pop(str(token or ""), None)
        if directive is None:
            raise KeyError(f"unknown directive token: {token}")
        return self._commit(directive, activity=activity)

    def drop_pending(self, token: str) -> None:
        """Forget an uncommitted proposal; replaced candidates leave no trace."""
        self._pending.pop(str(token or ""), None)

    def _commit(self, directive: DecisionDirective, *, activity: str) -> tuple[dict, str, tuple[str, ...]]:
        """Apply the legacy side effects only after a directive was selected."""
        for key, value in directive.runtime_updates.items():
            self.runtime[key] = value
        for key, amount in directive.runtime_increments.items():
            self.runtime[key] = int(self.runtime.get(key, 0)) + int(amount)
        if directive.completed_scenarios:
            self.mark_completed(
                list(directive.completed_scenarios),
                evidence_source=directive.completion_source or directive.source,
            )
        if directive.event_type:
            meta = {"activity": activity}
            if directive.target:
                meta["target"] = directive.target
            meta.update(directive.event_meta)
            meta.setdefault("reason", directive.reason)
            if "consent_button_retries" in directive.runtime_increments:
                meta["attempt"] = int(self.runtime.get("consent_button_retries", 0))
            self.emit(directive.event_type, **meta)
        return directive.decision(), directive.source, directive.effects
