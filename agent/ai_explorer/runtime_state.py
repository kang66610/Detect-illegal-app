"""Typed ownership for mutable state of one Appium detection run.

The workflow still persists a JSON-compatible mapping.  This module is the
single mutation seam for state whose invariants span login, phases and
permission verification; legacy readers can continue to consume the mapping
during the incremental migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import Callable, MutableMapping, Sequence


class ProbePhase(str, Enum):
    OBSERVE = "observe"
    DENY = "deny"
    ALLOW = "allow"


class LoginStatus(str, Enum):
    UNKNOWN = "unknown"
    WAITING = "waiting"
    TIMED_OUT = "timed_out"
    VERIFIED = "verified"


@dataclass(frozen=True)
class PermissionVerification:
    permission: str
    requested_action: str
    selected_permissions: tuple[str, ...]
    states: dict[str, bool | None]
    verified: bool

    @property
    def event_type(self) -> str:
        return "permission_allow_verified" if self.verified else "permission_allow_unverified"


@dataclass(frozen=True)
class PermissionGrantPoll:
    """The effective Android permission state observed after an allow tap."""

    selected_permissions: tuple[str, ...]
    states: dict[str, bool | None]
    attempts: int

    @property
    def verified(self) -> bool:
        return bool(self.selected_permissions) and all(
            self.states.get(permission) is True for permission in self.selected_permissions
        )


def poll_permission_grant(
    read_states: Callable[[str, list[str]], dict[str, bool | None]],
    *,
    package_name: str,
    selected_permissions: Sequence[str],
    max_attempts: int = 4,
    interval_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> PermissionGrantPoll:
    """Poll package-manager state until an Android allow response is visible.

    The system permission controller dismisses before package-manager state is
    always observable.  A single immediate read can therefore create a false
    ``permission_allow_unverified`` event.  Polling the condition keeps the
    terminal evidence tied to Android's effective grant state, with a bounded
    window and no guessed extra delay after the condition is true.
    """
    selected = tuple(str(item) for item in selected_permissions if str(item))
    if not selected:
        return PermissionGrantPoll(selected_permissions=selected, states={}, attempts=0)
    attempts = max(1, int(max_attempts))
    interval = max(0.0, float(interval_seconds))
    states: dict[str, bool | None] = {}
    for attempt in range(1, attempts + 1):
        states = dict(read_states(package_name, list(selected)) or {})
        result = PermissionGrantPoll(
            selected_permissions=selected,
            states=states,
            attempts=attempt,
        )
        if result.verified or attempt == attempts:
            return result
        sleep(interval)
    raise AssertionError("permission grant polling loop must return")


@dataclass(frozen=True)
class PhaseTransition:
    previous: ProbePhase
    current: ProbePhase


@dataclass(frozen=True)
class ActivePermissionProbe:
    permission: str
    trigger_target: str


class NavigationRunState:
    """Mapping-backed navigation facts that are safe to reuse across phases."""

    def __init__(self, storage: MutableMapping[str, object]):
        self._data = storage

    @property
    def verified_routes(self) -> list[tuple[str, ...]]:
        raw = self._data.get("verified_navigation_routes") or []
        return [tuple(str(part) for part in route if part) for route in raw]

    def record_verified_route(self, route: Sequence[str]) -> None:
        normalized = tuple(str(part).strip() for part in route if str(part).strip())
        if not normalized:
            raise ValueError("verified navigation route cannot be empty")
        routes = self.verified_routes
        if normalized not in routes:
            routes.append(normalized)
        self._data["verified_navigation_routes"] = [list(item) for item in routes]


class PermissionRunState:
    """Own permission-probe lifetime instead of exposing raw runtime keys."""

    def __init__(self, storage: MutableMapping[str, object]):
        self._data = storage

    @property
    def active_probe(self) -> ActivePermissionProbe | None:
        raw = self._data.get("pending_permission_denial_probe")
        if not isinstance(raw, dict):
            return None
        permission = str(raw.get("permission") or "").strip()
        target = str(raw.get("trigger_target") or "").strip()
        if not permission:
            return None
        return ActivePermissionProbe(permission=permission, trigger_target=target)

    def begin_denial_probe(self, *, permission: str, trigger_target: str) -> None:
        permission = str(permission or "").strip()
        if not permission:
            raise ValueError("permission denial probe requires a permission")
        self._data["pending_permission_denial_probe"] = {
            "permission": permission,
            "trigger_target": str(trigger_target or "").strip(),
        }
        self._data["permission_denial_probe_status"] = "active"

    def clear_phase_probe(self) -> None:
        self._data.pop("pending_permission_denial_probe", None)
        self._data.pop("permission_denial_probe_terminal", None)
        self._data.pop("permission_denial_probe_status", None)
        self._data.pop("permission_rationale_retries", None)


class DetectionRunState:
    """Own cross-cutting run invariants behind a small mapping-compatible interface."""

    def __init__(self, storage: MutableMapping[str, object]):
        self._data = storage
        self.navigation = NavigationRunState(storage)
        self.permission = PermissionRunState(storage)
        self._normalise_legacy_state()

    @classmethod
    def from_context(cls, ctx) -> "DetectionRunState":
        return cls(ctx.runtime)

    def _normalise_legacy_state(self) -> None:
        if self._data.get("manual_login_verified"):
            self._data["login_status"] = LoginStatus.VERIFIED.value
        elif self._data.get("manual_login_timed_out"):
            self._data["login_status"] = LoginStatus.TIMED_OUT.value
        else:
            self._data.setdefault("login_status", LoginStatus.UNKNOWN.value)
        self._data.setdefault("manual_login_waited_gate_fingerprints", [])
        self._data.setdefault("run_state_schema_version", 1)

    @property
    def phase(self) -> ProbePhase:
        raw = str(self._data.get("probe_profile") or ProbePhase.OBSERVE.value)
        try:
            return ProbePhase(raw)
        except ValueError:
            gap = f"invalid_probe_phase:{raw}"
            gaps = self._data.setdefault("run_state_recovery_gaps", [])
            if gap not in gaps:
                gaps.append(gap)
            return ProbePhase.OBSERVE

    @property
    def recovery_gaps(self) -> list[str]:
        return [str(item) for item in (self._data.get("run_state_recovery_gaps") or [])]

    @property
    def checkpoint_restored(self) -> bool:
        return bool(self._data.get("resume_checkpoint_restored"))

    def begin_phase(self, phase: ProbePhase | str) -> PhaseTransition:
        previous = self.phase
        current = phase if isinstance(phase, ProbePhase) else ProbePhase(str(phase))
        self._data["probe_profile"] = current.value
        if current is not previous:
            self.permission.clear_phase_probe()
            self._data.pop("last_permission_verification", None)
            self._data.pop("permission_allow_verified", None)
        return PhaseTransition(previous=previous, current=current)

    def export_checkpoint_state(self) -> dict:
        """Return the typed, JSON-compatible state owned by this Module."""
        return {
            "probe_profile": self.phase.value,
            "verified_navigation_routes": [list(route) for route in self.navigation.verified_routes],
            "pending_permission_denial_probe": (
                {
                    "permission": self.permission.active_probe.permission,
                    "trigger_target": self.permission.active_probe.trigger_target,
                }
                if self.permission.active_probe else None
            ),
            "permission_denial_probe_status": self._data.get("permission_denial_probe_status"),
            "login_status": self.login_status.value,
            "manual_login_verified": bool(self._data.get("manual_login_verified")),
            "manual_login_waited_gate_fingerprints": list(
                self._login_wait_gate_fingerprints("manual_login_waited_gate_fingerprints")
            ),
            "prior_probe_login_gate_fingerprints": list(
                self._login_wait_gate_fingerprints("prior_probe_login_gate_fingerprints")
            ),
        }

    def restore_checkpoint_state(self, payload: dict) -> None:
        allowed = {
            "probe_profile", "verified_navigation_routes", "pending_permission_denial_probe",
            "permission_denial_probe_status", "login_status", "manual_login_verified",
            "manual_login_waited_gate_fingerprints", "prior_probe_login_gate_fingerprints",
        }
        for key in allowed:
            if key in payload:
                self._data[key] = payload[key]
        # Force validation to record corrupt legacy values as recovery gaps.
        _ = self.phase
        _ = self.login_status
        self._data["resume_checkpoint_restored"] = True

    @property
    def login_status(self) -> LoginStatus:
        raw = str(self._data.get("login_status") or LoginStatus.UNKNOWN.value)
        try:
            return LoginStatus(raw)
        except ValueError:
            return LoginStatus.UNKNOWN

    @property
    def authenticated_paths_covered(self) -> bool:
        return self.login_status is LoginStatus.VERIFIED

    def _login_wait_gate_fingerprints(self, key: str) -> set[str]:
        raw = self._data.get(key) or []
        if not isinstance(raw, (list, tuple, set)):
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    def login_wait_already_consumed(self, gate_fingerprint: str) -> bool:
        """Return true only when this semantic login gate was previously waited."""
        gate = str(gate_fingerprint or "").strip()
        if not gate:
            return False
        return gate in (
            self._login_wait_gate_fingerprints("manual_login_waited_gate_fingerprints")
            | self._login_wait_gate_fingerprints("prior_probe_login_gate_fingerprints")
        )

    def mark_login_waiting(self, *, gate_fingerprint: str = "") -> None:
        self._data["manual_login_waited"] = True
        self._data["login_status"] = LoginStatus.WAITING.value
        gate = str(gate_fingerprint or "").strip()
        if gate:
            fingerprints = self._login_wait_gate_fingerprints("manual_login_waited_gate_fingerprints")
            fingerprints.add(gate)
            self._data["manual_login_waited_gate_fingerprints"] = sorted(fingerprints)

    def mark_login_timed_out(self) -> None:
        self._data["manual_login_verified"] = False
        self._data["manual_login_timed_out"] = True
        self._data["login_status"] = LoginStatus.TIMED_OUT.value

    def mark_login_verified(self, *, source: str) -> None:
        if not source:
            raise ValueError("login verification requires an evidence source")
        self._data["manual_login_verified"] = True
        self._data["manual_login_timed_out"] = False
        self._data["login_status"] = LoginStatus.VERIFIED.value
        self._data["login_verification_source"] = source

    def record_permission_allow_result(
        self,
        *,
        permission: str,
        selected_permissions: list[str] | tuple[str, ...],
        states: dict[str, bool | None],
    ) -> PermissionVerification:
        selected = tuple(str(item) for item in selected_permissions if item)
        verified = bool(selected) and all(states.get(item) is True for item in selected)
        result = PermissionVerification(
            permission=str(permission or ""),
            requested_action="allow",
            selected_permissions=selected,
            states=dict(states),
            verified=verified,
        )
        self._data["last_permission_verification"] = {
            "permission": result.permission,
            "requested_action": result.requested_action,
            "selected_permissions": list(result.selected_permissions),
            "states": result.states,
            "verified": result.verified,
        }
        self._data["permission_allow_verified"] = result.verified
        return result
