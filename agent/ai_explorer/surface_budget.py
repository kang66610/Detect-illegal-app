"""Traversal budgets for pages and routes that cannot advance privacy coverage."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SurfaceBudgetDecision:
    action: str
    reason: str
    first_observation: bool


class SurfaceBudgetPolicy:
    """Persist semantic-surface observations and produce one bounded exit."""

    def __init__(self, runtime: dict) -> None:
        self.runtime = runtime

    def leave_low_value(self, *, surface_key: str, surface_kind: str, is_root: bool) -> SurfaceBudgetDecision:
        observations = self.runtime.setdefault("low_value_surface_observations", {})
        count = int(observations.get(surface_key, 0)) + 1
        observations[surface_key] = count
        return SurfaceBudgetDecision(
            action="stop" if is_root else "back",
            reason=(
                f"{surface_kind} 页面不推进隐私、权限、撤回/注销或投诉反馈覆盖；"
                "保留一次观察后返回其它安全路径"
            ),
            first_observation=count == 1,
        )

    def route_replacement(self, *, useful_sibling: str = "") -> dict:
        if useful_sibling:
            return {
                "action": "click", "target": useful_sibling,
                "reason": "剪枝低审计价值入口，改查同页其它合规相关路径",
            }
        return {
            "action": "back", "target": "",
            "reason": "低审计价值入口不能推进规则覆盖，返回继续其它路径",
        }

    def record_global_target_attempt(self, global_key: str) -> int:
        """Own the global retry counter; the legacy runtime key stays a projection."""
        attempts = self.runtime.setdefault("global_target_attempts", {})
        key = str(global_key)
        attempts[key] = int(attempts.get(key, 0)) + 1
        return attempts[key]

    def raise_global_target_floor(self, global_key: str, *, minimum: int) -> int:
        attempts = self.runtime.setdefault("global_target_attempts", {})
        key = str(global_key)
        attempts[key] = max(int(minimum), int(attempts.get(key, 0)))
        return attempts[key]

    def record_root_route_attempt(self, route_key: str) -> int:
        routes = self.runtime.setdefault("root_route_attempts", {})
        key = str(route_key)
        routes[key] = int(routes.get(key, 0)) + 1
        return routes[key]
