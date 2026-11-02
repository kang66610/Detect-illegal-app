"""Pure progression policy for permission-impact scenarios."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionScenarioStep(str, Enum):
    NONE = "none"
    START_DENIAL_PROBE = "start_denial_probe"
    RETRY_BUSINESS_ACTION = "retry_business_action"
    MARK_BLOCKED = "mark_blocked"
    MARK_SUBFEATURE_ONLY = "mark_subfeature_only"
    MARK_UNCONFIRMED = "mark_unconfirmed"


@dataclass(frozen=True)
class PermissionScenarioInput:
    prompt_visible: bool = False
    response_action: str = ""
    active_probe: bool = False
    business_target: str = ""
    target_visible: bool = False
    retry_attempted: bool = False
    denial_blocked: bool = False
    denial_subfeature_only: bool = False
    remaining_steps: int = 0


@dataclass(frozen=True)
class PermissionScenarioDirective:
    step: PermissionScenarioStep
    target: str = ""


class PermissionScenarioPolicy:
    """Decide scenario state transitions; Appium performs any resulting click."""

    def decide(self, facts: PermissionScenarioInput) -> PermissionScenarioDirective:
        target = str(facts.business_target or "")
        if facts.prompt_visible:
            if str(facts.response_action or "").lower() == "deny" and target:
                return PermissionScenarioDirective(
                    PermissionScenarioStep.START_DENIAL_PROBE, target,
                )
            return PermissionScenarioDirective(PermissionScenarioStep.NONE)
        if not facts.active_probe:
            return PermissionScenarioDirective(PermissionScenarioStep.NONE)
        if facts.denial_blocked and target:
            return PermissionScenarioDirective(PermissionScenarioStep.MARK_BLOCKED, target)
        if facts.denial_subfeature_only:
            return PermissionScenarioDirective(PermissionScenarioStep.MARK_SUBFEATURE_ONLY, target)
        if target and facts.target_visible and not facts.retry_attempted:
            return PermissionScenarioDirective(
                PermissionScenarioStep.RETRY_BUSINESS_ACTION, target,
            )
        if int(facts.remaining_steps) <= 0:
            return PermissionScenarioDirective(PermissionScenarioStep.MARK_UNCONFIRMED, target)
        return PermissionScenarioDirective(PermissionScenarioStep.NONE)
