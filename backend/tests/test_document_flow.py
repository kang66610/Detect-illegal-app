from agent.ai_explorer.document_flow import (
    DocumentFlowInput,
    DocumentFlowPolicy,
    DocumentFlowStep,
)
from agent.ai_explorer.document_session import DocumentReadingLedger


def test_document_flow_retries_blank_body_before_marking_it_unavailable():
    ledger = DocumentReadingLedger()
    policy = DocumentFlowPolicy()

    first = policy.decide(DocumentFlowInput(
        key="privacy", body_blank=True, blank_retry_limit=2,
    ), ledger)
    second = policy.decide(DocumentFlowInput(
        key="privacy", body_blank=True, blank_retry_limit=2,
    ), ledger)

    assert first.step is DocumentFlowStep.WAIT_BODY
    assert second.step is DocumentFlowStep.MARK_UNAVAILABLE


def test_document_flow_requires_two_bottom_observations_before_completion():
    ledger = DocumentReadingLedger()
    policy = DocumentFlowPolicy()

    first = policy.decide(DocumentFlowInput(key="privacy", scroll_status="bottom"), ledger)
    second = policy.decide(DocumentFlowInput(key="privacy", scroll_status="bottom"), ledger)

    assert first.step is DocumentFlowStep.RETRY_BOTTOM
    assert second.step is DocumentFlowStep.COMPLETE_AND_BACK


def test_document_flow_aborts_after_bounded_stuck_scrolls():
    ledger = DocumentReadingLedger()
    policy = DocumentFlowPolicy()

    for _ in range(2):
        directive = policy.decide(DocumentFlowInput(
            key="privacy", scroll_status="stuck", stuck_retry_limit=3,
        ), ledger)
        assert directive.step is DocumentFlowStep.RETRY_STUCK
    directive = policy.decide(DocumentFlowInput(
        key="privacy", scroll_status="stuck", stuck_retry_limit=3,
    ), ledger)

    assert directive.step is DocumentFlowStep.MARK_INCOMPLETE_AND_BACK


def test_document_flow_backs_out_of_an_already_completed_document():
    ledger = DocumentReadingLedger()
    ledger.finish("privacy", bottom_confirmed=True)

    directive = DocumentFlowPolicy().decide(DocumentFlowInput(key="privacy"), ledger)

    assert directive.step is DocumentFlowStep.ALREADY_COMPLETE_AND_BACK


def test_combined_document_link_redirects_to_the_first_unread_inline_title():
    from agent.ai_explorer.document_state import CombinedDocumentRedirectPolicy

    directive = CombinedDocumentRedirectPolicy().directive(
        action="click",
        target="我已阅读《服务协议》和《隐私政策》",
        unread_titles=("《隐私政策》",),
        has_overlay=False,
    )

    assert directive is not None
    assert (directive.action, directive.target, directive.source, directive.priority) == (
        "click", "《隐私政策》", "deterministic_document", 150,
    )
