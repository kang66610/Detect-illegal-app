def test_document_identity_resolver_prefers_rendered_body_over_entry_origin():
    from agent.ai_explorer.document_session import (
        DocumentIdentityInput,
        DocumentIdentityResolver,
        DocumentIdentityRules,
    )

    rules = DocumentIdentityRules(
        consent_dialog=lambda _items: False,
        privacy_dialog_button=lambda _item: False,
        visible_text=lambda _items: "第三方SDK目录",
        rendered_kind=lambda text: "service_terms" if "服务协议正文" in text else None,
        document_entry_page=lambda _activity, _items: False,
        login_gate=lambda _activity, _items: False,
        low_value_kind=lambda _activity, _items, _text: None,
        customer_service_surface=lambda _activity, _text, _items: False,
        has_body_surface=lambda _activity, _items: True,
        body_kind=lambda _text: None,
        target_is_document_route=lambda _target: True,
        infer_kind=lambda _target: "privacy_policy",
        canonical_kind=lambda value: value,
        title_for_kind=lambda kind: {"service_terms": "服务协议", "privacy_policy": "隐私政策"}.get(kind, kind),
        login_activity_terms=("login",), document_terms=("隐私政策",), follow_terms=(),
    )

    identity = DocumentIdentityResolver(rules).resolve(DocumentIdentityInput(
        activity=".WebViewActivity", elements=[], screen_text="服务协议正文", document_origin="第三方SDK目录",
    ))

    assert identity is not None
    assert identity.key == ".WebViewActivity:document:服务协议"
    assert identity.source == "rendered_body"


def test_page_state_document_accessors_prefer_reading_ledger_over_legacy_projection():
    from agent.ai_explorer.page_state import PageState

    state = PageState(completed_documents={"legacy"}, document_scrolls={"legacy": 2})
    state.start_document("ledger", entry_clicks=3)
    state.documents.mark_scrolled("ledger")
    state.documents.finish("ledger", bottom_confirmed=True)

    assert state.document_is_complete("legacy") is True
    assert state.document_is_complete("ledger") is True
    assert state.document_scroll_count("ledger") == 1
    assert state.document_entry_click_count("ledger") == 3
