"""Prevent an unrecoverable probe phase from contaminating its successor."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PhaseIntegrityDecision:
    allow_next_phase: bool
    coverage_gap: str = ""
    reason: str = ""


def assess_phase_integrity(
    results: Iterable[object], *, current_profile: str, next_profile: str,
) -> PhaseIntegrityDecision:
    """Accept only a phase whose adapter failures are recoverable.

    The next permission posture has a different evidence contract. Starting it
    after a failed checkpoint replay would make its observations look valid
    while its navigation and app state are unknown.
    """
    for result in results:
        stats = getattr(result, "stats", {}) or {}
        failure = stats.get("failure") if isinstance(stats, dict) else None
        if not isinstance(failure, dict):
            continue
        category = str(failure.get("category") or "engine_failure")
        # A transport/session creation failure has no phase evidence at all.
        # It is retryable at the task boundary, but the alternate permission
        # posture must not start and appear as a successful second phase.
        if category == "device_unavailable":
            return PhaseIntegrityDecision(
                allow_next_phase=False,
                coverage_gap=f"phase_transition_blocked:{current_profile}:{category}",
                reason=(
                    f"{current_profile} 阶段未能建立设备会话，"
                    f"不启动 {next_profile} 阶段以避免零覆盖阶段误导用户"
                ),
            )
        if bool(failure.get("recoverable", True)):
            continue
        return PhaseIntegrityDecision(
            allow_next_phase=False,
            coverage_gap=f"phase_transition_blocked:{current_profile}:{category}",
            reason=(
                f"{current_profile} 阶段发生不可恢复的 {category}，"
                f"不启动 {next_profile} 阶段以避免跨阶段污染"
            ),
        )
    return PhaseIntegrityDecision(allow_next_phase=True)
