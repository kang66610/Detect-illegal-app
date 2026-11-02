def test_document_executor_completes_ledger_only_after_bottom_confirmation():
    from agent.ai_explorer.document_executor import DocumentExecutor
    from agent.ai_explorer.document_flow import DocumentFlowPolicy
    from agent.ai_explorer.document_session import DocumentReadingLedger

    ledger = DocumentReadingLedger()
    executor = DocumentExecutor(DocumentFlowPolicy(), ledger)

    first = executor.observe_scroll("policy", status="bottom", bottom_confirmations=2)
    second = executor.observe_scroll("policy", status="bottom", bottom_confirmations=2)

    assert first.completed is False
    assert second.completed is True
    assert ledger.completed_keys() == {"policy"}
