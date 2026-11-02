"""Assemble one probe profile's EngineResult through the completion gate.

``RunFinalizer`` only summarizes what the real state owners recorded: coverage
gaps come from the injected gap resolver, completion truth from
``ExplorationCompletionGate``, and performance/LLM stats from their ledgers.
It never re-infers rule facts and never mutates scenario state.
"""
from __future__ import annotations

from collections.abc import Callable

from agent.ai_explorer.exploration_completion import ExplorationCompletionGate
from agent.ai_explorer.llm_effectiveness import LLMEffectivenessLedger
from agent.ai_explorer.performance_budget import PerformanceBudget
from agent.common.event_log import record_event
from agent.detection_engines.base import DetectionContext, EngineResult


class RunFinalizer:
    """Finalize one probe profile: gate truth, events and EngineResult."""

    def __init__(
        self, *, completion_gate: ExplorationCompletionGate,
        performance_budget: PerformanceBudget,
        llm_effectiveness: LLMEffectivenessLedger,
        coverage_gaps_fn: Callable[..., list[str]],
    ) -> None:
        self.completion_gate = completion_gate
        self.performance_budget = performance_budget
        self.llm_effectiveness = llm_effectiveness
        self.coverage_gaps_fn = coverage_gaps_fn

    def finalize(
        self, ctx: DetectionContext, *, termination: dict, state,
        evidence: list[dict], findings: list, scenario_snapshot: dict,
        permission_prompts: int, login_gate_seen: bool,
        active_permission_probe: bool, pending_action_validation: bool,
        current_activity: str, llm_calls: int, last_step: int,
        save_pause_checkpoints: Callable[[dict], None],
    ) -> EngineResult:
        preliminary_gaps = self.coverage_gaps_fn(
            ctx, permission_prompts, login_gate_seen, len(state.covered_pages),
            scenario_snapshot=scenario_snapshot,
        )
        completion = self.completion_gate.assess(
            proposed_termination=termination,
            scenario_snapshot=scenario_snapshot,
            coverage_gaps=preliminary_gaps,
            active_document=state.document_active(),
            active_permission_probe=active_permission_probe,
            pending_action_validation=pending_action_validation,
            navigation_frontier_exhausted=bool(
                str((termination or {}).get("kind") or "") == "safe_frontier_exhausted"
                and state.navigation_graph.pending_click is None
                and state.navigation_replay.pending_click is None
            ),
            total_budget_exhausted=str((termination or {}).get("kind") or "") == "duration_limit_reached",
        )
        termination = completion.termination
        coverage_gaps = completion.gaps
        ctx.runtime["traversal_termination"] = termination
        ctx.runtime["coverage_gaps"] = coverage_gaps
        ctx.runtime["coverage_complete"] = completion.coverage_complete
        evidence.append(record_event(
            ctx, "appium", "traversal_terminated", **termination,
            steps=last_step, pages_covered=len(state.covered_pages),
        ))
        if coverage_gaps:
            evidence.append(record_event(
                ctx, "appium", "coverage_incomplete", gaps=coverage_gaps,
                login_gate_seen=login_gate_seen, permission_prompts=permission_prompts,
            ))
        # 汇总随证据归档并进入 stats：fallback 占比升高即模型链路静默
        # 退化的直接信号，不允许只体现在散落的 rejected 事件里。
        llm_effectiveness_summary = self.llm_effectiveness.summarize()
        evidence.append(record_event(
            ctx, "llm", "llm_effectiveness_summary", **llm_effectiveness_summary,
        ))
        save_pause_checkpoints(termination)
        return EngineResult(findings=findings, evidence_files=evidence, stats={
            "pages_covered": len(state.covered_pages),
            "scenarios": len(state.visited_page_targets),
            "current_page": current_activity,
            "llm_calls": llm_calls,
            "llm_fallbacks": len(ctx.runtime.get("llm_fallbacks", [])),
            "interaction_failures": len(ctx.runtime.get("interaction_failures") or []),
            "permission_prompts": permission_prompts,
            "scenario_coverage": scenario_snapshot,
            "coverage_gaps": coverage_gaps,
            "coverage_complete": completion.coverage_complete,
            "termination": termination,
            "performance_metrics": self.performance_budget.metrics(),
            "llm_effectiveness": llm_effectiveness_summary,
        })
