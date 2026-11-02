"""Pure document-reading transitions used by Appium document executors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent.ai_explorer.document_session import (
    DocumentReadingLedger,
    DocumentScrollDirective,
)


class DocumentFlowStep(str, Enum):
    NONE = "none"
    ALREADY_COMPLETE_AND_BACK = "already_complete_and_back"
    WAIT_BODY = "wait_body"
    MARK_UNAVAILABLE = "mark_unavailable"
    CONTINUE_SCROLL = "continue_scroll"
    RETRY_STUCK = "retry_stuck"
    RETRY_BOTTOM = "retry_bottom"
    COMPLETE_AND_BACK = "complete_and_back"
    MARK_INCOMPLETE_AND_BACK = "mark_incomplete_and_back"


@dataclass(frozen=True)
class DocumentFlowInput:
    key: str
    body_blank: bool = False
    scroll_status: str = ""
    viewport_fingerprint: str = ""
    blank_retry_limit: int = 3
    stuck_retry_limit: int = 3
    bottom_confirmations: int = 2


@dataclass(frozen=True)
class DocumentFlowDirective:
    step: DocumentFlowStep
    attempt: int = 0
    scrolls: int = 0


class DocumentFlowPolicy:
    """Translate document observations into driver-independent transitions."""

    def decide(
        self, facts: DocumentFlowInput, ledger: DocumentReadingLedger,
    ) -> DocumentFlowDirective:
        key = str(facts.key or "")
        if not key:
            return DocumentFlowDirective(DocumentFlowStep.NONE)
        if key in ledger.completed_keys():
            return DocumentFlowDirective(DocumentFlowStep.ALREADY_COMPLETE_AND_BACK)
        if facts.body_blank:
            attempts = ledger.observe_blank(key)
            if attempts < max(1, int(facts.blank_retry_limit)):
                return DocumentFlowDirective(DocumentFlowStep.WAIT_BODY, attempt=attempts)
            ledger.interrupt()
            return DocumentFlowDirective(DocumentFlowStep.MARK_UNAVAILABLE, attempt=attempts)
        if not facts.scroll_status:
            return DocumentFlowDirective(DocumentFlowStep.NONE)
        result = ledger.apply_scroll_status(
            key, facts.scroll_status,
            viewport_fingerprint=facts.viewport_fingerprint,
            stuck_retry_limit=facts.stuck_retry_limit,
            bottom_confirmations=facts.bottom_confirmations,
        )
        mapping = {
            DocumentScrollDirective.CONTINUE: DocumentFlowStep.CONTINUE_SCROLL,
            DocumentScrollDirective.RETRY_STUCK: DocumentFlowStep.RETRY_STUCK,
            DocumentScrollDirective.RETRY_BOTTOM: DocumentFlowStep.RETRY_BOTTOM,
            DocumentScrollDirective.COMPLETE: DocumentFlowStep.COMPLETE_AND_BACK,
            DocumentScrollDirective.ABORT_STUCK: DocumentFlowStep.MARK_INCOMPLETE_AND_BACK,
            DocumentScrollDirective.ABORT_UNVERIFIED: DocumentFlowStep.MARK_INCOMPLETE_AND_BACK,
        }
        return DocumentFlowDirective(
            mapping[result.directive], attempt=result.attempt, scrolls=result.scrolls,
        )
