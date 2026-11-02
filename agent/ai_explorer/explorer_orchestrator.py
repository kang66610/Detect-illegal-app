"""Single probe-profile lifecycle orchestration for the Appium explorer.

The orchestrator owns preparation and the single profile boundary.  The
deny/allow order, phase resets and cross-profile merge stay with ``workflow``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.detection_engines.base import EngineResult


class PhaseLoopControl:
    """Own termination checks for exactly one probe-profile page cycle."""

    def __init__(self, *, runtime: dict, deadline: float | None, duration_minutes: float) -> None:
        self._runtime = runtime
        self._deadline = deadline
        self._duration_minutes = duration_minutes

    def termination(self, *, now: float | None = None) -> dict | None:
        import time

        if self._deadline is not None and (now if now is not None else time.monotonic()) >= self._deadline:
            return {
                "kind": "duration_limit_reached",
                "reason": f"已达到本次模式的 {self._duration_minutes:g} 分钟运行上限",
            }
        is_canceled = self._runtime.get("is_canceled")
        if callable(is_canceled) and is_canceled():
            return {"kind": "canceled", "reason": "用户已取消检测任务"}
        is_terminated = self._runtime.get("is_terminated")
        if callable(is_terminated) and is_terminated():
            self._runtime["termination_requested"] = True
            return {"kind": "terminated", "reason": "用户已终止检测任务，保留终止前证据"}
        is_paused = self._runtime.get("is_paused")
        if callable(is_paused) and is_paused():
            return {"kind": "paused", "reason": "用户已暂停检测任务"}
        return None


class ExplorerOrchestrator:
    """Run exactly one probe profile cycle without touching phase order."""

    def __init__(
        self,
        *,
        prepare_phase: Callable[[Any], None],
        run_cycle: Callable[[Any], EngineResult],
    ) -> None:
        self._prepare_phase = prepare_phase
        self._run_cycle = run_cycle

    def run_phase(self, ctx) -> EngineResult:
        self._prepare_phase(ctx)
        return self._run_cycle(ctx)

    @staticmethod
    def activate_profile(*, activate: Callable[[str], None], package: str, emit: Callable[..., None]) -> None:
        """Activate one audited profile and preserve its timeline boundary."""
        emit("activating_app", package=package)
        activate(package)
        emit("app_activated", package=package)

    @staticmethod
    def observe_stable_page(
        *,
        begin: Callable[[str], object],
        finish: Callable[[object], None],
        stabilize: Callable[..., Any],
        step: int,
        cold_restarts: int,
    ) -> Any:
        """Time the stable-page boundary without exposing its internals to the loop."""
        token = begin("page_stability")
        try:
            return stabilize(step, cold_restarts=cold_restarts)
        finally:
            finish(token)
