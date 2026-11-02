"""Deterministic sibling-aware decisions for privacy/account/redress hubs."""
from __future__ import annotations

from dataclasses import dataclass

from agent.ai_explorer.decision_directive import DecisionDirective


@dataclass(frozen=True)
class HubDecisionInput:
    permission_only_phase: bool = False
    deny_probe_outstanding: bool = False
    media_probe: str = ""
    permission_drill_target: str = ""
    unread_document: str = ""
    document_kind: str = ""
    privacy_row: str = ""
    drill_target: str = ""
    logout_entry: str = ""
    progress_target: str = ""
    progress_is_media: bool = False
    progress_is_drill: bool = False
    scrolls: int = 0
    checklist_complete: bool = False


@dataclass(frozen=True)
class HubProgressCandidates:
    """Pre-classified hub routes; selection is owned outside the Appium loop."""

    capture: str = ""
    album: str = ""
    privacy: str = ""
    drill: str = ""
    unread: str = ""
    avatar: str = ""
    logout: str = ""
    fallback: str = ""
    deny_probe_outstanding: bool = False


class SettingsHubNavigator:
    """Choose one DFS edge from a settings/profile hub without touching Appium."""

    def next_target(self, facts: HubProgressCandidates) -> str | None:
        ordered = (
            facts.capture,
            facts.album,
            facts.privacy,
            facts.drill,
            facts.unread,
            facts.avatar if facts.deny_probe_outstanding else "",
            facts.logout,
            facts.avatar,
            facts.fallback,
        )
        return next((target for target in ordered if target), None)


@dataclass(frozen=True)
class HubScrollResult:
    attempts: int
    moved: bool
    exhausted: bool


class SettingsHubScrollPolicy:
    """Own retry/exhaustion semantics for a hub list; Appium only performs swipe."""

    def __init__(self, *, max_scrolls: int = 3) -> None:
        self.max_scrolls = max(1, int(max_scrolls))

    def observe(self, *, attempts: int, moved: bool) -> HubScrollResult:
        next_attempts = max(0, int(attempts)) + 1
        return HubScrollResult(
            attempts=next_attempts,
            moved=bool(moved),
            exhausted=next_attempts >= self.max_scrolls,
        )


class HubDecisionModule:
    """Own hub priority while exposing scroll as an explicit orchestration effect."""

    def propose_already_read_redirect(self, *, target: str) -> DecisionDirective | None:
        """Continue hub coverage after a document route was already read."""
        if not target:
            return None
        return DecisionDirective(
            "click", target,
            "已读条款不再打开，改点设置页上尚未访问的注销/授权入口",
            "deterministic_privacy_hub",
            priority=150,
        )

    def propose_next_hub_row(self, *, target: str) -> DecisionDirective | None:
        """Continue with another unseen hub row after the document route was read."""
        if not target:
            return None
        return DecisionDirective(
            "click", target,
            "已读条款不再打开，改点设置页其他未访问行",
            "deterministic_privacy_hub",
            priority=150,
        )

    def propose_consent_after_documents(self, *, target: str) -> DecisionDirective | None:
        """Allow consent only after the visible required documents were read."""
        if not target:
            return None
        return DecisionDirective(
            "click", target,
            "可见条款均已阅读，点击同意进入应用继续检测",
            "deterministic_consent",
            priority=150,
        )

    def propose_redress_entry(self, *, target: str, route_key: str) -> DecisionDirective | None:
        if not target:
            return None
        return DecisionDirective(
            "click", target,
            "发现投诉/举报/反馈/帮助支持/工单等救济入口，进入后核验上传、拍照、相册、语音等是否触发权限申请",
            "deterministic_scenario", "customer_service_entry_prioritized",
            {"redress_route_key": route_key, "scenario_items": ["4.2", "6.3"]},
        )

    def propose_hub_tab(self, *, target: str) -> DecisionDirective | None:
        if not target:
            return None
        return DecisionDirective(
            "click", target,
            "优先进入底部设置/我的枢纽，核验撤回同意、协议与账号入口",
            "deterministic_privacy_hub", "privacy_hub_tab_prioritized",
            runtime_updates={"privacy_hub_visited": True},
        )

    def propose(
        self, facts: HubDecisionInput, *, include_terminal: bool = True,
    ) -> DecisionDirective | None:
        if facts.media_probe and facts.deny_probe_outstanding:
            return self._media(facts.media_probe, "设置/资料页优先触发头像或拍照/相册，核验 2.3/4.2 权限与拒权后果")
        if facts.permission_only_phase and facts.permission_drill_target:
            return DecisionDirective(
                "click", facts.permission_drill_target,
                "允许权限阶段仅回放个人资料/反馈等权限相关入口，不重复文档、注销和普通资料路径",
                "deterministic_permission_phase", "permission_phase_route_prioritized",
            )
        if facts.unread_document and not facts.permission_only_phase:
            return DecisionDirective(
                "click", facts.unread_document,
                "设置枢纽上仍有未读隐私政策/协议/清单，先完整阅读，再继续其它非拒权路径",
                "deterministic_document", "required_document_prioritized",
                {"document_kind": facts.document_kind},
            )
        if facts.privacy_row and not facts.permission_only_phase:
            return DecisionDirective(
                "click", facts.privacy_row,
                "设置页优先进入可见的注销/授权撤回入口，核验 3.8/6.1",
                "deterministic_privacy_hub", "privacy_path_row_prioritized",
            )
        if facts.drill_target and not facts.permission_only_phase:
            return DecisionDirective(
                "click", facts.drill_target,
                "个人中心壳页先进入设置/关于我们，再核验注销、协议与退出登录",
                "deterministic_privacy_hub", "hub_settings_drill_prioritized",
                runtime_updates={"hub_settings_drilled": True},
            )
        if facts.media_probe:
            return self._media(facts.media_probe, "合规文档已读，继续触发头像或拍照/相册，核验权限申请与业务后果")
        if facts.logout_entry:
            return DecisionDirective(
                "click", facts.logout_entry,
                "点开退出登录确认框核验流程边界，不提交退出以保留会话",
                "deterministic_privacy_hub", "logout_entry_exploration_prioritized",
            )
        if not include_terminal:
            return None
        if facts.progress_target and not facts.permission_only_phase:
            updates = {"hub_settings_drilled": True} if facts.progress_is_drill else {}
            effects = ("revoke_media_permissions",) if facts.progress_is_media else ()
            return DecisionDirective(
                "click", facts.progress_target,
                "设置/个人信息页条款可能已读，继续核验头像/上传或其它合规入口",
                "deterministic_privacy_hub", "hub_progress_prioritized",
                runtime_updates=updates, effects=effects,
            )
        if facts.permission_only_phase:
            return DecisionDirective(
                "back", "", "允许权限阶段当前枢纽已无权限相关入口，返回继续其它权限触发路径",
                "deterministic_permission_phase",
            )
        if facts.scrolls >= 3 and facts.checklist_complete:
            return DecisionDirective(
                "wait", "", "枢纽必选行已尝试且滚动足够，结束本枢纽空转",
                "deterministic_privacy_hub", "privacy_hub_path_exhausted",
                runtime_updates={"privacy_hub_search_exhausted": True},
                effects=("no_action",),
            )
        return None

    @staticmethod
    def _media(target: str, reason: str) -> DecisionDirective:
        return DecisionDirective(
            "click", target, reason, "deterministic_privacy_hub",
            "hub_media_probe_prioritized", effects=("revoke_media_permissions",),
        )
