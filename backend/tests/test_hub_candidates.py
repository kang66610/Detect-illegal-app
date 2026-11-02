from agent.ai_explorer.hub_decision import HubDecisionModule


def test_already_read_document_redirect_to_hub_privacy_row_is_a_candidate():
    directive = HubDecisionModule().propose_already_read_redirect(
        target="注销账号",
    )

    assert directive is not None
    assert (directive.action, directive.target, directive.source, directive.priority) == (
        "click", "注销账号", "deterministic_privacy_hub", 150,
    )


def test_already_read_document_redirect_to_next_hub_row_is_a_candidate():
    directive = HubDecisionModule().propose_next_hub_row(target="授权管理")

    assert directive is not None
    assert (directive.action, directive.target, directive.source, directive.priority) == (
        "click", "授权管理", "deterministic_privacy_hub", 150,
    )


def test_already_read_document_redirect_to_consent_is_a_candidate():
    directive = HubDecisionModule().propose_consent_after_documents(target="同意")

    assert directive is not None
    assert (directive.action, directive.target, directive.source, directive.priority) == (
        "click", "同意", "deterministic_consent", 150,
    )
