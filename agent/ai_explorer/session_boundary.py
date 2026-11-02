"""Pure candidates for account/session-destroying navigation boundaries."""
from __future__ import annotations

from agent.ai_explorer.decision_directive import DecisionDirective


class SessionBoundaryPolicy:
    """Preserve the session before any logout-confirmation exploration."""

    def observation_only_directive(
        self,
        *,
        action: str,
        target: str,
        is_logout_target: bool,
        explore_confirmation: bool,
        replacement: str = "",
    ) -> DecisionDirective | None:
        if (
            str(action or "") != "click"
            or not str(target or "")
            or not is_logout_target
            or explore_confirmation
        ):
            return None
        if replacement:
            return DecisionDirective(
                "click", replacement,
                "退出登录入口默认只记录，改走当前页其它可逆合规或敏感业务入口",
                "safety_boundary", priority=150,
                effects=("mark_session_boundary_observed",),
            )
        return DecisionDirective(
            "back", "", "退出登录入口默认只记录，返回上一级继续探索并保留会话",
            "safety_boundary", priority=150,
            effects=("mark_session_boundary_observed",),
        )

    def defer_for_deny_probe(
        self,
        *,
        action: str,
        target: str,
        deny_probe_outstanding: bool,
        is_session_boundary: bool,
        replacement: str = "",
    ) -> DecisionDirective | None:
        if (
            str(action or "") != "click"
            or not str(target or "")
            or not deny_probe_outstanding
            or not is_session_boundary
        ):
            return None
        if replacement:
            return DecisionDirective(
                "click", replacement,
                "拒绝权限场景尚未完成，先触发可见的敏感业务入口，再处理可能破坏会话的账号边界",
                "deny_permission_priority", priority=150,
                effects=("mark_session_boundary_deferred",),
            )
        return DecisionDirective(
            "back", "",
            "拒绝权限场景尚未完成，延后退出/注销入口并返回上一级寻找其它敏感业务路径",
            "deny_permission_priority", priority=150,
            effects=("mark_session_boundary_deferred",),
        )

    def destructive_confirmation_directive(
        self, *, action: str, target: str, is_destructive_confirmation: bool,
    ) -> DecisionDirective | None:
        if (
            str(action or "") != "click"
            or not str(target or "")
            or not is_destructive_confirmation
        ):
            return None
        return DecisionDirective(
            "back", "", "已到达注销/删除确认页，按无损策略返回",
            "safety_boundary", priority=150,
            effects=("record_destructive_confirmation_blocked",),
        )

    def logout_confirmation_directive(
        self, *, action: str, target: str, is_logout_confirmation: bool,
    ) -> DecisionDirective | None:
        if (
            str(action or "") != "click"
            or not str(target or "")
            or not is_logout_confirmation
        ):
            return None
        return DecisionDirective(
            "back", "", "已观察退出登录确认边界，保留当前会话并返回继续检测",
            "safety_boundary", priority=150,
            runtime_updates={
                "logout_confirmation_observed": True,
                "logout_entry_explored": True,
            },
            effects=("record_logout_confirmation_blocked",),
        )

    def repeated_logout_directive(
        self,
        *,
        action: str,
        target: str,
        is_logout_target: bool,
        already_explored: bool,
        source: str,
    ) -> DecisionDirective | None:
        if (
            str(action or "") != "click"
            or not str(target or "")
            or not is_logout_target
            or not already_explored
            or str(source or "") in {"deterministic_privacy_hub", "deterministic_scenario"}
        ):
            return None
        return DecisionDirective(
            "back", "", "退出登录边界已核验，保留会话并返回继续检测",
            "safety_boundary", priority=150,
            effects=("record_repeated_logout_blocked",),
        )
