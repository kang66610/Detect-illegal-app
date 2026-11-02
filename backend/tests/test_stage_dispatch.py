import pytest

from agent.agent_core.stage_dispatch import StageDispatcher, UnknownStageError


def test_stage_dispatcher_executes_the_named_stage_with_shared_context():
    observed = []
    dispatcher = StageDispatcher({
        "traversing": lambda context: observed.append(context["task_id"]),
    })

    dispatcher.dispatch("traversing", {"task_id": 42})

    assert observed == [42]


def test_stage_dispatcher_returns_the_stage_result_to_its_caller():
    dispatcher = StageDispatcher({"reporting": lambda _context: "reported"})

    assert dispatcher.dispatch("reporting", {}) == "reported"


def test_stage_dispatcher_rejects_a_stage_without_a_handler():
    with pytest.raises(UnknownStageError, match="reporting"):
        StageDispatcher({}).dispatch("reporting", {})
