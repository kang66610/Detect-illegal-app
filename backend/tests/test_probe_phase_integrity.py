from types import SimpleNamespace


def test_nonrecoverable_runtime_failure_blocks_the_next_permission_phase():
    """Allow must not start from a deny phase whose recovery checkpoint failed."""
    from agent.agent_core.probe_phase_integrity import assess_phase_integrity

    decision = assess_phase_integrity([
        SimpleNamespace(stats={"failure": {
            "category": "recovery_exhausted", "recoverable": False,
            "coverage_gap": "recovery_exhausted",
        }}),
    ], current_profile="deny", next_profile="allow")

    assert decision.allow_next_phase is False
    assert decision.coverage_gap == "phase_transition_blocked:deny:recovery_exhausted"


def test_recoverable_engine_failure_does_not_prevent_the_next_phase():
    from agent.agent_core.probe_phase_integrity import assess_phase_integrity

    decision = assess_phase_integrity([
        SimpleNamespace(stats={"failure": {
            "category": "session_lost", "recoverable": True,
        }}),
    ], current_profile="deny", next_profile="allow")

    assert decision.allow_next_phase is True


def test_device_unavailable_blocks_the_next_phase_even_when_marked_recoverable():
    """No Appium session means the first posture produced no comparable evidence."""
    from agent.agent_core.probe_phase_integrity import assess_phase_integrity

    decision = assess_phase_integrity([
        SimpleNamespace(stats={"failure": {
            "category": "device_unavailable", "recoverable": True,
        }}),
    ], current_profile="deny", next_profile="allow")

    assert decision.allow_next_phase is False
    assert decision.coverage_gap == "phase_transition_blocked:deny:device_unavailable"
