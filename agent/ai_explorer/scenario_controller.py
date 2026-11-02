"""Ordered, evidence-driven execution of device-side legal scenarios."""
from __future__ import annotations

from dataclasses import dataclass

from agent.rule_engine.scenario_execution import ScenarioExecution, ScenarioExecutionLedger


@dataclass(frozen=True)
class ScenarioTemplate:
    item: str
    goal: str
    milestones: tuple[str, ...]
    same_target_from: int | None = None


@dataclass(frozen=True)
class ScenarioTransition:
    accepted: bool
    item: str
    event: str
    reason: str = ""


_TEMPLATES = {
    "4.2": ScenarioTemplate(
        item="4.2",
        goal="拒绝权限后重试同一业务功能并比较结果",
        milestones=(
            "permission_prompt", "permission_denied",
            "business_action_retried", "function_blocked",
        ),
        same_target_from=0,
    ),
    "3.8": ScenarioTemplate(
        item="3.8",
        goal="核验撤回同意或授权入口",
        milestones=("withdraw_entry_observed",),
    ),
}


class ScenarioController:
    def __init__(self, templates: list[ScenarioTemplate]) -> None:
        self._templates = {template.item: template for template in templates}
        self._ledger = ScenarioExecutionLedger([
            {"item": template.item, "goal": template.goal, "executor": "device"}
            for template in templates
        ])
        self._positions = {template.item: 0 for template in templates}
        self._semantic_targets: dict[str, str] = {}

    @classmethod
    def for_items(cls, items: list[str] | tuple[str, ...]) -> "ScenarioController":
        templates = [
            _TEMPLATES[item] for item in (str(value) for value in items)
            if item in _TEMPLATES
        ]
        return cls(templates)

    def execution(self, item: str) -> ScenarioExecution | None:
        # Keep phase-local controllers safe for diagnostic callers too; an
        # omitted scenario is a normal cross-phase condition, not a dict bug.
        return self._ledger.executions.get(str(item))

    def observe(
        self, event: str, *, item: str, target: str = "", source: str,
        direct_outcome: bool = False,
    ) -> ScenarioTransition:
        item = str(item)
        event = str(event)
        template = self._templates.get(item)
        if template is None:
            # Shared explorer callbacks can outlive a phase-local controller
            # (for example 1.2 emitted while the 4.2 controller is active).
            # Such an observation is irrelevant to this controller, not a
            # malformed state transition that should crash the worker.
            return ScenarioTransition(False, item, event, "scenario_not_planned")
        position = self._positions[item]
        if position >= len(template.milestones):
            return ScenarioTransition(False, item, event, "scenario_already_terminal")
        expected = template.milestones[position]
        direct_terminal = bool(
            direct_outcome
            and item == "4.2"
            and event == "function_blocked"
            and expected == "business_action_retried"
        )
        if event != expected and not direct_terminal:
            return ScenarioTransition(False, item, event, f"expected:{expected}")
        normalized_target = str(target or "").strip()
        if template.same_target_from is not None:
            anchor = self._semantic_targets.get(item, "")
            if position == template.same_target_from and normalized_target:
                self._semantic_targets[item] = normalized_target
            elif anchor and normalized_target and normalized_target != anchor:
                return ScenarioTransition(False, item, event, "semantic_target_changed")
        if position == 0:
            self._ledger.begin(item, target=normalized_target)
        is_final = direct_terminal or position == len(template.milestones) - 1
        if is_final:
            self._ledger.observe_evidence(item, source=source)
        else:
            self._ledger.observe_step(
                item, step=event, source=source, target=normalized_target,
            )
        self._positions[item] = len(template.milestones) if direct_terminal else position + 1
        return ScenarioTransition(True, item, event)
