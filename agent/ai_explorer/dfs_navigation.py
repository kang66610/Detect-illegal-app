"""Pure DFS/backtracking policy for the Appium traversal loop."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DfsNavigationStep(str, Enum):
    NONE = "none"
    EXPLORE_SIBLING = "explore_sibling"
    SCROLL = "scroll"


@dataclass(frozen=True)
class DfsNavigationInput:
    deep_mode: bool
    current_action: str
    role: str
    decision_source: str
    sibling_target: str = ""
    can_scroll: bool = False
    scroll_attempts: int = 0
    max_scrolls: int = 0
    consent_blocked: bool = False
    pre_app_entry: bool = False
    settings_hub: bool = False


@dataclass(frozen=True)
class DfsNavigationDirective:
    step: DfsNavigationStep
    target: str = ""
    reason: str = ""


class DfsNavigationPolicy:
    """Select the next safe DFS move without accessing Appium state."""

    _EXIT_ACTIONS = frozenset({"back", "stop", "wait"})
    _BLOCKED_SOURCES = frozenset({
        "frontier_recovery", "coverage_recovery", "coverage_pruning",
        "crash_route_recovery", "stale_action_recovery", "safety_boundary",
        "already_read_document", "deterministic_privacy_hub",
        "deterministic_consent", "deterministic_consent_checkbox",
    })
    _BLOCKED_ROLES = frozenset({"consent_dialog", "document_body", "login_gate"})

    def decide(self, facts: DfsNavigationInput) -> DfsNavigationDirective:
        if not facts.deep_mode or str(facts.current_action or "") not in self._EXIT_ACTIONS:
            return DfsNavigationDirective(DfsNavigationStep.NONE)
        role = str(facts.role or "")
        if (
            role in self._BLOCKED_ROLES
            or role.startswith("low_value_")
            or facts.consent_blocked
            or facts.pre_app_entry
        ):
            return DfsNavigationDirective(DfsNavigationStep.NONE)
        if facts.sibling_target and str(facts.decision_source or "") not in self._BLOCKED_SOURCES:
            return DfsNavigationDirective(
                DfsNavigationStep.EXPLORE_SIBLING,
                target=str(facts.sibling_target),
                reason="深度搜索：当前页面仍有未访问的可逆兄弟入口，先探索再决定回退",
            )
        if (
            not facts.settings_hub
            and facts.can_scroll
            and int(facts.scroll_attempts) < max(1, int(facts.max_scrolls))
        ):
            return DfsNavigationDirective(
                DfsNavigationStep.SCROLL,
                reason="当前可见入口已无推进，滚动发现折叠区以下的新兄弟入口",
            )
        return DfsNavigationDirective(DfsNavigationStep.NONE)
