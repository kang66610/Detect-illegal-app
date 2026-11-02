"""Stateful decision module for the post-entry SDK observation checkpoint."""
from __future__ import annotations

from dataclasses import dataclass

from agent.ai_explorer.decision_directive import DecisionDirective


@dataclass(frozen=True)
class SdkObservationInput:
    pending: bool
    eligible: bool
    content_tab: str = ""
    quiet_main: bool = False
    settings_hub: bool = False
    is_root: bool = False
    back_attempts: int = 0
    wait_attempts: int = 0
    dwell_seconds: float = 0.0
    armed: bool = False


@dataclass(frozen=True)
class SdkObservationGateFacts:
    """Allow-phase conditions for granting collection-observation permissions."""

    probe_profile: str = ""
    already_granted: bool = False
    consent_dialog_visible: bool = False
    permission_prompt_visible: bool = False
    consent_seen: bool = False
    consent_accepted: bool = False
    foreign_start_surface: bool = False
    consent_timestamp_ms: int = 0
    post_consent_window_ms: int = 30000
    permission_prompt_seen_after_consent: bool = False
    public_surface_seen: bool = False
    now_ms: int = 0


class SdkObservationGate:
    """Own when the allow phase may grant phone/location for observation."""

    def should_enter(self, facts: SdkObservationGateFacts) -> bool:
        if facts.probe_profile and facts.probe_profile != "allow":
            return False
        if facts.already_granted:
            return False
        if facts.consent_dialog_visible or facts.permission_prompt_visible:
            return False
        if facts.consent_seen and not facts.consent_accepted:
            return False
        if facts.foreign_start_surface:
            return False
        if facts.consent_timestamp_ms:
            elapsed = facts.now_ms - facts.consent_timestamp_ms
            if elapsed < facts.post_consent_window_ms and not facts.permission_prompt_seen_after_consent:
                return False
        elif not facts.public_surface_seen:
            return False
        return True


def grant_observation_permissions(device, package_name: str, permissions) -> list[str]:
    """Grant the APK permission list once; returns the granted permission ids."""
    grant = getattr(device, "grant_runtime_permissions", None)
    if callable(grant) and package_name:
        return list(grant(package_name, list(permissions or [])))
    return []


class SdkObservationDecisionModule:
    """Own the bounded main-content dwell gate without blocking other modules forever."""

    def propose(self, facts: SdkObservationInput) -> DecisionDirective | None:
        if not facts.pending or not facts.eligible:
            return None
        if facts.quiet_main:
            return DecisionDirective(
                "observe", "", "已在主内容页，停留以便观察 SDK 采集",
                "deterministic_sdk_observe", "sdk_observation_dwelled",
                {"seconds": facts.dwell_seconds, "armed": facts.armed},
                {"sdk_observation_dwell_done": True, "sdk_observation_dwell_armed": False},
                effects=("perform_sdk_dwell", "continue_loop"),
            )
        if facts.content_tab and not facts.settings_hub:
            return DecisionDirective(
                "click", facts.content_tab,
                "进入应用后先打开主内容页并停留，观察 SDK 采集后再去设置/协议",
                "deterministic_sdk_observe", "sdk_observation_tab_prioritized",
                runtime_updates={"sdk_observation_dwell_armed": True},
            )
        if facts.settings_hub and not facts.is_root and facts.back_attempts < 2 and facts.content_tab:
            return DecisionDirective(
                "back", "", "先返回应用主界面观察 SDK 采集，再阅读设置中的协议",
                "deterministic_sdk_observe", "sdk_observation_return_to_main",
                runtime_increments={"sdk_observe_backs": 1},
            )
        if facts.dwell_seconds <= 0:
            return DecisionDirective(
                "observe", "", "SDK 观察停留时间为零，结束观察门闩",
                "deterministic_sdk_observe",
                runtime_updates={"sdk_observation_dwell_done": True, "sdk_observation_dwell_armed": False},
                effects=("no_action",),
            )
        if facts.wait_attempts + 1 >= 2 or facts.settings_hub:
            return DecisionDirective(
                "observe", "", "无法进入可静默观察的主内容页，结束 SDK 观察门闩",
                "deterministic_sdk_observe", "sdk_observation_dwell_skipped",
                runtime_updates={"sdk_observation_dwell_done": True, "sdk_observation_dwell_armed": False},
                runtime_increments={"sdk_observe_waits": 1}, effects=("no_action",),
            )
        return DecisionDirective(
            "wait", "", "SDK 静默观察未完成，暂留当前页不进入设置/客服/LLM 探索",
            "deterministic_sdk_observe", runtime_increments={"sdk_observe_waits": 1},
        )
