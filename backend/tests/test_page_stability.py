from types import SimpleNamespace


def test_loading_shell_detector_keeps_document_and_external_pages_out_of_restart_path():
    from agent.ai_explorer.page_stability import LoadingShellDetector

    detector = LoadingShellDetector(
        is_external=lambda _activity, elements: any(item.get("external") for item in elements),
        has_document_body=lambda _activity, elements: any(item.get("document") for item in elements),
        has_external_document_body=lambda elements: any(item.get("external_document") for item in elements),
    )

    bare = SimpleNamespace(activity="com.example.Main", xml="<hierarchy />", elements=[])
    policy = SimpleNamespace(
        activity="com.example.WebView", xml="<hierarchy><node class=""android.webkit.WebView""/></hierarchy>",
        elements=[{"document": True}],
    )
    external = SimpleNamespace(activity="com.browser.CustomTab", xml="<hierarchy />", elements=[{"external": True}])

    assert detector.is_loading(bare, active_document=False) is True
    assert detector.is_loading(policy, active_document=False) is False
    assert detector.is_loading(external, active_document=False) is False
    assert detector.is_loading(bare, active_document=True) is False


def test_legacy_loading_shell_wrapper_delegates_to_stability_detector(monkeypatch):
    import agent.ai_explorer.explorer_engine as explorer
    from agent.ai_explorer.page_state import PageState, parse_page

    calls = []

    class SpyDetector:
        def __init__(self, **_kwargs):
            calls.append("created")

        def is_loading(self, _page, *, active_document):
            calls.append(active_document)
            return True

    monkeypatch.setattr(explorer, "LoadingShellDetector", SpyDetector, raising=False)
    page = parse_page("com.example.Main", "<hierarchy />")

    assert explorer._page_is_loading_shell(page, PageState()) is True
    assert calls == ["created", False]
