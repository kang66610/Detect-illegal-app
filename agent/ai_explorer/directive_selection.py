"""Collect directive proposals while keeping legacy branch state preview local."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agent.ai_explorer.directive_preview import DirectivePreviewState


@dataclass
class DirectiveSelectionSession:
    runtime: dict
    applier: object
    preview: DirectivePreviewState = field(init=False)
    proposals: list = field(default_factory=list)
    _on_selected: dict[str, Callable[[tuple[str, ...]], None]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.preview = DirectivePreviewState(self.runtime)

    def add(self, directive, *, on_selected: Callable[[tuple[str, ...]], None] | None = None):
        """Register a directive as a side-effect-free candidate.

        ``on_selected`` receives the committed effects tuple only when the
        pipeline finally selects this directive's token; a replaced or
        rejected candidate never runs it.
        """
        proposal = self.applier.to_proposal(directive)
        self.preview.preview(directive)
        self.proposals.append(proposal)
        if on_selected is not None:
            self._on_selected[proposal.token] = on_selected
        return proposal

    def commit_token(self, token: str, *, activity: str):
        """Commit one directive immediately (legacy continue/no-action timing)."""
        on_selected = self._on_selected.pop(str(token or ""), None)
        committed = self.applier.commit_selected(token, activity=activity)
        if on_selected is not None:
            on_selected(committed[2])
        return committed

    def commit(self, final_action, *, activity: str):
        """Commit only the directive whose action still survives later guards."""
        token = str(getattr(final_action, "token", "") or "")
        proposal = next((item for item in self.proposals if item.token == token), None)
        if proposal is not None:
            survives = (
                proposal.action == getattr(final_action, "action", "")
                and proposal.target == getattr(final_action, "target", "")
                and proposal.source == getattr(final_action, "source", "")
            )
            if survives:
                return self.commit_token(token, activity=activity)
            self._on_selected.pop(token, None)
            self.applier.drop_pending(token)
        return final_action.as_decision(), final_action.source, ()

    def discard(self) -> None:
        """Drop unselected proposals and preview state for this page cycle."""
        self.preview.discard()
        for proposal in self.proposals:
            self.applier.drop_pending(proposal.token)
        self.proposals.clear()
        self._on_selected.clear()
