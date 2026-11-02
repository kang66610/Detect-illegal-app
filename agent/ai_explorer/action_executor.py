"""Execute one frozen action without reinterpreting page semantics."""
from __future__ import annotations

import time
from dataclasses import dataclass

from agent.common.exceptions import ExplorationError


@dataclass(frozen=True)
class ActionExecutionResult:
    action: str
    target: str
    succeeded: bool
    error: str = ""
    elapsed_seconds: float = 0.0


class ActionExecutor:
    def __init__(self, client, *, clock=time.monotonic) -> None:
        self.client = client
        self.clock = clock

    def execute(self, final_action) -> ActionExecutionResult:
        return self.execute_decision(final_action.as_decision())

    def execute_decision(self, decision: dict) -> ActionExecutionResult:
        started = self.clock()
        action = str(decision.get("action") or "")
        target = str(decision.get("target") or "")
        try:
            self.client.perform(decision)
        except ExplorationError as exc:
            return ActionExecutionResult(
                action=action, target=target,
                succeeded=False, error=str(exc), elapsed_seconds=self.clock() - started,
            )
        return ActionExecutionResult(
            action=action, target=target,
            succeeded=True, elapsed_seconds=self.clock() - started,
        )

    def perform_or_raise(self, decision: dict) -> ActionExecutionResult:
        result = self.execute_decision(decision)
        if not result.succeeded:
            raise ExplorationError(result.error)
        return result

    def execute_and_record(self, final_action, *, page, state, commit_target: bool = False) -> ActionExecutionResult:
        """Commit generic navigation only after the frozen action succeeds."""
        result = self.execute(final_action)
        if not result.succeeded:
            return result
        if result.action == "click" and commit_target and result.target:
            state.commit_target(page, result.target)
        state.record_action(page, result.action)
        return result
