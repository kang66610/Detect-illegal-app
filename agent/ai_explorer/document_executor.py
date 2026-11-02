"""Document-only execution transitions built on the shared reading ledger."""
from __future__ import annotations

from dataclasses import dataclass

from agent.ai_explorer.document_flow import (
    DocumentFlowInput, DocumentFlowPolicy, DocumentFlowStep,
)
from agent.ai_explorer.document_session import DocumentReadingLedger


@dataclass(frozen=True)
class DocumentExecutionResult:
    step: DocumentFlowStep
    completed: bool = False
    attempt: int = 0
    scrolls: int = 0


class DocumentExecutor:
    def __init__(self, policy: DocumentFlowPolicy, ledger: DocumentReadingLedger) -> None:
        self.policy = policy
        self.ledger = ledger

    def observe_blank(self, key: str, *, blank_retry_limit: int = 3) -> DocumentExecutionResult:
        """Route a blank-body observation through the shared flow policy."""
        directive = self.policy.decide(DocumentFlowInput(
            key=key, body_blank=True, blank_retry_limit=blank_retry_limit,
        ), self.ledger)
        return DocumentExecutionResult(
            step=directive.step, completed=False, attempt=directive.attempt,
        )

    def observe_scroll(
        self, key: str, *, status: str, viewport_fingerprint: str = "",
        stuck_retry_limit: int = 3, bottom_confirmations: int = 2,
    ) -> DocumentExecutionResult:
        directive = self.policy.decide(DocumentFlowInput(
            key=key, scroll_status=status, viewport_fingerprint=viewport_fingerprint,
            stuck_retry_limit=stuck_retry_limit, bottom_confirmations=bottom_confirmations,
        ), self.ledger)
        completed = directive.step is DocumentFlowStep.COMPLETE_AND_BACK
        if completed:
            self.ledger.finish(key, bottom_confirmed=True)
        return DocumentExecutionResult(
            step=directive.step, completed=completed,
            attempt=directive.attempt, scrolls=directive.scrolls,
        )
