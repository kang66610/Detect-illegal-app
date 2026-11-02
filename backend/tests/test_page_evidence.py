from agent.detection_engines.page_semantics import PageRole, classify_observation


def test_page_evidence_builder_keeps_overlay_as_role_evidence_only():
    from agent.ai_explorer.page_evidence import (
        PageEvidenceBuilder,
        PageEvidenceInput,
        PageEvidenceSignals,
    )

    elements = (
        {"text": "同意", "target": "agree", "clickable": True, "displayed": True},
        {"text": "不同意", "target": "decline", "clickable": True, "displayed": True},
    )
    observation = PageEvidenceBuilder().build_observation(PageEvidenceInput(
        activity="com.example.MainActivity",
        elements=elements,
        screen_text="",
        previous_action="",
        route=(),
        signals=PageEvidenceSignals(consent_dialog=True, main_content=True),
    ))

    resolved = classify_observation(observation)

    assert resolved.role is PageRole.CONSENT_DIALOG
    assert [item.value for item in resolved.blocked_roles] == ["main_content"]


def test_legacy_page_semantics_constructs_observation_through_evidence_builder(monkeypatch):
    import agent.ai_explorer.explorer_engine as explorer
    from agent.ai_explorer.page_evidence import PageEvidenceBuilder
    from agent.ai_explorer.page_state import PageState, parse_page

    calls = []

    class SpyBuilder:
        def build_observation(self, value):
            calls.append(value)
            return PageEvidenceBuilder().build_observation(value)

    monkeypatch.setattr(explorer, "PageEvidenceBuilder", SpyBuilder, raising=False)
    page = parse_page(
        "com.example.MainActivity",
        '<hierarchy><node text="同意" clickable="true" bounds="[0,0][10,10]"/></hierarchy>',
    )

    explorer._page_semantics(page.activity, page.elements, PageState())

    assert len(calls) == 1


def test_perception_ocr_policy_covers_gate_and_chat_but_not_document_body():
    from agent.ai_explorer.page_observer import PerceptionOcrPolicy

    policy = PerceptionOcrPolicy(
        has_document_body=lambda activity, _elements: "webview" in activity.lower(),
        is_consent=lambda _elements: False,
        is_launch_gate=lambda activity: "splash" in activity.lower(),
        visible_text=lambda elements: " ".join(str(item.get("text") or "") for item in elements),
        is_settings_hub=lambda _activity, _elements: False,
        element_label=lambda item: str(item.get("text") or ""),
    )

    assert policy.needs_perception(".SplashActivity", []) is True
    assert policy.needs_perception(".WebViewActivity", []) is False
    assert policy.needs_interactive_ocr(
        "com.example.CustomerActivity", "请输入消息", [{"text": ""}], has_ocr=False,
    ) is True
    assert policy.needs_interactive_ocr(
        "com.example.CustomerActivity", "请输入消息", [{"text": "相册", "clickable": True}], has_ocr=False,
    ) is True


def test_legacy_perception_wrapper_delegates_to_page_observer_policy(monkeypatch):
    import agent.ai_explorer.explorer_engine as explorer

    calls = []

    class SpyPolicy:
        def __init__(self, **_kwargs):
            calls.append("created")

        def needs_perception(self, _activity, _elements):
            calls.append("checked")
            return True

    monkeypatch.setattr(explorer, "PerceptionOcrPolicy", SpyPolicy, raising=False)

    assert explorer._needs_perception_ocr(".MainActivity", []) is True
    assert calls == ["created", "checked"]
