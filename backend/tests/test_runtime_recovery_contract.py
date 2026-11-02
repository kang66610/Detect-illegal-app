from agent.ai_explorer.runtime_recovery import (
    RecoveryDisposition, RuntimeRecoveryCoordinator,
)
from agent.common.exceptions import ExplorationError
import pytest


class _PermissionProbes:
    active = None


def _coordinator(runtime, events, *, replay_result):
    class Client:
        recover_calls = 0

        def perform(self, _decision):
            raise ExplorationError("执行遍历操作 back 失败：socket hang up")

        def recover_runtime_session(self, _package, _error):
            self.recover_calls += 1
            return True

    return RuntimeRecoveryCoordinator(
        client=Client(),
        package_name="com.example.demo",
        runtime=runtime,
        permission_probes=_PermissionProbes(),
        save_checkpoint=lambda: "checkpoint.json",
        replay_navigation=lambda: replay_result,
        is_document_target=lambda _target: False,
        emit=lambda event_type, **meta: events.append((event_type, meta)),
        note_recovery=lambda: None,
        permission_probe_steps=3,
    )


def test_recovery_requires_checkpoint_replay_before_claiming_recovered():
    runtime = {"navigation_replay_required": True}
    events = []
    coordinator = _coordinator(runtime, events, replay_result=False)

    with pytest.raises(ExplorationError, match="socket hang up"):
        coordinator.perform_safe_action(
            4, {"action": "back", "target": ""}, recovery_kind="external_return",
        )
    assert runtime["runtime_session_recovery_attempted"] is True
    assert runtime["runtime_session_recovery_status"] == "replay_failed"
    assert runtime["runtime_recovery_checkpoint"] == "checkpoint.json"
    assert "runtime_session_recovered" not in {event[0] for event in events}
    assert "runtime_session_replay_failed" in {event[0] for event in events}


def test_successful_recovery_records_replay_and_only_then_claims_recovered():
    runtime = {}
    events = []
    coordinator = _coordinator(runtime, events, replay_result=True)

    assert coordinator.perform_safe_action(
        4, {"action": "back", "target": ""}, recovery_kind="external_return",
    ) is True
    assert runtime["runtime_session_recovery_attempted"] is True
    assert runtime["runtime_session_recovery_status"] == "recovered"
    assert runtime["runtime_checkpoint_replayed"] is True
    assert "runtime_session_recovered" in {event[0] for event in events}


def test_recovery_budget_counts_failed_attempts_and_does_not_loop_forever():
    runtime = {"navigation_replay_required": True}
    events = []
    coordinator = _coordinator(runtime, events, replay_result=False)

    for _ in range(2):
        with pytest.raises(ExplorationError, match="socket hang up"):
            coordinator.perform_safe_action(
                4, {"action": "back", "target": ""}, recovery_kind="external_return",
            )

    assert runtime["runtime_session_recovery_attempts"] == 2
    assert runtime["runtime_session_recovery_status"] == "exhausted"
    assert [event[0] for event in events].count("runtime_session_replay_failed") == 1


def test_recovery_does_not_remain_recovered_when_post_recovery_page_is_unreadable():
    events = []

    class Client:
        def __init__(self):
            self.reads = 0

        def page(self):
            self.reads += 1
            raise ExplorationError("socket hang up")

        def recover_runtime_session(self, _package, _error):
            return True

    runtime = {"navigation_replay_required": False}
    coordinator = RuntimeRecoveryCoordinator(
        client=Client(),
        package_name="com.example.demo",
        runtime=runtime,
        permission_probes=_PermissionProbes(),
        save_checkpoint=lambda: "checkpoint.json",
        replay_navigation=lambda: False,
        is_document_target=lambda _target: False,
        emit=lambda event_type, **meta: events.append((event_type, meta)),
        note_recovery=lambda: None,
        permission_probe_steps=3,
    )

    with pytest.raises(ExplorationError, match="socket hang up"):
        coordinator.read_page(1)

    assert runtime["runtime_session_recovery_status"] == "failed"
    assert "runtime_session_recovered" in {event[0] for event in events}
    assert [event[0] for event in events].count("runtime_session_recovery_failed") == 1


def test_resumed_coordinator_keeps_previous_recovery_budget():
    runtime = {"runtime_session_recovery_attempts": 1}
    events = []
    coordinator = _coordinator(runtime, events, replay_result=True)

    with pytest.raises(ExplorationError, match="socket hang up"):
        coordinator.perform_safe_action(
            4, {"action": "back", "target": ""}, recovery_kind="external_return",
        )

    assert runtime["runtime_session_recovery_status"] == "exhausted"
    assert runtime["runtime_session_recovery_attempts"] == 2


def test_recovery_result_marks_unsafe_click_for_redecision_after_replay():
    runtime = {}
    events = []
    coordinator = _coordinator(runtime, events, replay_result=True)

    result = coordinator.recover_runtime_loss_result(
        4, ExplorationError("socket hang up"), operation="click",
    )

    assert result.recovered is True
    assert result.disposition is RecoveryDisposition.REDECIDE
    assert result.checkpoint_replayed is True


def test_foreground_reactivation_replays_the_last_safe_navigation_route():
    runtime = {}
    events = []
    coordinator = _coordinator(runtime, events, replay_result=True)

    assert coordinator.replay_after_reactivation(8, reason="应用回到桌面") is True
    assert runtime["runtime_checkpoint_replayed"] is True
    assert runtime["runtime_session_recovery_status"] == "reactivation_replayed"
    assert ("navigation_replay_after_reactivation", {
        "step": 8, "reason": "应用回到桌面",
    }) in events
