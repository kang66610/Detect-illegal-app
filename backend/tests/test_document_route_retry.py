from agent.ai_explorer.document_state import (
    pending_document_route_retry,
    schedule_document_route_retry,
)


def test_first_crashed_consent_document_route_is_queued_for_the_same_target_retry():
    runtime = {}

    assert schedule_document_route_retry(runtime, "《隐私政策》", retry_limit=1) is True
    assert pending_document_route_retry(runtime) == "《隐私政策》"
    assert schedule_document_route_retry(runtime, "《隐私政策》", retry_limit=1) is False
