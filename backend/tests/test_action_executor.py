from types import SimpleNamespace

import pytest


def test_action_executor_returns_success_without_interpreting_page_state():
    from agent.ai_explorer.action_executor import ActionExecutor
    from agent.ai_explorer.action_pipeline import FinalAction

    calls = []
    executor = ActionExecutor(SimpleNamespace(perform=lambda decision: calls.append(decision)))
    result = executor.execute(FinalAction("click", "upload", "test", "llm"))

    assert result.succeeded is True
    assert result.action == "click"
    assert calls == [{"action": "click", "target": "upload", "reason": "test"}]


def test_action_executor_preserves_exploration_error_as_failure():
    from agent.ai_explorer.action_executor import ActionExecutor
    from agent.ai_explorer.action_pipeline import FinalAction
    from agent.common.exceptions import ExplorationError

    executor = ActionExecutor(SimpleNamespace(perform=lambda _decision: (_ for _ in ()).throw(ExplorationError("tap failed"))))
    result = executor.execute(FinalAction("click", "upload", "test", "llm"))

    assert result.succeeded is False
    assert result.error == "tap failed"


def test_action_executor_commits_click_only_after_success():
    from agent.ai_explorer.action_executor import ActionExecutor
    from agent.ai_explorer.action_pipeline import FinalAction
    from agent.ai_explorer.page_state import PageState, parse_page

    page = parse_page(".MainActivity", '<hierarchy><node text="上传"/></hierarchy>')
    state = PageState()
    executor = ActionExecutor(SimpleNamespace(perform=lambda _decision: None))

    result = executor.execute_and_record(
        FinalAction("click", "upload", "test", "llm"), page=page, state=state,
        commit_target=True,
    )

    assert result.succeeded is True
    assert state.target_visited(page, "upload") is True
    assert state.last_action == "click"
