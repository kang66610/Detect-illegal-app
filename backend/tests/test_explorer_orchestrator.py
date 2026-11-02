"""Single probe-profile orchestration boundary for the Appium explorer."""
from types import SimpleNamespace

from agent.ai_explorer.explorer_orchestrator import ExplorerOrchestrator, PhaseLoopControl
from agent.detection_engines.base import EngineResult


def test_orchestrator_runs_one_profile_without_mutating_phase_order():
    ctx = SimpleNamespace(runtime={"probe_profile": "deny"})

    def runner(value):
        return EngineResult(
            findings=[], evidence_files=[],
            stats={"probe_profile": value.runtime["probe_profile"]},
        )

    orchestrator = ExplorerOrchestrator(prepare_phase=lambda _value: None, run_cycle=runner)
    result = orchestrator.run_phase(ctx)

    assert result.stats["probe_profile"] == "deny"
    assert ctx.runtime["probe_profile"] == "deny"


def test_orchestrator_prepares_once_before_running_one_profile_cycle():
    calls = []
    ctx = SimpleNamespace(runtime={"probe_profile": "allow"})

    orchestrator = ExplorerOrchestrator(
        prepare_phase=lambda value: calls.append(("prepare", value.runtime["probe_profile"])),
        run_cycle=lambda value: calls.append(("run", value.runtime["probe_profile"])) or EngineResult(),
    )

    orchestrator.run_phase(ctx)

    assert calls == [("prepare", "allow"), ("run", "allow")]


def test_phase_loop_control_stops_for_a_terminated_profile_and_marks_runtime():
    runtime = {"is_terminated": lambda: True}

    termination = PhaseLoopControl(
        runtime=runtime, deadline=None, duration_minutes=0,
    ).termination()

    assert termination == {"kind": "terminated", "reason": "用户已终止检测任务，保留终止前证据"}
    assert runtime["termination_requested"] is True


def test_orchestrator_activates_the_profile_and_preserves_activation_events():
    actions = []
    events = []

    ExplorerOrchestrator.activate_profile(
        activate=lambda package: actions.append(package),
        package="com.demo",
        emit=lambda event_type, **meta: events.append((event_type, meta)),
    )

    assert actions == ["com.demo"]
    assert events == [
        ("activating_app", {"package": "com.demo"}),
        ("app_activated", {"package": "com.demo"}),
    ]


def test_orchestrator_times_one_stable_page_observation():
    calls = []

    observed = ExplorerOrchestrator.observe_stable_page(
        begin=lambda name: calls.append(("begin", name)) or "token",
        finish=lambda token: calls.append(("finish", token)),
        stabilize=lambda step, **kwargs: calls.append(("stabilize", step, kwargs)) or "page",
        step=3,
        cold_restarts=2,
    )

    assert observed == "page"
    assert calls == [
        ("begin", "page_stability"),
        ("stabilize", 3, {"cold_restarts": 2}),
        ("finish", "token"),
    ]


def test_engine_run_delegates_exactly_one_phase_to_orchestrator(monkeypatch):
    import agent.ai_explorer.explorer_engine as explorer_module

    calls = {}

    class _SpyOrchestrator:
        def __init__(self, *, prepare_phase, run_cycle):
            calls["prepare_phase"] = prepare_phase
            calls["run_cycle"] = run_cycle

        def run_phase(self, ctx):
            calls["ctx"] = ctx
            return "phase-result-sentinel"

    monkeypatch.setattr(explorer_module, "ExplorerOrchestrator", _SpyOrchestrator)
    engine = explorer_module.AppiumExplorerEngine(client=object(), llm=None)
    ctx = SimpleNamespace(runtime={})

    result = explorer_module.AppiumExplorerEngine.run(engine, ctx)

    assert result == "phase-result-sentinel"
    assert calls["ctx"] is ctx
    assert calls["prepare_phase"].__name__ == "<lambda>"
    assert calls["run_cycle"].__name__ == "_run_phase_cycle"
