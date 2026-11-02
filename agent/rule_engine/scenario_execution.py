"""Stateful ownership of legal-rule Scenario executions."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExecutionState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    EVIDENCE_OBSERVED = "evidence_observed"
    NO_VIOLATION_EVIDENCE = "no_violation_evidence"
    BLOCKED_LOGIN = "requires_login"
    BLOCKED_EXTERNAL = "blocked_external"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_SERVER_AUDIT = "requires_server_audit"


TERMINAL_EXECUTION_STATES = {
    ExecutionState.EVIDENCE_OBSERVED,
    ExecutionState.NO_VIOLATION_EVIDENCE,
    ExecutionState.BLOCKED_LOGIN,
    ExecutionState.BLOCKED_EXTERNAL,
    ExecutionState.NOT_APPLICABLE,
    ExecutionState.REQUIRES_SERVER_AUDIT,
}


@dataclass
class ScenarioExecution:
    item: str
    goal: str
    executor: str = "device"
    state: ExecutionState = ExecutionState.PENDING
    step: str = "discover"
    attempts: int = 0
    targets: list[str] = field(default_factory=list)
    evidence_sources: list[str] = field(default_factory=list)
    reason: str = "尚未执行对应的自动化检测场景"
    route_checkpoint: dict = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_EXECUTION_STATES


class ScenarioExecutionLedger:
    """Own transitions; callers cannot mark a scenario complete without evidence."""

    def __init__(self, plan: list[dict]):
        self.executions: dict[str, ScenarioExecution] = {}
        for row in plan:
            executor = str(row.get("executor") or "device")
            state = (
                ExecutionState.REQUIRES_SERVER_AUDIT
                if executor == "server" else ExecutionState.PENDING
            )
            reason = (
                "需要导入服务端审计事件后核验"
                if executor == "server" else "尚未执行对应的自动化检测场景"
            )
            item = str(row["item"])
            self.executions[item] = ScenarioExecution(
                item=item, goal=str(row.get("goal") or ""), executor=executor,
                state=state, reason=reason,
            )

    def begin(self, item: str, *, target: str = "", route_checkpoint: dict | None = None) -> ScenarioExecution | None:
        execution = self.executions.get(str(item))
        if execution is None:
            return None
        if execution.terminal:
            return execution
        execution.state = ExecutionState.ACTIVE
        execution.attempts += 1
        execution.step = "target_selected"
        execution.reason = "已选择可见、安全的目标，等待页面或行为证据"
        if target and target not in execution.targets:
            execution.targets.append(target)
        if route_checkpoint:
            execution.route_checkpoint = dict(route_checkpoint)
        return execution

    def advance(self, item: str, *, step: str, reason: str = "") -> ScenarioExecution | None:
        execution = self.executions.get(str(item))
        if execution is None:
            return None
        if not execution.terminal:
            execution.state = ExecutionState.ACTIVE
            execution.step = str(step)
            if reason:
                execution.reason = str(reason)
        return execution

    def observe_step(
        self, item: str, *, step: str, source: str, target: str = "",
    ) -> ScenarioExecution | None:
        """Record non-terminal ordered evidence without claiming completion."""
        execution = self.executions.get(str(item))
        if execution is None:
            return None
        if not source:
            raise ValueError("scenario step requires an evidence source")
        if execution.terminal:
            return execution
        execution.state = ExecutionState.ACTIVE
        execution.step = str(step)
        execution.reason = "已取得中间步骤证据，继续执行完整场景"
        if target and target not in execution.targets:
            execution.targets.append(target)
        if source not in execution.evidence_sources:
            execution.evidence_sources.append(source)
        return execution

    def observe_evidence(self, item: str, *, source: str) -> ScenarioExecution | None:
        execution = self.executions.get(str(item))
        if execution is None:
            return None
        if not source:
            raise ValueError("scenario completion requires an evidence source")
        execution.state = ExecutionState.EVIDENCE_OBSERVED
        execution.step = "evidence_observed"
        execution.reason = "已取得该场景对应的设备侧观察证据"
        if source not in execution.evidence_sources:
            execution.evidence_sources.append(source)
        return execution

    def block(self, item: str, *, state: str, reason: str) -> ScenarioExecution | None:
        execution = self.executions.get(str(item))
        if execution is None:
            return None
        if execution.state is ExecutionState.EVIDENCE_OBSERVED:
            return execution
        execution.state = ExecutionState(state)
        execution.step = "terminal"
        execution.reason = str(reason)
        return execution

    def outstanding(self) -> list[str]:
        return [item for item, execution in self.executions.items() if not execution.terminal]

    def row(self, item: str) -> dict | None:
        """Return a serialisable scenario row without raising on unknown ids.

        Scenario ids may come from an LLM proposal, a stale checkpoint, or a
        newer rule catalog.  An unknown id is an out-of-plan observation, not
        a worker-fatal condition, so callers receive ``None`` and can record
        the event explicitly.
        """
        execution = self.executions.get(str(item))
        if execution is None:
            return None
        return {
            "item": execution.item,
            "goal": execution.goal,
            "state": (
                "attempted" if execution.state is ExecutionState.ACTIVE else execution.state.value
            ),
            "reason": execution.reason,
            "attempts": execution.attempts,
            "targets": list(execution.targets),
            "evidence_sources": list(execution.evidence_sources),
            "executor": execution.executor,
            "step": execution.step,
        }
