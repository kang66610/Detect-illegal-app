"""Last-mile action safety, applied after deterministic and LLM arbitration."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class FinalActionContext:
    is_root: bool
    low_value_surface_kind: str = ""


class FinalActionSafetyPolicy:
    """Convert unsafe clicks to a scoped back/stop action in a fixed order."""

    CHECK_ORDER = (
        "foreign_app_launch",
        "low_audit_value_route",
        "transaction_boundary",
        "unlabelled_structural_container",
        "destructive_confirmation",
        "stale_or_invisible_target",
    )

    def __init__(self, *, checks: Mapping[str, Callable[[str], bool]] | None = None) -> None:
        self.checks = dict(checks or {})

    def enforce(self, decision: dict, context: FinalActionContext) -> tuple[dict, str | None]:
        final = dict(decision or {})
        if final.get("action") != "click":
            return final, None
        reason = "low_audit_value_surface" if context.low_value_surface_kind else ""
        target = str(final.get("target") or "")
        if not reason:
            reason = next((
                name for name in self.CHECK_ORDER
                if name in self.checks and self.checks[name](target)
            ), "")
        if not reason:
            return final, None
        return ({
            "action": "stop" if context.is_root else "back",
            "target": "",
            "reason": reason,
        }, reason)
