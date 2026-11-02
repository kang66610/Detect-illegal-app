from types import SimpleNamespace


def test_checkpoint_repository_round_trips_version_four_page_state(tmp_path):
    from agent.ai_explorer.page_state import PageState, parse_page
    from agent.ai_explorer.run_checkpoint import TraversalCheckpointRepository

    runtime = {"read_document_titles": {"隐私政策"}}
    state = PageState()
    page = parse_page(".MainActivity", '<hierarchy><node text="首页"/></hierarchy>')
    state.covered_pages.add(page.surface_fingerprint)
    state.start_document(".WebView:document:隐私政策", kind="privacy_policy")
    state.documents.finish(".WebView:document:隐私政策", bottom_confirmed=True)

    repository = TraversalCheckpointRepository(tmp_path, runtime)
    repository.save_traversal(
        state=state, run_state=None,
        findings=[{"kind": "demo", "category": 1, "payload": {}}], evidence=[{"type": "timeline"}],
    )
    restored_state = PageState()
    restored = repository.restore_traversal(restored_state)

    assert restored.restored is True
    assert restored.payload["version"] == 4
    assert restored_state.documents.completed_keys() == {".WebView:document:隐私政策"}
