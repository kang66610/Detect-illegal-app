"""State machine for permission-denial business-impact probes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class PermissionProbeStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    SUBFEATURE_ONLY = "subfeature_only"
    ATTEMPTED_UNBLOCKED = "attempted_unblocked"


@dataclass
class PermissionDenialProbe:
    permission: str
    remaining_steps: int
    trigger_target: str
    retry_attempted: bool = False
    prompt_screenshot: dict | None = None
    trigger_screenshot: dict | None = None
    trigger_activity: str = ""
    navigation_replay: dict = field(default_factory=dict)
    route_replayed: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


class PermissionProbeLedger:
    """Own one active 4.2 probe and its legacy runtime projection."""

    def __init__(self, runtime: dict) -> None:
        self.runtime = runtime
        self.active: PermissionDenialProbe | None = self._restore(
            runtime.get("pending_permission_denial_probe")
        )

    @staticmethod
    def _restore(raw: object) -> PermissionDenialProbe | None:
        if not isinstance(raw, dict) or not raw.get("trigger_target"):
            return None
        return PermissionDenialProbe(
            permission=str(raw.get("permission") or ""),
            remaining_steps=max(0, int(raw.get("remaining_steps") or 0)),
            trigger_target=str(raw.get("trigger_target") or ""),
            retry_attempted=bool(raw.get("retry_attempted")),
            prompt_screenshot=raw.get("prompt_screenshot"),
            trigger_screenshot=raw.get("trigger_screenshot"),
            trigger_activity=str(raw.get("trigger_activity") or ""),
            navigation_replay=dict(raw.get("navigation_replay") or {}),
            route_replayed=bool(raw.get("route_replayed")),
        )

    def _persist(self) -> None:
        if self.active:
            self.runtime["pending_permission_denial_probe"] = self.active.as_dict()
        else:
            self.runtime.pop("pending_permission_denial_probe", None)

    def start(self, **values: object) -> PermissionDenialProbe:
        self.active = PermissionDenialProbe(
            permission=str(values.get("permission") or ""),
            remaining_steps=max(0, int(values.get("remaining_steps") or 0)),
            trigger_target=str(values.get("trigger_target") or ""),
            retry_attempted=bool(values.get("retry_attempted")),
            prompt_screenshot=values.get("prompt_screenshot"),
            trigger_screenshot=values.get("trigger_screenshot"),
            trigger_activity=str(values.get("trigger_activity") or ""),
            navigation_replay=dict(values.get("navigation_replay") or {}),
        )
        self.runtime["permission_denial_probe_status"] = PermissionProbeStatus.ACTIVE.value
        self._persist()
        return self.active

    def tick(self) -> PermissionDenialProbe | None:
        if self.active:
            self.active.remaining_steps -= 1
            self._persist()
        return self.active

    def refresh_after_recovery(self, *, minimum_steps: int, route_replayed: bool) -> None:
        if not self.active:
            return
        self.active.remaining_steps = max(self.active.remaining_steps, int(minimum_steps))
        self.active.route_replayed = bool(route_replayed)
        self._persist()

    def mark_retry_attempted(self) -> None:
        if self.active:
            self.active.retry_attempted = True
            self._persist()

    def complete(self, status: PermissionProbeStatus, *, terminal: bool = False) -> None:
        self.runtime["permission_denial_probe_status"] = status.value
        if terminal:
            self.runtime["permission_denial_probe_terminal"] = True
        self.active = None
        self._persist()

    def clear(self) -> None:
        self.active = None
        self._persist()
