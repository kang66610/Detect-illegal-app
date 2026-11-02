"""RunFinalizer assembles one probe profile's EngineResult via the gate."""
from pathlib import Path
from types import SimpleNamespace

from agent.ai_explorer.exploration_completion import ExplorationCompletionGate
from agent.ai_explorer.llm_effectiveness import LLMEffectivenessLedger
from agent.ai_explorer.performance_budget import PerformanceBudget
from agent.ai_explorer.run_finalizer import RunFinalizer


def _finalizer():
    return RunFinalizer(
        completion_gate=ExplorationCompletionGate(),
        performance_budget=PerformanceBudget({}),
        llm_effectiveness=LLMEffectivenessLedger(),
        coverage_gaps_fn=lambda *_args, **_kwargs: [],
    )


def _state():
    return SimpleNamespace(
        covered_pages={"a", "b"},
        visited_page_targets={"t1"},
        document_active=lambda: False,
        navigation_graph=SimpleNamespace(pending_click=None),
        navigation_replay=SimpleNamespace(pending_click=None),
    )


def _ctx(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=tmp_path, runtime={},
        apk=SimpleNamespace(permissions=[]), task=SimpleNamespace(mode="fast"),
    )


def _event_types(evidence):
    return [row["meta"]["event_type"] for row in evidence if "meta" in row]


def test_finalizer_reports_pending_scenario_via_completion_gate(tmp_path):
    finalizer = _finalizer()
    ctx = _ctx(tmp_path)
    saved_terminations = []

    result = finalizer.finalize(
        ctx, termination={"kind": "safe_frontier_exhausted", "reason": "路径耗尽"},
        state=_state(), evidence=[], findings=[],
        scenario_snapshot={"items": [{"item": "4.2", "state": "attempted"}]},
        permission_prompts=0, login_gate_seen=False,
        active_permission_probe=False, pending_action_validation=False,
        current_activity=".MainActivity", llm_calls=2, last_step=7,
        save_pause_checkpoints=lambda termination: saved_terminations.append(termination),
    )

    assert result.stats["coverage_complete"] is False
    # Navigation exhaustion and scenario completion are different truths: the
    # frontier-exhausted kind stays, the unfinished scenario stays visible.
    assert result.stats["termination"]["kind"] == "safe_frontier_exhausted"
    assert result.stats["scenario_coverage"]["items"][0]["item"] == "4.2"
    assert saved_terminations == [result.stats["termination"]]
    assert result.stats["pages_covered"] == 2
    assert result.stats["llm_calls"] == 2
    assert ctx.runtime["traversal_termination"]["kind"] == "safe_frontier_exhausted"


def test_finalizer_keeps_truthful_exhaustion_and_records_termination_event(tmp_path):
    finalizer = _finalizer()
    evidence = []
    ctx = _ctx(tmp_path)

    result = finalizer.finalize(
        ctx, termination={"kind": "safe_frontier_exhausted", "reason": "路径耗尽"},
        state=_state(), evidence=evidence, findings=[],
        scenario_snapshot={"items": [{"item": "4.2", "state": "evidence_observed"}]},
        permission_prompts=1, login_gate_seen=False,
        active_permission_probe=False, pending_action_validation=False,
        current_activity=".MainActivity", llm_calls=0, last_step=3,
        save_pause_checkpoints=lambda termination: None,
    )

    assert result.stats["coverage_complete"] is True
    assert result.stats["termination"]["kind"] == "safe_frontier_exhausted"
    assert result.findings == []
    event_types = _event_types(evidence)
    assert "traversal_terminated" in event_types
    assert "llm_effectiveness_summary" in event_types
