"""真实 Appium + LLM 页面遍历引擎。"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path

from agent.ai_explorer.appium_client import AppiumClient
from agent.ai_explorer.action_arbitration import ActionProposal, DecisionAudit
from agent.ai_explorer.action_pipeline import ActionPipeline
from agent.ai_explorer.action_executor import ActionExecutor
from agent.ai_explorer.page_evidence import (
    PageEvidenceBuilder,
    PageEvidenceInput,
    PageEvidenceSignals,
)
from agent.ai_explorer.target_catalog import (
    TargetCatalogView, TargetKind, bounds_retry_target,
    llm_catalog_elements, matching_elements,
    global_target_key as _global_target_key,
    identity_values_for_target as _target_identity_values,
    labels_for_click_target as _labels_for_click_target,
)
from agent.ai_explorer.action_safety_checks import (
    DESTRUCTIVE_CONFIRM_TERMS, SafetyCheckFacts, SafetyChecks, bounds_tuple,
    is_destructive_confirmation, is_low_audit_value_route,
    is_stale_or_invisible_target, is_transaction_target,
    is_unlabelled_structural_bounds_target,
    NON_AUDIT_MAINTENANCE_TERMS as _NON_AUDIT_MAINTENANCE_TERMS,
)
from agent.ai_explorer.document_state import (
    CombinedDocumentRedirectPolicy,
    DOCUMENT_KIND_ID_HINTS as _DOCUMENT_KIND_ID_HINTS,
    DOCUMENT_TITLE_GROUPS as _DOCUMENT_TITLE_GROUPS,
    REQUIRED_DOCUMENT_KIND_TERMS as _REQUIRED_DOCUMENT_KIND_TERMS,
    already_read_document_target as _already_read_document_target,
    block_document_route as _block_document_route,
    blocked_document_kinds as _blocked_document_kinds,
    click_reopens_incomplete_document as _click_reopens_incomplete_document,
    clickable_host_for_document_kind as _clickable_host_for_document_kind,
    consent_document_titles as _consent_document_titles,
    consent_instruction_label as _is_consent_instruction_label,
    document_body_kind_from_text as _document_body_kind_from_text,
    document_kinds_in as _document_kinds_in,
    document_session_already_read as _document_session_already_read,
    document_title_already_read as _document_title_already_read,
    element_label as _element_label,
    exhausted_document_kinds as _exhausted_document_kinds,
    failed_inline_document_kinds as _failed_inline_document_kinds,
    failed_inline_document_titles as _failed_inline_document_titles,
    host_is_unsafe_document_click as _host_is_unsafe_document_click,
    inline_document_title_is_safe as _inline_document_title_is_safe,
    infer_document_kind as _infer_document_kind,
    inline_document_titles_in as _inline_document_titles_in,
    kind_has_direct_clickable_entry as _kind_has_direct_clickable_entry,
    normalize_document_title as _normalize_document_title,
    note_failed_inline_document as _note_failed_inline_document,
    preferred_inline_document_target as _preferred_inline_document_target,
    prune_unread_document_gaps as _prune_unread_document_gaps,
    quoted_or_exact_document_titles as _quoted_or_exact_document_titles,
    read_document_kinds as _read_document_kinds,
    read_document_titles as _read_document_titles,
    handle_consent_document_crash_retry as _handle_consent_document_crash_retry,
    reconcile_document_completion_route as _reconcile_document_completion_route,
    pending_document_route_retry as _pending_document_route_retry,
    remember_consent_document_titles as _remember_consent_document_titles,
    required_document_kind as _required_document_kind,
    skip_already_read_document as _skip_already_read_document,
    tightest_enclosing_clickable as _tightest_enclosing_clickable,
    unread_document_gap_resolved as _unread_document_gap_resolved,
    unread_for_page as _unread_for_page,
    unread_inline_titles_for_target as _unread_inline_titles_for_target,
    unread_remembered_consent_title as _unread_remembered_consent_title,
    unread_required_document_target as _unread_required_document_target,
    visible_required_document_titles as _visible_required_document_titles,
)
from agent.ai_explorer.consent_vocabulary import (
    AUTHENTICATED_LOGOUT_TERMS as _AUTHENTICATED_LOGOUT_TERMS,
    CONSENT_BUTTON_IDS as _CONSENT_BUTTON_IDS,
    CONSENT_DIALOG_HUB_EXCLUSION_TERMS as _CONSENT_DIALOG_HUB_EXCLUSION_TERMS,
    CONSENT_TERMS as _CONSENT_TERMS,
    DECLINE_BUTTON_IDS as _DECLINE_BUTTON_IDS,
    DECLINE_TERMS as _DECLINE_TERMS,
    DOCUMENT_TERMS as _DOCUMENT_TERMS,
    LOGIN_SURFACE_CLASSIFIER as _LOGIN_SURFACE_CLASSIFIER,
    POLICY_TERMS as _POLICY_TERMS,
    PRIVACY_DIALOG_BUTTON_IDS as _PRIVACY_DIALOG_BUTTON_IDS,
    authenticated_logout_target as _is_authenticated_logout_target,
    consent_or_decline_control as _is_consent_or_decline_control,
    entry_choice_bypass_target as _entry_choice_bypass_target,
    explicit_consent_target as _explicit_consent_target,
    id_matches_any_hint as _id_matches_any_hint,
    is_checkbox_like as _is_checkbox_like,
    is_consent_dialog as _is_consent_dialog,
    is_short_decline_label as _is_short_decline_label,
    login_bypass_target as _login_bypass_target,
    prechecked_consent_checkbox as _prechecked_consent_checkbox,
    resource_id_matches_hint as _resource_id_matches_hint,
    short_control_label as _short_control_label,
    target_has_decline_semantics as _target_has_decline_semantics,
    unchecked_consent_checkbox as _unchecked_consent_checkbox,
)
from agent.ai_explorer.hub_navigation import (
    HUB_DISTRACTOR_TERMS as _HUB_DISTRACTOR_TERMS,
    HUB_EXPLORATION_ROW_TERMS as _HUB_EXPLORATION_ROW_TERMS,
    MAIN_CONTENT_TAB_PRIORITY as _MAIN_CONTENT_TAB_PRIORITY,
    MAIN_CONTENT_TAB_TERMS as _MAIN_CONTENT_TAB_TERMS,
    hub_avatar_probe_target as _hub_avatar_probe_target,
    hub_drill_target as _hub_drill_target,
    hub_privacy_action_target as _hub_privacy_action_target,
    hub_progress_target as _hub_progress_target,
    identity_is_hub_distractor as _identity_is_hub_distractor,
    is_bottom_nav_hub_tab as _is_bottom_nav_hub_tab,
    is_top_level_navigation_target as _is_top_level_navigation_target,
    logout_entry_exploration_target as _logout_entry_exploration_target,
    main_content_tab_target as _main_content_tab_target,
    next_hub_exploration_target as _next_hub_exploration_target,
    next_top_level_audit_target as _next_top_level_audit_target_def,
    observe_logout_rows_without_clicking as _observe_logout_rows_without_clicking,
    privacy_hub_tab_target as _privacy_hub_tab_target,
    target_is_hub_reentry as _target_is_hub_reentry,
)
from agent.ai_explorer.llm_controller import LLMController
from agent.ai_explorer.navigation_state import classify_navigation_surface
from agent.ai_explorer.dfs_navigation import (
    DfsNavigationInput, DfsNavigationPolicy, DfsNavigationStep,
)
from agent.ai_explorer.page_state import NavigationReplayEdge, PageState, parse_page
from agent.ai_explorer.navigation_replay import (
    NavigationReplaySafety, replay_navigation_route,
)
from agent.ai_explorer.runtime_state import DetectionRunState, poll_permission_grant
from agent.ai_explorer.run_checkpoint import RunCheckpointCodec, TraversalCheckpointRepository
from agent.ai_explorer.permission_probe import PermissionProbeLedger, PermissionProbeStatus
from agent.ai_explorer.document_flow import (
    DocumentFlowPolicy, DocumentFlowStep,
)
from agent.ai_explorer.document_executor import DocumentExecutor
from agent.ai_explorer.document_session import (
    DocumentIdentityInput, DocumentIdentityResolver, DocumentIdentityRules,
)
from agent.ai_explorer.exploration_completion import ExplorationCompletionGate
from agent.ai_explorer.explorer_orchestrator import ExplorerOrchestrator, PhaseLoopControl
from agent.ai_explorer.run_finalizer import RunFinalizer
from agent.ai_explorer.page_observer import PageObserver, PerceptionOcrPolicy
from agent.ai_explorer.runtime_recovery import RuntimeRecoveryCoordinator
from agent.ai_explorer.action_effect import ActionEffectLedger
from agent.ai_explorer.login_session import (
    LoginDecisionModule, LoginSurfaceClassifier, ManualLoginWaiter,
    TestAccountLoginAdapter,
)
from agent.ai_explorer.page_stability import LoadingShellDetector, PageStabilityCoordinator
from agent.ai_explorer.surface_budget import SurfaceBudgetPolicy
from agent.ai_explorer.decision_directive import DecisionDirectiveApplier
from agent.ai_explorer.directive_selection import DirectiveSelectionSession
from agent.ai_explorer.session_boundary import SessionBoundaryPolicy
from agent.ai_explorer.consent_decision import ConsentDecisionInput, ConsentDecisionModule
from agent.ai_explorer.permission_decision import PermissionDecisionInput, PermissionDecisionModule
from agent.ai_explorer.permission_scenario import (
    PermissionScenarioInput, PermissionScenarioPolicy, PermissionScenarioStep,
)
from agent.ai_explorer.hub_decision import (
    HubDecisionInput, HubDecisionModule, HubProgressCandidates,
    SettingsHubNavigator, SettingsHubScrollPolicy,
)
from agent.ai_explorer.redress_media_probe import (
    COMPLAINT_TERMS as _COMPLAINT_TERMS,
    DELETE_OBSTACLE_TERMS as _DELETE_OBSTACLE_TERMS,
    DELETE_TERMS as _DELETE_TERMS,
    EXPLICIT_REDRESS_ACTION_TERMS as _EXPLICIT_REDRESS_ACTION_TERMS,
    WITHDRAW_TERMS as _WITHDRAW_TERMS,
    MediaProbePermissionGuard, RedressMediaProbeExecutor, RedressMediaProbePolicy,
    complaint_or_cs_entry_target as _complaint_or_cs_entry_target,
    media_family,
    page_visible_text as _page_visible_text,
    privacy_path_observations as _privacy_path_observations,
    redress_entry_target as _redress_entry_target,
)
from agent.ai_explorer.redress_media_probe import (
    _CS_ATTACH_LABEL_TERMS,
    _CS_MEDIA_ID_HINTS,
    _CS_MEDIA_LABEL_TERMS,
    _REDRESS_SURFACE_DETECTOR,
    _customer_service_sensitive_control,
    _cs_media_priority,
    _file_picker_camera_target,
    _is_customer_service_surface,
    _is_redress_interaction_surface,
    _iter_customer_service_media_targets,
    _iter_media_album_chooser_targets,
    _iter_media_capture_chooser_targets,
    _labels_for_media_identity,
    _media_album_chooser_target,
    _media_capture_chooser_target,
    _media_family_of,
    _next_media_family_candidate,
    _prefer_labeled_media_probe,
    _redress_sensitive_control,
    _semantic_sensitive_business_control,
    _sensitive_business_control,
)
from agent.ai_explorer.rule_evidence_executor import RuleEvidenceExecutor
from agent.ai_explorer.final_action_policy import FinalActionContext, FinalActionSafetyPolicy
from agent.ai_explorer.sdk_observation import (
    SdkObservationDecisionModule, SdkObservationGate, SdkObservationGateFacts,
    SdkObservationInput, grant_observation_permissions,
)
from agent.ai_explorer.scenario_controller import ScenarioController
from agent.ai_explorer.llm_proposal import LLMProposalAdapter
from agent.ai_explorer.llm_effectiveness import LLMEffectivenessLedger
from agent.ai_explorer.performance_budget import PerformanceBudget
from agent.ai_explorer.replay_format import (
    ReplayWriter, replay_facts_for_semantics, replay_semantics_for_resolved,
)
from agent.agent_core.audit_contract import observe_page, record_action, record_recovery
from agent.common.exceptions import ExplorationError
from agent.common.event_log import record_event
from agent.rule_engine.scenario_plan import ScenarioFrontier, device_scenario_plan
from agent.detection_engines.base import DetectionContext, EngineResult, Finding
from agent.detection_engines.screen_text import (
    extract_words_from_image,
    ocr_text_blob,
)
from agent.detection_engines.page_semantics import (
    EvidenceSource,
    PageScope,
    PageRole,
    PageSemantics,
    RoleEvidence,
    classify_observation,
    is_foreign_package,
    is_system_camera_activity,
)
from agent.detection_engines.ui_roles import (
    annotate_elements,
    forced_service_consent,
    misleading_consent_copy,
    roles_for_element,
    scenarios_for_roles,
)


_DOCUMENT_FOLLOW_TERMS = (
    "个人信息收集清单", "信息收集清单", "个人信息清单", "权限说明",
    "共享个人信息清单", "与第三方共享",
    "第三方sdk", "第三方插件", "第三方信息共享清单",
)
# Route vocabularies consumed by the pure low-audit-value predicate: protected
# compliance labels always win, then maintenance pruning, then the
# settings/permission exemptions, then the generic marketing/commerce prune.
_LOW_VALUE_PROTECTED_ROUTE_TERMS = (
    *_COMPLAINT_TERMS, *_DOCUMENT_TERMS, *_DOCUMENT_FOLLOW_TERMS,
    *_DELETE_TERMS, *_WITHDRAW_TERMS,
    "权限管理", "权限设置", "申请权限", "系统权限", "授权", "相机", "拍照",
    "相册", "图片", "上传", "文件", "麦克风", "permission", "camera",
    "photo", "upload", "microphone", "个性化", "定向推送", "定向广告",
    "推荐管理", "广告偏好", "personalized", "targeted ads", "ad preferences",
)
_LOW_VALUE_EXEMPT_ROUTE_TERMS = (
    *_COMPLAINT_TERMS, *_DOCUMENT_TERMS, *_DOCUMENT_FOLLOW_TERMS,
    *_DELETE_TERMS, *_WITHDRAW_TERMS,
    "权限管理", "权限设置", "申请权限", "系统权限", "授权", "相机", "拍照", "相册", "图片", "上传", "文件", "麦克风",
    "permission", "camera", "photo", "upload", "microphone",
    "设置", "个人中心", "用户中心", "账户中心", "账号中心",
    "settings", "profile", "account center",
    "个性化", "定向推送", "定向广告", "推荐管理", "广告偏好",
    "personalized", "targeted ads", "ad preferences",
)
# Vocabulary owner is the pure safety module; the alias keeps legacy readers.
_DESTRUCTIVE_CONFIRM_TERMS = DESTRUCTIVE_CONFIRM_TERMS
_CRASH_RESOURCE_IDS = ("android:id/aerr_close", "android:id/aerr_wait", "android:id/aerr_restart")
_CUSTOM_CRASH_RESOURCE_TERMS = (
    "customactivityoncrash", "custom_activity_on_crash", "error_activity_restart_button",
    "error_activity_more_info_button",
)
_CRASH_TEXT_TERMS = (
    "keeps stopping", "has stopped", "isn't responding", "not responding",
    "停止运行", "已停止", "持续停止", "无响应",
)
_LAUNCHER_ACTIVITY_TERMS = ("nexuslauncheractivity", "launcheractivity", "com.android.launcher")
_FILE_PICKER_ACTIVITY_TERMS = (
    "documentsui", ".picker.pickactivity", "filepicker", "photopicker",
    "picker.external", "externalpickeractivity",
)
_CUSTOM_TAB_ACTIVITY_TERMS = (
    "customtabactivity", "customtabs", "chrome.browser",
    "apps.chrome", "android.chrome", "com.android.chrome",
)
_DOCUMENT_ROUTE_ID_HINTS = (
    "privacy", "policy", "private", "yinsi", "yszc",
    "agreement", "protocol", "terms", "fwxy", "useragree",
    "sdk", "third_app", "collect", "share", "qdml",
)
# Same clause, different on-screen wording / punctuation. Do not alias
# 《使用条款》 with 《服务协议》 — those remain independent titles.
_PERMISSION_ACTIVITY_TERMS = ("permissioncontroller", "grantpermissionsactivity", "permission.ui")
_PERMISSION_RESOURCE_PREFIXES = (
    "com.android.permissioncontroller:id/",
    "com.google.android.permissioncontroller:id/",
)
# Java packages often differ from applicationId by a module segment
# (com.vendor.product vs com.vendor.main.ui.Splash). Do not treat a different
# product under the same vendor (com.tencent.mm vs com.tencent.mobileqq) as self.
_APP_MODULE_SEGMENTS = frozenset({
    "main", "app", "ui", "lib", "core", "common", "module", "feature",
    "home", "base", "biz", "internal", "component", "application", "client",
    "mine", "setting", "user", "account", "web", "login", "device", "iot",
    "smart", "family", "member", "personal", "about", "protocol", "privacy",
    "message", "push", "shop", "pay", "media",
})

_SETTINGS_HUB_NAVIGATOR = SettingsHubNavigator()


def _activity_belongs_to_package(activity: str, package_name: str) -> bool:
    """True when this Activity is the audited app, even if applicationId ≠ Java package."""
    text = str(activity or "").strip()
    package = str(package_name or "").strip()
    if not text or not package:
        return False
    lowered = text.lower()
    pkg = package.lower()
    if text.startswith(".") or pkg in lowered:
        return True
    act_parts = [part for part in lowered.split(".") if part]
    pkg_parts = [part for part in pkg.split(".") if part]
    if len(act_parts) < 2 or len(pkg_parts) < 2 or act_parts[:2] != pkg_parts[:2]:
        return False
    if act_parts[:len(pkg_parts)] == pkg_parts:
        return True
    return len(act_parts) >= 3 and act_parts[2] in _APP_MODULE_SEGMENTS


def _associated_start_activity(
    activity: str, package_name: str, foreground_package: str = "",
) -> bool:
    text = str(activity or "")
    package = str(package_name or "")
    if not text or not package:
        return False
    if _activity_belongs_to_package(text, package):
        return False
    fg = str(foreground_package or "").strip().lower()
    pkg = package.lower()
    # Appium current_package is the applicationId. Same process ≠ another product.
    if fg and (fg == pkg or pkg in fg):
        return False
    lowered = text.lower()
    if any(term in lowered for term in (
        *_LAUNCHER_ACTIVITY_TERMS, *_PERMISSION_ACTIVITY_TERMS,
        *_CUSTOM_TAB_ACTIVITY_TERMS, *_FILE_PICKER_ACTIVITY_TERMS,
        "settings", "setting", "permission", "webview", "customtab",
    )):
        return False
    if lowered.startswith(("com.android.", "com.google.android.", "android.", "org.chromium.")):
        return False
    if fg and fg != pkg and not fg.startswith(
        ("com.android.", "com.google.android.", "android.", "org.chromium.")
    ):
        return True
    return "." in text


_SPECIAL_PERMISSION_TERMS = {
    "overlay": (
        "display over other apps", "appear on top", "悬浮窗",
        "显示在其他应用上层", "显示在其他应用的上层",
    ),
    "all_files": ("all files access", "manage all files", "所有文件访问", "所有文件"),
    "accessibility": ("accessibility", "无障碍"),
    "notification": ("notification access", "通知使用权"),
}
_PURPOSE_TERMS = ("目的", "用于", "以便", "为了", "为您", "权限说明")
_DENIAL_BLOCK_TERMS = ("暂无", "无", "没有", "未授予", "需要")
_DENIAL_PERMISSION_TERMS = ("权限", "授权")
_APP_EXIT_DIALOG_TERMS = ("退出应用", "退出程序", "关闭应用", "是否退出", "确认退出", "要退出", "再按一次退出")
# Reversible does not automatically mean useful for a privacy-compliance audit.
# These routes are generic marketing/commerce surfaces seen across Apps; they
# consume the traversal budget without advancing a rule scenario.  Redress,
# policy, permission and account-control labels are explicitly exempted below.
_LOW_AUDIT_VALUE_ROUTE_TERMS = (
    "广告", "推广", "促销", "营销", "会员", "vip", "开通", "续费", "订阅",
    "邀请", "分享好友", "返现", "红包", "优惠券", "领券", "奖励", "抽奖",
    "拼团", "砍价", "兑换", "提现", "充值", "购买", "立即购买", "商城",
    "刷新次数", "购买次数", "刷新购买", "活动规则",
    "advert", "promotion", "premium", "membership", "subscribe", "subscription",
    "invite", "referral", "refer a friend", "cashback", "coupon", "reward",
    "lottery", "redeem", "top up", "purchase", "buy now", "upgrade plan",
)
_LOW_VALUE_COMMERCIAL_ACTIVITY_TERMS = (
    "vipbuy", "vip_buy", "memberbuy", "member_buy", "membership", "paywall",
    "purchase", "recharge", "topup", "subscribe", "subscription", "promotion",
    "inviteactivity", "invite_activity", "referral", "rewardactivity", "mallactivity",
)
_LOW_VALUE_HELP_TERMS = (
    "使用帮助", "功能帮助", "操作帮助", "新手帮助", "帮助教程", "使用教程",
    "操作教程", "新手教程", "常见问题", "功能介绍", "使用指南", "操作指南",
    "help tutorial", "user guide", "getting started", "how to use", "faq",
)
_DOCUMENT_KIND_DISPLAY_TITLES = {
    "privacy_policy": "隐私政策",
    "user_agreement": "用户协议",
    "service_terms": "服务协议",
    "disclosure_list": "第三方SDK/个人信息清单",
}
@dataclass(frozen=True)
class DocumentCompletionResolution:
    """Bind the clicked document route to the body that was actually read."""

    entry_target: str
    actual_title: str
    expected_kind: str | None
    observed_kind: str | None
    completed_kind: str | None
    mismatch: bool


_DOCUMENT_HUB_ACTIVITY_TERMS = (
    "setting", "avatar", "profile", "about", "userinfo", "personalinfo", "accountsetting",
    "accountcenter", "usercenter", "securitycenter", "mine",
)
_DOCUMENT_HUB_ROW_TERMS = (
    "头像", "昵称", "退出登录", "关于我们", "个人信息", "个人资料", "账户信息", "性别", "账号管理",
    "账户中心", "账号中心", "用户中心", "个人主页", "安全中心", "消息中心", "设置", "更多设置",
    "avatar", "nickname", "log out", "sign out", "about us", "message center", "settings",
)
# Used only to tell a first-run consent sheet apart from a real settings hub.
_LOGIN_ACTIVITY_TERMS = ("login", "signin", "signup", "register")
_LOGIN_CONTROL_TERMS = ("password", "phone", "mobile", "verify", "code", "login", "register", "send", "账号", "密码", "验证码", "登录", "注册")
_LOGIN_FIELD_TERMS = ("password", "phone", "mobile", "account", "email", "verify", "code", "账号", "密码", "手机号", "验证码")
_LOGIN_SUBMIT_TERMS = ("login", "signin", "sign in", "register", "登录", "注册", "下一步", "获取验证码")
_PROFILE_LOGIN_ENTRY_TERMS = (
    "点击此处登录", "点击登录", "立即登录", "去登录", "登录/注册", "请先登录", "点击头像登录",
    "未登录", "未登陆", "login / register", "sign in", "not logged in", "log in",
)
_LOGGED_OUT_PROFILE_TERMS = (
    "未登录", "未登陆", "尚未登录", "请先登录", "游客模式", "游客身份",
    "not logged in", "sign in to continue", "guest mode",
)
_AUTHENTICATED_PROFILE_TERMS = ("我的", "个人中心", "账户中心", "账号管理", "消息中心", "我的报料", "我的救援")
_LOGIN_SUCCESS_NOTICE_TERMS = (
    "登录成功", "成功登录", "登陆成功", "成功登陆", "已成功登录", "登录已成功",
    "欢迎回来", "login successful", "logged in successfully", "signed in successfully",
)
_LOGOUT_CONFIRM_BUTTON_TERMS = ("确定", "确认", "退出登录", "sign out", "log out", "ok", "yes")
_SENSITIVE_PERMISSION_TERMS = ("CAMERA", "RECORD_AUDIO", "READ_PHONE", "CALL_PHONE", "READ_MEDIA", "READ_EXTERNAL", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION")
_EMPTY_PAGE_RETRIES = 3
_DEFAULT_PAGE_SETTLE_RETRIES = 4
_DEFAULT_PAGE_SETTLE_WAIT_SECONDS = 3.0
_REQUIRED_EXPLORATION_TARGET_TERMS = (
    "隐私", "privacy", "policy", "协议", "条款", "terms", "设置", "setting", "settings", "我的", "个人", "profile",
    "账户", "账号", "account", "注销", "删除", "投诉", "举报", "反馈", "帮助", "工单", "客服", "关于",
    "撤回", "授权管理",
)
_ONBOARDING_TRANSITION_TERMS = (
    "ivgoto", "立即体验", "进入应用", "开始使用", "开启体验", "跳过引导",
    "get started", "enter app", "start using", "continue to app",
)
_BUSINESS_ACTION_TERMS = (
    "客服", "投诉", "举报", "反馈", "帮助支持", "报料", "救援", "工单", "语音", "麦克风", "录音", "拍照", "相机",
    "相册", "图片", "上传", "头像", "文件", "导航", "路况", "查询", "扫码",
    "customer service", "ticket", "voice", "microphone", "record", "camera",
    "photo", "upload", "avatar", "file", "navigation", "scan",
)


def _clickable_count(page) -> int:
    return LoadingShellDetector.clickable_count(page)


def _page_is_loading_shell(page, state: PageState | None = None) -> bool:
    """Compatibility adapter for the stability module's loading detector."""
    detector = LoadingShellDetector(
        is_external=lambda activity, elements: bool(_external_navigation_surface(activity, elements)),
        has_document_body=_has_document_body_surface,
        has_external_document_body=_external_document_body_visible,
    )
    return detector.is_loading(page, active_document=bool(state and state.document_active()))


def _has_document_body_surface(activity: str, elements: list[dict]) -> bool:
    lowered = str(activity or "").lower()
    if any(term in lowered for term in (*_CUSTOM_TAB_ACTIVITY_TERMS, "webview")):
        return True
    # In-app disclosure bodies (SDK directory / policy detail) often use
    # ScrollView/RecyclerView rather than WebView; treat them as readable bodies.
    if any(term in lowered for term in (
        "thirdappprivacy", "thirdpartysdk", "sdklist", "sdkdir", "sdkdetail",
        "policydetail", "privacydetail", "agreementdetail", "protocoldetail",
    )):
        return True
    if any("webview" in str(item.get("class_name") or "").lower() for item in elements):
        return True
    return _looks_like_in_app_disclosure_body(activity, elements)


def _looks_like_in_app_disclosure_body(activity: str, elements: list[dict]) -> bool:
    """Long SDK/policy detail pages with few hub rows — not a settings link list."""
    if _is_consent_dialog(elements):
        return False
    act = str(activity or "").lower()
    if any(term in act for term in _DOCUMENT_HUB_ACTIVITY_TERMS):
        return False
    blob = " ".join(
        str(item.get(key) or "")
        for item in elements for key in ("text", "content_desc")
    )
    compact = re.sub(r"\s+", "", blob)
    if len(compact) < 80:
        return False
    body_hits = sum(
        1 for term in (
            "收集的信息", "收集信息", "使用目的", "申请的权限", "第三方sdk", "sdk名称",
            "隐私政策", "用户协议", "服务协议", "极光", "友盟", "微信开放平台",
        )
        if term.lower() in compact.lower()
    )
    if body_hits < 2:
        return False
    # Hub link lists expose several short clickable policy titles; bodies do not.
    short_doc_links = 0
    for item in elements:
        if not item.get("clickable"):
            continue
        label = re.sub(
            r"\s+", "",
            " ".join(str(item.get(key) or "") for key in ("text", "content_desc")),
        )
        if 0 < len(label) <= 16 and _required_document_kind(label):
            short_doc_links += 1
    return short_doc_links < 2


def _looks_like_settings_or_profile(activity: str, elements: list[dict]) -> bool:
    if _has_document_body_surface(activity, elements):
        return False
    if any(term in str(activity or "").lower() for term in _DOCUMENT_HUB_ACTIVITY_TERMS):
        return True
    short_labels = [
        " ".join(str(item.get(key) or "") for key in ("text", "content_desc")).strip()
        for item in elements
    ]
    short_labels = [label for label in short_labels if 0 < len(label) <= 12]
    if sum(1 for term in _DOCUMENT_HUB_ROW_TERMS if any(term.lower() in label.lower() for label in short_labels)) >= 2:
        return True
    # 「我的」壳页：有设置/关于钻取行 + 个人中心痕迹，即使缺头像/退出登录文案。
    blob = " ".join(short_labels).lower()
    has_drill = any(term in blob for term in ("设置", "更多设置", "关于我们", "settings", "about"))
    has_profile = any(term in blob for term in (
        "我", "我的", "个人中心", "用户中心", "账户中心", "账号中心", "个人主页",
        "个人信息", "账户信息", "消息中心", "账户", "账号", "mine", "profile", "account",
    ))
    return has_drill and has_profile


def _looks_like_main_content_surface(
    activity: str, elements: list[dict], package_name: str = "",
) -> bool:
    """True for bookstore/home content, not login, consent, or the profile hub."""
    if _is_consent_dialog(elements) or _is_login_gate(activity, elements):
        return False
    if _looks_like_settings_or_profile(activity, elements):
        return False
    if _associated_start_activity(activity, package_name):
        return False
    lowered = str(activity or "").lower()
    package = str(package_name or "").lower()
    if lowered.startswith(("com.google.android.", "com.android.")) and package not in lowered:
        return False
    if any(term in lowered for term in ("library", "bookstore", "bookshelf", "homeactivity")):
        return True
    if re.search(r"\.(home|main)[a-z]*activity", lowered):
        return True
    blob = " ".join(
        str(item.get(key) or "") for item in elements for key in ("text", "content_desc", "resource_id")
    ).lower()
    return any(term.lower() in blob for term in _MAIN_CONTENT_TAB_PRIORITY)


def _bounds_click_target_for(target: str, elements: list[dict]) -> str:
    """Return the visible bounds for one bounded retry after an ID tap misses."""
    return bounds_retry_target(
        target, elements, is_unsafe_host=_host_is_unsafe_document_click,
    )


def _has_clickable_document_entry(elements: list[dict]) -> bool:
    entry_terms = tuple(term.lower() for term in (*_DOCUMENT_TERMS, *_POLICY_TERMS, *_DOCUMENT_FOLLOW_TERMS))
    for item in elements:
        blob = " ".join(str(item.get(key) or "") for key in ("text", "content_desc", "resource_id")).lower()
        if not any(term in blob for term in entry_terms):
            continue
        if item.get("clickable") and not _host_is_unsafe_document_click(item):
            return True
        kind = _required_document_kind(blob) or next(
            (name for name, hints in _DOCUMENT_KIND_ID_HINTS.items() if any(hint in blob for hint in hints)),
            "privacy_policy",
        )
        if not item.get("clickable") and _clickable_host_for_document_kind(elements, kind, item):
            return True
    return False


def _is_document_entry_page(activity: str, elements: list[dict]) -> bool:
    """True for settings/about/profile hubs that *link* to policies, not the body."""
    if _is_consent_dialog(elements) or _has_document_body_surface(activity, elements):
        return False
    if _has_clickable_document_entry(elements):
        return True
    visible = _visible_required_document_kinds(elements)
    if not visible:
        return False
    clickable_n = sum(1 for item in elements if item.get("clickable"))
    if len(visible) >= 2 and clickable_n >= 3:
        return True
    return bool(_looks_like_settings_or_profile(activity, elements) and clickable_n >= 2)


def _page_semantics(
    activity: str,
    elements: list[dict],
    state: PageState,
    *,
    screen_text: str = "",
    package_name: str = "",
    foreground_package: str = "",
) -> PageSemantics:
    """Resolve exactly one authoritative role before any pruning or action."""
    external = _external_navigation_surface(activity, elements)
    system_overlay = _is_system_overlay_surface(elements)
    foreign_app = is_foreign_package(
        package_name,
        foreground_package,
        allowed_system_surface=_is_allowed_non_audited_surface(
            activity, package_name, foreground_package,
        ),
    )
    document_body = bool(_document_key(activity, elements, state, screen_text=screen_text))
    low_value_kind = _low_audit_value_surface_kind(activity, elements, screen_text)
    entry_choice_surface = bool(_entry_choice_bypass_target(elements))
    signals = PageEvidenceSignals(
        launcher=_is_launcher_activity(activity),
        system_overlay=system_overlay,
        permission_prompt=bool(_permission_prompt(activity, elements)),
        system_settings=bool(_system_settings_surface(activity, elements)),
        file_picker=external == "file_picker",
        system_camera=is_system_camera_activity(activity),
        external_browser=external == "custom_tab",
        foreign_app=foreign_app,
        crash=bool(_crash_reason(activity, elements, screen_text)),
        consent_dialog=_is_consent_dialog(elements),
        document_body=document_body,
        login_gate=_is_login_gate(activity, elements),
        logged_out_profile=_logged_out_profile_visible(elements, extra_text=screen_text),
        splash_or_gate=(
            entry_choice_surface
            or (
                _is_launch_gate_activity(activity)
                and not _looks_like_settings_or_profile(activity, elements)
            )
        ),
        loading_shell=_page_is_loading_shell(
            type("Page", (), {"activity": activity, "elements": elements})(), state,
        ),
        document_hub=(
            not entry_choice_surface
            and (
                _is_document_entry_page(activity, elements)
                or _looks_like_settings_or_profile(activity, elements)
            )
        ),
        privacy_hub=(not entry_choice_surface and _looks_like_settings_or_profile(activity, elements)),
        main_content=_looks_like_main_content_surface(activity, elements, package_name),
        low_value_kind=low_value_kind,
    )
    supporting_evidence: list[RoleEvidence] = []
    route_evidence = (
        (PageRole.SYSTEM_LAUNCHER, _is_launcher_activity(activity), "launcher_activity"),
        (PageRole.SYSTEM_FILE_PICKER, external == "file_picker", "file_picker_activity"),
        (PageRole.SYSTEM_CAMERA, is_system_camera_activity(activity), "system_camera_activity"),
        (PageRole.EXTERNAL_BROWSER, external == "custom_tab", "custom_tab_activity"),
    )
    for role, matched, hit in route_evidence:
        if matched:
            supporting_evidence.append(RoleEvidence(
                role=role, source=EvidenceSource.ROUTE, strength=130, hits=(hit,),
            ))
    # Screen-only crash copy comes from OCR fallback, while a native crash
    # dialog remains represented by the ordinary UI-tree fact above.
    if screen_text and _crash_reason(activity, [], screen_text):
        supporting_evidence.append(RoleEvidence(
            role=PageRole.CRASH, source=EvidenceSource.OCR, strength=110,
            hits=("screen_crash_copy",),
        ))
    if document_body and state.document_active():
        supporting_evidence.append(RoleEvidence(
            role=PageRole.DOCUMENT_BODY,
            source=EvidenceSource.RUNTIME_CHECKPOINT,
            strength=125,
            hits=("active_document",),
        ))
    elif document_body and state.last_action == "click":
        supporting_evidence.append(RoleEvidence(
            role=PageRole.DOCUMENT_BODY,
            source=EvidenceSource.PREVIOUS_ACTION,
            strength=115,
            hits=("document_route_click",),
        ))
    observation = PageEvidenceBuilder().build_observation(PageEvidenceInput(
        activity=activity,
        elements=tuple(elements),
        screen_text=screen_text,
        previous_action=str(state.last_action or ""),
        route=tuple(state.navigation_replay.semantic_route().split(" > ")),
        signals=signals,
        supporting_evidence=tuple(supporting_evidence),
    ))
    return classify_observation(observation)


def _is_system_overlay_surface(elements: list[dict]) -> bool:
    """Detect notification/quick-settings overlays despite a stale App Activity."""
    system_nodes = 0
    for element in elements:
        identity = " ".join(str(element.get(key) or "") for key in (
            "resource_id", "target", "package", "class_name",
        )).lower()
        if "com.android.systemui" in identity:
            system_nodes += 1
    # One status-bar node is normal. A notification shade exposes a dense
    # SystemUI tree, so require at least two independent controls.
    return system_nodes >= 2


def _page_role(
    activity: str,
    elements: list[dict],
    state: PageState,
    *,
    screen_text: str = "",
    package_name: str = "",
    foreground_package: str = "",
) -> str:
    """Compatibility view of the authoritative Page semantics."""
    return _page_semantics(
        activity, elements, state, screen_text=screen_text,
        package_name=package_name, foreground_package=foreground_package,
    ).legacy_role


def _document_probe_allowed_for_role(role: PageRole) -> bool:
    """Only hub/content roles may start a policy-link probe.

    Startup/login-choice surfaces can display policy links, but probing them
    after consent has already been accepted reopens the gate and prevents the
    public entry button from reaching the app's main surface.
    """
    return role in {
        PageRole.DOCUMENT_HUB,
        PageRole.LOGGED_OUT_PROFILE,
        PageRole.MAIN_CONTENT,
        PageRole.APP_PAGE,
    }


def _catalog_target_for_role(
    semantics: PageSemantics, kind: str, *, label: str = "",
) -> str | None:
    """Return an executable target from the sole catalog for this page role."""
    try:
        expected = TargetKind(str(kind or ""))
    except ValueError:
        return None
    return TargetCatalogView(tuple(semantics.targets), semantics.has_overlay).target_for_kind(
        expected, label=label,
    )


def _catalog_label_for_target(semantics: PageSemantics, target: str) -> str:
    return TargetCatalogView(tuple(semantics.targets), semantics.has_overlay).label_for_target(target)


def _catalog_target_kind(semantics: PageSemantics, target: str) -> str:
    kind = TargetCatalogView(tuple(semantics.targets), semantics.has_overlay).kind_for_target(target)
    return kind.value if kind else ""


def _is_overlay_catalog_target(semantics: PageSemantics, target: str, kind: str) -> bool:
    """Match a semantic overlay target without re-inspecting background UI."""
    try:
        expected = TargetKind(str(kind or ""))
    except ValueError:
        return False
    return TargetCatalogView(tuple(semantics.targets), semantics.has_overlay).is_overlay_target(
        target, expected,
    )


def _catalog_execution_target(semantics: PageSemantics, value: str) -> str | None:
    """Resolve a visible label/id only through the adjudicated target catalog."""
    return TargetCatalogView(tuple(semantics.targets), semantics.has_overlay).resolve(value)


def _catalog_document_target(
    semantics: PageSemantics, requested: str = "", *, ctx: DetectionContext | None = None,
) -> str | None:
    """Resolve a raw document selector through the role catalog.

    The document ledger owns read/failure ordering. The catalog only validates
    that its selected row belongs to the current overlay, rather than replacing
    that order with a lexical catalog sort.
    """
    if requested:
        resolved = _catalog_execution_target(semantics, requested)
        if resolved and _catalog_target_kind(semantics, resolved) == "document":
            return resolved
    # An inline-click miss is not a completed read. Keep each visible document
    # eligible for its bounded second probe before moving to the checkbox or
    # agree button. This prevents an inaccessible first link from silently
    # changing the consent order.
    attempts = (ctx.runtime.get("inline_document_open_attempts") or {}) if ctx else {}
    for item in semantics.targets:
        if _catalog_target_kind(semantics, item.target) != "document":
            continue
        kind = _required_document_kind(item.label or item.target)
        if kind and int(attempts.get(kind, 0)) < 2:
            return item.target
    return None


def _llm_catalog_elements(semantics: PageSemantics) -> list[dict]:
    """Expose only the role-scoped executable catalog to the LLM."""
    return llm_catalog_elements(tuple(semantics.targets))


def _click_matches_privacy_path(target: str, elements: list[dict], path_kind: str) -> bool:
    """True when the click target is a discovered 注销/授权/投诉 entry (not confirm)."""
    observations = _privacy_path_observations(elements, "")
    key = {
        "delete": "delete_targets",
        "withdraw": "withdraw_targets",
        "complaint": "complaint_targets",
    }.get(path_kind)
    if not key:
        return False
    raw = str(target or "")
    if raw in set(observations.get(key) or []):
        return True
    terms = {
        "delete": _DELETE_TERMS,
        "withdraw": _WITHDRAW_TERMS,
        "complaint": _COMPLAINT_TERMS,
    }[path_kind]
    identity = " ".join(_target_identity_values(raw, elements)).lower()
    if any(term.lower() in identity for term in _DESTRUCTIVE_CONFIRM_TERMS):
        return False
    return any(term.lower() in identity for term in terms)


def _privacy_path_verification_surface(activity: str, elements: list[dict], page_text: str = "") -> str | None:
    """Return delete/withdraw when the page is the verification surface, not just a hub row."""
    blob = f"{activity} {page_text} {_page_visible_text(elements)}".lower()
    clickable_n = sum(1 for e in elements if e.get("clickable"))
    hub_list = _looks_like_settings_or_profile(activity, elements) and clickable_n >= 5
    if any(term.lower() in blob for term in _DESTRUCTIVE_CONFIRM_TERMS):
        return "delete"
    if any(term in blob for term in (
        "cancelaccount", "cancel_account", "deleteaccount", "delete_account",
        "unregister", "logoff",
    )):
        return "delete"
    # 注销账号 on a dense settings list is still discovery; the cancel-account
    # Activity / confirm page is verification.
    if not hub_list and any(term in blob for term in ("注销账号", "账号注销", "删除账号")):
        return "delete"
    if any(term in blob for term in (
        "withdraw", "authmanage", "auth_manage", "permissionmanage",
        "撤回同意", "撤回授权", "撤销同意", "管理授权", "权限开关",
    )):
        if hub_list and "授权管理" in blob and not any(
            term in blob for term in ("撤回同意", "撤销同意", "关闭授权", "权限开关")
        ):
            return None
        if hub_list and not any(term in blob for term in ("撤回同意", "撤销同意", "关闭授权", "权限开关")):
            return None
        return "withdraw"
    if (not hub_list) and "授权管理" in blob:
        return "withdraw"
    return None


def _legacy_document_key(
    activity: str,
    elements: list[dict],
    state: PageState,
    *,
    screen_text: str = "",
    document_origin: str = "",
) -> str | None:
    """Identify a policy/terms document and keep reading it across viewports."""
    # A consent dialog mentioning a policy is an entry surface, not evidence
    # that its long document has been read to the end.
    if any(
        _id_matches_any_hint(str(element.get("resource_id") or ""), _PRIVACY_DIALOG_BUTTON_IDS)
        for element in elements
    ):
        return None
    if _is_consent_dialog(elements):
        return None
    activity_lower = str(activity or "").lower()
    visible_text = f"{_page_visible_text(elements)} {screen_text}".strip()
    rendered_kind = _rendered_document_body_kind(visible_text)
    if rendered_kind:
        # Rendered body evidence outranks stale WebView template controls and
        # generic Activity names.  This prevents a privacy clause opened from
        # a consent sheet from becoming a 120-second manual-login gate.
        title = _DOCUMENT_KIND_DISPLAY_TITLES.get(rendered_kind, rendered_kind)
        return f"{activity}:document:{title}"
    # A settings/profile/about hub is a navigation surface even when a
    # previous document scroll left an active session behind.  Resolve this
    # structural boundary before inheriting ``active_document``; otherwise a
    # return to 个人信息 can be mistaken for another policy viewport and the
    # whole hub is scrolled instead of exploring its policy rows.
    if _is_document_entry_page(activity, elements):
        return None
    # Once a document viewport has been verified and a scroll was issued, its
    # next viewport belongs to that same document.  Policy prose commonly
    # contains "手机号/验证码/登录" and some WebViews even expose template
    # EditTexts; checking the login shape first would discard the active
    # document session and incorrectly pause for manual authentication.  An
    # explicit Login/Verify Activity remains a stronger boundary: it can be a
    # real transition away from an old document session.
    if (
        state.active_document
        and state.last_action == "scroll"
        and not any(term in activity_lower for term in _LOGIN_ACTIVITY_TERMS)
    ):
        return state.active_document
    # A policy/terms link may open a reused in-app WebView whose accessibility
    # tree contains template EditTexts or login words.  The verified preceding
    # click is stronger evidence than that incidental shape: treat only its
    # direct child as a document-loading surface, never as a human-login gate.
    origin_is_document_route = _target_is_document_route(document_origin)
    if _is_login_gate(activity, elements) and not origin_is_document_route:
        return None
    # Low-value classification is a pruning hint, not a structural veto for an
    # *active* document.  A generic WebView with no established document
    # identity remains prunable; an active policy may contain the same words.
    low_value_kind = _low_audit_value_surface_kind(activity, elements, screen_text)
    active_scroll_document = bool(state.active_document and state.last_action == "scroll")
    if low_value_kind and not active_scroll_document:
        return None
    # Customer-service conversations commonly reuse a generic WebViewActivity.
    # They are interactive business surfaces, not policy bodies: classifying
    # them as long documents makes the explorer scroll once and immediately
    # back out instead of probing voice/camera/album/upload controls.
    if _is_customer_service_surface(activity, visible_text, elements):
        return None
    # Login/verify screens often reprint 用户协议 in a footer. That is not
    # a policy body, and must not inherit a leftover active_document.
    if (
        any(term in activity_lower for term in _LOGIN_ACTIVITY_TERMS)
        and not _has_document_body_surface(activity, elements)
    ):
        return None
    # Splash/welcome often embed policy names in a first-run gate.  Only skip
    # scrolling when this is not actually a WebView/Custom Tab document body.
    if (
        any(term in activity_lower for term in ("welcome", "splash", "guide", "intro", "onboard"))
        and not _has_document_body_surface(activity, elements)
    ):
        return None
    has_body_surface = _has_document_body_surface(activity, elements)
    # Bind the document to the body that is actually visible.  A settings row
    # can say “第三方 SDK 目录” while a reused WebView/Custom Tab renders the
    # service agreement.  Continuing under the click label corrupts both the
    # timeline and the read/dedup ledger.
    observed_kind = _document_body_kind_from_text(visible_text) if has_body_surface else None
    if observed_kind:
        title = _DOCUMENT_KIND_DISPLAY_TITLES.get(observed_kind, observed_kind)
        return f"{activity}:document:{title}"
    if origin_is_document_route:
        origin_kind = _infer_document_kind(document_origin, "")
        title = _DOCUMENT_KIND_DISPLAY_TITLES.get(origin_kind, origin_kind or "body")
        return f"{activity}:document:{title}"
    # WebView ClickableSpans keep titles on clickable nodes; settings rows are
    # already excluded above, so include those labels only on a document surface.
    include_clickable = has_body_surface
    normalized = " ".join(
        " ".join((element.get("text", ""), element.get("content_desc", "")))
        for element in elements if include_clickable or not element.get("clickable")
    ).lower()
    document_terms = (*_DOCUMENT_TERMS, *_DOCUMENT_FOLLOW_TERMS, "sdk目录", "第三方sdk", "收集的信息", "使用目的")
    matches = [(normalized.find(term.lower()), term.lower()) for term in document_terms if term.lower() in normalized]
    if matches:
        # The same WebView Activity is commonly reused for both the privacy
        # policy and terms. Keep their progress independent by binding the
        # document key to the first visible title/heading term.
        _, identity = min(matches, key=lambda item: item[0])
        # Canonicalize aliases (English/Chinese labels and resource-id
        # spellings) to the semantic document family.  Without this, the
        # first visit opened from ``privacy_entry`` is keyed as ``隐私政策``
        # while the same body after a back is keyed as ``privacy policy`` and
        # gets read again from the top.
        canonical_kind = _required_document_kind(identity)
        canonical_title = _DOCUMENT_KIND_DISPLAY_TITLES.get(canonical_kind or "")
        return f"{activity}:document:{canonical_title or identity}"
    if has_body_surface:
        # Body surface without a canonical title — still scroll as one document.
        return f"{activity}:document:body"
    return None


def _document_key(
    activity: str,
    elements: list[dict],
    state: PageState,
    *,
    screen_text: str = "",
    document_origin: str = "",
) -> str | None:
    """Compatibility adapter for the document-owned identity resolver."""
    rules = DocumentIdentityRules(
        consent_dialog=_is_consent_dialog,
        privacy_dialog_button=lambda element: _id_matches_any_hint(
            str(element.get("resource_id") or ""), _PRIVACY_DIALOG_BUTTON_IDS,
        ),
        visible_text=_page_visible_text,
        rendered_kind=_rendered_document_body_kind,
        document_entry_page=_is_document_entry_page,
        login_gate=_is_login_gate,
        low_value_kind=_low_audit_value_surface_kind,
        customer_service_surface=_is_customer_service_surface,
        has_body_surface=_has_document_body_surface,
        body_kind=_document_body_kind_from_text,
        target_is_document_route=_target_is_document_route,
        infer_kind=lambda target: _infer_document_kind(target, ""),
        canonical_kind=_required_document_kind,
        title_for_kind=lambda kind: _DOCUMENT_KIND_DISPLAY_TITLES.get(kind, kind),
        login_activity_terms=_LOGIN_ACTIVITY_TERMS,
        document_terms=_DOCUMENT_TERMS,
        follow_terms=_DOCUMENT_FOLLOW_TERMS,
    )
    identity = DocumentIdentityResolver(rules).resolve(DocumentIdentityInput(
        activity=activity,
        elements=elements,
        screen_text=screen_text,
        document_origin=document_origin,
        active_key=str(state.documents.active_key or state.active_document or ""),
        last_action=str(state.last_action or ""),
    ))
    return identity.key if identity else None


def _crash_reason(activity: str, elements: list[dict], page_text: str) -> str | None:
    """Return a device-observed crash reason; never ask the LLM to dismiss it."""
    visible_elements = [element for element in elements if element.get("displayed", True)]
    resource_ids = {str(element.get("resource_id") or "").lower() for element in visible_elements}
    if resource_ids.intersection(_CRASH_RESOURCE_IDS):
        return "Android 应用崩溃提示"
    normalized_text = str(page_text or "").lower()
    if _is_custom_crash_surface(visible_elements, normalized_text):
        return "应用内自定义崩溃提示"
    if any(term in normalized_text for term in _CRASH_TEXT_TERMS):
        return "Android 报告应用停止响应或崩溃"
    if any(term in activity.lower() for term in _LAUNCHER_ACTIVITY_TERMS):
        return "应用已退出至系统桌面"
    return None


def _is_custom_crash_surface(elements: list[dict], page_text: str) -> bool:
    visible = [element for element in elements if element.get("displayed", True)]
    resource_ids = {str(element.get("resource_id") or "").lower() for element in visible}
    has_restart_id = any(
        "restart_button" in resource_id or "error_activity_restart" in resource_id
        for resource_id in resource_ids
    )
    has_details_id = any(
        "more_info_button" in resource_id or "error_activity_more_info" in resource_id
        for resource_id in resource_ids
    )
    text = str(page_text or "").lower()
    return bool(
        (has_restart_id and (has_details_id or _custom_crash_text_visible(text)))
        or _custom_crash_text_visible(text)
    )


def _custom_crash_text_visible(normalized_text: str) -> bool:
    text = str(normalized_text or "").lower()
    unexpected = any(term in text for term in (
        "an unexpected error occurred", "unexpected error occurred",
        "发生意外错误", "出现意外错误",
    ))
    restart = any(term in text for term in ("restart app", "重新启动应用"))
    details = any(term in text for term in ("error details", "错误详情"))
    return (unexpected and (restart or details)) or (restart and details)


def _crash_dialog_dismiss_target(elements: list[dict]) -> str | None:
    """Close a system crash dialog without restarting the broken activity."""
    for item in elements:
        if not item.get("clickable"):
            continue
        resource_id = str(item.get("resource_id") or "").lower()
        if resource_id in {"android:id/aerr_close", "android:id/aerr_ok"}:
            return str(item.get("resource_id") or item.get("text") or "") or None
        identity = " ".join(str(item.get(key) or "") for key in ("text", "content_desc", "resource_id")).lower()
        if any(term in identity for term in ("关闭应用", "关闭", "close app", "aerr_close")):
            if any(term in identity for term in ("等待", "wait", "重新打开", "aerr_restart", "aerr_wait")):
                continue
            return str(item.get("resource_id") or item.get("text") or item.get("content_desc") or "") or None
    return None


def _looks_like_in_app_webview_entry(target: str, elements: list[dict]) -> bool:
    blob = str(target or "").lower()
    for item in elements:
        values = (item.get("resource_id"), item.get("text"), item.get("content_desc"), item.get("target"))
        if target and target in values:
            blob += " " + " ".join(str(value or "") for value in values).lower()
    return any(term in blob for term in ("webview", "webactivity", "客服", ":id/web", "oi_web"))


def _is_launcher_activity(activity: str) -> bool:
    return any(term in str(activity or "").lower() for term in _LAUNCHER_ACTIVITY_TERMS)


def _inline_document_open_succeeded(origin_activity: str, next_activity: str, next_elements: list[dict]) -> bool:
    """A book-title tap only counts if a real document surface appeared."""
    if _is_launcher_activity(next_activity):
        return False
    if _crash_reason(next_activity, next_elements, " ".join(
        str(item.get(key) or "") for item in next_elements for key in ("text", "content_desc")
    )):
        return False
    if _external_navigation_surface(next_activity, next_elements) == "custom_tab":
        return True
    if next_activity != origin_activity and not _is_consent_dialog(next_elements):
        return True
    # Same-activity overlay: a WebView/body appeared and the consent popup is gone.
    if not _is_consent_dialog(next_elements) and (
        _external_document_body_visible(next_elements)
        or any("webview" in str(item.get("class_name") or "").lower() for item in next_elements)
    ):
        return True
    return False


def _is_third_party_channel_login_target(target: str, elements: list[dict]) -> bool:
    identity = " ".join(
        str(item.get(key) or "")
        for item in elements
        for key in ("resource_id", "text", "content_desc", "target")
        if target and target in (item.get("resource_id"), item.get("text"), item.get("content_desc"), item.get("target"))
    ).lower() or str(target or "").lower()
    return any(term in identity for term in ("qq", "微信", "wechat", "weixin")) and any(
        term in identity for term in ("qq", "微信", "wechat", "weixin", "login", "登录", "客服")
    )


def _channel_unavailable_dialog_dismiss_target(elements: list[dict], page_text: str) -> str | None:
    blob = str(page_text or "").lower()
    if not any(term in blob for term in (
        "没有检测到qq", "qq版本过低", "没有检测到微信", "未安装qq", "未安装微信",
        "wechat not installed", "qq not installed",
    )):
        return None
    for item in elements:
        if not item.get("clickable"):
            continue
        identity = " ".join(str(item.get(key) or "") for key in ("resource_id", "text", "content_desc")).lower()
        if any(term in identity for term in ("确定", "知道了", "我知道了", "btn_pos", "btnok", "btn_ok", "ok_btn")):
            if any(term in identity for term in ("取消", "cancel")):
                continue
            return str(item.get("resource_id") or item.get("text") or item.get("content_desc") or "") or None
    return None


def _transient_notice_dismiss_target(elements: list[dict], page_text: str) -> str | None:
    """Return the exact acknowledgement control for a transient notice.

    Copy-success/toast-like dialogs are effects of an already explored route,
    not new DFS pages.  Some layouts expose a clickable full-screen scrim; it
    must never win over the labelled acknowledgement button.
    """
    compact = re.sub(r"\s+", "", str(page_text or "")).lower()
    if not any(term in compact for term in (
        "已复制", "复制成功", "已拷贝", "保存成功", "备份成功", "操作成功",
        "提交成功", "设置成功", "修改成功", "更新成功", "完成",
        "copiedtoclipboard", "addresscopied", "linkcopied", "success", "completed",
    )):
        return None
    preferred = (
        "我知道了", "知道了", "确定", "好的", "关闭", "gotit", "ok", "close",
        "btn_pos", "btn_positive", "btn_ok", "btnok", "ok_btn",
    )
    for item in elements:
        if not item.get("clickable"):
            continue
        values = [str(item.get(key) or "") for key in ("text", "content_desc", "resource_id")]
        identity = re.sub(r"\s+", "", " ".join(values)).lower()
        if not identity or any(term in identity for term in ("取消", "cancel")):
            continue
        if any(term in identity for term in preferred):
            return next((value for value in values if value), None)
    return None


def _is_app_exit_confirmation(target: str, elements: list[dict], page_text: str = "") -> bool:
    """True for the confirm button on an 'exit the app?' dialog."""
    blob = (page_text or " ".join(_element_label(item) for item in elements)).lower()
    if not any(term.lower() in blob for term in _APP_EXIT_DIALOG_TERMS):
        return False
    identities = [str(target or "")]
    for element in elements:
        values = (element.get("resource_id"), element.get("text"), element.get("content_desc"), element.get("target"))
        if target and target in values:
            identities.extend(str(value or "") for value in values)
    normalized = " ".join(identities).lower()
    if any(term in normalized for term in ("取消", "cancel", "btn_cancel", "btncancel", "不同意")):
        return False
    return any(term in normalized for term in (
        "确定", "确认", "退出", "btnok", "btn_ok", "ok_btn", "btn_positive", "btn_confirm",
    ))


def _permission_prompt(activity: str, elements: list[dict]) -> dict | None:
    """Recognise Android's system permission surface without trusting the LLM.

    A permission dialog is not an ordinary App page: its allow/deny choice must
    be deterministic and its screenshot must stay bound to the resulting rule.
    """
    # A Settings-backed special access page can retain the preceding
    # GrantPermissions activity name on Android 15.  Content wins over that
    # stale activity value, otherwise it becomes a false runtime permission.
    if _special_permission_page(activity, elements):
        return None
    activity_lower = activity.lower()
    resource_ids = [str(item.get("resource_id") or "") for item in elements]
    is_system_surface = any(term in activity_lower for term in _PERMISSION_ACTIVITY_TERMS) or any(
        resource_id.lower().startswith(prefix) for resource_id in resource_ids
        for prefix in _PERMISSION_RESOURCE_PREFIXES
    )
    if not is_system_surface:
        return None
    message = " ".join(
        part for item in elements for part in (str(item.get("text") or ""), str(item.get("content_desc") or "")) if part
    )
    if not message:
        return None
    labels = {
        "相机": ("拍摄照片", "录制视频", "相机", "take pictures", "record video", "camera"),
        "麦克风": ("录制音频", "录音", "麦克风", "record audio", "microphone"),
        "电话": ("拨打和管理电话", "通话", "电话", "make and manage phone calls", "phone calls"),
        "存储": ("照片和视频", "音乐和音频", "文件", "存储", "photos and videos", "music and audio", "files"),
        "定位": ("位置信息", "位置", "access this device's location", "location"),
    }
    message_lower = message.lower()
    permission_label = next((name for name, terms in labels.items() if any(term in message_lower for term in terms)), "系统权限")
    return {"message": message[:500], "permission_label": permission_label}


def _in_app_permission_rationale_continue_target(elements: list[dict]) -> str | None:
    """Continue control on an in-app pre-permission sheet (not the system dialog).

    Many apps show「权限申请」+ purpose +「好的」before Android's Allow/Deny.
    Leaving that sheet untouched blocks 2.3/4.2 probes that previously worked.
    """
    blob = " ".join(
        str(item.get(key) or "")
        for item in elements for key in ("text", "content_desc", "resource_id")
    )
    # Match against the spaced blob on purpose: the English triggers below
    # ("permission request", "needs the following permission") need their
    # spaces, so a whitespace-stripped copy would silently never match.
    looks_like_rationale = any(term in blob for term in (
        "权限申请", "申请权限", "需要以下权限", "需要获取", "需要访问", "需要使用",
        "permission request", "needs the following permission",
    )) and any(term in blob for term in (
        "摄像头", "相机", "相册", "存储", "麦克风", "定位", "位置", "电话",
        "camera", "microphone", "location", "storage", "photos",
    ))
    if not looks_like_rationale and not (
        "权限申请" in blob and any(term in blob for term in ("为了", "用于", "以便", "修改用户头像", "正常使用"))
    ):
        return None
    continue_terms = ("好的", "知道了", "我知道了", "继续", "去开启", "立即开启", "允许", "确定")
    skip_terms = ("取消", "拒绝", "不允许", "暂不", "以后再说", "cancel", "deny", "不同意")
    for item in elements:
        if not item.get("clickable"):
            continue
        identity = " ".join(
            str(item.get(key) or "") for key in ("target", "resource_id", "text", "content_desc")
        )
        compact_id = re.sub(r"\s+", "", identity)
        if any(term in identity for term in skip_terms):
            continue
        if any(term in compact_id for term in continue_terms) or compact_id.lower() in {"ok", "okay"}:
            return str(
                item.get("target") or item.get("resource_id") or item.get("text") or item.get("content_desc") or ""
            ) or None
    return None


def _permission_rationale_decision(
    ctx: DetectionContext, state: PageState, page, target: str,
) -> dict:
    """Resolve a visible app-owned rationale without an LLM wait-loop."""
    base = {
        "action": "click", "target": target,
        "reason": "应用内权限说明弹窗先点继续/好的，再迎系统权限框做拒权核验",
    }
    if not state.target_visited(page, target):
        return base
    if ctx.runtime.get("permission_denial_probe_terminal"):
        return {
            "action": "back", "target": "",
            "reason": "该权限拒绝后果已形成结论，关闭重复权限说明并继续其它路径",
        }
    retries = ctx.runtime.setdefault("permission_rationale_retries", {})
    key = f"{page.surface_fingerprint}:{target}"
    count = int(retries.get(key, 0))
    if count < 1:
        retries[key] = count + 1
        state.forget_target(page, target)
        return {
            **base,
            "reason": "应用内权限说明首次点击未离开，控件有界重试一次",
        }
    return {
        "action": "back", "target": "",
        "reason": "应用内权限说明重复点击仍无进展，返回继续其它合规路径",
    }


def _is_hub_deferred_document_kind(kind: str | None, title: str = "") -> bool:
    """True for policy-family links that belong on settings/profile/about hubs.

    First-run consent sheets may *name* these clauses, but the audit now opens
    and reads them from 设置/我的/个人信息/关于我们 to avoid splash→Chrome
    duplication. Any required-document kind counts.
    """
    if kind in {"privacy_policy", "user_agreement", "service_terms", "disclosure_list"}:
        return True
    blob = re.sub(r"\s+", "", str(title or "")).lower()
    return any(term in blob for term in (
        "隐私政策", "隐私协议", "用户协议", "服务协议", "使用条款", "服务条款",
        "第三方sdk", "sdk目录", "sdk清单", "收集清单", "共享清单", "个人信息收集清单",
        "信息收集清单", "第三方信息共享", "privacy", "user agreement", "terms of",
    ))


def _is_splash_deferred_document_target(target: str, elements: list[dict]) -> bool:
    """True when a click would open a splash 《政策/协议/SDK》 link that belongs on hubs."""
    raw = str(target or "").strip()
    if not raw or not _is_consent_dialog(elements):
        return False
    if _is_consent_click(raw, elements) or _target_has_decline_semantics(raw, elements):
        return False
    if _unchecked_consent_checkbox(elements) and raw == _unchecked_consent_checkbox(elements):
        return False
    kind = _required_document_kind(raw) or _infer_document_kind(raw, "")
    if _is_hub_deferred_document_kind(kind, raw):
        return True
    if _target_is_document_route(raw):
        return True
    identities = " ".join(_target_identity_values(raw, elements))
    return _is_hub_deferred_document_kind(_required_document_kind(identities), identities)


def _system_settings_surface(activity: str, elements: list[dict]) -> str | None:
    """Classify Android Settings surfaces before generic DFS sees controls.

    System app-details pages contain destructive rows such as uninstall and
    force-stop.  They are never ordinary App pages and must be handled by the
    narrow permission-return state machine.
    """
    low_activity = str(activity or "").lower()
    if not (
        low_activity.startswith("com.android.settings")
        or ".com.android.settings" in low_activity
    ):
        return None
    text = re.sub(r"\s+", "", " ".join(
        str(item.get(key) or "")
        for item in elements for key in ("text", "content_desc", "resource_id")
    ).lower())
    if any(term in text for term in (
        "卸载", "强行停止", "强制停止", "uninstall", "forcestop",
        "通知", "存储和缓存", "storage&cache", "移动数据和wifi",
    )):
        return "app_details"
    if any(term in text for term in ("应用权限", "权限管理", "apppermissions", "permissionmanager")):
        return "permission_manager"
    if any(term in text for term in ("显示在其他应用上层", "所有文件", "无障碍", "通知使用权")):
        return "special_access"
    return "settings_generic"


def _special_permission_page(activity: str, elements: list[dict]) -> str | None:
    """Recognise Settings-backed special access, not a runtime permission.

    Overlay/accessibility/all-files access is granted in Android Settings and
    has no ordinary Allow/Deny dialog.  It must never be clicked or toggled by
    the audit because that would alter a device-wide capability.
    """
    text = " ".join(
        str(item.get(key) or "") for item in elements for key in ("text", "content_desc")
    ).lower()
    compact = re.sub(r"\s+", "", text)
    detected = next((
        kind for kind, terms in _SPECIAL_PERMISSION_TERMS.items()
        if any(re.sub(r"\s+", "", term.lower()) in compact for term in terms)
    ), None)
    # Most special-access pages live in Settings. Overlay has a unique title
    # and may expose a stale PermissionController activity, so allow that one
    # independently of the current activity name.
    if detected == "overlay":
        return detected
    return detected if "settings" in activity.lower() else None


def _special_permission_state(elements: list[dict]) -> str:
    """Read the visible special-access state without changing any setting."""
    text = " ".join(
        str(item.get(key) or "") for item in elements for key in ("text", "content_desc")
    ).lower()
    compact = re.sub(r"\s+", "", text)
    if any(re.sub(r"\s+", "", term) in compact for term in ("not allowed", "not permitted", "不允许", "未允许", "已关闭", "关闭")):
        return "denied"
    if any(re.sub(r"\s+", "", term) in compact for term in ("allowed", "permitted", "已允许", "开启")):
        return "allowed"
    return "unknown"


def _purpose_explained(page_text: str, permission_label: str = "") -> bool:
    """True only when the *permission request* itself states a collection purpose.

    Generic marketing copy such as “为您推荐” on a profile page must not count
    as informing the user why a camera/storage permission is being requested.
    """
    text = re.sub(r"\s+", "", str(page_text or "")).lower()
    if not text:
        return False
    has_permission_context = any(term in text for term in (
        "权限", "授权", "permission", "权限说明", "申请打开", "需要获取", "需要访问", "需要使用",
    ))
    has_purpose = any(term in text for term in (
        "目的", "用于", "以便", "为了", "权限说明", "使用场景", "场景包括", "可用于",
    ))
    permission_matches = not permission_label or _permission_is_referenced(permission_label, text)
    return has_permission_context and has_purpose and permission_matches


def _permission_request_context_key(permission: str, activity: str, business_target: str) -> str:
    """Identify one permission request by its user-visible business context."""
    permission_key = re.sub(r"\s+", "", str(permission or "")).lower()
    target_key = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(business_target or "")).lower()
    activity_key = str(activity or "").rsplit(".", 1)[-1].lower()
    return f"{permission_key}|{activity_key}|{target_key[:120]}"


def _should_report_permission_rerequest(
    previous: dict | int | float | None,
    *,
    context_key: str,
    business_action_sequence: int,
    denial_business_retry: bool,
) -> bool:
    """Report only an unsolicited repeat in the same business context.

    Entering another feature, or explicitly tapping the feature again, is a
    new user intent and cannot be turned into RULE_3_REREQUEST merely because
    Android uses the same permission name.
    """
    if not previous or denial_business_retry or not isinstance(previous, dict):
        return False
    return bool(
        str(previous.get("context_key") or "") == str(context_key or "")
        and int(previous.get("business_action_sequence") or 0) == int(business_action_sequence or 0)
    )


def _denial_blocks_function(page_text: str) -> bool:
    text = str(page_text or "").lower()
    if any(term in text for term in _DENIAL_PERMISSION_TERMS) and any(term in text for term in _DENIAL_BLOCK_TERMS):
        return True
    # WebView business pages can present the consequence in English even when
    # Android's permission dialog was localised.  Require a concrete
    # permission-denied phrase, not merely a generic error label.
    return any(phrase in text for phrase in (
        "no permission", "permission denied", "permission is required", "storage permission",
    ))


def _permission_is_referenced(permission: str, page_text: str) -> bool:
    """Do not bind a post-denial message to a different permission."""
    aliases = {
        "相机": ("相机", "摄像", "拍照", "camera"),
        "定位": ("定位", "位置", "location"),
        "电话": ("电话", "通话", "拨打", "phone"),
        "存储": ("存储", "文件", "相册", "storage", "photos"),
        "麦克风": ("麦克风", "录音", "语音", "microphone"),
        "联系人": ("联系人", "通讯录", "contacts"),
        "短信": ("短信", "sms"),
    }
    text = (page_text or "").lower()
    return any(term.lower() in text for term in aliases.get(permission, (permission,)))


def _manifest_permissions_for_label(permission: str, declared: list[str]) -> list[str]:
    groups = {
        "相机": {"android.permission.CAMERA"},
        "麦克风": {"android.permission.RECORD_AUDIO"},
        "定位": {"android.permission.ACCESS_FINE_LOCATION", "android.permission.ACCESS_COARSE_LOCATION"},
        "联系人": {"android.permission.READ_CONTACTS", "android.permission.WRITE_CONTACTS"},
        "电话": {"android.permission.READ_PHONE_STATE", "android.permission.CALL_PHONE"},
        "短信": {"android.permission.READ_SMS", "android.permission.SEND_SMS"},
        "存储": {
            "android.permission.READ_EXTERNAL_STORAGE", "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO",
            "android.permission.READ_MEDIA_AUDIO", "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
        },
    }
    wanted = groups.get(str(permission or ""), set())
    return sorted(set(str(item) for item in (declared or [])) & wanted)


def _denial_blocks_base_service(
    permission: str,
    page_text: str,
    elements: list[dict],
    business_action: str,
) -> dict:
    """Separate a denied permission's intrinsic subfeature from base service.

    A camera denial preventing *taking a photo* is technically necessary for
    that subfeature.  RULE_4_2 needs evidence that an otherwise usable base
    service is blocked by a non-essential permission.
    """
    action = re.sub(r"\s+", "", str(business_action or "")).lower()
    intrinsic_terms = {
        "相机": ("拍照", "拍摄", "录像", "录制视频", "扫码", "扫描", "camera", "capture", "recordvideo", "scan"),
        "麦克风": ("录音", "语音", "麦克风", "microphone", "recordaudio"),
        "定位": ("定位", "导航", "附近", "location", "navigate"),
        "联系人": ("通讯录", "联系人", "contacts"),
        "电话": ("拨号", "拨打电话", "callphone"),
    }
    permission_intrinsic = any(
        term.lower() in action for term in intrinsic_terms.get(permission, ())
    )
    labels = re.sub(r"\s+", "", " ".join(
        str(item.get(key) or "")
        for item in elements for key in ("text", "content_desc", "resource_id")
    ).lower())
    alternative_service_available = any(term in labels for term in (
        "以后再说", "暂不开启", "取消", "关闭", "notnow", "cancel",
        "输入", "提交", "发送", "相册", "图库", "选择文件", "album", "gallery",
    ))
    explicit_base_block = any(term in re.sub(r"\s+", "", str(page_text or "")).lower() for term in (
        "无法继续使用本应用", "无法使用本应用", "拒绝后无法使用", "必须开启权限才能继续使用",
        "退出应用", "无法", "不能使用", "不可使用",
        "cannotcontinuetheapp", "cannotusetheapp", "permissionrequiredtocontinue", "cannot",
    ))
    denial_message = _denial_blocks_function(page_text) and _permission_is_referenced(permission, page_text)
    blocked = bool(
        denial_message and explicit_base_block
        and not permission_intrinsic and not alternative_service_available
    )
    return {
        "blocked": blocked,
        "permission_intrinsic_to_action": permission_intrinsic,
        "alternative_service_available": alternative_service_available,
        "explicit_base_service_block": explicit_base_block,
        "permission_message_matched": denial_message,
    }


def _is_privacy_dialog_decision(target: str, page_text: str, elements: list[dict] | None = None) -> bool:
    """True when the click is an explicit consent action on a policy dialog."""
    if not any(term in page_text for term in _POLICY_TERMS):
        return False
    if elements is not None:
        if not _is_consent_dialog(elements):
            return False
        return _is_consent_click(target, elements)
    target_lower = target.lower()
    if _id_matches_any_hint(target_lower, _DECLINE_BUTTON_IDS):
        return False
    return any(term in target_lower for term in _CONSENT_TERMS) or _id_matches_any_hint(
        target_lower, _CONSENT_BUTTON_IDS
    )


def _is_privacy_dialog_decline(target: str, page_text: str, elements: list[dict]) -> bool:
    """True for 不同意/拒绝/退出 on a first-run policy dialog only."""
    if not _is_consent_dialog(elements):
        return False
    if not any(term in page_text for term in _POLICY_TERMS):
        return False
    return _target_has_decline_semantics(target, elements)


def _rendered_document_body_kind(page_text: str) -> str | None:
    """Return a document kind only for a substantial rendered clause body.

    OCR can recover the real body while the accessibility tree still exposes
    stale template EditTexts from a reused WebView Activity.  A title alone is
    insufficient (consent sheets and hubs also contain titles), so require a
    substantial body and multiple policy concepts; when the heading is lost,
    privacy-specific prose supplies the conservative fallback identity.
    """
    compact = re.sub(r"\s+", "", str(page_text or ""))
    if len(compact) < 120:
        return None
    kind = _document_body_kind_from_text(compact)
    lowered = compact.lower()
    if not kind:
        privacy_hits = sum(term in lowered for term in ("隐私", "个人信息", "收集", "使用", "权限"))
        agreement_hits = sum(term in lowered for term in ("用户协议", "服务协议", "服务条款", "terms of service"))
        return "privacy_policy" if privacy_hits >= 4 and agreement_hits < 2 else None
    body_hits = sum(
        term.lower() in lowered
        for term in (
            "个人信息", "收集", "使用", "目的", "方式", "范围", "本政策",
            "开发者", "生效日期", "投诉", "撤回同意", "服务条款",
        )
    )
    if body_hits >= 3:
        return kind
    return None


def _visible_required_document_kinds(elements: list[dict]) -> set[str]:
    kinds: set[str] = set()
    for element in elements:
        kinds.update(_document_kinds_in(_element_label(element)))
    return kinds


def _click_failed_due_to_missing_element(error: str) -> bool:
    text = str(error or "").lower()
    return "could not be located" in text or "no such element" in text or "nosuchelement" in text


def _is_consent_click(target: str, elements: list[dict]) -> bool:
    if _target_has_decline_semantics(target, elements):
        return False
    consent = _explicit_consent_target(elements)
    if consent and target == consent:
        return True
    target_lower = str(target or "").lower()
    if _id_matches_any_hint(target_lower, _DECLINE_BUTTON_IDS):
        return False
    if _id_matches_any_hint(target_lower, _CONSENT_BUTTON_IDS):
        return True
    compact = re.sub(r"\s+", "", str(target or ""))
    if not compact or len(compact) > 12:
        return False
    return any(term in compact for term in _CONSENT_TERMS)


def _is_launch_gate_activity(activity: str) -> bool:
    return any(
        term in str(activity or "").lower()
        for term in ("splash", "welcome", "guide", "intro", "onboard")
    )


def _needs_perception_ocr(activity: str, elements: list[dict]) -> bool:
    """Compatibility adapter for the observer-owned OCR policy."""
    policy = PerceptionOcrPolicy(
        has_document_body=_has_document_body_surface,
        is_consent=_is_consent_dialog,
        is_launch_gate=_is_launch_gate_activity,
        visible_text=_page_visible_text,
        is_settings_hub=_looks_like_settings_or_profile,
        element_label=_element_label,
    )
    return policy.needs_perception(activity, elements)


def _is_pre_app_entry_surface(activity: str, elements: list[dict], ctx: DetectionContext) -> bool:
    """True until the audited app has been entered past the first-run gate."""
    if _is_consent_dialog(elements):
        return True
    if ctx.runtime.get("consent_dialog_seen") and not ctx.runtime.get("consent_accepted"):
        return True
    if _is_launch_gate_activity(activity) and not (
        ctx.runtime.get("consent_accepted") or ctx.runtime.get("public_app_surface_seen")
    ):
        return True
    return False


def _hub_scenarios_outstanding(frontier: ScenarioFrontier) -> bool:
    remaining = frontier.snapshot().get("remaining_items", [])
    return any(item in remaining for item in ("1.3", "3.8", "6.1"))


def _page_names_privacy_policy(elements: list[dict], extra_text: str = "") -> bool:
    blob = f"{_page_visible_text(elements)} {extra_text}"
    compact = re.sub(r"\s+", "", blob)
    compact_lower = compact.lower()
    if any(
        mark.lower() in compact_lower
        for mark in ("《隐私政策》", "《隐私协议》", "《隐私声明》", "privacy policy", "privacy agreement")
    ):
        return True
    for element in elements:
        visible = re.sub(r"\s+", "", f"{element.get('text') or ''}{element.get('content_desc') or ''}")
        if not visible or any(cue in visible for cue in ("我已阅读", "已阅读并同意")):
            continue
        if _required_document_kind(visible) == "privacy_policy" and len(visible) <= 16:
            return True
    return False


def _permission_denial_probe_outstanding(
    ctx: DetectionContext, scenario_frontier: ScenarioFrontier | None = None,
) -> bool:
    """Whether the deny profile still owes a conclusive 4.2 business probe."""
    action = str((ctx.cfg.get("detection") or {}).get("permission_probe_action") or "").lower()
    if action != "deny" or ctx.runtime.get("permission_denial_probe_terminal"):
        return False
    if "4.2" in set(ctx.runtime.get("scenario_completed_items") or []):
        return False
    if scenario_frontier is not None:
        remaining = set(scenario_frontier.snapshot().get("remaining_items") or [])
        return "4.2" in remaining
    return True


def _hub_list_may_need_swipe(page) -> bool:
    """Whether a settings hub should be swiped even without scrollable=true.

    RecyclerView/Compose settings lists often omit the flag, so 注销 below the
    fold would never appear. Personal-info forms (昵称/头像/手机号) and media
    source sheets are not that kind of list — swiping them only burns steps.
    """
    elements = list(getattr(page, "elements", None) or [])
    if _media_capture_chooser_target(elements) or _media_album_chooser_target(elements):
        return False
    page_blob = " ".join(
        str(item.get(key) or "")
        for item in elements for key in ("text", "content_desc", "resource_id")
    )
    if any(term in page_blob for term in ("照相机", "请选择图片", "选择图片来源", "修改头像", "编辑资料")):
        return False
    formish = 0
    for term in ("昵称", "头像", "性别", "年龄", "城市", "手机号", "nickname", "avatar", "gender", "birthday"):
        if any(term in str(item.get("text") or "") or term in str(item.get("content_desc") or "") for item in elements):
            formish += 1
    if formish >= 2:
        return False
    if formish >= 1 and any(term in page_blob for term in ("头像", "avatar", "oi_head", "headimage")):
        return False
    if any(item.get("scrollable") for item in elements):
        return True
    return formish < 2


def _generic_page_may_need_swipe(page, *, page_role: str = "") -> bool:
    """Return whether a non-document App viewport has discoverable content below.

    Scrolling is a navigation edge in deep mode, not a document-only action.
    This covers business lists, feedback/complaint forms and Compose screens
    while excluding consent, login, system and long-document flows that have
    dedicated policies.
    """
    if page_role.startswith("low_value_") or page_role in {
        "consent_dialog", "document_body", "login_gate", "system_permission",
        "system_launcher", "system_file_picker", "external_browser", "foreign_app",
        "splash_or_gate", "loading_shell",
    }:
        return False
    elements = list(getattr(page, "elements", None) or [])
    if any(item.get("scrollable") for item in elements):
        return True
    list_classes = ("recyclerview", "listview", "scrollview", "lazycolumn", "webview")
    if any(any(term in str(item.get("class_name") or "").lower() for term in list_classes) for item in elements):
        return True
    # Compose sometimes exposes only bounded rows. Several full-width rows
    # reaching the lower viewport are enough to justify one verified swipe.
    bounded = [
        _bounds_tuple(str(item.get("bounds") or ""))
        for item in elements if item.get("clickable")
    ]
    bounded = [item for item in bounded if item]
    height = max((item[3] for item in bounded), default=0)
    lower_rows = sum(1 for item in bounded if height and item[3] >= height * 0.72)
    return len(bounded) >= 4 and lower_rows >= 2


def _scroll_hub_for_privacy_path(
    client, ctx: DetectionContext, state: PageState, page, activity: str,
    evidence: list[dict], reason: str,
) -> bool:
    """Swipe the settings hub while 3.8/6.1 still need a visible path.

    Many RecyclerView/Compose lists never expose ``scrollable=true``. Mock
    clients without ``scroll_down`` still return False so unit tests stay safe.
    """
    scroll_policy = SettingsHubScrollPolicy(max_scrolls=3)
    max_scrolls = scroll_policy.max_scrolls
    if int(ctx.runtime.get("hub_privacy_scrolls", 0)) >= max_scrolls:
        return False
    if not _hub_list_may_need_swipe(page):
        return False
    scroll_down = getattr(client, "scroll_down", None)
    if not callable(scroll_down):
        return False
    try:
        moved = bool(scroll_down())
    except ExplorationError as exc:
        evidence.append(record_event(
            ctx, "appium", "privacy_hub_scroll_failed",
            activity=activity, error=str(exc)[:300],
        ))
        return False
    scroll_result = scroll_policy.observe(
        attempts=int(ctx.runtime.get("hub_privacy_scrolls", 0)), moved=moved,
    )
    ctx.runtime["hub_privacy_scrolls"] = scroll_result.attempts
    if not scroll_result.moved:
        if scroll_result.exhausted:
            ctx.runtime["privacy_hub_search_exhausted"] = True
            evidence.append(record_event(
                ctx, "appium", "privacy_hub_path_exhausted", activity=activity,
                reason="设置枢纽已多次滚动仍未见注销/授权入口",
            ))
        return False
    state.record_action(page, "scroll")
    evidence.append(record_event(
        ctx, "appium", "privacy_hub_scrolled", activity=activity,
        attempt=ctx.runtime["hub_privacy_scrolls"], reason=reason,
    ))
    if scroll_result.exhausted:
        ctx.runtime["privacy_hub_search_exhausted"] = True
    return True


def _document_scroll_status(
    client, *, legacy_false_status: str = "stuck",
) -> str:
    """Normalize old/new clients to moved/bottom/stuck document semantics."""
    structured = getattr(client, "scroll_document_down", None)
    if callable(structured):
        status = str(structured() or "").strip().lower()
        if status in {"moved", "bottom", "stuck"}:
            return status
        return "stuck"
    legacy = getattr(client, "scroll_down", None)
    if not callable(legacy):
        raise ExplorationError("当前 Appium 客户端不支持文档滚动")
    return "moved" if bool(legacy()) else legacy_false_status


def _is_self_app_launch_click(target: str, activity: str, package_name: str, app_name: str) -> bool:
    """True when the model tries to tap the app icon/name while already inside it."""
    if _is_launcher_activity(activity) or not _activity_belongs_to_package(activity, package_name):
        return False
    compact = re.sub(r"\s+", "", str(target or ""))
    name = re.sub(r"\s+", "", str(app_name or ""))
    return bool(name) and compact == name


_IN_APP_SAFE_LABEL_TERMS = (
    "同意", "拒绝", "取消", "确定", "确认", "关闭", "返回", "跳过", "下一步", "完成",
    "隐私", "政策", "协议", "条款", "设置", "我的", "首页", "发现", "消息", "场景",
    "登录", "注册", "账号", "账户", "注销", "撤回", "授权", "投诉", "客服", "关于",
    "清单", "sdk", "通知", "推送", "固件", "家庭", "推荐", "书城", "书架",
    "我", "继续", "更多", "查看", "打开", "进入",
    "agree", "accept", "deny", "cancel", "ok", "back", "skip", "next", "continue", "settings",
    "profile", "home", "login", "privacy", "policy", "terms", "account", "delete",
)


def _match_elements_for_target(target: str, elements: list[dict]) -> list[dict]:
    return matching_elements(target, elements)


def _is_foreign_app_launch_click(
    target: str,
    activity: str,
    package_name: str,
    app_name: str,
    elements: list[dict],
    foreground_package: str = "",
) -> bool:
    """True when already inside the audited app but the model taps another app icon.

    Launcher icons sometimes leak into OCR/accessibility while a splash is up.
    Tapping them switches the audit to a different installed package.
    """
    pkg = str(package_name or "").strip()
    if not pkg:
        return False
    inside = _activity_belongs_to_package(activity, pkg)
    fg = str(foreground_package or "").strip().lower()
    if fg:
        inside = inside or fg == pkg.lower() or pkg.lower() in fg
    if _is_launcher_activity(activity) or not inside:
        return False
    compact_target = re.sub(r"\s+", "", str(target or ""))
    audited_name = re.sub(r"\s+", "", str(app_name or ""))
    if not compact_target or (audited_name and compact_target == audited_name):
        return False
    matched = _match_elements_for_target(target, elements)
    in_app_matches = [
        element for element in matched
        if not any(term in str(element.get("resource_id") or "").lower() for term in (
            "launcher", "workspace", "hotseat", "all_apps", "bubbletext",
        ))
        and (
            bool(str(element.get("resource_id") or "").strip())
            or bool(roles_for_element(element))
            or _is_bottom_nav_hub_tab(element, elements)
        )
    ]
    if in_app_matches:
        return False
    explicit_launcher_node = any(
        any(term in str(element.get("resource_id") or "").lower() for term in (
            "launcher", "workspace", "hotseat", "all_apps", "bubbletext",
        ))
        for element in matched
    )
    if (
        any(term.lower() in compact_target.lower() for term in _IN_APP_SAFE_LABEL_TERMS)
        and not explicit_launcher_node
    ):
        return False
    if _required_document_kind(compact_target) or re.search(r"《.+》", compact_target):
        return False
    if not matched:
        # Absence from the current accessibility snapshot means stale/OCR-only,
        # not "another App". The stale-target guard handles it without blocking
        # legitimate canvas-rendered account/profile destinations.
        return False

    def _resource_id_looks_in_app(resource_id: str) -> bool:
        rid = str(resource_id or "").strip().lower()
        if not rid:
            return False
        if pkg.lower() in rid:
            return True
        if any(term in rid for term in (
            "launcher", "workspace", "hotseat", "all_apps", "bubbletext",
        )):
            return False
        # Any ordinary control id (even without package prefix) is in-app UI.
        return True

    for element in matched:
        resource_id = str(element.get("resource_id") or "")
        if any(term in resource_id.lower() for term in (
            "launcher", "workspace", "hotseat", "all_apps", "bubbletext",
        )):
            return True
        if _resource_id_looks_in_app(resource_id):
            return False
        if roles_for_element(element):
            return False
        label = re.sub(
            r"\s+", "",
            f"{element.get('text') or ''}{element.get('content_desc') or ''}",
        )
        if not label:
            return False
        if audited_name and label == audited_name:
            return False
        if any(term.lower() in label.lower() for term in _IN_APP_SAFE_LABEL_TERMS):
            return False
        if _required_document_kind(label) or re.search(r"《.+》", label):
            return False
        # Nicknames, phone numbers and canvas tabs are often short clickable
        # labels without ids. Only explicit launcher ids/classes are sufficient
        # evidence for crossing the foreign-App safety boundary.
        if element.get("clickable"):
            return False
    return False


def _is_allowed_non_audited_surface(
    activity: str, package_name: str, foreground_package: str = "",
) -> bool:
    """Surfaces that may leave the audited package without foreign-app recovery.

    Launcher exits keep using the existing foreground-relaunch path.
    Permission prompts, Custom Tabs and file pickers are temporary system UI.
    Broad com.android.* matching is avoided so other installed apps still count
    as package drift.
    """
    del package_name  # reserved for future audited-vs-system heuristics
    lowered = str(activity or "").lower()
    fg = str(foreground_package or "").strip().lower()
    blob = f"{lowered} {fg}"
    if any(term in blob for term in (
        *_LAUNCHER_ACTIVITY_TERMS,
        *_PERMISSION_ACTIVITY_TERMS,
        *_CUSTOM_TAB_ACTIVITY_TERMS,
        *_FILE_PICKER_ACTIVITY_TERMS,
    )):
        return True
    system_markers = (
        "permissioncontroller",
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.android.settings",
        "com.google.android.settings",
        "com.android.chrome",
        "com.chrome.",
        "org.chromium.",
        "com.android.documentsui",
        "com.google.android.documentsui",
        "com.android.intentresolver",
        "com.android.systemui",
        "com.google.android.apps.photos",
        "com.android.camera",
    )
    return any(marker in blob for marker in system_markers)


def _has_left_audited_package(
    activity: str, package_name: str, foreground_package: str = "",
) -> bool:
    """True when the foreground process is another third-party app."""
    pkg = str(package_name or "").strip().lower()
    if not pkg:
        return False
    if _is_allowed_non_audited_surface(activity, package_name, foreground_package):
        return False
    fg = str(foreground_package or "").strip().lower()
    if fg:
        if fg == pkg or pkg in fg:
            return False
        return True
    # Without current_package, relative activities (".MainActivity") are ambiguous.
    text = str(activity or "").strip()
    if not text or text.startswith("."):
        return False
    return not _activity_belongs_to_package(text, package_name)


def _is_document_body_hyperlink(target: str, activity: str, elements: list[dict]) -> bool:
    """In-app WebView 《清单》 spans are not independent accessibility routes.

    Chrome Custom Tabs can follow those links in another process. Tapping the
    same ClickableSpan inside the audited app's WebView commonly crashes
    UiAutomator2, so the explorer scrolls instead of opening nested documents.
    """
    if not _has_document_body_surface(activity, elements):
        return False
    if any(term in str(activity or "").lower() for term in _CUSTOM_TAB_ACTIVITY_TERMS):
        return False
    identity = str(target or "")
    lowered = identity.lower()
    if any(term in lowered for term in ("back", "返回", "ll_back", "iv_back", "btn_back")):
        return False
    if re.search(r"《.+》", identity) or _required_document_kind(identity):
        return True
    return False


def _raster_screenshot_ready(path: Path) -> bool:
    try:
        header = path.read_bytes()[:8]
    except OSError:
        return False
    return header.startswith(b"\x89PNG") or header.startswith(b"\xff\xd8")


def _redirect_after_ignored_app_icon(
    ctx: DetectionContext,
    state: PageState,
    page,
    *,
    consent_accepted: bool,
    settings_hub: bool,
    hub_pending: bool,
) -> dict:
    """After ignoring foreign/self app icons, prefer unread docs / hub — never idle-wait forever."""
    unread_now = _unread_for_page(ctx, page.elements, state.targets_visited_on(page))
    if unread_now:
        return {
            "action": "click", "target": unread_now,
            "reason": "已在应用内，改为打开尚未阅读的条款",
            "source": "deterministic_document",
        }
    hub_tab = _privacy_hub_tab_target(page.elements)
    if hub_tab and not state.target_visited(page, hub_tab):
        return {
            "action": "click", "target": hub_tab,
            "reason": "忽略其它应用后改点我的/设置进入隐私枢纽",
            "source": "deterministic_privacy_hub",
        }
    if settings_hub and hub_pending:
        hub_row = _hub_privacy_action_target(ctx, page.elements, state.targets_visited_on(page))
        if hub_row:
            return {
                "action": "click", "target": hub_row,
                "reason": "忽略其它应用后改点设置页隐私相关入口",
                "source": "deterministic_privacy_hub",
            }
    idle = int(ctx.runtime.get("home_idle_cycles", 0)) + 1
    ctx.runtime["home_idle_cycles"] = idle
    idle_limit = max(2, int(ctx.cfg.get("detection", {}).get("home_idle_cycle_limit", 3)))
    if consent_accepted and idle >= idle_limit:
        return {
            "action": "stop", "target": "",
            "reason": "首页连续无进展（忽略其它应用后仍无枢纽/条款入口），结束遍历避免空转",
            "source": "home_idle_exhausted",
        }
    return {
        "action": "wait", "target": "",
        "reason": "已在被测应用内，忽略其它应用图标并等待本应用界面",
        "source": "wait",
    }


def _refresh_privacy_policy_text(ctx: DetectionContext) -> None:
    """Keep the 2.1/6.5 corpus to privacy policy + disclosure lists.

    User-service agreements often contain SLA “N个工作日” language that must
    not be treated as a personal-information complaint deadline.
    """
    by_kind = ctx.runtime.get("policy_text_fragments_by_kind") or {}
    parts: list[str] = []
    for kind in ("privacy_policy", "disclosure_list"):
        parts.extend(by_kind.get(kind) or [])
    if parts:
        joined = "\n".join(parts)
        ctx.runtime["privacy_policy_text"] = joined
        ctx.runtime["policy_text"] = joined
        return
    unknown = by_kind.get("unknown") or ctx.runtime.get("policy_text_fragments") or []
    if unknown:
        ctx.runtime["policy_text"] = "\n".join(unknown)


def _append_policy_fragment(ctx: DetectionContext, fragment: str, target: str = "") -> None:
    text = str(fragment or "").strip()
    if len(text) < 20:
        return
    kind = _infer_document_kind(target, text) or "unknown"
    fragments = ctx.runtime.setdefault("policy_text_fragments", [])
    if text not in fragments:
        fragments.append(text)
    by_kind = ctx.runtime.setdefault("policy_text_fragments_by_kind", {})
    bucket = by_kind.setdefault(kind, [])
    if text not in bucket:
        bucket.append(text)
    _refresh_privacy_policy_text(ctx)


def _mark_required_document_read(
    ctx: DetectionContext, target: str, scenario_frontier=None, page_text: str = "",
    body_kind_hint: str | None = None,
) -> str | None:
    expected = _infer_document_kind(target, "")
    valid_kinds = set(dict(_REQUIRED_DOCUMENT_KIND_TERMS))
    body_kind = body_kind_hint if body_kind_hint in valid_kinds else None
    if body_kind is None and page_text:
        body_kind = _document_body_kind_from_text(page_text)
    mismatch = bool(expected and body_kind and expected != body_kind)
    if mismatch:
        # Click said SDK directory but body is 服务协议 — do not stamp either
        # the wrong kind or the wrong title. User/service agreements also stay
        # independent because the UI may expose both as separate documents.
        marker = {
            "target": str(target or "")[:200],
            "expected": expected,
            "observed": body_kind,
        }
        mismatches = ctx.runtime.setdefault("document_kind_mismatches", [])
        if marker not in mismatches:
            mismatches.append(marker)
        aliases = {
            _normalize_document_title(item)
            for item in (target, _DOCUMENT_KIND_DISPLAY_TITLES.get(expected or "", "")) if item
        }
        observed_routes = ctx.runtime.setdefault("document_route_observed_kinds", {})
        for alias in aliases:
            if alias:
                observed_routes[alias] = body_kind
        kind = body_kind
    else:
        kind = _infer_document_kind(target, page_text) or body_kind
    if not kind:
        return None
    kinds = _read_document_kinds(ctx)
    kinds.add(kind)
    ctx.runtime["read_document_kinds"] = kinds
    titles = _read_document_titles(ctx)
    canonical_title = _DOCUMENT_KIND_DISPLAY_TITLES.get(kind, "")
    if not mismatch:
        titles.add(_normalize_document_title(target))
    if canonical_title:
        titles.add(_normalize_document_title(canonical_title))
    preferred = _preferred_inline_document_target(page_text if mismatch else target, kind)
    if preferred:
        titles.add(_normalize_document_title(preferred))
    compact = _normalize_document_title(f"{target} {page_text}")
    for term in dict(_REQUIRED_DOCUMENT_KIND_TERMS).get(kind, ()):
        needle = _normalize_document_title(term)
        if needle and needle in compact:
            titles.add(needle)
    ctx.runtime["read_document_titles"] = titles
    _prune_unread_document_gaps(ctx)
    if kind == "privacy_policy":
        ctx.runtime["privacy_policy_read_complete"] = True
        ctx.runtime["policy_document_read_complete"] = True
    completed_by_kind = ctx.runtime.setdefault("document_read_complete_by_kind", {})
    completed_by_kind[kind] = True
    if scenario_frontier is not None and kind in {"user_agreement", "service_terms"}:
        scenario_frontier.mark_completed(["1.4"], evidence_source="terms_document_read")
    if scenario_frontier is not None and kind == "privacy_policy":
        scenario_frontier.mark_completed(["1.1", "2.4"], evidence_source="policy_semantics_reviewed")
    return kind


def _record_document_completion(
    ctx: DetectionContext,
    *,
    document_key: str,
    entry_target: str,
    page_text: str,
    scenario_frontier=None,
) -> DocumentCompletionResolution:
    """Record one completed body without losing its original click target.

    A reused WebView can show a user agreement after the user clicked a
    privacy-policy link.  The actual body is valid evidence for the agreement,
    but it is not evidence that the privacy policy was available or read.
    """
    actual_title = str(document_key or "").rsplit(":document:", 1)[-1]
    source_target = str(entry_target or actual_title)
    expected_kind = _infer_document_kind(source_target, "")
    observed_kind = (
        _document_body_kind_from_text(page_text)
        or _rendered_document_body_kind(page_text)
        or _required_document_kind(actual_title)
        or _infer_document_kind(actual_title, "")
    )
    if not observed_kind:
        fragments = ctx.runtime.get("policy_text_fragments_by_kind") or {}
        observed_kind = _rendered_document_body_kind(
            "\n".join(str(item) for values in fragments.values() for item in values)
        )
    completed_kind = _mark_required_document_read(
        ctx,
        source_target,
        scenario_frontier,
        page_text=page_text,
        body_kind_hint=observed_kind,
    )
    routes = ctx.runtime.setdefault("completed_document_routes", set())
    if not isinstance(routes, set):
        routes = set(routes or ())
        ctx.runtime["completed_document_routes"] = routes
    if entry_target and not (expected_kind and observed_kind and expected_kind != observed_kind):
        routes.add(entry_target)
    return DocumentCompletionResolution(
        entry_target=source_target,
        actual_title=actual_title,
        expected_kind=expected_kind,
        observed_kind=observed_kind,
        completed_kind=completed_kind,
        mismatch=bool(expected_kind and observed_kind and expected_kind != observed_kind),
    )


def _document_wait_should_be_kept(
    page_role: PageRole,
    document_key: str | None,
    state: PageState,
) -> bool:
    """Only an active unread document may suppress the normal wait breaker."""
    key = str(document_key or "")
    return bool(
        page_role is PageRole.DOCUMENT_BODY
        and key
        and not state.document_is_complete(key)
    )


def _document_viewport_fingerprint(page_text: str, kind: str | None = None) -> str | None:
    """Stable identity for one visible document viewport.

    Apps often expose the same body through differently named or stale links.
    Identity therefore comes from the rendered body, never the click label or
    a previously cached document kind.
    """
    normalized = re.sub(r"\s+", "", str(page_text or "")).lower()
    normalized = re.sub(r"\d{1,2}:\d{2}", "", normalized)
    if len(normalized) < 24:
        return None
    sample = normalized[:2400]
    return hashlib.sha256(sample.encode("utf-8")).hexdigest()


def _external_document_progress_key(
    runtime: dict, surface: str, origin_target: str, observed_kind: str | None,
) -> str:
    """Keep anonymous Custom-Tab documents separate by observed body kind.

    Chrome can erase the originating Appium label after a coordinate retry.
    Until the body reveals its kind, continue the most recently active key for
    that surface/origin; once identified, switch to a kind-specific key.
    """
    # Prefer the semantic body kind over the raw click label.  The same
    # document may be exposed as English/Chinese text or a resource id; using
    # that raw label here creates duplicate progress keys and repeat reads.
    raw_origin = _normalize_document_title(origin_target) or "anonymous"
    # Canonicalise aliases only when the originating target itself carries a
    # document meaning.  For opaque route ids (e.g. ``terms-entry-one``), keep
    # the route-specific base so two different entries with the same body kind
    # can still be compared for stale-content reuse.
    origin_kind = str(_required_document_kind(origin_target) or "").strip()
    if not origin_kind:
        lowered_origin = str(origin_target or "").lower()
        # Resource-id aliases are canonicalised when their hint is specific
        # (privacy/user-agreement/service-id tokens).  Generic ``terms`` or
        # ``agreement`` substrings are deliberately excluded because apps
        # commonly use them in distinct opaque route ids.
        specific_id_hints = {
            hint
            for hints in _DOCUMENT_KIND_ID_HINTS.values()
            for hint in hints
            if hint not in {"terms", "agreement"}
        }
        if any(hint in lowered_origin for hint in specific_id_hints):
            origin_kind = str(_infer_document_kind(origin_target, "") or "").strip()
    origin = origin_kind or raw_origin
    base = f"{surface}:{origin}"
    raw_base = f"{surface}:{raw_origin}"
    active = runtime.setdefault("external_document_active_keys", {})
    if observed_kind:
        key = f"{base}:{observed_kind}"
        active[base] = key
        # Preserve the anonymous/raw alias so a subsequent body read whose
        # originating label disappeared can continue the same semantic key.
        active[raw_base] = key
        return key
    return str(active.get(base) or active.get(raw_base) or f"{base}:unknown")


def _external_body_identity_status(
    *,
    origin_target: str,
    expected_kind: str | None,
    observed_kind: str | None,
    viewport_fingerprint: str | None,
    completed_fingerprints: set[str],
    previous_origin_target: str = "",
    previous_viewport_fingerprint: str = "",
) -> str:
    """Classify a Custom Tab body only after its navigation identity settles."""
    if not viewport_fingerprint:
        return "unknown"
    already_complete = viewport_fingerprint in set(completed_fingerprints or set())
    same_previous_body = bool(
        previous_origin_target
        and previous_origin_target != str(origin_target or "")
        and previous_viewport_fingerprint == viewport_fingerprint
    )
    kind_mismatch = bool(
        expected_kind and observed_kind and expected_kind != observed_kind
    )
    if already_complete and same_previous_body and kind_mismatch:
        return "stale_mismatch"
    if already_complete:
        return "duplicate"
    return "new"


_RESUME_RUNTIME_KEYS = (
    "read_document_titles",
    "read_document_kinds",
    "seen_document_kinds",
    "runtime_session_recovery_attempted",
    "runtime_session_recovery_attempts",
    "runtime_session_recoveries",
    "runtime_session_recovery_status",
    "runtime_recovery_checkpoint",
    "runtime_checkpoint_replayed",
    "navigation_replay_required",
    "engine_failure",
    "engine_failures",
    "consent_document_titles",
    "completed_document_fingerprints",
    "completed_document_routes",
    "external_document_followed_links",
    "nested_document_followed_links",
    "policy_text_fragments",
    "policy_text_fragments_by_kind",
    "privacy_policy_text",
    "policy_text",
    "policy_document_read_complete",
    "privacy_policy_read_complete",
    "document_read_complete_by_kind",
    "scenario_completed_items",
    "scenario_coverage",
    "pending_permission_denial_probe",
    "permission_denial_retry_targets",
    "permission_denial_probe_status",
    "permission_denial_probe_terminal",
    "last_business_trigger_action",
    "login_status",
    "login_verification_source",
    "manual_login_waited",
    "manual_login_verified",
    "manual_login_timed_out",
    "last_permission_verification",
    "permission_allow_verified",
)
_RESUME_SET_RUNTIME_KEYS = (
    "read_document_titles", "read_document_kinds", "seen_document_kinds",
    "consent_document_titles", "completed_document_fingerprints",
    "completed_document_routes", "external_document_followed_links",
    "nested_document_followed_links", "permission_denial_retry_targets",
)


def _phase_artifact_path(ctx: DetectionContext, category: str, filename: str) -> Path:
    """Return a phase-isolated path so dual runs cannot overwrite evidence."""
    profile = re.sub(
        r"[^0-9a-zA-Z_-]+", "_", str(ctx.runtime.get("probe_profile") or "observe")
    ).strip("_") or "observe"
    path = ctx.data_dir / str(category) / profile / str(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _save_navigation_replay_checkpoint(ctx: DetectionContext, state: PageState) -> Path:
    """Persist the small breadcrumb ledger before repairing a lost session."""
    return TraversalCheckpointRepository(ctx.data_dir, ctx.runtime).save_navigation(state)


def _restore_navigation_replay_checkpoint(ctx: DetectionContext, state: PageState) -> bool:
    if not ctx.runtime.get("resume_requested"):
        return False
    return TraversalCheckpointRepository(ctx.data_dir, ctx.runtime).restore_navigation(state)


def _save_traversal_checkpoint(
    ctx: DetectionContext,
    state: PageState,
    findings: list[Finding],
    evidence: list[dict],
) -> Path:
    return TraversalCheckpointRepository(
        ctx.data_dir, ctx.runtime,
        runtime_keys=_RESUME_RUNTIME_KEYS,
        set_like_keys=_RESUME_SET_RUNTIME_KEYS,
    ).save_traversal(
        state=state, run_state=DetectionRunState.from_context(ctx),
        findings=findings, evidence=evidence,
    )


def _restore_traversal_checkpoint(
    ctx: DetectionContext, state: PageState,
) -> tuple[list[Finding], list[dict]]:
    if not ctx.runtime.get("resume_requested"):
        return [], []
    repository = TraversalCheckpointRepository(
        ctx.data_dir, ctx.runtime,
        runtime_keys=_RESUME_RUNTIME_KEYS,
        set_like_keys=_RESUME_SET_RUNTIME_KEYS,
    )
    restored = repository.restore_traversal(state)
    if not restored.restored:
        return [], []
    payload = restored.payload
    typed_payload = payload.get("run_state")
    if isinstance(typed_payload, dict):
        restore_result = RunCheckpointCodec.restore(
            typed_payload, DetectionRunState.from_context(ctx),
        )
        if not restore_result.restored:
            ctx.runtime.setdefault("run_state_recovery_gaps", []).append(
                f"checkpoint_restore:{restore_result.reason}"
            )
    findings = [
        Finding(
            kind=str(item.get("kind") or ""),
            category=int(item.get("category") or 0),
            payload=dict(item.get("payload") or {}),
        )
        for item in payload.get("findings") or []
        if item.get("kind") and int(item.get("category") or 0) in range(1, 7)
    ]
    evidence = [dict(item) for item in payload.get("evidence") or [] if isinstance(item, dict)]
    ctx.runtime["resume_checkpoint_restored"] = True
    return findings, evidence


_is_destructive_confirmation = is_destructive_confirmation


def _is_logout_confirmation_dialog(page_text: str, elements: list[dict] | None = None) -> bool:
    """True for a logout confirm sheet — not the settings row that opens it."""
    blob = re.sub(r"\s+", "", str(page_text or "")).lower()
    if not any(term.lower() in blob for term in _AUTHENTICATED_LOGOUT_TERMS):
        # Some dialogs only say「确定退出」without repeating 退出登录.
        if not any(term in blob for term in ("确定退出", "确认退出", "是否退出", "要退出登录")):
            return False
    affirmative = ("确定", "确认", "退出", "ok", "yes")
    dismissive = ("取消", "再想想", "暂不", "否", "cancel", "no")
    has_affirm = any(term in blob for term in affirmative)
    has_dismiss = any(term in blob for term in dismissive)
    if has_affirm and has_dismiss:
        return True
    if elements:
        labels = [
            re.sub(r"\s+", "", _short_control_label(item) or "")
            for item in elements if item.get("clickable")
        ]
        short = [label for label in labels if 0 < len(label) <= 8]
        return (
            any(any(term in label.lower() for term in affirmative) for label in short)
            and any(any(term in label.lower() for term in dismissive) for label in short)
            and any(term.lower() in blob for term in (*_AUTHENTICATED_LOGOUT_TERMS, "退出"))
        )
    return False


def _logout_confirmation_cancel_target(elements: list[dict]) -> str | None:
    """Return only a short, explicit dismiss action from a logout dialog."""
    dismissive = ("取消", "再想想", "暂不", "否", "cancel", "not now", "no")
    destructive = ("确定", "确认", "退出", "注销", "删除", "yes", "ok")
    for item in elements:
        if not item.get("clickable") or not item.get("displayed", True):
            continue
        label = re.sub(r"\s+", "", _short_control_label(item) or "").lower()
        if not label or len(label) > 10:
            continue
        if any(term in label for term in destructive):
            continue
        if any(term in label for term in dismissive):
            return str(
                item.get("target") or item.get("resource_id")
                or item.get("text") or item.get("content_desc") or ""
            ) or None
    return None


def _permission_related_hub_drill_target(
    elements: list[dict], visited_targets: set[str],
) -> str | None:
    """Navigation row worth replaying during the allow-only comparison pass."""
    visited = set(visited_targets)
    ranked: list[tuple[int, str]] = []
    for element in elements:
        if not element.get("clickable") or _is_bottom_nav_hub_tab(element, elements):
            continue
        target = str(
            element.get("target") or element.get("resource_id")
            or element.get("text") or element.get("content_desc") or ""
        )
        if not target or target in visited:
            continue
        identity = " ".join(
            str(element.get(key) or "")
            for key in ("target", "resource_id", "text", "content_desc")
        ).lower()
        if any(term in identity for term in (
            "隐私政策", "用户协议", "服务协议", "sdk", "条款",
            "注销", "退出登录", "清除缓存", "检查更新",
            "生日", "出生日期", "地区", "城市", "location", "birthday",
        )):
            continue
        if any(term in identity for term in (
            "头像", "avatar", "head_image", "headimage", "上传", "upload",
        )):
            ranked.append((0, target))
        elif any(term in identity for term in (
            "个人信息", "个人资料", "编辑资料", "账号与安全", "账户与安全",
            "userinfo", "personaldata", "profile", "accountsecurity",
        )):
            ranked.append((1, target))
        elif any(term in identity for term in (
            "客服", "投诉", "举报", "反馈", "工单", "帮助与支持",
            "customer service", "complaint", "feedback", "support", "ticket",
        )):
            ranked.append((2, target))
    ranked.sort()
    return ranked[0][1] if ranked else None


def _hub_checklist_complete(ctx: DetectionContext) -> bool:
    """True when required hub drills for 3.8/6.1-style audit have been attempted."""
    return bool(
        ctx.runtime.get("hub_settings_drilled")
        or ctx.runtime.get("delete_paths_observed")
        or ctx.runtime.get("withdraw_paths_observed")
    ) and bool(
        ctx.runtime.get("logout_entry_explored")
        or ctx.runtime.get("logout_confirmation_observed")
        or int(ctx.runtime.get("hub_privacy_scrolls", 0)) >= 3
    )


def _is_logout_confirmation_target(target: str, elements: list[dict]) -> bool:
    """Recognise the affirmative button on an already identified logout dialog."""
    identities = _target_identity_values(target, elements)
    value = " ".join(identities).strip().lower()
    return bool(value) and any(term.lower() in value for term in _LOGOUT_CONFIRM_BUTTON_TERMS)


def _is_required_exploration_target(target: str, elements: list[dict]) -> bool:
    """Return whether a safe fallback target advances a required privacy goal.

    A model may decide to stop too early, but the worker must not replace that
    with arbitrary UI clicking.  Only visible, privacy-relevant navigation is
    eligible for the deterministic stop override below.
    """
    identities = [str(target or "")]
    for element in elements:
        if target and target in (element.get("resource_id"), element.get("text"), element.get("content_desc")):
            identities.extend(str(element.get(key) or "") for key in ("resource_id", "text", "content_desc"))
            if roles_for_element(element) & {
                "document_link", "privacy_hub_entry", "settings_entry", "withdraw_control",
                "delete_control", "complaint_control", "business_trigger", "personalization_control",
            }:
                return True
    normalized = " ".join(identities).lower()
    return any(term.lower() in normalized for term in _REQUIRED_EXPLORATION_TARGET_TERMS)


def _is_low_audit_value_route(target: str, elements: list[dict]) -> bool:
    """Delegate to the pure predicate; the label resolution stays page-local."""
    return is_low_audit_value_route(
        target,
        _labels_for_click_target(target, elements),
        protected_terms=_LOW_VALUE_PROTECTED_ROUTE_TERMS,
        maintenance_terms=_NON_AUDIT_MAINTENANCE_TERMS,
        exempt_terms=_LOW_VALUE_EXEMPT_ROUTE_TERMS,
        low_value_terms=_LOW_AUDIT_VALUE_ROUTE_TERMS,
    )


def _surface_has_explicit_compliance_action(elements: list[dict]) -> bool:
    """Whether a low-value-looking page still exposes a rule-bearing edge.

    Generic “customer service” on a paywall is usually sales support.  It does
    not keep the whole commercial page alive unless the UI also exposes an
    actual complaint/feedback/ticket action or another privacy-control route.
    """
    action_terms = (
        *_DOCUMENT_TERMS, *_DOCUMENT_FOLLOW_TERMS, *_DELETE_TERMS, *_WITHDRAW_TERMS,
        *_EXPLICIT_REDRESS_ACTION_TERMS,
        "权限管理", "授权管理", "隐私设置", "个人信息管理", "账号与安全",
        "permission settings", "privacy settings", "account security",
    )
    for item in elements:
        if not item.get("clickable"):
            continue
        identity = " ".join(
            str(item.get(key) or "")
            for key in ("target", "resource_id", "text", "content_desc")
        ).lower()
        if any(term.lower() in identity for term in action_terms):
            return True
    return False


def _low_audit_value_surface_kind(
    activity: str, elements: list[dict], screen_text: str = "",
) -> str | None:
    """Classify whole screens that should be observed once and left.

    This is deliberately semantic and App-independent.  A single VIP banner
    on a home page is not enough: the activity or most visible actions must be
    commercial, or the viewport must contain several independent commercial
    signals.  Explicit privacy/redress/account controls always win.
    """
    visible = f"{activity} {_page_visible_text(elements)} {screen_text}".lower()
    if _is_redress_interaction_surface(activity, visible):
        return None
    if _surface_has_explicit_compliance_action(elements):
        return None

    compact_visible = re.sub(r"\s+", "", visible)
    empty_state_patterns = (
        r"(?:暂无|没有|未找到|无).{0,12}(?:数据|记录|内容|结果|消息|文件|书本|资源|项目|订单|收藏|历史)",
        r"(?:数据|记录|内容|结果|消息|文件|书本|资源|项目|订单|收藏|历史)(?:为空|不存在)",
    )
    english_empty = (
        "no data", "no records", "no results", "no content", "no files",
        "nothing here", "empty state", "not found",
    )
    if (
        any(re.search(pattern, compact_visible) for pattern in empty_state_patterns)
        or any(term in visible for term in english_empty)
        or "空空如也" in compact_visible
    ):
        return "empty_state"

    # Read-only writing/usage dashboards and profile value pickers do not
    # advance a privacy rule.  They are observed once and left; permission
    # controls named location/定位 remain handled on the originating feature.
    if (
        any(term in compact_visible for term in ("作品数", "章节数", "总字数", "近7天", "写作统计", "创作统计"))
        or any(term in visible for term in ("word count", "writing statistics", "chapters"))
    ):
        return "usage_statistics"
    activity_lower = str(activity or "").lower()
    if (
        any(term in activity_lower for term in ("locationset", "birthday", "datepick", "regionselect", "cityselect"))
        and any(term in compact_visible for term in ("选择地区", "选择城市", "生日", "出生日期", "北京", "天津", "河北省"))
    ):
        return "profile_attribute_editor"

    clickable = [item for item in elements if item.get("clickable")]
    low_clicks = 0
    for item in clickable:
        target = str(
            item.get("target") or item.get("resource_id") or item.get("text")
            or item.get("content_desc") or ""
        )
        if target and _is_low_audit_value_route(target, elements):
            low_clicks += 1
    distinct_commercial_terms = {
        term.lower() for term in _LOW_AUDIT_VALUE_ROUTE_TERMS if term.lower() in visible
    }
    commercial_activity = any(
        term in str(activity or "").lower() for term in _LOW_VALUE_COMMERCIAL_ACTIVITY_TERMS
    )
    commercial_actions_dominate = bool(clickable) and low_clicks * 2 >= len(clickable)
    commercial_copy_dominates = len(distinct_commercial_terms) >= 4
    if distinct_commercial_terms and (
        commercial_activity or commercial_actions_dominate or commercial_copy_dominates
    ):
        return "commercial"

    help_title = any(term in visible for term in (
        "帮助", "教程", "指南", "常见问题", "help", "tutorial", "guide", "faq",
    ))
    help_body = any(term.lower() in visible for term in _LOW_VALUE_HELP_TERMS)
    if help_title and help_body:
        return "help_tutorial"
    return None


def _frontier_recovery_attempt_allowed(runtime: dict, route_key: str, limit: int = 1) -> bool:
    """Consume one bounded recovery attempt for a semantic route.

    The key is independent of PageState fingerprints, which change after a
    redraw.  This prevents a previously exhausted avatar/home route from being
    revived merely because the same page was rendered with different bounds.
    """
    key = str(route_key or "").strip()
    if not key:
        return False
    attempts = runtime.setdefault("frontier_recovery_attempts", {})
    count = int(attempts.get(key, 0))
    if count >= max(1, int(limit)):
        return False
    attempts[key] = count + 1
    return True


def _is_safe_deep_probe_target(target: str, elements: list[dict]) -> bool:
    """Allow deep mode to visit a visible business route after an early stop.

    This is intentionally narrower than arbitrary clicking: irreversible,
    credential, payment and submission controls remain excluded.  Visiting a
    read-only business entry is necessary to trigger contextual permission
    prompts (for example, storage access from customer service) and build the
    denial-to-business-impact evidence chain required by rule 4.1.
    """
    if not _target_is_visible(target, elements):
        return False
    if _is_low_audit_value_route(target, elements):
        return False
    if _is_unlabelled_structural_bounds_target(target, elements):
        return False
    identities = [str(target or "")]
    for element in elements:
        values = (
            str(element.get("target") or ""),
            str(element.get("resource_id") or ""),
            str(element.get("text") or ""),
            str(element.get("content_desc") or ""),
        )
        if target and target not in values:
            continue
        identities.extend(str(element.get(key) or "") for key in ("resource_id", "text", "content_desc"))
        if _is_consent_or_decline_control(element) or _is_checkbox_like(element):
            return False
        if _id_matches_any_hint(str(element.get("resource_id") or ""), _PRIVACY_DIALOG_BUTTON_IDS):
            return False
    normalized = " ".join(identities).lower()
    blocked = (
        "删除", "注销", "清除", "退出登录", "退出应用", "退出程序", "关闭应用",
        "支付", "付款", "下单", "购买", "充值",
        "提交", "发送", "发布", "保存", "返回", "确认订单", "转账", "发送验证码", "登录", "注册", "密码",
        "delete", "logout", "payment", "purchase", "submit", "password", "back",
    )
    if _is_app_exit_confirmation(target, elements):
        return False
    return not any(term in normalized for term in blocked)


def _next_safe_deep_target(
    elements: list[dict], visited: set[str], *, ctx: DetectionContext | None = None,
) -> str | None:
    """Next visible reversible edge for generic sibling-aware deep search."""
    candidates: list[tuple[int, int, str]] = []
    for index, item in enumerate(elements):
        if not item.get("clickable"):
            continue
        target = str(
            item.get("target") or item.get("resource_id") or item.get("text")
            or item.get("content_desc") or ""
        )
        if not target or target in visited or not _is_safe_deep_probe_target(target, elements):
            continue
        roles = roles_for_element(item)
        # Rules-library routes first, then ordinary reversible business edges.
        priority = 0 if roles & {
            "document_link", "privacy_hub_entry", "settings_entry", "withdraw_control",
            "complaint_control", "business_trigger", "personalization_control",
        } else 1
        candidates.append((priority, index, target))
    candidates.sort()
    return candidates[0][2] if candidates else None


# Pure safety predicates live in agent.ai_explorer.action_safety_checks;
# these aliases keep the legacy call sites readable until Phase G cleanup.
_is_transaction_target = is_transaction_target


_target_is_visible = is_stale_or_invisible_target


_is_unlabelled_structural_bounds_target = is_unlabelled_structural_bounds_target


def _enforce_final_action_safety(
    decision: dict,
    *,
    activity: str,
    elements: list[dict],
    low_value_surface_kind: str | None,
    audited_package: str,
    audited_app_name: str,
    foreground_package: str,
    is_root: bool,
) -> tuple[dict, str | None]:
    """Revalidate the action after every LLM and deterministic override."""
    policy = FinalActionSafetyPolicy(checks=SafetyChecks.for_page(SafetyCheckFacts(
        activity=activity,
        audited_package=audited_package,
        audited_app_name=audited_app_name,
        foreground_package=foreground_package,
        elements=tuple(elements),
        foreign_app_launcher=lambda target: _is_foreign_app_launch_click(
            target, activity, audited_package, audited_app_name, elements,
            foreground_package=foreground_package,
        ),
        label_blob_for=lambda target: _labels_for_click_target(target, elements),
        protected_route_terms=_LOW_VALUE_PROTECTED_ROUTE_TERMS,
        maintenance_terms=_NON_AUDIT_MAINTENANCE_TERMS,
        exempt_route_terms=_LOW_VALUE_EXEMPT_ROUTE_TERMS,
        low_value_route_terms=_LOW_AUDIT_VALUE_ROUTE_TERMS,
    )))
    return policy.enforce(
        decision,
        FinalActionContext(
            is_root=is_root,
            low_value_surface_kind=str(low_value_surface_kind or ""),
        ),
    )


def _action_identity(target: str, elements: list[dict], reason: str = "") -> str:
    """Return only display-level metadata for classifying an observed click."""
    identities = [str(target or ""), str(reason or "")]
    for element in elements:
        if target and target in (
            str(element.get("target") or ""),
            str(element.get("resource_id") or ""), str(element.get("text") or ""),
            str(element.get("content_desc") or ""),
        ):
            identities.extend(str(element.get(key) or "") for key in ("resource_id", "text", "content_desc"))
    return " ".join(identities).lower()


def _bounds_tuple(value: str) -> tuple[int, int, int, int] | None:
    return bounds_tuple(value)


def _is_onboarding_transition(target: str, elements: list[dict], reason: str = "") -> bool:
    identity = _action_identity(target, elements, reason)
    return any(term.lower() in identity for term in _ONBOARDING_TRANSITION_TERMS)


def _is_business_trigger_action(target: str, elements: list[dict], reason: str = "") -> bool:
    """Separate a genuine feature invocation from consent/onboarding/navigation.

    Rule 4(1) asks whether a permission is requested *before* the user invokes
    the corresponding business feature. A click such as “立即体验” merely exits
    onboarding and must not make a startup permission look business-triggered.
    """
    # The target and its visible control define the action.  LLM reasoning may
    # mention a later camera/avatar goal while it is currently opening a policy;
    # mixing that prose into classification caused document links to receive a
    # coordinate "business retry" and reopen the same body.
    identity = _action_identity(target, elements)
    if any(term.lower() in identity for term in _ONBOARDING_TRANSITION_TERMS):
        return False
    non_business = (
        *_DOCUMENT_TERMS, *_POLICY_TERMS, "设置", "关于", "我的", "个人中心",
        "登录", "注册", "返回", "同意", "不同意", "取消", "setting", "about",
        "profile", "login", "register", "back", "agree", "decline",
    )
    if _target_is_document_route(target) or any(term.lower() in identity for term in non_business):
        return False
    if any(term.lower() in identity for term in _BUSINESS_ACTION_TERMS):
        return True
    # Screen-recipe / LLM media assists on 2.3/4.2 paths are business probes even
    # when the accessibility tree hides the mic/album label.
    reason_l = str(reason or "").lower()
    if str(target or "").startswith("relative:") and any(
        token in reason_l for token in ("4.2", "2.3", "客服", "权限", "语音", "相册", "上传", "媒体")
    ):
        return True
    return False


def _looks_like_main_surface(activity: str, elements: list[dict]) -> bool:
    """Recognise app-level roots so route depth is not measured from Splash."""
    activity_lower = (activity or "").lower()
    if any(term in activity_lower for term in ("permission", "settings", "launcher", "webview", "splash")):
        return False
    if "homeactivity" in activity_lower or "hometab" in activity_lower:
        return True
    # ``MainActivity`` is commonly a single host for every Fragment/Compose
    # destination. Treating the Activity name as the root reset DFS on detail
    # pages. Require several controls that are actually laid out in the bottom
    # navigation band; persistent text elsewhere is not enough.
    bounded = []
    for item in elements:
        bounds = _bounds_tuple(str(item.get("bounds") or ""))
        if bounds:
            bounded.append((item, bounds))
    height = max((bounds[3] for _, bounds in bounded), default=0)
    root_tabs: set[str] = set()
    if height:
        for item, bounds in bounded:
            if not item.get("clickable") or (bounds[1] + bounds[3]) / 2 < height * 0.78:
                continue
            identity = " ".join(str(item.get(key) or "") for key in (
                "text", "content_desc", "resource_id",
            )).lower()
            for term in ("首页", "我的", "消息", "设置", "发现", "home", "profile", "account"):
                if term in identity:
                    root_tabs.add(term)
    return len(root_tabs) >= 3


def _next_top_level_audit_target(
    elements: list[dict], visited_route_keys: set[str] | None = None,
) -> str | None:
    """Low-audit pruning is engine-owned vocabulary; inject it into the hub picker."""
    return _next_top_level_audit_target_def(
        elements, visited_route_keys, low_audit_route_check=_is_low_audit_value_route,
    )


def _should_anchor_root(state: PageState, page, last_target: str = "") -> bool:
    """Anchor only a verified top-level transition, never any MainActivity child."""
    if not _looks_like_main_surface(page.activity, page.elements):
        return False
    if state.navigation_depth == 0 or state.is_root_page(page):
        return True
    return _is_top_level_navigation_target(last_target, page.elements)


def _authenticated_session_visible(elements: list[dict], extra_text: str = "") -> bool:
    """Return whether the visible UI contains non-sensitive proof of login.

    Some apps reuse a class such as ``LoginKT`` for both the credential form
    and a logged-in profile tab.  An Activity name, or merely leaving the
    form, is therefore not enough.  We only use display-level account anchors
    already visible to the tester: an explicit sign-out control, or a masked /
    full mobile number together with two profile destinations, or a user label
    together with those destinations.  The value itself is never stored.
    Toast copy such as “登录成功” is also treated as session proof.
    """
    return _LOGIN_SURFACE_CLASSIFIER.authenticated(elements, extra_text=extra_text)


def _is_login_gate(activity: str, elements: list[dict]) -> bool:
    """Identify a real credential form, never a policy sentence or login entry.

    WebViews often contain words such as “登录、手机号、验证码”.  Those words are
    policy content, not a safe reason to suspend the audit for manual login.
    Require an actual editable credential control plus a visible submit action.
    """
    return _LOGIN_SURFACE_CLASSIFIER.is_login_gate(activity, elements)


def _credential_login_surface(
    activity: str, elements: list[dict], *, document_key: str | None,
) -> bool:
    """A verified document viewport cannot simultaneously be a login gate."""
    return not document_key and _is_login_gate(activity, elements)


def _login_invitation_target(elements: list[dict], page_text: str = "") -> str | None:
    """Return an explicit, non-credential transition into the login form.

    Many apps first show a modal such as “该功能需要登录 / 前往登录” on a
    main-tab Activity.  It is not yet a credential form, but backing out here
    silently removes every login-required scenario from coverage.  We may
    safely enter the form; credentials remain strictly human-only.
    """
    return _LOGIN_SURFACE_CLASSIFIER.invitation_target(elements, page_text)


def _logged_out_profile_visible(elements: list[dict], extra_text: str = "") -> bool:
    """True when the profile/hub clearly shows a guest / not-logged-in state."""
    return _LOGIN_SURFACE_CLASSIFIER.logged_out_profile(elements, extra_text=extra_text)


def _profile_login_entry(elements: list[dict], extra_text: str = "") -> str | None:
    """Find a visible profile-page login *entry*, never a credential control.

    Covers “点击此处登录”, the common banner “未登录”, and a clickable avatar
    wrapping that label. The actual form remains strictly hands-off.
    """
    return _LOGIN_SURFACE_CLASSIFIER.profile_entry(elements, extra_text=extra_text)


def _external_navigation_surface(activity: str, elements: list[dict] | None = None) -> str | None:
    """Classify non-App surfaces that must not consume an App traversal path."""
    surface = classify_navigation_surface(activity, elements)
    return surface.kind if surface.kind in {"file_picker", "custom_tab"} else None


def _external_document_body_visible(elements: list[dict]) -> bool:
    """Conservatively detect readable content in a browser surface.

    Chrome's toolbar is exposed through UiAutomator even when the WebView body
    is blank, so a non-empty accessibility tree alone is not enough.  Prefer
    actual text/scrollable WebView nodes and ignore the browser chrome labels.
    The visual blank-body probe in ``AppiumClient`` is used as a second signal
    when WebView accessibility is disabled.
    """
    chrome_terms = {
        "close", "back", "forward", "share", "more", "refresh", "地址栏",
        "返回", "关闭", "分享", "更多", "搜索", "https", "http://", "https://",
    }
    readable = 0
    for item in elements:
        if item.get("scrollable") or "webview" in str(item.get("class_name") or "").lower():
            return True
        if item.get("clickable"):
            continue
        text = " ".join(str(item.get(key) or "") for key in ("text", "content_desc")).strip()
        lowered = text.lower()
        if len(text) >= 16 and not any(term in lowered for term in chrome_terms):
            readable += len(text)
    return readable >= 20


def _target_is_document_route(target: str) -> bool:
    normalized = str(target or "").lower()
    if any(term.lower() in normalized for term in (*_DOCUMENT_TERMS, *_DOCUMENT_FOLLOW_TERMS, *_POLICY_TERMS)):
        return True
    # Settings rows often expose only a resource id such as oi_private.
    return any(hint in normalized for hint in _DOCUMENT_ROUTE_ID_HINTS)


def _external_document_looks_like_policy(elements: list[dict]) -> bool:
    blob = " ".join(
        str(item.get(key) or "")
        for item in elements
        for key in ("text", "content_desc", "resource_id")
    ).lower()
    return any(term.lower() in blob for term in (*_DOCUMENT_TERMS, *_POLICY_TERMS))


def _treat_as_external_policy_document(origin_target: str, elements: list[dict]) -> bool:
    return _target_is_document_route(origin_target) or (
        _external_document_body_visible(elements) and _external_document_looks_like_policy(elements)
    )


def _document_follow_target(elements: list[dict], visited: set[str], current_document: str = "") -> str | None:
    """Pick a visible in-document privacy disclosure link not read yet."""
    parent = _normalize_document_title(str(current_document or "").rsplit(":document:", 1)[-1])
    candidates: list[tuple[int, str]] = []
    for element in elements:
        if not element.get("clickable"):
            continue
        label = " ".join(
            str(element.get(key) or "") for key in ("text", "content_desc", "resource_id")
        ).strip()
        normalized = re.sub(r"\s+", "", label).lower()
        if not normalized or normalized in visited:
            continue
        if parent and _normalize_document_title(label) == parent:
            continue
        if not any(term.lower() in normalized for term in _DOCUMENT_FOLLOW_TERMS):
            continue
        if any(term in normalized for term in ("返回", "关闭", "分享", "更多", "地址栏", "refresh")):
            continue
        target = str(element.get("resource_id") or element.get("text") or element.get("content_desc") or "").strip()
        if target:
            priority = 0 if any(term.lower() in normalized for term in ("个人信息收集清单", "信息收集清单", "个人信息清单")) else 1
            candidates.append((priority, target))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1] if candidates else None


def _root_route_key(activity: str, target: str) -> str:
    """Stable identity for a root-page probe across redraws.

    Root pages often get a new surface fingerprint after returning from a
    settings/business screen (selected tab, counters and bounds can change).
    Using the page fingerprint alone therefore lets the same route be opened
    repeatedly.  Keep the key semantic and display-only so it is safe to use
    as a loop guard without persisting sensitive UI content.
    """
    normalized = re.sub(r"\d+", "#", str(target or "").strip().lower())
    normalized = re.sub(r"\s+", " ", normalized)
    return f"{str(activity or '').strip()}|{normalized[:160]}"


def _scenario_items_for_action(target: str, elements: list[dict]) -> set[str]:
    """Map the final executable target to legal scenarios from visible roles.

    This runs after arbitration, so deterministic DFS/pruning clicks and LLM
    clicks share the same accounting path.  Scenario statistics no longer
    depend on whether a separate frontier recommender happened to nominate
    the winning action first.
    """
    raw = str(target or "")
    raw_bounds = raw[len("bounds:"):] if raw.startswith("bounds:") else ""
    roles: set[str] = set()
    for item in elements:
        values = {
            str(item.get("target") or ""), str(item.get("resource_id") or ""),
            str(item.get("text") or ""), str(item.get("content_desc") or ""),
        }
        if raw in values or (raw_bounds and raw_bounds == str(item.get("bounds") or "")):
            roles.update(roles_for_element(item))
    if not roles and raw:
        roles.update(roles_for_element({"text": raw, "target": raw, "clickable": True}))
    return scenarios_for_roles(roles)


def _coverage_gaps(
    ctx: DetectionContext,
    permission_prompts: int,
    login_gate_seen: bool,
    pages_covered: int,
    scenario_snapshot: dict | None = None,
) -> list[str]:
    """Return unmet evidence goals; absence is never converted into compliance."""
    gaps: list[str] = []
    if not ctx.runtime.get("policy_document_read_complete") or ctx.runtime.get("incomplete_documents"):
        gaps.append("未完成可访问隐私政策/服务条款的全文阅读")
    seen_kinds = {str(kind) for kind in (ctx.runtime.get("seen_document_kinds") or set())}
    read_kinds = {str(kind) for kind in (ctx.runtime.get("read_document_kinds") or set())}
    agreement_family = {"user_agreement", "service_terms"}
    if (seen_kinds & agreement_family) and not (read_kinds & agreement_family):
        gaps.append("可见的用户服务协议/服务条款未完成阅读")
    declared_permissions = [str(permission).upper() for permission in (getattr(ctx.apk, "permissions", None) or [])]
    if any(any(term in permission for term in _SENSITIVE_PERMISSION_TERMS) for permission in declared_permissions) and not permission_prompts:
        gaps.append("已声明敏感权限，但本次可访问路径未触发系统授权提示")
    if login_gate_seen and not ctx.runtime.get("manual_login_verified"):
        gaps.append("登录后功能未覆盖：需在模拟器中由人工完成登录后再继续核验")
    special_results = ctx.runtime.get("special_permission_probe_results", {})
    for permission_type in sorted(ctx.runtime.get("special_permissions_observed", set())):
        outcome = special_results.get(permission_type)
        if outcome == "app_resumed":
            gaps.append(
                f"特殊权限“{permission_type}”已保持拒绝状态并返回应用；未触发依赖该权限的业务功能，必要性仍待后续场景核验"
            )
        else:
            gaps.append(f"特殊权限“{permission_type}”已记录系统授权状态；尚未完成拒绝后业务路径核验")
    if getattr(ctx.task, "mode", "fast") == "deep" and pages_covered < 3:
        gaps.append(f"深度检测基础覆盖不足：仅覆盖 {pages_covered} 个页面，未达到可出具结论的最小范围")
    if not ctx.runtime.get("withdraw_paths_observed") and not ctx.runtime.get("privacy_hub_visited"):
        gaps.append("未进入设置/个人中心核验撤回同意与授权管理入口")
    if scenario_snapshot:
        unresolved = [
            str(row.get("item") or "")
            for row in (scenario_snapshot.get("items") or [])
            if row.get("state") not in {
                "evidence_observed", "requires_server_audit", "not_applicable",
            }
            and row.get("item")
        ]
        if unresolved:
            gaps.append(f"场景义务尚未完成：{', '.join(dict.fromkeys(unresolved))}")
    _prune_unread_document_gaps(ctx)
    read_kinds = {str(kind) for kind in _read_document_kinds(ctx)}
    pending = [
        gap for gap in ctx.runtime.get("rule_coverage_gaps", [])
        if not _unread_document_gap_resolved(str(gap), read_kinds)
    ]
    return list(dict.fromkeys([
        *[gap for gap in gaps if not _unread_document_gap_resolved(str(gap), read_kinds)],
        *pending,
    ]))


def _wait_for_manual_login(client: AppiumClient, ctx: DetectionContext, wait_seconds: int) -> bool:
    """Compatibility entry point; the login state machine lives in its module."""
    interrupted = lambda: any(
        callable(check) and check()
        for check in (
            ctx.runtime.get("is_canceled"),
            ctx.runtime.get("is_paused"),
            ctx.runtime.get("is_terminated"),
        )
    )
    def emit(event_type: str, **meta) -> None:
        item = record_event(ctx, "appium", event_type, **meta)
        ctx.runtime.setdefault("manual_login_probe_evidence", []).append(item)

    waiter = ManualLoginWaiter(
        client=client,
        runtime=ctx.runtime,
        detection_config=ctx.cfg.get("detection", {}),
        package_name=str(getattr(ctx.apk, "package_name", "") or ""),
        parse_page=parse_page,
        authenticated_visible=_authenticated_session_visible,
        is_login_gate=_is_login_gate,
        looks_like_main_content=_looks_like_main_content_surface,
        screenshot_path=lambda: _phase_artifact_path(
            ctx, "screenshot", "manual-login-probe.png",
        ),
        screenshot_ready=_raster_screenshot_ready,
        extract_screen_text=lambda path: ocr_text_blob(extract_words_from_image(path) or []),
        emit=emit,
        interrupted=interrupted,
    )
    return waiter.wait(wait_seconds)


def _record_decision_override(
    ctx: DetectionContext,
    evidence: list,
    *,
    activity: str,
    original: dict | None,
    new_decision: dict,
    source: str,
    reason: str,
    **extra,
) -> None:
    """Record when an LLM/fallback proposal is rewritten by deterministic guards."""
    if not original:
        return
    if (
        original.get("action") == new_decision.get("action")
        and str(original.get("target") or "") == str(new_decision.get("target") or "")
    ):
        return
    evidence.append(record_event(
        ctx, "appium", "llm_decision_overridden", activity=activity,
        original_action=original.get("action"),
        original_target=original.get("target"),
        original_reason=str(original.get("reason") or "")[:300],
        new_action=new_decision.get("action"),
        new_target=new_decision.get("target"),
        new_reason=str(new_decision.get("reason") or "")[:300],
        override_source=source,
        reason=reason,
        **extra,
    ))


_NON_OVERRIDABLE_STOP_SOURCES = {
    "coverage_pruning",
    "safety_boundary",
    "home_idle_exhausted",
    "deterministic_frontier_incomplete",
    "deterministic_frontier_exhausted",
}


def _stop_override_allowed(decision_source: str) -> bool:
    """A circuit-breaker stop must not be revived by generic deep search."""
    return str(decision_source or "") not in _NON_OVERRIDABLE_STOP_SOURCES


def _deep_search_consent_blocked(consent_dialog: bool, consent_dialog_seen: object) -> bool:
    """同意弹窗页禁止深搜覆盖 LLM 的等待决策。

    任务 281：元素级 ``_is_consent_dialog`` 在条款探测返回后失判，导致模型
    正确的 wait 被覆盖成点击「Appium Settings」这类无关目标。本页周期已判
    定为同意弹窗、或阶段台账记录到 consent_dialog_seen 时，一律不再抢点。
    """
    return bool(consent_dialog or consent_dialog_seen)


def _call_llm_fallback(
    llm, elements: list[dict], visited: set[str], allow_dialog_actions: bool = False, **kwargs,
) -> dict:
    """Call fallback_action with optional scene kwargs; tolerate older test doubles."""
    try:
        return llm.fallback_action(elements, visited, allow_dialog_actions, **kwargs)
    except TypeError:
        try:
            return llm.fallback_action(elements, visited, **kwargs)
        except TypeError:
            return llm.fallback_action(elements, visited)

def _bind_screenshot_to_finding(screenshot: dict | None, finding_kind: str) -> None:
    """Allow one permission screenshot to support multiple independent rules."""
    if not screenshot:
        return
    meta = screenshot.setdefault("meta", {})
    existing = meta.get("finding_kind")
    kinds = list(meta.get("finding_kinds") or [])
    if existing and existing not in kinds:
        kinds.append(existing)
    if finding_kind not in kinds:
        kinds.append(finding_kind)
    meta["finding_kinds"] = kinds
    meta.pop("finding_kind", None)


def _perform_action(client, decision: dict):
    """Execute one decision through the shared action executor."""
    assert client is not None
    return ActionExecutor(client).perform_or_raise(decision)


def _revoke_media_probe_permissions(
    ctx: DetectionContext, evidence: list[dict], activity: str, client,
) -> None:
    """Keep camera/storage denied right before a 2.3/4.2 media probe."""
    device = getattr(client, "_device", None) if client else None
    guard = MediaProbePermissionGuard(
        device=device,
        package_name=str(getattr(ctx.apk, "package_name", "") or ""),
    )
    revoked = guard.revoke()
    if revoked:
        evidence.append(record_event(
            ctx, "appium", "media_probe_permissions_revoked",
            activity=activity, package=guard.package_name, revoked=revoked,
        ))


def _maybe_enter_sdk_observation_phase(
    ctx: DetectionContext, activity: str, elements: list[dict], evidence: list[dict], client,
) -> None:
    """Grant phone/location only after first-run permission scenes had a chance."""
    entered = SdkObservationGate().should_enter(SdkObservationGateFacts(
        probe_profile=str(ctx.runtime.get("probe_profile") or ""),
        already_granted=bool(ctx.runtime.get("sdk_observation_permissions_granted")),
        consent_dialog_visible=bool(_is_consent_dialog(elements)),
        permission_prompt_visible=bool(_permission_prompt(activity, elements)),
        consent_seen=bool(ctx.runtime.get("consent_dialog_seen")),
        consent_accepted=bool(ctx.runtime.get("consent_accepted")),
        foreign_start_surface=bool(_associated_start_activity(
            activity,
            str(getattr(ctx.apk, "package_name", "") or ""),
            foreground_package=str(getattr(client, "last_package", "") or "") if client else "",
        )),
        consent_timestamp_ms=int(ctx.runtime.get("consent_timestamp_ms") or 0),
        post_consent_window_ms=max(0, int(ctx.cfg.get("detection", {}).get(
            "post_consent_permission_window_ms", 30000,
        ))),
        permission_prompt_seen_after_consent=bool(
            ctx.runtime.get("permission_prompt_seen_after_consent")
        ),
        public_surface_seen=bool(ctx.runtime.get("public_app_surface_seen")),
        now_ms=int(time.time() * 1000),
    ))
    if not entered:
        return
    device = getattr(client, "_device", None) if client else None
    granted = grant_observation_permissions(
        device, ctx.apk.package_name, list(getattr(ctx.apk, "permissions", None) or []),
    )
    ctx.runtime["sdk_observation_permissions_granted"] = True
    evidence.append(record_event(
        ctx, "appium", "collection_observability_permissions_granted",
        package=ctx.apk.package_name, granted_count=len(granted), granted=granted,
        phase="sdk_observation",
    ))


def _click_nested_disclosure_if_present(
    ctx: DetectionContext, state: PageState, page, activity: str,
    evidence: list[dict], origin: str, client,
    recovery: RuntimeRecoveryCoordinator | None = None,
) -> bool:
    """Open a collection/SDK list linked from a finished parent document.

    Mid-scroll taps on WebView ClickableSpans often crash UiAutomator2.
    After the parent has been scrolled to the end, follow each such link
    once. A failed tap is recovered and skipped, not treated as coverage.
    """
    followed = ctx.runtime.setdefault("nested_document_followed_links", set())
    target = _document_follow_target(page.elements, followed, origin)
    if not target:
        return False
    followed.add(target)
    try:
        _perform_action(client, {
            "action": "click", "target": target,
            "reason": "父条款已读完，继续打开正文中的收集/共享清单",
        })
    except ExplorationError as exc:
        evidence.append(record_event(
            ctx, "appium", "nested_document_link_failed", activity=activity,
            parent=origin, target=target, error=str(exc)[:300],
        ))
        if recovery is not None:
            recovery.recover_runtime_loss(len(evidence), exc)
        return False
    state.commit_target(page, target)
    state.record_action(page, "click")
    ctx.runtime["last_appium_action"] = {
        "action": "click", "target": target, "declined_privacy": False,
    }
    evidence.append(record_event(
        ctx, "appium", "nested_document_link_followed", activity=activity,
        parent=origin, target=target,
    ))
    return True


class AppiumExplorerEngine:
    """将设备操作限制为 Appium 点击/返回；模型仅负责在页面白名单中选择动作。"""
    def __init__(self, client: AppiumClient | None = None, llm: LLMController | None = None):
        self.client = client
        self.llm = llm
        self._prepared = False

    def prepare(self, ctx: DetectionContext) -> None:
        if not ctx.apk_path or not ctx.apk_path.exists():
            raise ExplorationError("真实遍历缺少已解密 APK")
        package_name = ctx.apk.package_name
        if not package_name:
            raise ExplorationError("APK 未解析出包名，无法启动真实遍历")
        self.client = self.client or AppiumClient(ctx.cfg)
        record_event(ctx, "appium", "session_connecting")
        self.client.connect()
        record_event(ctx, "appium", "session_connected")
        reuse_install = bool(
            ctx.runtime.get("apk_installed_for_task")
            and ctx.cfg.get("detection", {}).get("reuse_app_install_between_probe_phases", True)
        )
        if reuse_install:
            record_event(
                ctx, "appium", "apk_data_reset_skipped", package=package_name,
                reason="同一检测任务的后续权限阶段复用应用数据和登录态，不重复清除",
            )
        else:
            record_event(ctx, "appium", "installing_apk", package=package_name)
            was_installed = self.client.install(ctx.apk_path, package_name)
            ctx.runtime["apk_installed_for_task"] = True
            record_event(
                ctx, "appium",
                "apk_data_cleared" if was_installed else "apk_fresh_installed",
                package=package_name,
                operation="pm_clear" if was_installed else "install",
            )
        if ctx.cfg.get("detection", {}).get("reset_runtime_permissions", True):
            device = getattr(self.client, "_device", None)
            revoke = getattr(device, "revoke_runtime_permissions", None)
            permissions = list(getattr(ctx.apk, "permissions", None) or [])
            if callable(revoke):
                revoked = revoke(package_name, permissions)
                record_event(
                    ctx, "appium", "runtime_permissions_reset",
                    package=package_name, revoked_count=len(revoked),
                    phase="permission_dialog",
                    probe_profile=str(ctx.runtime.get("probe_profile") or "observe"),
                )
            # Phone/location stay denied until the post-consent 4.1 window
            # closes.  Phase B grants them for SDK observation.
            ctx.runtime["sdk_observation_permissions_granted"] = False
        self._prepared = True

    def run(self, ctx: DetectionContext) -> EngineResult:
        """Delegate the single probe profile cycle to the orchestrator."""
        return ExplorerOrchestrator(
            prepare_phase=lambda value: self.prepare(value) if not self._prepared else None,
            run_cycle=self._run_phase_cycle,
        ).run_phase(ctx)

    def _run_phase_cycle(self, ctx: DetectionContext) -> EngineResult:
        assert self.client is not None
        llm = self.llm or LLMController(ctx.cfg)
        llm_proposals = LLMProposalAdapter(llm)
        llm_effectiveness = LLMEffectivenessLedger()
        performance_budget = PerformanceBudget(ctx.cfg.get("detection", {}))
        replay_writer = ReplayWriter(_phase_artifact_path(ctx, "runtime", "appium-replay.jsonl"))
        run_state = DetectionRunState.from_context(ctx)
        action_pipeline = ActionPipeline()
        permission_probes = PermissionProbeLedger(ctx.runtime)
        completion_gate = ExplorationCompletionGate()
        run_finalizer = RunFinalizer(
            completion_gate=completion_gate,
            performance_budget=performance_budget,
            llm_effectiveness=llm_effectiveness,
            coverage_gaps_fn=_coverage_gaps,
        )
        action_effects = ActionEffectLedger(ctx.runtime)
        action_executor = ActionExecutor(self.client)
        perform_action = action_executor.perform_or_raise
        surface_budget = SurfaceBudgetPolicy(ctx.runtime)
        dfs_navigation = DfsNavigationPolicy()
        consent_decisions = ConsentDecisionModule()
        permission_decisions = PermissionDecisionModule()
        permission_scenarios = PermissionScenarioPolicy()
        document_flows = DocumentFlowPolicy()
        hub_decisions = HubDecisionModule()
        login_decisions = LoginDecisionModule()
        sdk_observation_decisions = SdkObservationDecisionModule()
        test_account_login = TestAccountLoginAdapter(
            ctx.cfg.get("detection", {}), ctx.runtime, self.client,
        )
        limits = ctx.cfg["detection"]["mode_limits"][ctx.task.mode]
        state = PageState()
        document_executor = DocumentExecutor(document_flows, state.documents)
        findings, evidence = _restore_traversal_checkpoint(ctx, state)
        replay_checkpoint_restored = _restore_navigation_replay_checkpoint(ctx, state)
        if ctx.runtime.get("resume_checkpoint_restored"):
            evidence.append(record_event(
                ctx, "appium", "traversal_checkpoint_restored",
                read_document_kinds=sorted(_read_document_kinds(ctx)),
                read_document_titles=sorted(_read_document_titles(ctx)),
                completed_documents=len(state.documents.completed_keys() | state.completed_documents),
            ))
        if replay_checkpoint_restored:
            evidence.append(record_event(
                ctx, "appium", "navigation_replay_checkpoint_restored",
                edge_count=len(state.navigation_replay.replay_edges()),
            ))
        seen_text = ""
        interaction_failures = 0
        llm_calls = 0
        prior_app_page_text = ""
        prior_app_screenshot: dict | None = None
        pending_special_permission_probe: dict | None = None
        permission_prompts = 0
        permission_prompt_history: list[dict] = []
        business_actions_after_consent = 0
        login_gate_seen = False
        deep_probe_count = 0
        started_at = time.monotonic()
        duration_minutes = max(0.0, float(limits.get("max_duration_minutes", 0) or 0))
        deadline = started_at + duration_minutes * 60 if duration_minutes else None
        loop_control = PhaseLoopControl(
            runtime=ctx.runtime, deadline=deadline, duration_minutes=duration_minutes,
        )
        active_plan = list(ctx.runtime.get("active_device_scenario_plan") or device_scenario_plan())
        scenario_frontier = RuleEvidenceExecutor.wrap(ScenarioFrontier(active_plan))
        scenario_controller = ScenarioController.for_items(["3.8", "4.2"])
        restored_scenarios = [
            str(item) for item in (ctx.runtime.get("scenario_completed_items") or []) if item
        ]
        if restored_scenarios:
            scenario_frontier.mark_completed(
                restored_scenarios, evidence_source="resume_checkpoint",
            )
        foreground_exit_recoveries = 0
        app_crash_recoveries = 0
        loading_shell_cold_restarts = 0
        termination: dict | None = None
        last_step = 0
        activity = ""
        emit = lambda event_type, **meta: evidence.append(
            record_event(ctx, "appium", event_type, **meta)
        )
        directive_applier = DecisionDirectiveApplier(
            runtime=ctx.runtime, emit=emit,
            mark_completed=scenario_frontier.mark_completed,
        )
        directive_selection = DirectiveSelectionSession(ctx.runtime, directive_applier)
        perception_policy = PerceptionOcrPolicy(
            has_document_body=_has_document_body_surface,
            is_consent=_is_consent_dialog,
            is_launch_gate=_is_launch_gate_activity,
            visible_text=_page_visible_text,
            is_settings_hub=_looks_like_settings_or_profile,
            element_label=_element_label,
        )
        page_observer = PageObserver(
            client=self.client,
            runtime=ctx.runtime,
            detection_config=ctx.cfg.get("detection", {}),
            artifact_path=lambda name: _phase_artifact_path(ctx, "screenshot", name),
            emit=emit,
            needs_perception=perception_policy.needs_perception,
            visible_text=_page_visible_text,
            needs_interactive_perception=lambda observed_activity, observed_text, observed_elements: (
                perception_policy.needs_interactive_ocr(
                    observed_activity, observed_text, observed_elements, has_ocr=False,
                )
            ),
            # Keep the explorer module's injection seam: existing diagnostics and
            # tests replace this symbol to provide deterministic OCR output.
            word_extractor=extract_words_from_image,
        )

        replay_safety = NavigationReplaySafety(
            is_document_route=_target_is_document_route,
            is_transaction_target=_is_transaction_target,
            is_destructive_confirmation=_is_destructive_confirmation,
            is_app_exit_confirmation=_is_app_exit_confirmation,
            is_logout_confirmation_target=_is_logout_confirmation_target,
            is_consent_or_decline_control=_is_consent_or_decline_control,
            is_safe_deep_probe_target=_is_safe_deep_probe_target,
            is_launcher_activity=_is_launcher_activity,
            has_left_audited_package=_has_left_audited_package,
        )
        recovery = RuntimeRecoveryCoordinator(
            client=self.client,
            package_name=ctx.apk.package_name,
            runtime=ctx.runtime,
            permission_probes=permission_probes,
            save_checkpoint=lambda: str(_save_navigation_replay_checkpoint(ctx, state)),
            replay_navigation=lambda: replay_navigation_route(
                self.client, ctx, state, evidence, replay_safety,
            ),
            is_document_target=_target_is_document_route,
            emit=emit,
            note_recovery=lambda: record_recovery(ctx, "appium_runtime_session"),
            permission_probe_steps=int(
                ctx.cfg.get("detection", {}).get("permission_probe_post_steps", 6)
            ),
        )
        read_page_with_runtime_recovery = recovery.read_page
        page_stability = PageStabilityCoordinator(
            read_page=read_page_with_runtime_recovery,
            parse_page=parse_page,
            is_loading=lambda current: _page_is_loading_shell(current, state),
            clickable_count=_clickable_count,
            client=self.client,
            package_name=ctx.apk.package_name,
            config=ctx.cfg.get("detection", {}),
            appium_config=ctx.cfg.get("appium", {}),
            runtime=ctx.runtime,
            save_checkpoint=lambda: str(_save_navigation_replay_checkpoint(ctx, state)),
            replay_navigation=lambda: replay_navigation_route(
                self.client, ctx, state, evidence, replay_safety,
            ),
            emit=emit,
            note_recovery=lambda: record_recovery(ctx, "loading_shell_cold_restart"),
            empty_retries=_EMPTY_PAGE_RETRIES,
        )
        try:
            # This is a deterministic coverage contract, not an LLM prompt.
            # The model can only select controls from the observed whitelist;
            # these scenarios remain outstanding until their signals are seen.
            ctx.runtime["device_scenario_plan"] = active_plan
            evidence.append(record_event(ctx, "appium", "scenario_plan_started",
                                         scenarios=ctx.runtime["device_scenario_plan"]))
            ExplorerOrchestrator.activate_profile(
                activate=self.client.activate,
                package=ctx.apk.package_name,
                emit=lambda event_type, **meta: record_event(ctx, "appium", event_type, **meta),
            )
            for step in range(limits["max_pages"]):
                last_step = step + 1
                if termination := loop_control.termination():
                    break
                stability = ExplorerOrchestrator.observe_stable_page(
                    begin=performance_budget.begin,
                    finish=performance_budget.finish,
                    stabilize=page_stability.stabilize,
                    step=step + 1,
                    cold_restarts=loading_shell_cold_restarts,
                )
                activity = stability.activity
                page = stability.page
                empty_attempts = stability.empty_attempts
                settle_attempts = stability.settle_attempts
                settle_retries = max(0, int(ctx.cfg.get("detection", {}).get(
                    "page_settle_retries", _DEFAULT_PAGE_SETTLE_RETRIES,
                )))
                loading_shell_cold_restarts = stability.cold_restarts
                page, ocr_blob = page_observer.enrich(
                    page, activity=activity, step=step + 1,
                )
                evidence.append(record_event(ctx, "appium", "page_observed", activity=activity, element_count=len(page.elements), step=step + 1))
                foreground_package = str(getattr(self.client, "last_package", "") or "")
                if _has_left_audited_package(
                    activity,
                    str(getattr(ctx.apk, "package_name", "") or ""),
                    foreground_package=foreground_package,
                ):
                    # 5.3 minimal hook: foreign package + explicit authorize/consent copy.
                    # Avoid broad false positives (plain system chooser / empty chrome).
                    foreign_blob = _page_visible_text(page.elements)
                    foreign_consent_terms = (
                        "授权登录", "确认授权", "允许打开", "打开应用", "使用以下应用打开",
                        "同意授权", "授权并打开", "authorize", "open with",
                    )
                    if (
                        not ctx.runtime.get("third_party_app_gate_seen")
                        and not _permission_prompt(activity, page.elements)
                        and any(term.lower() in foreign_blob.lower() for term in foreign_consent_terms)
                    ):
                        ctx.runtime["third_party_app_gate_seen"] = True
                        scenario_frontier.mark_completed(
                            ["5.3"], evidence_source="third_party_app_consent_observed",
                        )
                        evidence.append(record_event(
                            ctx, "appium", "third_party_app_consent_observed",
                            activity=activity, step=step + 1,
                            foreground_package=foreground_package,
                            evidence_source="third_party_app_consent_observed",
                        ))
                    drift_limit = max(1, int(ctx.cfg.get("detection", {}).get("foreign_app_relaunch_limit", 6)))
                    drift_count = int(ctx.runtime.get("foreign_app_recoveries", 0))
                    evidence.append(record_event(
                        ctx, "appium", "foreign_app_surface_detected",
                        activity=activity, step=step + 1,
                        foreground_package=foreground_package,
                        audited_package=str(getattr(ctx.apk, "package_name", "") or ""),
                        reason="当前前台已离开被测应用包，拉回后继续检测",
                    ))
                    if drift_count >= drift_limit:
                        evidence.append(record_event(
                            ctx, "appium", "foreign_app_relaunch_exhausted",
                            activity=activity, step=step + 1, attempts=drift_count,
                        ))
                        termination = {
                            "kind": "safe_frontier_exhausted",
                            "reason": "多次误入其它应用并已拉回，按已覆盖路径结束遍历",
                        }
                        break
                    try:
                        self.client.activate(ctx.apk.package_name)
                    except ExplorationError as exc:
                        evidence.append(record_event(
                            ctx, "appium", "foreign_app_recovery_failed",
                            activity=activity, step=step + 1, error=str(exc)[:300],
                        ))
                        raise ExplorationError(f"已离开被测应用且无法重新启动：{exc}") from exc
                    replayed = recovery.replay_after_reactivation(
                        step + 1,
                        reason="检测进入外部应用后已重新拉起被测应用",
                    )
                    ctx.runtime["foreign_app_recoveries"] = drift_count + 1
                    record_recovery(ctx, "foreign_app_reactivation")
                    evidence.append(record_event(
                        ctx, "appium", "foreign_app_recovered",
                        activity=activity, step=step + 1,
                        package=ctx.apk.package_name,
                        attempt=ctx.runtime["foreign_app_recoveries"],
                        navigation_replayed=replayed,
                    ))
                    continue
                if _associated_start_activity(
                    activity,
                    str(getattr(ctx.apk, "package_name", "") or ""),
                    foreground_package=foreground_package,
                ):
                    if not ctx.runtime.get("associated_start_reported"):
                        ctx.runtime["associated_start_reported"] = True
                        findings.append(Finding(kind="associated_start", category=3, payload={
                            "activity": activity, "package_name": ctx.apk.package_name,
                        }))
                        evidence.append(record_event(
                            ctx, "appium", "associated_start_detected", activity=activity,
                            finding_kind="associated_start",
                        ))
                if not page.elements:
                    page, ocr_blob = page_observer.force_ocr(
                        page, activity=activity, step=step + 1,
                    )
                if not page.elements:
                    screenshot = _phase_artifact_path(ctx, "screenshot", f"page-unavailable-{step + 1:03d}.png")
                    if self.client.screenshot(screenshot):
                        evidence.append({"type": "screenshot", "path": str(screenshot), "meta": {
                            "page": activity, "step": step, "reason": "empty_accessibility_tree",
                        }})
                    evidence.append(record_event(
                        ctx, "appium", "page_content_unavailable", activity=activity,
                        step=step + 1, retries=empty_attempts,
                    ))
                    raise ExplorationError(
                        f"页面 {activity or '未知 Activity'} 连续 {empty_attempts} 次未返回可解析元素，"
                        "无法确认遍历覆盖，已停止生成合规结论"
                    )
                observe_page(ctx, page, step + 1)
                seen_kinds = ctx.runtime.setdefault("seen_document_kinds", set())
                seen_kinds.update(_visible_required_document_kinds(page.elements))
                external_surface = _external_navigation_surface(activity, page.elements)
                # If the runtime recovered directly back into the app, retry
                # the exact document link once.  PageState intentionally keeps
                # the original click as visited for loop prevention, so this
                # recovery path must run before the generic duplicate-target
                # branch below.  It is capped per audit and only uses a
                # currently visible, whitelisted target.
                interrupted_target = str(ctx.runtime.get("external_document_interrupted_target") or "")
                if interrupted_target and not external_surface:
                    retry_count = int(ctx.runtime.get("external_document_retry_count", 0))
                    launcher_surface = any(
                        term in str(activity or "").lower() for term in _LAUNCHER_ACTIVITY_TERMS
                    )
                    if launcher_surface:
                        # The foreground-recovery branch below will relaunch
                        # the app.  Do not discard the document marker while
                        # the launcher is visible, otherwise a reboot between
                        # the tap and Custom Tab loses the only safe retry.
                        evidence.append(record_event(
                            ctx, "appium", "external_document_recovery_retry_deferred",
                            activity=activity, target=interrupted_target,
                            reason="当前为系统桌面，等待应用前台恢复后再重试条款入口",
                        ))
                    elif retry_count >= 1:
                        ctx.runtime.pop("external_document_interrupted_target", None)
                        evidence.append(record_event(
                            ctx, "appium", "external_document_recovery_retry_skipped",
                            activity=activity, target=interrupted_target,
                            reason="恢复后的外部条款重试已达到单次上限",
                        ))
                    elif _target_is_visible(interrupted_target, page.elements):
                        ctx.runtime["external_document_retry_count"] = retry_count + 1
                        ctx.runtime.pop("external_document_recovery_waits", None)
                        ctx.runtime.pop("external_document_interrupted_target", None)
                        retry_decision = {
                            "action": "click", "target": interrupted_target,
                            "reason": "运行时恢复后重试未完成的隐私政策/服务条款入口",
                        }
                        try:
                            perform_action(retry_decision)
                            state.commit_target(page, interrupted_target)
                            state.record_action(page, "click")
                            ctx.runtime["last_appium_action"] = {
                                "action": "click", "target": interrupted_target,
                                "declined_privacy": False,
                            }
                            evidence.append(record_event(
                                ctx, "appium", "external_document_recovery_retry",
                                activity=activity, target=interrupted_target,
                                retry_index=retry_count + 1,
                            ))
                            continue
                        except ExplorationError as exc:
                            evidence.append(record_event(
                                ctx, "appium", "external_document_recovery_retry_failed",
                                activity=activity, target=interrupted_target,
                                error=str(exc)[:300],
                            ))
                    else:
                        # A freshly recreated Appium session can observe the
                        # app's root container for one or two frames before
                        # the privacy dialog is rendered.  Do not discard the
                        # retry marker on that transient state; otherwise a
                        # valid policy link is permanently skipped after a
                        # runtime recovery.  Re-read the page a bounded number
                        # of times, then downgrade to a coverage gap.
                        recovery_waits = int(ctx.runtime.get("external_document_recovery_waits", 0))
                        recovery_wait_limit = 2
                        if len(page.elements) <= 1 and recovery_waits < recovery_wait_limit:
                            ctx.runtime["external_document_recovery_waits"] = recovery_waits + 1
                            evidence.append(record_event(
                                ctx, "appium", "external_document_recovery_retry_wait",
                                activity=activity, target=interrupted_target,
                                attempt=recovery_waits + 1, max_attempts=recovery_wait_limit,
                                reason="恢复后应用页面仍在渲染，保留条款入口重试标记",
                            ))
                            time.sleep(max(0, float(ctx.cfg.get("appium", {}).get("page_wait_seconds", 1))))
                            continue
                        ctx.runtime.pop("external_document_interrupted_target", None)
                        ctx.runtime.pop("external_document_recovery_waits", None)
                        evidence.append(record_event(
                            ctx, "appium", "external_document_recovery_retry_skipped",
                            activity=activity, target=interrupted_target,
                            reason="恢复后当前页面未重新显示原条款入口",
                        ))
                if external_surface:
                    last_action = ctx.runtime.get("last_appium_action") or {}
                    origin_target = str(last_action.get("target") or "")
                    external_effect = action_effects.observe(
                        current_surface=page.surface_fingerprint,
                        permission_prompt=False,
                    )
                    if external_effect:
                        evidence.append(record_event(
                            ctx, "appium", "action_effect_observed",
                            activity=activity,
                            target=external_effect.target or origin_target,
                            parent_surface=external_effect.parent_surface,
                            child_surface=page.surface_fingerprint,
                            effect="external_surface",
                        ))
                    # A terms/policy link may legitimately use a Chrome
                    # Custom Tab.  Wait briefly for a usable body rather than
                    # calling it read or immediately abandoning it.  A blank
                    # browser after the bounded wait is coverage evidence,
                    # not a reason to crash the whole Appium session.
                    loading_key = f"{external_surface}:{_normalize_document_title(origin_target) or 'anonymous'}"
                    waits = ctx.runtime.setdefault("external_document_waits", {})
                    wait_limit = max(0, int(ctx.cfg["detection"].get("external_document_wait_retries", 3)))
                    if (
                        external_surface == "custom_tab"
                        and _treat_as_external_policy_document(origin_target, page.elements)
                        and not _external_document_body_visible(page.elements)
                        and int(waits.get(loading_key, 0)) < wait_limit
                    ):
                        waits[loading_key] = int(waits.get(loading_key, 0)) + 1
                        evidence.append(record_event(
                            ctx, "appium", "external_document_loading_wait", activity=activity,
                            target=origin_target, attempt=waits[loading_key], max_attempts=wait_limit,
                        ))
                        time.sleep(max(0, float(ctx.cfg["detection"].get("external_document_wait_seconds", 3))))
                        continue
                    if external_surface == "custom_tab" and _treat_as_external_policy_document(origin_target, page.elements):
                        body_seen = _external_document_body_visible(page.elements)
                        blank_body = None
                        if hasattr(self.client, "document_body_is_blank"):
                            try:
                                blank_body = self.client.document_body_is_blank()
                            except Exception:
                                blank_body = None
                        if body_seen or blank_body is False:
                            document_fragment = " ".join(
                                " ".join(str(element.get(key) or "") for key in ("text", "content_desc"))
                                for element in page.elements
                                if not element.get("clickable")
                            ).strip()
                            current_body_kind = _document_body_kind_from_text(document_fragment)
                            external_key = _external_document_progress_key(
                                ctx.runtime, external_surface, origin_target, current_body_kind,
                            )
                            document_session = state.documents.start(
                                external_key,
                                kind=str(current_body_kind or ""),
                                title=str(origin_target or ""),
                                source_activity=activity,
                                source_target=origin_target,
                                entry_clicks=state.navigation_depth,
                            )
                            observed_kind = str(
                                current_body_kind or document_session.observed_kind or document_session.kind
                            ) or None
                            expected_kind = _required_document_kind(origin_target) or _infer_document_kind(
                                origin_target, "",
                            )
                            effective_target = (
                                _DOCUMENT_KIND_DISPLAY_TITLES.get(observed_kind, observed_kind)
                                if observed_kind else origin_target
                            )
                            _append_policy_fragment(
                                ctx, document_fragment, effective_target or document_fragment,
                            )
                            viewport_fingerprint = _document_viewport_fingerprint(
                                document_fragment, observed_kind or expected_kind,
                            )
                            document_session = state.documents.observe_body(
                                external_key,
                                visible=True,
                                kind=str(observed_kind or ""),
                                viewport_fingerprint=viewport_fingerprint or "",
                            )
                            completed_fingerprints = ctx.runtime.setdefault(
                                "completed_document_fingerprints", set(),
                            )
                            if isinstance(completed_fingerprints, list):
                                completed_fingerprints = set(completed_fingerprints)
                                ctx.runtime["completed_document_fingerprints"] = completed_fingerprints
                            previous_identity = dict(
                                ctx.runtime.get("last_external_document_identity") or {}
                            )
                            identity_status = _external_body_identity_status(
                                origin_target=origin_target,
                                expected_kind=expected_kind,
                                observed_kind=observed_kind,
                                viewport_fingerprint=viewport_fingerprint,
                                completed_fingerprints=completed_fingerprints,
                                previous_origin_target=str(previous_identity.get("origin_target") or ""),
                                previous_viewport_fingerprint=str(
                                    previous_identity.get("viewport_fingerprint") or ""
                                ),
                            )
                            if identity_status == "stale_mismatch" and not document_session.complete:
                                identity_waits = ctx.runtime.setdefault(
                                    "external_document_identity_waits", {},
                                )
                                identity_limit = max(0, int(ctx.cfg["detection"].get(
                                    "external_document_identity_wait_retries", 2,
                                )))
                                identity_attempt = int(identity_waits.get(external_key, 0))
                                if identity_attempt < identity_limit:
                                    identity_waits[external_key] = identity_attempt + 1
                                    evidence.append(record_event(
                                        ctx, "appium", "external_document_identity_wait",
                                        activity=activity, target=origin_target,
                                        expected=expected_kind, observed=observed_kind,
                                        attempt=identity_attempt + 1,
                                        max_attempts=identity_limit,
                                        reason="外部浏览器仍显示上一份正文，等待新导航身份稳定",
                                    ))
                                    time.sleep(max(0, float(ctx.cfg["detection"].get(
                                        "external_document_identity_wait_seconds", 1,
                                    ))))
                                    continue
                                if origin_target:
                                    ctx.runtime.setdefault("blocked_document_targets", set()).add(origin_target)
                                evidence.append(record_event(
                                    ctx, "appium", "stale_external_document_body_rejected",
                                    activity=activity, target=origin_target,
                                    expected=expected_kind, observed=observed_kind,
                                    reason="新入口未产生新 URL/正文身份，不把上一份条款记到当前入口",
                                ))
                                try:
                                    returned = recovery.perform_safe_action(step + 1, {
                                        "action": "back", "target": "",
                                        "reason": "外部条款入口仍显示旧正文，返回改查其它入口",
                                    }, recovery_kind="external_return")
                                    if returned:
                                        state.record_action(page, "back")
                                except ExplorationError as exc:
                                    evidence.append(record_event(
                                        ctx, "appium", "action_failed", activity=activity,
                                        action="back", error=str(exc)[:300],
                                    ))
                                continue
                            if identity_status == "duplicate":
                                state.documents.finish(external_key, bottom_confirmed=True)
                                _mark_required_document_read(
                                    ctx, effective_target or origin_target,
                                    scenario_frontier, page_text=document_fragment,
                                    body_kind_hint=observed_kind,
                                )
                                if origin_target:
                                    ctx.runtime.setdefault("blocked_document_targets", set()).add(origin_target)
                                    ctx.runtime.setdefault("completed_document_routes", set()).add(origin_target)
                                evidence.append(record_event(
                                    ctx, "appium", "duplicate_document_body_skipped",
                                    activity=activity, target=effective_target,
                                    origin_target=origin_target,
                                    document_kind=observed_kind or expected_kind,
                                    reason="正文内容指纹已完整阅读，返回继续其它路径",
                                ))
                                try:
                                    returned = recovery.perform_safe_action(step + 1, {
                                        "action": "back", "target": "",
                                        "reason": "同一正文已完整阅读，返回继续其它路径",
                                    }, recovery_kind="external_return")
                                    if returned:
                                        state.record_action(page, "back")
                                except ExplorationError as exc:
                                    evidence.append(record_event(
                                        ctx, "appium", "action_failed", activity=activity,
                                        action="back", error=str(exc)[:300],
                                    ))
                                continue
                            if viewport_fingerprint:
                                ctx.runtime["last_external_document_identity"] = {
                                    "origin_target": origin_target,
                                    "viewport_fingerprint": viewport_fingerprint,
                                    "observed_kind": observed_kind,
                                }
                            screenshot = _phase_artifact_path(
                                ctx, "screenshot", f"external-document-{len(evidence):03d}.png",
                            )
                            if self.client.screenshot(screenshot):
                                evidence.append({"type": "screenshot", "path": str(screenshot), "meta": {
                                    "page": activity, "document": effective_target,
                                    "origin_target": origin_target,
                                    "document_scroll": document_session.scrolls,
                                }})
                            try:
                                scroll_status = _document_scroll_status(
                                    self.client, legacy_false_status="legacy_bottom",
                                )
                            except ExplorationError as exc:
                                evidence.append(record_event(
                                    ctx, "appium", "external_document_scroll_failed", activity=activity,
                                    target=origin_target, error=str(exc)[:300],
                                ))
                                recovered = recovery.recover_runtime_loss(len(evidence), exc)
                                if recovered:
                                    evidence.append(record_event(
                                        ctx, "appium", "external_document_scroll_session_recovered",
                                        activity=activity, target=origin_target,
                                    ))
                                    continue
                                # Soft-abort: never treat a hung swipe as “read complete”.
                                _block_document_route(ctx, origin_target)
                                state.documents.interrupt()
                                incomplete = ctx.runtime.setdefault("incomplete_documents", [])
                                marker = {
                                    "document": origin_target,
                                    "reason": "external_document_scroll_session_lost",
                                    "scrolls": document_session.scrolls,
                                    "error": str(exc)[:200],
                                }
                                if marker not in incomplete:
                                    incomplete.append(marker)
                                gap = (
                                    f"外部条款“{origin_target}”滑动时会话断开且无法恢复，"
                                    "不能认定已完成全文阅读"
                                )
                                gaps = ctx.runtime.setdefault("rule_coverage_gaps", [])
                                if gap not in gaps:
                                    gaps.append(gap)
                                evidence.append(record_event(
                                    ctx, "appium", "external_document_scroll_aborted", activity=activity,
                                    target=origin_target, scrolls=document_session.scrolls,
                                    reason="外部条款滑动失败，不认定已读，返回应用继续其它路径",
                                ))
                                try:
                                    returned = recovery.perform_safe_action(step + 1, {
                                        "action": "back", "target": "",
                                        "reason": "外部条款滑动失败，返回应用继续检测",
                                    }, recovery_kind="external_return")
                                    if returned:
                                        state.record_action(page, "back")
                                except ExplorationError as back_exc:
                                    evidence.append(record_event(
                                        ctx, "appium", "action_failed", activity=activity, action="back",
                                        error=str(back_exc)[:300],
                                    ))
                                continue
                            retry_limit = max(1, int(ctx.cfg["detection"].get("document_stuck_retries", 3)))
                            required_bottom = max(2, int(
                                ctx.cfg["detection"].get("document_bottom_confirmations", 2)
                            ))
                            scroll_transition = document_executor.observe_scroll(
                                external_key,
                                status=scroll_status,
                                viewport_fingerprint=viewport_fingerprint or "",
                                stuck_retry_limit=retry_limit,
                                bottom_confirmations=required_bottom,
                            )
                            if scroll_transition.step is DocumentFlowStep.CONTINUE_SCROLL:
                                evidence.append(record_event(
                                    ctx, "appium", "external_document_scrolled", activity=activity,
                                    target=effective_target, origin_target=origin_target,
                                    document_kind=observed_kind or expected_kind,
                                    scroll_index=scroll_transition.scrolls,
                                ))
                                # Keep reading until Appium verifies that the
                                # viewport no longer changes.  A screen-count
                                # cap cannot distinguish a long policy from an
                                # infinite feed and previously truncated valid
                                # 21+ screen documents.
                                continue
                            if scroll_transition.step is DocumentFlowStep.RETRY_STUCK:
                                    evidence.append(record_event(
                                        ctx, "appium", "external_document_scroll_stuck_retry",
                                        activity=activity, target=origin_target,
                                        attempt=scroll_transition.attempt, retry_limit=retry_limit,
                                        reason="滚动未变化但驱动未确认到底，重试以区分页面卡住与真实页尾",
                                    ))
                                    time.sleep(max(0, float(ctx.cfg["detection"].get("document_stuck_wait_seconds", 2))))
                                    continue
                            if scroll_transition.step is DocumentFlowStep.MARK_INCOMPLETE_AND_BACK:
                                _block_document_route(ctx, origin_target)
                                state.documents.interrupt()
                                incomplete = ctx.runtime.setdefault("incomplete_documents", [])
                                marker = {
                                    "document": origin_target,
                                    "reason": "external_document_scroll_stuck",
                                    "scrolls": document_session.scrolls,
                                }
                                if marker not in incomplete:
                                    incomplete.append(marker)
                                evidence.append(record_event(
                                    ctx, "appium", "external_document_scroll_stuck_aborted",
                                    activity=activity, target=origin_target,
                                    scrolls=document_session.scrolls,
                                    reason="连续滚动无变化且未得到页尾确认，不把文档误记为已读",
                                ))
                                try:
                                    returned = recovery.perform_safe_action(step + 1, {
                                        "action": "back", "target": "",
                                        "reason": "条款页面持续卡住，保留未读标记并返回其它路径",
                                    }, recovery_kind="external_return")
                                    if returned:
                                        state.record_action(page, "back")
                                except ExplorationError as exc:
                                    evidence.append(record_event(
                                        ctx, "appium", "action_failed", activity=activity,
                                        action="back", error=str(exc)[:300],
                                    ))
                                continue
                            if scroll_transition.step is DocumentFlowStep.RETRY_BOTTOM:
                                evidence.append(record_event(
                                    ctx, "appium", "external_document_bottom_confirmation_retry",
                                    activity=activity, target=origin_target,
                                    attempt=scroll_transition.attempt,
                                    required=1 if scroll_status == "legacy_bottom" else required_bottom,
                                    reason="首次无更多滚动仅作为页尾候选，再确认一次防止瞬时卡顿",
                                ))
                                continue
                            if scroll_transition.step is DocumentFlowStep.COMPLETE_AND_BACK:
                                # A non-blank body with no verified viewport change
                                # means the browser is already at the bottom (short
                                # document) or has no scrollable content.
                                _refresh_privacy_policy_text(ctx)
                                ctx.runtime["incomplete_documents"] = [
                                    item for item in ctx.runtime.get("incomplete_documents", [])
                                    if item.get("document") not in {origin_target, effective_target}
                                ]
                                completed_kind = _mark_required_document_read(
                                    ctx, origin_target or effective_target,
                                    scenario_frontier, page_text=document_fragment,
                                    body_kind_hint=observed_kind,
                                )
                                if origin_target:
                                    ctx.runtime.setdefault("completed_document_routes", set()).add(origin_target)
                                completed_fingerprints = ctx.runtime.setdefault(
                                    "completed_document_fingerprints", set(),
                                )
                                if isinstance(completed_fingerprints, list):
                                    completed_fingerprints = set(completed_fingerprints)
                                    ctx.runtime["completed_document_fingerprints"] = completed_fingerprints
                                completed_fingerprints.update(document_session.viewport_fingerprints)
                                if viewport_fingerprint:
                                    completed_fingerprints.add(viewport_fingerprint)
                                state.documents.finish(external_key, bottom_confirmed=True)
                                if (
                                    expected_kind
                                    and observed_kind
                                    and expected_kind != observed_kind
                                ):
                                    # Prevent the same mislabeled route from
                                    # reopening, while leaving the intended kind
                                    # outstanding for a different valid entry.
                                    if origin_target:
                                        ctx.runtime.setdefault("blocked_document_targets", set()).add(origin_target)
                                    evidence.append(record_event(
                                        ctx, "appium", "document_kind_mismatch", activity=activity,
                                        target=origin_target, actual_target=effective_target,
                                        expected=expected_kind, observed=observed_kind,
                                        reason="点击目标与正文标题不一致，已按正文实际条款记账",
                                    ))
                                    # Keep the intended clause outstanding so a later
                                    # correct open can still complete disclosure_list.
                                    kinds = _read_document_kinds(ctx)
                                    if expected_kind in kinds and observed_kind != expected_kind:
                                        kinds.discard(expected_kind)
                                        ctx.runtime["read_document_kinds"] = kinds
                                evidence.append(record_event(
                                    ctx, "appium", "external_document_read_complete", activity=activity,
                                    target=effective_target, origin_target=origin_target,
                                    entry_target=origin_target,
                                    observed_body_title=effective_target,
                                    scrolls=document_session.scrolls,
                                    reason="正文可见且已验证到达底部或页面无需滚动",
                                    document_kind=observed_kind or expected_kind or _required_document_kind(origin_target),
                                ))
                                # A complete parent policy often links to a
                                # separate collection list or third-party SDK
                                # disclosure.  Follow each such link once before
                                # leaving the Custom Tab; otherwise the parent
                                # page being readable is incorrectly treated as
                                # full coverage of the linked disclosure.
                                followed_links = ctx.runtime.setdefault("external_document_followed_links", set())
                                follow_target = _document_follow_target(page.elements, followed_links, effective_target)
                                if follow_target:
                                    try:
                                        perform_action({
                                            "action": "click", "target": follow_target,
                                            "reason": "继续阅读隐私政策正文中链接的个人信息/第三方收集清单",
                                        })
                                        state.commit_target(page, follow_target)
                                        state.record_action(page, "click")
                                        followed_links.add(follow_target)
                                        ctx.runtime["last_appium_action"] = {
                                            "action": "click", "target": follow_target,
                                            "declined_privacy": False,
                                        }
                                        evidence.append(record_event(
                                            ctx, "appium", "external_document_link_followed",
                                            activity=activity, parent=origin_target,
                                            target=follow_target,
                                        ))
                                        continue
                                    except ExplorationError as exc:
                                        evidence.append(record_event(
                                            ctx, "appium", "external_document_link_failed",
                                            activity=activity, parent=origin_target,
                                            target=follow_target, error=str(exc)[:300],
                                        ))
                                        recovery.recover_runtime_loss(len(evidence), exc)
                                if ctx.runtime.get("external_document_interrupted_target") == origin_target:
                                    ctx.runtime.pop("external_document_interrupted_target", None)
                                if completed_kind == "privacy_policy":
                                    scenario_frontier.mark_completed(["1.1"], evidence_source="policy_document_read")
                        else:
                            blocked_targets = ctx.runtime.setdefault("blocked_document_targets", set())
                            if origin_target:
                                blocked_targets.add(origin_target)
                            incomplete = ctx.runtime.setdefault("incomplete_documents", [])
                            marker = {"document": origin_target, "reason": "external_browser_body_unavailable"}
                            if marker not in incomplete:
                                incomplete.append(marker)
                            scenario_frontier.mark_blocked(
                                ["1.1", "1.3"], "blocked_external",
                                "隐私/服务条款在外部浏览器未加载可阅读正文",
                            )
                            ctx.runtime.setdefault("rule_coverage_gaps", []).append(
                                f"外部隐私/服务条款“{origin_target}”在浏览器中未加载正文，不能认定已阅读"
                            )
                            evidence.append(record_event(
                                ctx, "appium", "external_document_unavailable", activity=activity,
                                target=origin_target, reason="custom_tab_body_unavailable",
                            ))
                            if ctx.runtime.get("external_document_interrupted_target") == origin_target:
                                ctx.runtime.pop("external_document_interrupted_target", None)
                    else:
                        camera_target = _file_picker_camera_target(page.elements) if external_surface == "file_picker" else None
                        remaining = scenario_frontier.snapshot().get("remaining_items") or []
                        if (
                            camera_target
                            and not ctx.runtime.get("file_picker_camera_probed")
                            and ("2.3" in remaining or "4.2" in remaining)
                        ):
                            ctx.runtime["file_picker_camera_probed"] = True
                            perform_action({
                                "action": "click", "target": camera_target,
                                "reason": "系统相册/文件选择器中优先触发拍照，核验权限申请是否同步告知目的",
                            })
                            state.commit_target(page, camera_target)
                            state.record_action(page, "click")
                            ctx.runtime["last_appium_action"] = {
                                "action": "click", "target": camera_target,
                                "declined_privacy": False, "is_business_action": True,
                            }
                            evidence.append(record_event(
                                ctx, "appium", "file_picker_camera_probe_started", activity=activity,
                                target=camera_target, origin_target=origin_target,
                            ))
                            continue
                        if external_surface == "file_picker":
                            # Android Photo Picker/DocumentsUI grants only the
                            # selected item and normally shows no broad storage
                            # permission dialog.  That direct transition is a
                            # positive scoped-access observation, not a missed
                            # permission prompt or a violation by itself.
                            scenario_frontier.mark_blocked(
                                ["2.3", "4.2"], "not_applicable",
                                "系统范围化图片/文件选择器未申请广泛相册或存储权限",
                            )
                            ctx.runtime["scoped_media_picker_observed"] = True
                            evidence.append(record_event(
                                ctx, "appium", "scoped_media_picker_observed",
                                activity=activity, origin_target=origin_target,
                                broad_permission_requested=False,
                                reason="系统选择器仅暴露用户选中的项目，无需弹出广泛相册/存储权限",
                            ))
                        evidence.append(record_event(
                            ctx, "appium", "external_surface_detected", activity=activity,
                            surface=external_surface, origin_target=origin_target,
                            note="系统/浏览器页面不作为应用页面遍历，也不执行先前页面的目标",
                            clickable_labels=[
                                " ".join(
                                    str(item.get(key) or "") for key in ("text", "content_desc", "resource_id")
                                ).strip()
                                for item in page.elements if item.get("clickable")
                            ][:20],
                        ))
                    try:
                        returned = recovery.perform_safe_action(
                            step + 1,
                            {"action": "back", "target": "", "reason": "返回应用继续遍历"},
                            recovery_kind="external_return",
                        )
                        if not returned:
                            evidence.append(record_event(
                                ctx, "appium", "external_surface_return_deferred_after_recovery",
                                activity=activity, surface=external_surface,
                                origin_target=origin_target,
                                reason="会话已恢复；返回动作未被自动重试，交由下一轮重新观察和裁决",
                            ))
                            continue
                        state.record_action(page, "back")
                        ctx.runtime["last_appium_action"] = {
                            "action": "back", "target": "", "declined_privacy": False,
                        }
                        evidence.append(record_event(
                            ctx, "appium", "external_surface_returned_to_app", activity=activity,
                            surface=external_surface, origin_target=origin_target,
                        ))
                        interaction_failures = 0
                        continue
                    except ExplorationError as exc:
                        evidence.append(record_event(
                            ctx, "appium", "external_surface_return_failed", activity=activity,
                            surface=external_surface, error=str(exc)[:300],
                        ))
                        raise ExplorationError(f"无法从外部页面返回应用：{exc}") from exc
                if (
                    not _is_login_gate(activity, page.elements)
                    and not _is_consent_dialog(page.elements)
                    and not _is_launcher_activity(activity)
                    and not (
                        ctx.runtime.get("consent_dialog_seen")
                        and not ctx.runtime.get("consent_accepted")
                    )
                    and (
                        _looks_like_main_surface(activity, page.elements)
                        or _looks_like_main_content_surface(
                            activity, page.elements, str(getattr(ctx.apk, "package_name", "") or ""),
                        )
                        or _looks_like_settings_or_profile(activity, page.elements)
                    )
                ):
                    ctx.runtime["public_app_surface_seen"] = True
                update_progress = ctx.runtime.get("update_traversal")
                if callable(update_progress):
                    update_progress(step + 1, len(state.covered_pages), limits["max_pages"], activity)
                page_text = " ".join(" ".join((e["text"], e["content_desc"])) for e in page.elements)
                if ocr_blob:
                    page_text = f"{page_text} {ocr_blob}"
                elif ctx.runtime.get("last_screen_text"):
                    page_text = f"{page_text} {ctx.runtime.get('last_screen_text')}"
                page_text = page_text.lower()
                # The observer owns the bounded chat/feedback OCR policy.
                page, ocr_blob = page_observer.enrich_interactive(
                    page, activity=activity, step=step + 1,
                    page_text=page_text, prior_ocr=ocr_blob,
                )
                if ocr_blob:
                    page_text = " ".join(" ".join((e["text"], e["content_desc"])) for e in page.elements)
                    page_text = f"{page_text} {ocr_blob}"
                page_text = page_text.lower()
                current_page_semantics = _page_semantics(
                    activity, page.elements, state,
                    screen_text=page_text,
                    package_name=str(getattr(ctx.apk, "package_name", "") or ""),
                    foreground_package=foreground_package,
                )
                low_value_surface_kind = (
                    current_page_semantics.low_value_kind
                    if current_page_semantics.role is PageRole.LOW_VALUE else None
                )
                # Resolve a pending click/back against the newly observed page
                # before deriving the route-sensitive graph node. Otherwise a
                # returned root is temporarily keyed with the stale child route.
                state.navigation_replay.observe(page)
                state.set_semantic_context(
                    role=current_page_semantics.legacy_role,
                    phase=run_state.phase.value,
                )
                is_new = state.is_new(page)
                prior_target = str((ctx.runtime.get("last_appium_action") or {}).get("target") or "")
                if _should_anchor_root(state, page, prior_target):
                    state.anchor_root(page)
                action_effect = action_effects.observe(
                    current_surface=page.surface_fingerprint,
                    permission_prompt=bool(_permission_prompt(activity, page.elements)),
                    coordinate_target=lambda target: _bounds_click_target_for(target, page.elements),
                )
                if action_effect:
                    performance_budget.record_action_effect(
                        action_effect.global_key or f"{action_effect.parent_surface}::{action_effect.target}",
                        effective=action_effect.status != "no_effect",
                    )
                    if action_effect.status != "no_effect":
                        evidence.append(record_event(
                            ctx, "appium", "action_effect_observed",
                            activity=activity, target=action_effect.target,
                            parent_surface=action_effect.parent_surface,
                            child_surface=page.surface_fingerprint,
                            effect=action_effect.status,
                            execution_layer=action_effect.execution_layer,
                            page_role=action_effect.page_role,
                        ))
                        if (
                            action_effect.consent_action
                            and not current_page_semantics.has_overlay
                            and (
                                current_page_semantics.scope is PageScope.AUDITED_APP
                                or current_page_semantics.role is PageRole.SYSTEM_PERMISSION
                            )
                        ):
                            # A click command alone is not consent. Confirm
                            # that the audited app actually left its consent
                            # overlay before allowing post-consent traversal.
                            ctx.runtime["consent_observed"] = True
                            ctx.runtime["consent_accepted"] = True
                            ctx.runtime["consent_timestamp_ms"] = int(time.time() * 1000)
                            business_actions_after_consent = 0
                            evidence.append(record_event(
                                ctx, "appium", "privacy_consent_clicked", activity=activity,
                                target=action_effect.target,
                                recognition="consent_action_semantic_effect_confirmed",
                            ))
                    elif action_effect.target:
                        evidence.append(record_event(
                            ctx, "appium", "action_no_effect",
                            activity=activity, target=action_effect.target,
                            attempts=action_effect.attempts,
                            execution_layer=action_effect.execution_layer,
                            page_role=action_effect.page_role,
                            reason="Appium 点击命令成功，但页面、弹窗和权限状态均未发生语义变化",
                        ))
                        if action_effect.retry_target:
                            coordinate_target = action_effect.retry_target
                            retry_decision = {
                                "action": "click", "target": coordinate_target,
                                "reason": "敏感业务入口首次点击无效果，改用当前控件坐标有界重试一次",
                            }
                            try:
                                perform_action(retry_decision)
                                record_action(ctx)
                                state.record_action(page, "click")
                                # Preserve the semantic origin for an external
                                # page opened by the coordinate fallback.  The
                                # raw bounds are only a delivery mechanism and
                                # must not become the document's title/kind.
                                ctx.runtime["last_appium_action"] = {
                                    "action": "click",
                                    "target": action_effect.target,
                                    "performed_target": coordinate_target,
                                    "declined_privacy": False,
                                    "is_business_action": True,
                                }
                                action_effects.schedule(
                                    surface=page.surface_fingerprint,
                                    activity=activity,
                                    target=coordinate_target,
                                    semantic_target=action_effect.target,
                                    global_key=action_effect.global_key,
                                    is_business_action=True,
                                    coordinate_retry=True,
                                    execution_layer=action_effect.execution_layer,
                                    page_role=action_effect.page_role,
                                )
                                evidence.append(record_event(
                                    ctx, "appium", "action_no_effect_coordinate_retry",
                                    activity=activity, target=action_effect.target,
                                    retry_target=coordinate_target,
                                    reason=retry_decision["reason"],
                                ))
                                evidence.append(record_event(
                                    ctx, "appium", "business_trigger_retry_without_transition",
                                    activity=activity, original_target=action_effect.target,
                                    target=coordinate_target,
                                    reason=retry_decision["reason"],
                                ))
                                continue
                            except ExplorationError as exc:
                                evidence.append(record_event(
                                    ctx, "appium", "action_failed", activity=activity,
                                    action="click", target=coordinate_target,
                                    error=str(exc)[:300],
                                ))
                        state.mark_target(page, action_effect.target)
                        if action_effect.execution_layer != "overlay":
                            surface_budget.raise_global_target_floor(
                                action_effect.global_key, minimum=2,
                            )
                        evidence.append(record_event(
                            ctx, "appium", "target_no_effect_exhausted",
                            activity=activity, target=action_effect.target,
                            attempts=action_effect.attempts,
                            execution_layer=action_effect.execution_layer,
                            page_role=action_effect.page_role,
                            reason="无语义变化的入口已封锁，继续探索同级其它目标",
                        ))
                pending_deep_probe = ctx.runtime.pop("pending_deep_probe", None)
                if pending_deep_probe:
                    if pending_deep_probe.get("surface") == page.surface_fingerprint:
                        evidence.append(record_event(
                            ctx, "appium", "deep_probe_no_effect", activity=activity,
                            target=pending_deep_probe.get("target"),
                            reason="点击后页面与权限状态均未变化，标记该按钮无效果并继续同层其它候选",
                        ))
                    else:
                        evidence.append(record_event(
                            ctx, "appium", "deep_probe_descended", activity=activity,
                            target=pending_deep_probe.get("target"),
                            parent_surface=pending_deep_probe.get("surface"),
                            child_surface=page.surface_fingerprint,
                        ))
                seen_text += " " + page_text
                preceding_action = dict(ctx.runtime.get("last_appium_action") or {})
                document_origin = str(preceding_action.get("target") or "") if state.last_action == "click" else ""
                document_key = _document_key(
                    activity, page.elements, state, screen_text=page_text,
                    document_origin=document_origin,
                )
                already_read_document = False
                if document_key:
                    already_read_kind = _document_session_already_read(
                        ctx, document_origin=document_origin, page_text=page_text,
                    )
                    if already_read_kind:
                        # 同一 kind 已有完整阅读证据：此后每个视口都跳过，
                        # 不再重开应用内会话；可见事件每个文档只发一次。
                        if _skip_already_read_document(state, document_key):
                            evidence.append(record_event(
                                ctx, "appium", "document_already_read_skip",
                                activity=activity, document=document_key,
                                document_kind=already_read_kind, origin=document_origin,
                                reason="该条款此前已形成完整阅读证据，跳过重复阅读",
                            ))
                        # Keep the semantic key through the document-flow
                        # branch below.  It deterministically backs out of the
                        # already-complete body; dropping the key here leaves
                        # the page role as document_body and lets the LLM wait
                        # forever for an unrelated unread privacy policy.
                        state.finish_document(document_key)
                        already_read_document = True
                if document_key and not already_read_document:
                    # Rule 1.3 measures the actual navigation chain to this
                    # document, not every unrelated control clicked earlier
                    # in the app.
                    observed_kind = (
                        _document_body_kind_from_text(page_text)
                        or _required_document_kind(document_key)
                    )
                    state.start_document(
                        document_key,
                        state.navigation_depth,
                        kind=observed_kind or "",
                        title=document_key.rsplit(":document:", 1)[-1],
                        source_activity=activity,
                        source_target=document_origin,
                    )
                    _append_policy_fragment(ctx, page_text, document_key)
                    # WebView policy pages often expose no body text in the
                    # accessibility tree.  Force OCR only then — a short native
                    # TextView title must not burn a screenshot every step.
                    meaningful_nodes = sum(
                        1 for item in page.elements
                        if len(str(item.get("text") or "").strip()) >= 4
                        or len(str(item.get("content_desc") or "").strip()) >= 4
                    )
                    if meaningful_nodes == 0 and not ocr_blob:
                        page, ocr_blob = page_observer.force_ocr(
                            page, activity=activity, step=step + 1,
                        )
                        page_text = " ".join(
                            " ".join((e["text"], e["content_desc"])) for e in page.elements
                        ).lower()
                        seen_text += " " + page_text
                        _append_policy_fragment(ctx, page_text, document_key)
                    if ocr_blob:
                        _append_policy_fragment(ctx, ocr_blob, document_key)
                if state.should_capture(page):
                    screenshot = _phase_artifact_path(
                        ctx, "screenshot", f"page-{len(state.captured_views):03d}.png",
                    )
                    if self.client.screenshot(screenshot):
                        page_screenshot = {"type": "screenshot", "path": str(screenshot), "meta": {
                            "page": activity, "step": step, "document_scroll": state.document_scroll_count(document_key or ""),
                        }}
                        evidence.append(page_screenshot)
                        ctx.runtime.setdefault("screenshot_by_surface", {})[
                            page.surface_fingerprint
                        ] = str(screenshot)
                        if current_page_semantics.privacy_hub:
                            ctx.runtime["privacy_hub_screenshot"] = str(screenshot)
                        if not ctx.runtime.get("initial_surface_screenshot"):
                            ctx.runtime["initial_surface_screenshot"] = str(screenshot)
                    else:
                        page_screenshot = None
                else:
                    page_screenshot = None

                initial_consent_observation = False
                if current_page_semantics.has_overlay and not ctx.runtime.get("initial_consent_baseline_seen"):
                    # Capture the only state eligible for a “default checked”
                    # conclusion before any document, consent or guest-entry
                    # action can mutate/reuse the control.
                    ctx.runtime["initial_consent_baseline_seen"] = True
                    ctx.runtime["initial_consent_surface"] = page.surface_fingerprint
                    initial_consent_observation = True
                prechecked_consent = _prechecked_consent_checkbox(
                    page.elements,
                    page_text,
                    initial_observation=initial_consent_observation,
                    screenshot_available=page_screenshot is not None,
                )
                already_ticked = int(ctx.runtime.get("consent_checkbox_clicks", 0)) > 0
                if prechecked_consent and not already_ticked and not ctx.runtime.get("prechecked_consent_reported"):
                    ctx.runtime["prechecked_consent_reported"] = True
                    payload = {
                        **prechecked_consent,
                        "page": activity,
                        "initial_consent_surface": ctx.runtime.get("initial_consent_surface"),
                        "screenshot": str(page_screenshot) if page_screenshot else "",
                    }
                    findings.append(Finding(kind="consent_checkbox_prechecked", category=3, payload=payload))
                    _bind_screenshot_to_finding(page_screenshot, "consent_checkbox_prechecked")
                    evidence.append(record_event(
                        ctx, "appium", "consent_checkbox_prechecked",
                        finding_kind="consent_checkbox_prechecked", **payload,
                    ))
                    scenario_frontier.mark_completed(["3.4"], finding_kind="consent_checkbox_prechecked")

                if _is_consent_dialog(page.elements) or (
                    not ctx.runtime.get("consent_accepted")
                    and _is_launch_gate_activity(activity)
                ):
                    remember_elements = list(page.elements)
                    if ocr_blob:
                        remember_elements.append({
                            "text": ocr_blob, "content_desc": "", "resource_id": "", "target": "",
                        })
                    _remember_consent_document_titles(ctx, remember_elements)
                if _is_consent_dialog(page.elements):
                    ctx.runtime["consent_dialog_seen"] = True
                    scenario_frontier.mark_completed(["1.2"], evidence_source="first_run_notice_observed")
                    if forced_service_consent(page_text) and not ctx.runtime.get("forced_consent_reported"):
                        ctx.runtime["forced_consent_reported"] = True
                        payload = {"page": activity, "page_text": page_text[:500]}
                        findings.append(Finding(kind="forced_consent_for_service_improvement", category=4, payload=payload))
                        _bind_screenshot_to_finding(page_screenshot, "forced_consent_for_service_improvement")
                        evidence.append(record_event(
                            ctx, "appium", "forced_consent_for_service_improvement",
                            finding_kind="forced_consent_for_service_improvement", **payload,
                        ))
                        scenario_frontier.mark_completed(["4.5"], finding_kind="forced_consent_for_service_improvement")
                    elif not ctx.runtime.get("forced_consent_reported"):
                        scenario_frontier.mark_completed(["4.5"], evidence_source="consent_not_forced_for_service")
                    if misleading_consent_copy(page_text, page.elements) and not ctx.runtime.get("misleading_consent_reported"):
                        ctx.runtime["misleading_consent_reported"] = True
                        payload = {"page": activity, "page_text": page_text[:500]}
                        findings.append(Finding(kind="misleading_consent_copy", category=3, payload=payload))
                        _bind_screenshot_to_finding(page_screenshot, "misleading_consent_copy")
                        evidence.append(record_event(
                            ctx, "appium", "misleading_consent_copy",
                            finding_kind="misleading_consent_copy", **payload,
                        ))
                        scenario_frontier.mark_completed(["3.7"], finding_kind="misleading_consent_copy")
                    else:
                        scenario_frontier.mark_completed(["3.7"], evidence_source="consent_copy_consistent")

                privacy_paths = _privacy_path_observations(page.elements, page_text)
                # Logout is a destructive/authentication boundary, not an
                # open-ended business route.  Once its confirmation dialog
                # has been observed, keep the session and do not treat logout
                # as the withdraw-consent path required by item 3.8.
                logout_confirmation = _is_logout_confirmation_dialog(page_text, page.elements)
                if logout_confirmation:
                    if not ctx.runtime.get("logout_confirmation_observed"):
                        ctx.runtime["logout_confirmation_observed"] = True
                        evidence.append(record_event(
                            ctx, "appium", "logout_confirmation_observed",
                            activity=activity, note="已观察退出登录确认边界；不提交退出操作",
                        ))
                    ctx.runtime["logout_entry_explored"] = True
                    attempts = int(ctx.runtime.get("logout_confirmation_dismiss_attempts", 0))
                    cancel_target = _logout_confirmation_cancel_target(page.elements)
                    if attempts >= 3:
                        evidence.append(record_event(
                            ctx, "appium", "logout_confirmation_stuck", activity=activity,
                            attempts=attempts,
                            reason="退出确认框经返回和显式取消仍未关闭，停止当前分支避免重复点击",
                        ))
                        termination = {
                            "kind": "frontier_incomplete",
                            "reason": "退出登录确认框无法安全关闭，已停止以保护登录会话",
                            "remaining_items": scenario_frontier.snapshot().get("remaining_items") or [],
                        }
                        break
                    # First use Android back; if the same dialog remains, prefer
                    # its explicit 取消/再想想 control. Both paths are bounded.
                    decision = {
                        "action": "click" if attempts >= 1 and cancel_target else "back",
                        "target": cancel_target if attempts >= 1 and cancel_target else "",
                        "reason": "已核验退出登录确认框，安全关闭并保留会话继续检测",
                    }
                    try:
                        perform_action(decision)
                        state.record_action(page, decision["action"])
                        ctx.runtime["logout_confirmation_dismiss_attempts"] = attempts + 1
                        evidence.append(record_event(
                            ctx, "appium", "logout_confirmation_backed_out", activity=activity,
                            dismiss_action=decision["action"], target=decision.get("target") or "",
                            attempt=attempts + 1,
                        ))
                    except ExplorationError as exc:
                        evidence.append(record_event(
                            ctx, "appium", "action_failed", activity=activity, action=decision["action"],
                            error=str(exc)[:300],
                        ))
                    continue
                ctx.runtime.pop("logout_confirmation_dismiss_attempts", None)
                if (
                    not _is_consent_dialog(page.elements)
                    and (
                        _looks_like_settings_or_profile(activity, page.elements)
                        or _is_document_entry_page(activity, page.elements)
                    )
                ):
                    ctx.runtime["privacy_hub_visited"] = True
                for path_kind, targets in (
                    ("delete", privacy_paths["delete_targets"]),
                    ("complaint", privacy_paths["complaint_targets"]),
                    ("withdraw", privacy_paths["withdraw_targets"]),
                    ("personalization", privacy_paths["personalization_targets"]),
                ):
                    runtime_key = f"{path_kind}_paths_observed"
                    known = ctx.runtime.setdefault(runtime_key, set())
                    new_targets = [target for target in targets if target not in known]
                    if new_targets:
                        known.update(new_targets)
                        evidence.append(record_event(
                            ctx, "appium", "privacy_service_path_discovered", activity=activity,
                            path_kind=path_kind, targets=new_targets,
                            note=(
                                "已发现撤回同意或授权管理入口；进入该页后才算核验完成"
                                if path_kind == "withdraw" else
                                "已发现可访问入口；进入注销/删除页后才算核验完成，不会提交注销"
                                if path_kind == "delete" else
                                "仅发现可访问入口；不会提交注销/删除，后台处理结果仍需服务端审计"
                            ),
                        ))
                        # 3.8/6.1: discovery alone is not verification. Completion
                        # waits until the entry is opened (see action_completed).
                        if path_kind == "personalization":
                            scenario_frontier.mark_completed(["3.6"], evidence_source="personalization_opt_out_found")
                verification = _privacy_path_verification_surface(activity, page.elements, page_text)
                if verification == "delete" and "6.1" in (
                    scenario_frontier.snapshot().get("remaining_items") or []
                ):
                    scenario_frontier.mark_completed(["6.1"], evidence_source="delete_entry_found")
                    evidence.append(record_event(
                        ctx, "appium", "privacy_path_verified", activity=activity,
                        path_kind="delete", evidence_source="delete_entry_found",
                    ))
                elif verification == "withdraw" and "3.8" in (
                    scenario_frontier.snapshot().get("remaining_items") or []
                ):
                    transition = scenario_controller.observe(
                        "withdraw_entry_observed", item="3.8",
                        target="withdraw", source="withdraw_entry_found",
                    )
                    if transition.accepted:
                        scenario_frontier.mark_completed(["3.8"], evidence_source="withdraw_entry_found")
                        evidence.append(record_event(
                            ctx, "appium", "privacy_path_verified", activity=activity,
                            path_kind="withdraw", evidence_source="withdraw_entry_found",
                        ))
                if privacy_paths["delete_obstacle"] and not ctx.runtime.get("delete_obstacle_reported"):
                    ctx.runtime["delete_obstacle_reported"] = True
                    payload = {"page": activity, "message": page_text[:500], "targets": privacy_paths["delete_targets"]}
                    findings.append(Finding(kind="delete_obstacle", category=6, payload=payload))
                    _bind_screenshot_to_finding(page_screenshot, "delete_obstacle")
                    evidence.append(record_event(
                        ctx, "appium", "delete_obstacle_detected", finding_kind="delete_obstacle", **payload,
                    ))

                crash_reason = _crash_reason(activity, page.elements, page_text)
                if crash_reason:
                    # Launcher/crash dialogs are diagnostic system surfaces,
                    # not covered App pages.  Preserve their screenshot and
                    # timeline evidence but keep coverage accounting limited
                    # to the audited application.
                    state.covered_pages.discard(page.surface_fingerprint)
                    # Some OEM/system crash dialogs disappear before
                    # UiAutomator can expose their elements.  When that leaves
                    # us on Launcher, collect the app's own recent logcat
                    # summary so a native/ABI crash is not mislabeled as an
                    # unexplained traversal exit.
                    device_crash = None
                    if "系统桌面" in crash_reason and hasattr(self.client, "recent_app_crash"):
                        try:
                            device_crash = self.client.recent_app_crash(ctx.apk.package_name)
                        except Exception:
                            device_crash = None
                        if device_crash:
                            crash_reason = device_crash
                    last_action = ctx.runtime.get("last_appium_action") or {}
                    declined_privacy = bool(last_action.get("declined_privacy"))
                    # Pressing Android back from an app's final screen can
                    # legitimately return to Launcher.  That is an expected
                    # navigation result, not a second crash/background exit;
                    # finish the reachable frontier and preserve the evidence
                    # collected so far instead of failing the whole task.
                    if (
                        "系统桌面" in crash_reason
                        and not device_crash
                        and not declined_privacy
                        and last_action.get("action") == "back"
                        and ctx.runtime.get("public_app_surface_seen")
                        and not last_action.get("login_skip")
                        and not _permission_denial_probe_outstanding(ctx, scenario_frontier)
                    ):
                        evidence.append(record_event(
                            ctx, "appium", "app_exit_after_back_expected",
                            activity=activity, step=step + 1,
                            reason="最近一次操作为返回，应用正常退出到系统桌面；按已覆盖路径结束遍历",
                        ))
                        termination = {
                            "kind": "safe_frontier_exhausted",
                            "reason": "应用返回系统桌面，当前可安全访问路径已完成",
                        }
                        break
                    # Launcher without a system crash dialog is ambiguous.
                    # Clicking a document span or an exit dialog can send the
                    # process to the home screen; relaunch and continue.  Do
                    # not fail the audit just because the app left once.
                    if (
                        "系统桌面" in crash_reason
                        and not device_crash
                        and not declined_privacy
                    ):
                        relaunch_limit = max(1, int(ctx.cfg.get("detection", {}).get(
                            "launcher_relaunch_limit", 12,
                        )))
                        if foreground_exit_recoveries >= relaunch_limit:
                            evidence.append(record_event(
                                ctx, "appium", "app_left_foreground_relaunch_exhausted",
                                activity=activity, step=step + 1, attempts=foreground_exit_recoveries,
                                reason="多次回到桌面并已重新拉起，按已覆盖路径结束遍历，不记为崩溃失败",
                            ))
                            termination = {
                                "kind": "safe_frontier_exhausted",
                                "reason": "应用多次退出至系统桌面，已重新进入后仍无法稳定停留",
                            }
                            break
                        foreground_exit_recoveries += 1
                        evidence.append(record_event(
                            ctx, "appium", "app_left_foreground_recovering",
                            activity=activity, step=step + 1, last_action=last_action,
                            attempt=foreground_exit_recoveries,
                            reason="应用已到系统桌面，重新拉起后继续遍历，不中断任务",
                        ))
                        try:
                            self.client.activate(ctx.apk.package_name)
                        except ExplorationError as exc:
                            evidence.append(record_event(
                                ctx, "appium", "app_foreground_recovery_failed",
                                activity=activity, step=step + 1, error=str(exc)[:300],
                            ))
                            raise ExplorationError(f"应用离开前台且无法重新启动：{exc}") from exc
                        replayed = recovery.replay_after_reactivation(
                            step + 1,
                            reason="应用离开前台后已重新拉起",
                        )
                        record_recovery(ctx, "app_foreground_reactivation")
                        evidence.append(record_event(
                            ctx, "appium", "app_foreground_recovered",
                            activity=activity, step=step + 1,
                            package=ctx.apk.package_name, attempt=foreground_exit_recoveries,
                            navigation_replayed=replayed,
                        ))
                        continue
                    if "系统桌面" in crash_reason and declined_privacy:
                        crash_reason = "点击“不同意/拒绝”隐私提示后，应用按自身流程退出至系统桌面"
                        evidence.append(record_event(
                            ctx, "appium", "app_exited_after_privacy_decline",
                            activity=activity, reason=crash_reason, step=step + 1,
                            last_action=last_action,
                        ))
                        raise ExplorationError(f"应用主动退出，遍历中断：{crash_reason}")
                    crash_limit = max(1, int(ctx.cfg.get("detection", {}).get(
                        "app_crash_relaunch_limit",
                        ctx.cfg.get("detection", {}).get("launcher_relaunch_limit", 12),
                    )))
                    last_target = str(last_action.get("target") or "")
                    _handle_consent_document_crash_retry(
                        ctx, last_target, activity=activity, step=step + 1, reason=crash_reason,
                        forget_target=state.forget_target_everywhere, emit=emit,
                    )
                    if app_crash_recoveries >= crash_limit:
                        evidence.append(record_event(
                            ctx, "appium", "app_crash_relaunch_exhausted",
                            activity=activity, reason=crash_reason, step=step + 1,
                            attempts=app_crash_recoveries, last_action=last_action,
                        ))
                        termination = {
                            "kind": "app_crash_relaunch_exhausted",
                            "reason": "应用多次崩溃并已重新拉起，按已覆盖路径生成报告，不中断为失败任务",
                        }
                        break
                    app_crash_recoveries += 1
                    # Libraries such as CustomActivityOnCrash render an App-owned
                    # page with “RESTART APP”.  It is still a diagnostic surface,
                    # not a business page.  Back is the least destructive recovery:
                    # it normally returns to the parent screen and preserves login,
                    # DFS breadcrumbs and the deny-permission state.  Only relaunch
                    # when back fails, remains on the crash page, or lands on Home.
                    if _is_custom_crash_surface(page.elements, page_text):
                        evidence.append(record_event(
                            ctx, "appium", "app_crash_back_recovering",
                            activity=activity, reason=crash_reason, step=step + 1,
                            last_action=last_action, attempt=app_crash_recoveries,
                        ))
                        back_error = ""
                        try:
                            perform_action({
                                "action": "back", "target": "",
                                "reason": "自定义崩溃页优先返回上一级，保留会话和遍历位置",
                            })
                            state.record_action(page, "back")
                            verify_activity, verify_xml = self.client.page()
                            verify_page = parse_page(verify_activity, verify_xml)
                            verify_text = _page_visible_text(verify_page.elements)
                            recovered_by_back = bool(
                                not _is_launcher_activity(verify_activity)
                                and not _crash_reason(verify_activity, verify_page.elements, verify_text)
                            )
                        except Exception as exc:
                            # Some test/fake clients and vendor drivers raise a
                            # non-ExplorationError while the crash Activity dies.
                            # Treat it as a failed back validation and use the
                            # bounded relaunch fallback below.
                            recovered_by_back = False
                            back_error = str(exc)[:300]
                        if recovered_by_back:
                            record_recovery(ctx, "app_crash_back")
                            evidence.append(record_event(
                                ctx, "appium", "app_crash_back_recovered",
                                activity=activity, recovered_activity=verify_activity,
                                package=ctx.apk.package_name, attempt=app_crash_recoveries,
                                last_target=last_target,
                            ))
                            evidence.append(record_event(
                                ctx, "appium", "app_crash_recovered",
                                activity=activity, recovered_activity=verify_activity,
                                package=ctx.apk.package_name, attempt=app_crash_recoveries,
                                recovery_method="back_to_parent",
                            ))
                            continue
                        evidence.append(record_event(
                            ctx, "appium", "app_crash_back_failed",
                            activity=activity, attempt=app_crash_recoveries,
                            error=back_error, reason="返回未离开崩溃页或落到系统桌面，改用有界重新拉起",
                        ))
                    dismiss = _crash_dialog_dismiss_target(page.elements)
                    if dismiss:
                        try:
                            perform_action({
                                "action": "click", "target": dismiss,
                                "reason": "关闭系统崩溃提示后重新进入应用",
                            })
                        except ExplorationError:
                            pass
                    evidence.append(record_event(
                        ctx, "appium", "app_crash_recovering",
                        activity=activity, reason=crash_reason, step=step + 1,
                        last_action=last_action, attempt=app_crash_recoveries,
                    ))
                    try:
                        self.client.activate(ctx.apk.package_name)
                    except ExplorationError as exc:
                        evidence.append(record_event(
                            ctx, "appium", "app_crash_recovery_failed",
                            activity=activity, step=step + 1, error=str(exc)[:300],
                        ))
                        raise ExplorationError(f"应用崩溃后无法重新启动：{exc}") from exc
                    replayed = recovery.replay_after_reactivation(
                        step + 1,
                        reason="应用崩溃后已重新拉起",
                    )
                    record_recovery(ctx, "app_crash_reactivation")
                    evidence.append(record_event(
                        ctx, "appium", "app_crash_recovered",
                        activity=activity, step=step + 1,
                        package=ctx.apk.package_name, attempt=app_crash_recoveries,
                        navigation_replayed=replayed,
                    ))
                    continue

                special_permission = _special_permission_page(activity, page.elements)
                if special_permission:
                    observed = ctx.runtime.setdefault("special_permissions_observed", set())
                    first_visit = special_permission not in observed
                    observed.add(special_permission)
                    permission_state = _special_permission_state(page.elements)
                    evidence.append(record_event(
                        ctx, "appium", "special_permission_page_observed", activity=activity,
                        permission_type=special_permission, permission_state=permission_state, first_visit=first_visit,
                        note="已读取系统授权状态，不自动切换系统设置",
                    ))
                    if first_visit:
                        pending_special_permission_probe = {
                            "permission_type": special_permission,
                            "permission_state": permission_state,
                        }
                        try:
                            perform_action({"action": "back", "target": "", "reason": "跳过特殊系统权限设置"})
                            state.record_action(page, "back")
                            evidence.append(record_event(
                                ctx, "appium", "special_permission_returned_to_app", activity=activity,
                                permission_type=special_permission, permission_state=permission_state,
                            ))
                        except ExplorationError as exc:
                            evidence.append(record_event(
                                ctx, "appium", "action_failed", activity=activity,
                                action="back", target="", error=str(exc)[:300],
                            ))
                            break
                        continue
                    # The app reopened Settings after a safe return. Do not
                    # toggle a device-wide capability or cycle forever. A
                    # second visit proves the app is redirecting the denied
                    # path, so retain that evidence and end this device path.
                    evidence.append(record_event(
                        ctx, "appium", "special_permission_path_blocked", activity=activity,
                        permission_type=special_permission,
                    ))
                    try:
                        perform_action({"action": "back", "target": "", "reason": "特殊权限已核验，继续其他路径"})
                        state.record_action(page, "back")
                    except ExplorationError:
                        break
                    ctx.runtime.setdefault("special_permission_probe_results", {})[special_permission] = "settings_reopened"
                    break

                system_settings = _system_settings_surface(activity, page.elements)
                if system_settings and not special_permission:
                    # Android Settings is an external control plane, not an App
                    # DFS node.  Never click uninstall/force-stop/notification
                    # rows.  In allow replay, grant only the permission tied to
                    # the immediately preceding rationale and verify it through
                    # package manager before returning to the App.
                    state.covered_pages.discard(page.surface_fingerprint)
                    profile = str(ctx.runtime.get("probe_profile") or "observe")
                    permission_hint = str(ctx.runtime.get("last_permission_label") or "")
                    if not permission_hint:
                        rationale = str(ctx.runtime.get("last_permission_rationale_text") or prior_app_page_text or "")
                        permission_hint = next((
                            label for label in ("相机", "存储", "麦克风", "定位", "联系人", "电话", "短信")
                            if _permission_is_referenced(label, rationale)
                        ), "")
                    declared = list(getattr(ctx.apk, "permissions", None) or [])
                    selected = _manifest_permissions_for_label(permission_hint, declared)
                    granted: list[str] = []
                    states: dict[str, bool | None] = {}
                    device = getattr(self.client, "_device", None)
                    if profile == "allow" and selected and device is not None:
                        grant_selected = getattr(device, "grant_selected_runtime_permissions", None)
                        read_states = getattr(device, "runtime_permission_states", None)
                        if callable(grant_selected):
                            granted = list(grant_selected(ctx.apk.package_name, selected) or [])
                        if callable(read_states):
                            states = dict(read_states(ctx.apk.package_name, selected) or {})
                        verified = bool(selected and all(states.get(item) is True for item in selected))
                        ctx.runtime["allow_permission_verified"] = bool(
                            ctx.runtime.get("allow_permission_verified") or verified
                        )
                        evidence.append(record_event(
                            ctx, "appium", "permission_allow_recovered_from_settings",
                            activity=activity, settings_surface=system_settings,
                            permission=permission_hint, selected=selected,
                            granted=granted, states=states, verified=verified,
                            reason="系统设置页仅用于验证目标权限，禁止通用深度遍历",
                        ))
                        if not verified:
                            gap = f"允许权限阶段未能验证{permission_hint or '目标'}权限已授予"
                            if gap not in ctx.runtime.setdefault("rule_coverage_gaps", []):
                                ctx.runtime["rule_coverage_gaps"].append(gap)
                    else:
                        evidence.append(record_event(
                            ctx, "appium", "system_settings_navigation_blocked",
                            activity=activity, settings_surface=system_settings,
                            permission=permission_hint,
                            reason="系统设置不进入通用 DFS，未执行卸载/强停/通知等设备操作",
                        ))
                    try:
                        returned = recovery.perform_safe_action(step + 1, {
                            "action": "back", "target": "",
                            "reason": "完成目标权限状态核验，离开系统设置并返回应用",
                        }, recovery_kind="system_return")
                        if returned:
                            state.record_action(page, "back")
                    except ExplorationError as exc:
                        evidence.append(record_event(
                            ctx, "appium", "system_settings_return_failed",
                            activity=activity, error=str(exc)[:300],
                        ))
                        try:
                            self.client.activate(ctx.apk.package_name)
                        except ExplorationError:
                            termination = {
                                "kind": "system_settings_return_failed",
                                "reason": "系统设置页无法返回且应用重新拉起失败",
                            }
                            break
                    continue

                if pending_special_permission_probe:
                    probe = pending_special_permission_probe
                    permission_type = probe["permission_type"]
                    blocked_terms = {
                        "overlay": ("悬浮窗", "显示在其他应用上层", "display over other apps"),
                        "all_files": ("所有文件", "manage all files"),
                        "accessibility": ("无障碍", "accessibility"),
                        "notification": ("通知使用权", "notification access"),
                    }
                    text_lower = page_text.lower()
                    blocked = any(term in text_lower for term in blocked_terms.get(permission_type, ()))
                    outcome = "blocked_prompt" if blocked else "app_resumed"
                    ctx.runtime.setdefault("special_permission_probe_results", {})[permission_type] = outcome
                    evidence.append(record_event(
                        ctx, "appium", "special_permission_denial_probe_completed", activity=activity,
                        permission_type=permission_type, permission_state=probe["permission_state"],
                        outcome=outcome,
                    ))
                    pending_special_permission_probe = None

                permission_prompt = _permission_prompt(activity, page.elements)
                if permission_prompt:
                    permission_prompts += 1
                    if ctx.runtime.get("consent_timestamp_ms"):
                        ctx.runtime["permission_prompt_seen_after_consent"] = True
                    denied_labels = ctx.runtime.setdefault("permission_denied_labels", {})
                    permission_label = str(permission_prompt.get("permission_label") or "")
                    ctx.runtime["last_permission_label"] = permission_label
                    last_permission_action = ctx.runtime.get("last_appium_action") or {}
                    business_trigger = ctx.runtime.get("last_business_trigger_action") or {}
                    context_target = str(
                        business_trigger.get("target")
                        or (last_permission_action.get("target") if last_permission_action.get("is_business_action") else "")
                        or "unsolicited"
                    )
                    if context_target != "unsolicited" and "4.2" in (
                        scenario_frontier.snapshot().get("remaining_items") or []
                    ):
                        scenario_controller.observe(
                            "permission_prompt", item="4.2", target=context_target,
                            source="permission_prompt_observed",
                        )
                    context_activity = str(
                        business_trigger.get("activity")
                        or last_permission_action.get("activity")
                        or prior_app_page_text[:80]
                    )
                    request_context_key = _permission_request_context_key(
                        permission_label, context_activity, context_target,
                    )
                    business_action_sequence = int(ctx.runtime.get("business_action_sequence") or 0)
                    terminal_repeat_after_back = bool(
                        permission_label
                        and permission_label in denied_labels
                        and ctx.runtime.get("permission_denial_probe_terminal")
                        and last_permission_action.get("action") == "back"
                    )
                    if terminal_repeat_after_back:
                        dismiss_attempts = int(ctx.runtime.get("terminal_permission_prompt_dismiss_attempts", 0))
                        if dismiss_attempts >= 1:
                            evidence.append(record_event(
                                ctx, "appium", "terminal_permission_prompt_stuck",
                                activity=activity, permission=permission_label,
                                reason="拒权结论已形成，返回后仍是同一权限框；停止当前分支避免重复拒绝",
                            ))
                            termination = {
                                "kind": "frontier_incomplete",
                                "reason": "同一权限弹窗在拒绝并返回后仍未关闭，已停止重复操作",
                                "remaining_items": scenario_frontier.snapshot().get("remaining_items") or [],
                            }
                            break
                        ctx.runtime["terminal_permission_prompt_dismiss_attempts"] = dismiss_attempts + 1
                        perform_action({
                            "action": "back", "target": "",
                            "reason": "拒权核验已完成，关闭重复权限框而不再次点击拒绝",
                        })
                        state.record_action(page, "back")
                        evidence.append(record_event(
                            ctx, "appium", "terminal_permission_prompt_dismissed",
                            activity=activity, permission=permission_label,
                            dismiss_action="back",
                        ))
                        continue
                    # 4.2 post-denial business retry may re-show the same prompt; that is not 3.2.
                    is_denial_business_retry = bool(
                        permission_probes.active
                        and permission_probes.active.permission == permission_label
                    )
                    previous_denial = denied_labels.get(permission_label)
                    if permission_label and _should_report_permission_rerequest(
                        previous_denial,
                        context_key=request_context_key,
                        business_action_sequence=business_action_sequence,
                        denial_business_retry=is_denial_business_retry,
                    ):
                        rerequest_payload = {
                            **permission_prompt,
                            "page": activity,
                            "previously_denied_at_ms": previous_denial.get("denied_at_ms"),
                            "permission_context_key": request_context_key,
                            "business_action_sequence": business_action_sequence,
                            "unsolicited_same_context": True,
                        }
                        findings.append(Finding(
                            kind="permission_rerequest_after_denial", category=3, payload=rerequest_payload,
                        ))
                        _bind_screenshot_to_finding(page_screenshot, "permission_rerequest_after_denial")
                        evidence.append(record_event(
                            ctx, "appium", "permission_rerequest_after_denial",
                            finding_kind="permission_rerequest_after_denial", **rerequest_payload,
                        ))
                        scenario_frontier.mark_completed(
                            ["3.2"], finding_kind="permission_rerequest_after_denial",
                        )
                    scenario_frontier.mark_completed(["2.3"], evidence_source="permission_prompt_observed")
                    purpose_context = str(
                        ctx.runtime.get("last_permission_rationale_text") or prior_app_page_text or ""
                    )
                    purpose_context_available = bool(purpose_context.strip())
                    purpose_context_verified = bool(
                        purpose_context_available
                        and (
                            _permission_is_referenced(permission_label, purpose_context)
                            or any(term in re.sub(r"\s+", "", purpose_context).lower() for term in (
                                "权限使用说明", "权限说明", "permissionrequest", "申请权限",
                            ))
                            or context_target != "unsolicited"
                        )
                    )
                    purpose_known = _purpose_explained(
                        purpose_context, permission_label=permission_label,
                    )
                    prompt_payload = {
                        **permission_prompt, "page": activity, "purpose_explained_before_prompt": purpose_known,
                        "purpose_context_verified": purpose_context_verified,
                        "purpose_context_available": purpose_context_available,
                        "purpose_context": purpose_context[:500],
                    }
                    consent_time = ctx.runtime.get("consent_timestamp_ms")
                    elapsed_after_consent_ms = int(time.time() * 1000) - int(consent_time or 0)
                    consent_window_ms = int(ctx.cfg["detection"].get("permission_after_consent_window_seconds", 30)) * 1000
                    if consent_time and 0 <= elapsed_after_consent_ms <= consent_window_ms:
                        prompt_signature = (permission_prompt["permission_label"], permission_prompt["message"])
                        if not any(item["signature"] == prompt_signature for item in permission_prompt_history):
                            permission_prompt_history.append({
                                "signature": prompt_signature, "permission": permission_prompt["permission_label"],
                                "after_consent_ms": elapsed_after_consent_ms,
                            })
                        immediate_payload = {
                            **prompt_payload, "permission": permission_prompt["permission_label"],
                            "after_consent_ms": elapsed_after_consent_ms,
                            "consent_event_present": True,
                            "no_business_action_after_consent": business_actions_after_consent == 0,
                        }
                        if business_actions_after_consent == 0:
                            findings.append(Finding(
                                kind="permission_requested_immediately_after_consent", category=4, payload=immediate_payload,
                            ))
                            _bind_screenshot_to_finding(page_screenshot, "permission_requested_immediately_after_consent")
                            evidence.append(record_event(
                                ctx, "appium", "permission_requested_immediately_after_consent",
                                finding_kind="permission_requested_immediately_after_consent", **immediate_payload,
                            ))
                            scenario_frontier.mark_completed(
                                ["4.1"], finding_kind="permission_requested_immediately_after_consent",
                            )
                        else:
                            evidence.append(record_event(ctx, "appium", "permission_prompt_after_business_action",
                                                         **immediate_payload))
                        if len(permission_prompt_history) >= 2 and not ctx.runtime.get("batch_permission_observed"):
                            ctx.runtime["batch_permission_observed"] = True
                            batch_payload = {
                                "count": len(permission_prompt_history),
                                "permissions": [item["permission"] for item in permission_prompt_history],
                            }
                            findings.append(Finding(
                                kind="multiple_permissions_requested_after_consent", category=4,
                                payload=batch_payload,
                            ))
                            _bind_screenshot_to_finding(page_screenshot, "multiple_permissions_requested_after_consent")
                            evidence.append(record_event(
                                ctx, "appium", "multiple_permission_sequence_observed",
                                finding_kind="multiple_permissions_requested_after_consent", **batch_payload,
                            ))
                            scenario_frontier.mark_completed(
                                ["4.6"], finding_kind="multiple_permissions_requested_after_consent",
                            )
                    if not purpose_known and purpose_context_verified:
                        findings.append(Finding(kind="permission_purpose_not_informed", category=2, payload=prompt_payload))
                        _bind_screenshot_to_finding(page_screenshot, "permission_purpose_not_informed")
                        _bind_screenshot_to_finding(prior_app_screenshot, "permission_purpose_not_informed")
                        evidence.append(record_event(
                            ctx, "appium", "permission_prompt_without_purpose",
                            finding_kind="permission_purpose_not_informed", **prompt_payload,
                        ))
                        scenario_frontier.mark_completed(
                            ["2.3"], finding_kind="permission_purpose_not_informed",
                        )
                    else:
                        evidence.append(record_event(ctx, "appium", "permission_prompt_observed", **prompt_payload))

                    probe_action = str(ctx.cfg["detection"].get("permission_probe_action", "deny")).lower()
                    if probe_action not in {"allow", "deny", "observe"}:
                        probe_action = "deny"
                    if probe_action != "observe" and hasattr(self.client, "respond_to_permission"):
                        self.client.respond_to_permission(probe_action)
                        if probe_action == "deny":
                            now_denied_ms = int(time.time() * 1000)
                            ctx.runtime["permission_denied_at_ms"] = now_denied_ms
                            if permission_label:
                                denied_labels[permission_label] = {
                                    "denied_at_ms": now_denied_ms,
                                    "context_key": request_context_key,
                                    "business_action_sequence": business_action_sequence,
                                    "business_target": context_target,
                                }
                            if context_target != "unsolicited":
                                scenario_controller.observe(
                                    "permission_denied", item="4.2", target=context_target,
                                    source="permission_response_deny",
                                )
                        evidence.append(record_event(
                            ctx, "appium", "permission_response", action=probe_action,
                            permission=permission_prompt["permission_label"],
                        ))
                        if probe_action == "allow":
                            selected = _manifest_permissions_for_label(
                                permission_label,
                                list(getattr(ctx.apk, "permissions", None) or []),
                            )
                            device = getattr(self.client, "_device", None)
                            read_states = getattr(device, "runtime_permission_states", None)
                            grant_poll = (
                                poll_permission_grant(
                                    read_states,
                                    package_name=ctx.apk.package_name,
                                    selected_permissions=selected,
                                    max_attempts=int(ctx.cfg["detection"].get(
                                        "permission_grant_verify_attempts", 4,
                                    )),
                                    interval_seconds=float(ctx.cfg["detection"].get(
                                        "permission_grant_verify_interval_seconds", 1.0,
                                    )),
                                )
                                if selected and callable(read_states) else None
                            )
                            states = dict(grant_poll.states) if grant_poll else {}
                            verification = run_state.record_permission_allow_result(
                                permission=permission_label,
                                selected_permissions=selected,
                                states=states,
                            )
                            verified = verification.verified
                            ctx.runtime["allow_permission_verified"] = bool(
                                ctx.runtime.get("allow_permission_verified") or verified
                            )
                            evidence.append(record_event(
                                ctx, "appium", verification.event_type,
                                permission=permission_label, selected=selected,
                                states=states, verified=verified,
                                verification_attempts=(grant_poll.attempts if grant_poll else 0),
                            ))
                            if selected and not verified:
                                gap = f"允许权限阶段点击允许后未验证{permission_label}权限已授予"
                                if gap not in ctx.runtime.setdefault("rule_coverage_gaps", []):
                                    ctx.runtime["rule_coverage_gaps"].append(gap)
                        if probe_action == "deny":
                            retry_targets = ctx.runtime.setdefault("permission_denial_retry_targets", set())
                            last_action = ctx.runtime.get("last_appium_action") or {}
                            business_trigger = ctx.runtime.get("last_business_trigger_action") or {}
                            if last_action.get("is_business_action") and last_action.get("target"):
                                trigger_target = last_action.get("target")
                            elif business_trigger.get("is_business_action") and business_trigger.get("target"):
                                # In-app「好的」rationale sits between the media click and
                                # the system dialog; keep the original business binding.
                                trigger_target = business_trigger.get("target")
                            else:
                                trigger_target = None
                            scenario_directive = permission_scenarios.decide(PermissionScenarioInput(
                                prompt_visible=True,
                                response_action=probe_action,
                                business_target=str(trigger_target or ""),
                            ))
                            if scenario_directive.step is PermissionScenarioStep.START_DENIAL_PROBE:
                                permission_probes.start(
                                    permission=permission_prompt["permission_label"],
                                    remaining_steps=int(ctx.cfg["detection"].get("permission_probe_post_steps", 6)),
                                    trigger_target=scenario_directive.target,
                                    retry_attempted=scenario_directive.target in retry_targets,
                                    prompt_screenshot=page_screenshot,
                                    trigger_screenshot=prior_app_screenshot,
                                    trigger_activity=str((business_trigger or last_action).get("activity") or ""),
                                    navigation_replay=state.navigation_replay.as_dict(),
                                )
                            else:
                                permission_probes.clear()
                                evidence.append(record_event(
                                    ctx, "appium", "permission_denial_not_bound_to_business_action",
                                    permission=permission_prompt["permission_label"],
                                    preceding_target=last_action.get("target"),
                                    reason="权限出现在启动/引导/普通导航阶段，不能冒充业务拒权验证",
                                ))
                        state.record_action(page, f"permission_{probe_action}")
                        continue

                if permission_probes.active and not permission_prompt:
                    pending_denial_probe = permission_probes.tick()
                    assert pending_denial_probe is not None
                    denial_result = _denial_blocks_base_service(
                        pending_denial_probe.permission,
                        page_text,
                        page.elements,
                        pending_denial_probe.trigger_target,
                    )
                    denial_subfeature_only = bool(
                        denial_result["permission_message_matched"]
                        and (
                            denial_result["permission_intrinsic_to_action"]
                            or denial_result["alternative_service_available"]
                        )
                    )
                    retry_visible = bool(
                        _target_is_visible(pending_denial_probe.trigger_target, page.elements)
                        or (
                            pending_denial_probe.trigger_target.startswith("relative:")
                            and _is_customer_service_surface(activity, page_text)
                        )
                    )
                    scenario_directive = permission_scenarios.decide(PermissionScenarioInput(
                        active_probe=True,
                        business_target=pending_denial_probe.trigger_target,
                        target_visible=retry_visible,
                        retry_attempted=pending_denial_probe.retry_attempted,
                        denial_blocked=bool(denial_result["blocked"]),
                        denial_subfeature_only=denial_subfeature_only,
                        remaining_steps=pending_denial_probe.remaining_steps,
                    ))
                    if scenario_directive.step is PermissionScenarioStep.MARK_BLOCKED:
                        payload = {"page": activity, "permission": pending_denial_probe.permission,
                                   "message": page_text[:500], "probe_action": "deny",
                                   "business_action": pending_denial_probe.trigger_target,
                                   **denial_result,
                                   "base_service_blocked": True}
                        transition = scenario_controller.observe(
                            "function_blocked", item="4.2",
                            target=pending_denial_probe.trigger_target,
                            source="permission_denial_function_blocked",
                            direct_outcome=not pending_denial_probe.retry_attempted,
                        )
                        if transition.accepted:
                            findings.append(Finding(kind="permission_denial_blocks_function", category=4, payload=payload))
                            _bind_screenshot_to_finding(page_screenshot, "permission_denial_blocks_function")
                            _bind_screenshot_to_finding(pending_denial_probe.prompt_screenshot, "permission_denial_blocks_function")
                            _bind_screenshot_to_finding(pending_denial_probe.trigger_screenshot, "permission_denial_blocks_function")
                            evidence.append(record_event(
                                ctx, "appium", "permission_denial_function_blocked",
                                finding_kind="permission_denial_blocks_function", **payload,
                            ))
                            scenario_frontier.mark_completed(
                                ["4.2"], finding_kind="permission_denial_blocks_function",
                            )
                            permission_probes.complete(PermissionProbeStatus.BLOCKED, terminal=True)
                    elif scenario_directive.step is PermissionScenarioStep.MARK_SUBFEATURE_ONLY:
                        evidence.append(record_event(
                            ctx, "appium", "permission_denial_subfeature_only",
                            activity=activity,
                            permission=pending_denial_probe.permission,
                            business_action=pending_denial_probe.trigger_target,
                            **denial_result,
                            reason="拒绝仅影响权限本身必需的子功能，或基础服务仍有可用替代入口，不认定 RULE_4_2",
                        ))
                        permission_probes.complete(PermissionProbeStatus.SUBFEATURE_ONLY, terminal=True)
                    elif scenario_directive.step is PermissionScenarioStep.RETRY_BUSINESS_ACTION:
                        # Re-run the exact business action once after denial.
                        # Without this deterministic retry, returning to the
                        # same page was de-duplicated and the denial consequence
                        # shown in the human baseline could never be observed.
                        target = scenario_directive.target
                        permission_probes.mark_retry_attempted()
                        ctx.runtime.setdefault("permission_denial_retry_targets", set()).add(target)
                        perform_action({
                            "action": "click", "target": target,
                            "reason": "拒绝权限后重新执行原业务操作，核验功能是否被阻断",
                        })
                        evidence.append(record_event(
                            ctx, "appium", "permission_denial_business_action_retried",
                            activity=activity, target=target,
                            permission=pending_denial_probe.permission,
                        ))
                        scenario_controller.observe(
                            "business_action_retried", item="4.2", target=target,
                            source="permission_denial_business_action_retried",
                        )
                        continue
                    elif scenario_directive.step is PermissionScenarioStep.MARK_UNCONFIRMED:
                        evidence.append(record_event(ctx, "appium", "permission_denial_probe_complete",
                                                     permission=pending_denial_probe.permission, blocked=False))
                        # One unblocked feature cannot prove that every
                        # permission-dependent service remains usable. Keep
                        # 4.2 in the tri-state "attempted, not conclusive"
                        # state so other visible business routes may still be
                        # tested and the report never calls it compliant.
                        permission_probes.complete(PermissionProbeStatus.ATTEMPTED_UNBLOCKED)

                # Policy and terms pages are evidence-bearing long documents.
                # Read every reachable viewport before handing control back to
                # the LLM. Completion requires an observed unchanged viewport,
                # not an arbitrary number of swipes.
                if document_key and state.document_is_complete(document_key):
                    if _click_nested_disclosure_if_present(
                        ctx, state, page, activity, evidence, document_key,
                        self.client, recovery,
                    ):
                        continue
                    if state.last_action != "back":
                        evidence.append(record_event(
                            ctx, "appium", "already_read_document_body_skipped", activity=activity,
                            document=document_key, reason="同一份条款正文已读完，返回避免重复滚动",
                        ))
                        try:
                            perform_action({
                                "action": "back", "target": "",
                                "reason": "条款已读完，返回继续其他路径",
                            })
                            state.record_action(page, "back")
                        except ExplorationError as exc:
                            evidence.append(record_event(
                                ctx, "appium", "action_failed", activity=activity, action="back",
                                error=str(exc)[:300],
                            ))
                        continue
                elif document_key:
                    blank_body = None
                    if hasattr(self.client, "document_body_is_blank"):
                        try:
                            blank_body = self.client.document_body_is_blank()
                        except Exception:
                            blank_body = None
                    if blank_body is True:
                        retry_limit = max(1, int(ctx.cfg["detection"].get("document_blank_retries", 3)))
                        blank_transition = document_executor.observe_blank(
                            document_key, blank_retry_limit=retry_limit,
                        )
                        blank_observations = blank_transition.attempt
                        if blank_transition.step is DocumentFlowStep.WAIT_BODY:
                            evidence.append(record_event(
                                ctx, "appium", "document_content_waiting", activity=activity,
                                document=document_key, attempt=blank_observations, retry_limit=retry_limit,
                            ))
                            time.sleep(max(0, float(ctx.cfg["detection"].get("document_blank_wait_seconds", 2))))
                            continue
                        state.documents.interrupt()
                        state.interrupt_document(document_key)
                        incomplete = ctx.runtime.setdefault("incomplete_documents", [])
                        if not any(item.get("document") == document_key and item.get("reason") == "visible_body_blank" for item in incomplete):
                            incomplete.append({
                                "document": document_key, "reason": "visible_body_blank",
                                "observations": blank_observations,
                            })
                        ctx.runtime.setdefault("rule_coverage_gaps", []).append(
                            f"{document_key.rsplit(':document:', 1)[-1]}页面正文为空或持续加载失败，不能认定已完成全文阅读"
                        )
                        evidence.append(record_event(
                            ctx, "appium", "document_content_unavailable", activity=activity,
                            document=document_key, observations=blank_observations,
                            reason="visible_body_blank",
                        ))
                        try:
                            recovery.perform_safe_action(
                                step + 1,
                                {"action": "back", "target": "", "reason": "条款正文为空，返回继续其他合规路径"},
                                recovery_kind="normal",
                            )
                            state.record_action(page, "back")
                            evidence.append(record_event(
                                ctx, "appium", "document_blank_returned", activity=activity, document=document_key,
                            ))
                        except ExplorationError as exc:
                            evidence.append(record_event(
                                ctx, "appium", "action_failed", activity=activity, action="back", error=str(exc)[:300],
                            ))
                        continue
                    # Complete only when the next swipe no longer changes the
                    # viewport. The Appium client compares accessibility-tree
                    # and body-image signatures, so a fixed 20/24-screen cap is
                    # both less accurate and unnecessary.
                    try:
                        prior_scrolls = state.document_scroll_count(document_key)
                        scroll_status = _document_scroll_status(
                            self.client,
                            legacy_false_status="legacy_bottom" if prior_scrolls > 0 else "stuck",
                        )
                    except ExplorationError as exc:
                        evidence.append(record_event(
                            ctx, "appium", "document_scroll_failed", activity=activity,
                            document=document_key, error=str(exc)[:300],
                        ))
                        recovered = recovery.recover_runtime_loss(len(evidence), exc)
                        if recovered:
                            evidence.append(record_event(
                                ctx, "appium", "document_scroll_session_recovered",
                                activity=activity, document=document_key,
                            ))
                            continue
                        # Soft-stop: do not abort the whole audit on a hung
                        # WebView swipe. Cap the doc and leave so 3.8/4.2/6.1
                        # can still run on a fresh session if recovery failed.
                        scrolls = state.document_scroll_count(document_key)
                        state.documents.interrupt()
                        state.interrupt_document(document_key)
                        entry = str((ctx.runtime.get("last_appium_action") or {}).get("target") or "")
                        title = document_key.rsplit(":document:", 1)[-1]
                        _block_document_route(ctx, entry or title, page_text=page_text)
                        incomplete = ctx.runtime.setdefault("incomplete_documents", [])
                        marker = {
                            "document": document_key, "reason": "document_scroll_session_lost",
                            "scrolls": scrolls, "error": str(exc)[:200],
                        }
                        if marker not in incomplete:
                            incomplete.append(marker)
                        evidence.append(record_event(
                            ctx, "appium", "document_scroll_aborted", activity=activity,
                            document=document_key, scrolls=scrolls,
                            reason="条款滑动时会话断开且无法恢复，结束该正文并继续其它路径",
                        ))
                        try:
                            recovery.perform_safe_action(
                                step + 1,
                                {
                                    "action": "back", "target": "",
                                    "reason": "条款滑动失败，返回继续检测",
                                },
                                recovery_kind="normal",
                            )
                            state.record_action(page, "back")
                        except ExplorationError as back_exc:
                            evidence.append(record_event(
                                ctx, "appium", "action_failed", activity=activity, action="back",
                                error=str(back_exc)[:300],
                            ))
                        continue
                    retry_limit = max(1, int(ctx.cfg["detection"].get("document_stuck_retries", 3)))
                    required_bottom = max(2, int(
                        ctx.cfg["detection"].get("document_bottom_confirmations", 2)
                    ))
                    scroll_transition = document_executor.observe_scroll(
                        document_key,
                        status=scroll_status,
                        stuck_retry_limit=retry_limit,
                        bottom_confirmations=required_bottom,
                    )
                    state.documents.start(document_key).scrolls = scroll_transition.scrolls
                    state.sync_document_projections()
                    if scroll_transition.step is DocumentFlowStep.CONTINUE_SCROLL:
                        evidence.append(record_event(
                            ctx, "appium", "document_scrolled", activity=activity,
                            document=document_key, scroll_index=scroll_transition.scrolls,
                        ))
                        state.last_action = "scroll"
                        state.last_action_page = page.fingerprint
                        continue
                    if scroll_transition.step is DocumentFlowStep.RETRY_STUCK:
                            evidence.append(record_event(
                                ctx, "appium", "document_scroll_stuck_retry", activity=activity,
                                document=document_key, attempt=scroll_transition.attempt,
                                retry_limit=retry_limit,
                                reason="滚动未变化但驱动未确认到底，重试以区分页面卡住与真实页尾",
                            ))
                            time.sleep(max(0, float(ctx.cfg["detection"].get("document_stuck_wait_seconds", 2))))
                            continue
                    if scroll_transition.step is DocumentFlowStep.MARK_INCOMPLETE_AND_BACK:
                        scrolls = state.document_scroll_count(document_key)
                        incomplete = ctx.runtime.setdefault("incomplete_documents", [])
                        marker = {
                            "document": document_key,
                            "reason": "document_scroll_stuck",
                            "scrolls": scrolls,
                        }
                        if marker not in incomplete:
                            incomplete.append(marker)
                        evidence.append(record_event(
                            ctx, "appium", "document_scroll_stuck_aborted", activity=activity,
                            document=document_key, scrolls=scrolls,
                            reason="连续滚动无变化且未得到页尾确认，不把文档误记为已读",
                        ))
                        evidence.append(record_event(
                            ctx, "appium", "document_read_incomplete", activity=activity,
                            document=document_key, scrolls=scrolls, reason="document_scroll_stuck",
                        ))
                        state.documents.interrupt()
                        state.interrupt_document(document_key)
                        try:
                            returned = recovery.perform_safe_action(
                                step + 1,
                                {
                                    "action": "back", "target": "",
                                    "reason": "条款页面持续卡住，保留未读标记并返回其它路径",
                                },
                                recovery_kind="normal",
                            )
                            if returned:
                                state.record_action(page, "back")
                        except ExplorationError as exc:
                            evidence.append(record_event(
                                ctx, "appium", "action_failed", activity=activity,
                                action="back", error=str(exc)[:300],
                            ))
                        continue
                    if scroll_transition.step is DocumentFlowStep.RETRY_BOTTOM:
                        evidence.append(record_event(
                            ctx, "appium", "document_bottom_confirmation_retry", activity=activity,
                            document=document_key, attempt=scroll_transition.attempt,
                            required=1 if scroll_status == "legacy_bottom" else required_bottom,
                            reason="首次无更多滚动仅作为页尾候选，再确认一次防止瞬时卡顿",
                        ))
                        continue
                    scrolls = state.document_scroll_count(document_key)
                    # A WebView is not “read” merely because a swipe command
                    # returned without an exception.  Zero verified viewport
                    # changes and a safety-limit stop are both coverage gaps.
                    if scroll_transition.step is DocumentFlowStep.COMPLETE_AND_BACK:
                        state.finish_document(document_key)
                        ctx.runtime["incomplete_documents"] = [
                            item for item in ctx.runtime.get("incomplete_documents", [])
                            if item.get("document") != document_key
                        ]
                        _refresh_privacy_policy_text(ctx)
                        session = state.documents.sessions.get(document_key)
                        origin_route = str(
                            getattr(session, "source_target", "")
                            or (ctx.runtime.get("last_appium_action") or {}).get("target")
                            or ""
                        )
                        completion = _record_document_completion(
                            ctx,
                            document_key=document_key,
                            entry_target=origin_route,
                            page_text=page_text,
                            scenario_frontier=scenario_frontier,
                        )
                        evidence.append(record_event(
                            ctx, "appium", "document_read_complete", activity=activity,
                            document=document_key, scrolls=scrolls,
                            document_kind=completion.completed_kind or _required_document_kind(document_key),
                            entry_target=completion.entry_target,
                            observed_body_title=completion.actual_title,
                        ))
                        _reconcile_document_completion_route(
                            ctx, completion, activity=activity, page_text=page_text,
                            forget_target=state.forget_target_everywhere, emit=emit,
                        )
                        if completion.completed_kind == "privacy_policy":
                            scenario_frontier.mark_completed(["1.1"], evidence_source="policy_document_read")
                        if _click_nested_disclosure_if_present(
                            ctx, state, page, activity, evidence, document_key,
                            self.client, recovery,
                        ):
                            continue
                        entry_clicks = state.document_entry_click_count(document_key)
                        if entry_clicks > 4:
                            findings.append(Finding(
                                kind="policy_entry_exceeds_four_clicks", category=1,
                                payload={
                                    "click_count": entry_clicks, "document": document_key,
                                    "policy_entry_exceeds_four_clicks": True,
                                },
                            ))
                            scenario_frontier.mark_completed(
                                ["1.3"], finding_kind="policy_entry_exceeds_four_clicks",
                            )
                        elif state.root_surfaces:
                            scenario_frontier.mark_completed(
                                ["1.3"], evidence_source="policy_entry_within_four_clicks",
                            )
                    else:
                        reason = "scroll_not_verified"
                        incomplete = ctx.runtime.setdefault("incomplete_documents", [])
                        marker = {"document": document_key, "reason": reason, "scrolls": scrolls}
                        if marker not in incomplete:
                            incomplete.append(marker)
                        evidence.append(record_event(
                            ctx, "appium", "document_read_incomplete", activity=activity,
                            document=document_key, scrolls=scrolls, reason=reason,
                        ))
                        state.documents.interrupt()
                        state.interrupt_document(document_key)
                        retries = ctx.runtime.setdefault("incomplete_document_retries", {})
                        retries[document_key] = int(retries.get(document_key, 0)) + 1
                        entry = str((ctx.runtime.get("last_appium_action") or {}).get("target") or "")
                        if entry:
                            state.forget_target_everywhere(entry)
                        title = document_key.rsplit(":document:", 1)[-1]
                        if title:
                            state.forget_target_everywhere(title)
                        if retries[document_key] >= 2:
                            _block_document_route(ctx, entry or title, page_text=page_text)
                        try:
                            perform_action({
                                "action": "back", "target": "",
                                "reason": "条款正文滚动未验证，返回后允许从其他入口再读一次",
                            })
                            state.record_action(page, "back")
                        except ExplorationError as exc:
                            evidence.append(record_event(
                                ctx, "appium", "action_failed", activity=activity, action="back",
                                error=str(exc)[:300],
                            ))
                        continue

                credential_login_surface = _credential_login_surface(
                    activity, page.elements, document_key=document_key,
                )
                login_surface = credential_login_surface
                login_gate_seen = login_gate_seen or login_surface
                if _authenticated_session_visible(
                    page.elements, extra_text=str(ctx.runtime.get("manual_login_ocr_blob") or ""),
                ):
                    if not ctx.runtime.get("manual_login_verified"):
                        run_state.mark_login_verified(source="session_notice_or_profile")
                        evidence.append(record_event(
                            ctx, "appium", "manual_login_state_verified", activity=activity,
                            verification_source="session_notice_or_profile",
                        ))
                    login_surface = False
                if (
                    credential_login_surface
                    and ctx.runtime.get("manual_login_waited")
                    and ctx.runtime.get("manual_login_verified")
                ):
                    # A current credential form is stronger evidence than a
                    # stale OCR/login-success token retained from an earlier
                    # authenticated page. Never let its agreement footer or
                    # account fields fall through to document/LLM exploration.
                    if ctx.runtime.get("login_gate_revisit_returned"):
                        evidence.append(record_event(
                            ctx, "appium", "loop_prevented", activity=activity,
                            reason="login_gate_back_no_progress",
                        ))
                        termination = {
                            "kind": "safe_frontier_exhausted",
                            "reason": "登录页返回未产生进展，已停止重复操作",
                        }
                        break
                    ctx.runtime.pop("manual_login_ocr_blob", None)
                    ctx.runtime["login_gate_revisit_returned"] = True
                    evidence.append(record_event(
                        ctx, "appium", "login_gate_revisited",
                        activity=activity,
                        reason="当前仍为账号凭据页，忽略协议页脚并返回公开路径",
                    ))
                    try:
                        perform_action({
                            "action": "back", "target": "",
                            "reason": "登录页已完成一次人工检查，返回继续公开路径",
                        })
                        state.record_action(page, "back")
                    except ExplorationError as exc:
                        evidence.append(record_event(
                            ctx, "appium", "action_failed", activity=activity,
                            action="back", error=str(exc)[:300],
                        ))
                    continue
                transient_dismiss = _transient_notice_dismiss_target(page.elements, page_text)
                if transient_dismiss:
                    # PageSnapshot exposes the stable surface fingerprint;
                    # there is no content_fingerprint attribute.  Keeping the
                    # key page-local bounds the acknowledgement retries
                    # without crashing the traversal on a feedback popup.
                    notice_key = page.surface_fingerprint
                    notice_attempts = ctx.runtime.setdefault("transient_notice_dismiss_attempts", {})
                    attempt = int(notice_attempts.get(notice_key, 0))
                    action_effects.discard()
                    if attempt < 2:
                        notice_attempts[notice_key] = attempt + 1
                        perform_action({
                            "action": "click", "target": transient_dismiss,
                            "reason": "关闭复制成功等瞬态提示，继续探索原页面",
                        })
                        state.commit_target(page, transient_dismiss)
                        state.record_action(page, "click")
                        ctx.runtime["last_appium_action"] = {
                            "action": "click", "target": transient_dismiss,
                            "declined_privacy": False,
                        }
                        evidence.append(record_event(
                            ctx, "appium", "transient_notice_dismissed",
                            activity=activity, target=transient_dismiss, attempt=attempt + 1,
                        ))
                    else:
                        perform_action({
                            "action": "back", "target": "",
                            "reason": "瞬态提示连续两次未消失，返回上一级避免在遮罩层逗留",
                        })
                        state.record_action(page, "back")
                        ctx.runtime["last_appium_action"] = {
                            "action": "back", "target": "", "declined_privacy": False,
                        }
                        evidence.append(record_event(
                            ctx, "appium", "transient_notice_dismiss_exhausted",
                            activity=activity, target=transient_dismiss, attempts=attempt,
                        ))
                    continue
                channel_dismiss = _channel_unavailable_dialog_dismiss_target(page.elements, page_text)
                if channel_dismiss:
                    ctx.runtime["skip_third_party_channel_login"] = True
                    decision = {
                        "action": "click", "target": channel_dismiss,
                        "reason": "第三方登录不可用弹窗点确定后离开，避免反复点 QQ/微信",
                    }
                    perform_action(decision)
                    state.commit_target(page, channel_dismiss)
                    state.record_action(page, "click")
                    ctx.runtime["last_appium_action"] = {
                        "action": "click", "target": channel_dismiss, "declined_privacy": False,
                    }
                    evidence.append(record_event(
                        ctx, "appium", "channel_unavailable_dialog_dismissed",
                        activity=activity, target=channel_dismiss,
                    ))
                    continue
                if state.back_made_no_progress(page):
                    # 不能把 tab 目标存进 `recovery`：它已被本阶段的
                    # RuntimeRecoveryCoordinator 占用，遮蔽会让后续崩溃恢复崩掉。
                    recovery_target = _privacy_hub_tab_target(page.elements) or _main_content_tab_target(page.elements)
                    recovery_key = (
                        _global_target_key(activity, recovery_target, page.elements) if recovery_target else ""
                    )
                    remaining_items = scenario_frontier.snapshot().get("remaining_items", [])
                    blocking = [item for item in remaining_items if item in {"2.3", "3.8", "4.1", "4.2", "6.1"}]
                    if (
                        recovery_target
                        and not state.target_visited(page, recovery_target)
                        and scenario_frontier.snapshot().get("remaining")
                        and _frontier_recovery_attempt_allowed(ctx.runtime, recovery_key)
                    ):
                        decision = {
                            "action": "click", "target": recovery_target,
                            "reason": "返回未产生新页面，改走设置/主内容入口继续检测",
                        }
                        perform_action(decision)
                        state.commit_target(page, recovery_target)
                        state.record_action(page, "click")
                        ctx.runtime["last_appium_action"] = {
                            "action": "click", "target": recovery_target, "declined_privacy": False,
                        }
                        evidence.append(record_event(
                            ctx, "appium", "frontier_recovery_after_back_loop", activity=activity,
                            target=recovery_target, reason=decision["reason"],
                        ))
                        continue
                    if blocking and int(ctx.runtime.get("frontier_back_loop_deferred_count", 0)) < 2:
                        ctx.runtime["frontier_back_loop_deferred_count"] = int(
                            ctx.runtime.get("frontier_back_loop_deferred_count", 0)
                        ) + 1
                        ctx.runtime["frontier_back_loop_deferred"] = True
                        # Logged-out profile + 6.1 still pending: open login once
                        # instead of endlessly re-entering settings.
                        login_now = _profile_login_entry(
                            page.elements, extra_text=str(ctx.runtime.get("last_screen_text") or ""),
                        )
                        if (
                            login_now
                            and not ctx.runtime.get("manual_login_verified")
                            and not ctx.runtime.get("manual_login_timed_out")
                            and "6.1" in blocking
                            and not state.target_visited(page, login_now)
                        ):
                            decision = {
                                "action": "click", "target": login_now,
                                "reason": "未登录状态下注销入口不可见，先进入登录等待人工登录",
                            }
                            perform_action(decision)
                            state.commit_target(page, login_now)
                            state.record_action(page, "click")
                            ctx.runtime["last_appium_action"] = {
                                "action": "click", "target": login_now, "declined_privacy": False,
                            }
                            evidence.append(record_event(
                                ctx, "appium", "logged_out_login_prioritized", activity=activity,
                                target=login_now, remaining_items=blocking,
                            ))
                            continue
                        evidence.append(record_event(
                            ctx, "appium", "frontier_back_loop_deferred", activity=activity,
                            remaining_items=blocking,
                            reason="撤回/注销/权限场景尚未完成，暂不因返回无进展结束遍历",
                        ))
                        continue
                    evidence.append(record_event(ctx, "appium", "loop_prevented", activity=activity, reason="back_no_progress"))
                    termination = {"kind": "safe_frontier_exhausted", "reason": "返回未产生新页面，已避免无进展循环"}
                    break
                login_invitation = _login_invitation_target(page.elements, page_text)
                public_redress_target = _complaint_or_cs_entry_target(
                    page.elements, set(state.targets_visited_on(page)),
                )
                public_frontier_outstanding = bool(
                    public_redress_target
                    and any(item in (scenario_frontier.snapshot().get("remaining_items") or [])
                            for item in ("2.3", "4.2", "6.1"))
                )
                if login_invitation and public_frontier_outstanding:
                    evidence.append(record_event(
                        ctx, "appium", "login_invitation_deferred_for_public_frontier",
                        activity=activity, login_target=login_invitation,
                        public_target=public_redress_target,
                        reason="公开反馈/投诉/帮助入口仍可推进权限或救济场景，先按 DFS 完成公共前沿",
                    ))
                elif login_invitation and not state.target_visited(page, login_invitation):
                    decision = {
                        "action": "click", "target": login_invitation,
                        "reason": "进入登录表单并等待人工登录；自动化不会读取或填写账号凭据",
                    }
                    perform_action(decision)
                    state.commit_target(page, login_invitation)
                    state.record_action(page, "click")
                    ctx.runtime["last_appium_action"] = {
                        "action": "click", "target": login_invitation, "declined_privacy": False,
                    }
                    evidence.append(record_event(
                        ctx, "appium", "login_invitation_followed", activity=activity,
                        target=login_invitation, reason=decision["reason"],
                    ))
                    continue
                if login_surface and not ctx.runtime.get("manual_login_waited"):
                    automated_login = test_account_login.attempt(page.elements)
                    ctx.runtime["test_account_login_status"] = automated_login.status
                    if automated_login.status == "submitted":
                        evidence.append(record_event(
                            ctx, "appium", "test_account_login_submitted",
                            activity=activity,
                            username_target=automated_login.username_target,
                            password_target=automated_login.password_target,
                            submit_target=automated_login.submit_target,
                            credentials_logged=False,
                        ))
                        continue
                    login_gate_fingerprint = f"{activity}:{page.surface_fingerprint}"
                    reused_login_gate = run_state.login_wait_already_consumed(
                        login_gate_fingerprint,
                    )
                    run_state.mark_login_waiting(gate_fingerprint=login_gate_fingerprint)
                    wait_seconds = max(0, int(ctx.cfg["detection"].get("manual_login_wait_seconds", 0)))
                    if reused_login_gate:
                        wait_seconds = min(
                            wait_seconds,
                            max(0, int(ctx.cfg["detection"].get(
                                "subsequent_phase_login_wait_seconds", 5,
                            ))),
                        )
                    evidence.append(record_event(
                        ctx, "appium", "awaiting_manual_login", activity=activity, wait_seconds=wait_seconds,
                        login_gate_fingerprint=login_gate_fingerprint,
                        reused_phase_checkpoint=reused_login_gate,
                        message="请由人工在模拟器完成登录；如页面有登录条款，可取消勾选后手动点击验证码入口。系统不会读取或输入账号、密码、验证码，只观察界面变化与同时间窗设备请求。",
                    ))
                    manual_login_succeeded = _wait_for_manual_login(self.client, ctx, wait_seconds)
                    evidence.extend(ctx.runtime.pop("manual_login_probe_evidence", []))
                    registered_manual_probe_shots = ctx.runtime.setdefault(
                        "manual_auth_consent_probe_screenshot_paths", set(),
                    )
                    for observation in ctx.runtime.get("manual_auth_consent_code_request_observations", []):
                        shot_path = str(observation.get("screenshot_path") or "")
                        if not shot_path or shot_path in registered_manual_probe_shots:
                            continue
                        if Path(shot_path).is_file():
                            evidence.append({
                                "type": "screenshot", "path": shot_path,
                                "meta": {
                                    "finding_kinds": ["api_called_before_consent"],
                                    "manual_trigger": True,
                                    "consent_scope": "login_terms_checkbox",
                                },
                            })
                            registered_manual_probe_shots.add(shot_path)
                    if manual_login_succeeded:
                        # Toast copy such as “登录成功” often disappears before
                        # the next accessibility dump.  The wait checkpoint
                        # already saw session proof; do not let a later LLM
                        # look at the stale login form override that.
                        current_activity, current_xml = read_page_with_runtime_recovery(step + 1)
                        current_page = parse_page(current_activity, current_xml)
                        ocr_blob = str(ctx.runtime.get("manual_login_ocr_blob") or "")
                        identity_verified = _authenticated_session_visible(
                            current_page.elements, extra_text=ocr_blob,
                        )
                        run_state.mark_login_verified(
                            source="profile_identity" if identity_verified else "wait_checkpoint",
                        )
                        evidence.append(record_event(
                            ctx, "appium", "login_state_assessed", activity=current_activity,
                            logged_in=True,
                            verification_source=(
                                "profile_identity" if identity_verified else "wait_checkpoint"
                            ),
                        ))
                        evidence.append(record_event(
                            ctx, "appium", "manual_login_state_verified", activity=current_activity,
                            verification_source=(
                                "profile_identity" if identity_verified else "wait_checkpoint"
                            ),
                        ))
                        continue
                    evidence.append(record_event(ctx, "appium", "manual_login_timeout", activity=activity, wait_seconds=wait_seconds))
                    run_state.mark_login_timed_out()
                if login_surface and ctx.runtime.get("manual_login_timed_out"):
                    # A timeout is not proof that the tester failed to log in:
                    # re-check toast/profile OCR before asking the LLM, and
                    # never let a stale credential form veto a success notice.
                    current_activity, current_xml = read_page_with_runtime_recovery(step + 1)
                    current_page = parse_page(current_activity, current_xml)
                    ocr_blob = str(ctx.runtime.get("manual_login_ocr_blob") or "")
                    identity_verified = _authenticated_session_visible(
                        current_page.elements, extra_text=ocr_blob,
                    )
                    llm_payload = current_page.llm_payload()
                    if ocr_blob:
                        llm_payload["screen_text"] = ocr_blob
                    logged_in = identity_verified or bool(
                        getattr(llm, "assess_login_state", lambda _page: False)(llm_payload)
                    )
                    evidence.append(record_event(
                        ctx, "appium" if identity_verified else "llm", "login_state_assessed",
                        activity=current_activity, logged_in=logged_in,
                        verification_source="profile_identity" if identity_verified else "llm",
                    ))
                    if identity_verified:
                        run_state.mark_login_verified(source="profile_identity")
                        evidence.append(record_event(
                            ctx, "appium", "manual_login_confirmed_after_timeout",
                            activity=current_activity,
                            verification_source="profile_identity",
                        ))
                        continue
                    if logged_in:
                        evidence.append(record_event(
                            ctx, "llm", "login_state_candidate_unverified",
                            activity=current_activity,
                            reason="模型判断仅作为候选，缺少账号身份/会话控件证据，不能标记登录覆盖",
                        ))
                    # Login-only controls are out of scope after the human-login
                    # window expires. Leave the gate and keep exploring public
                    # settings, policy and permission paths instead of ending the
                    # entire inspection. Do not mark every previously attempted
                    # scenario as ``requires_login``: those attempts can belong
                    # to public policy/settings routes (and doing so used to
                    # hide valid policy findings such as rule 2.1).
                    evidence.append(record_event(
                        ctx, "appium", "login_path_skipped", activity=activity,
                        reason="人工登录超时；跳过登录相关场景，继续遍历无需登录路径",
                    ))
                    bypass = _login_bypass_target(page.elements)
                    login_exit = login_decisions.propose_timeout_exit(
                        bypass_target=bypass or "",
                        bypass_visited=bool(bypass and state.target_visited(page, bypass)),
                        back_already_done=bool(ctx.runtime.get("login_skip_back_done")),
                    )
                    if "terminate_login_gate_unresolved" in login_exit.effects:
                        evidence.append(record_event(
                            ctx, "appium", "login_gate_unresolved", activity=activity,
                            reason="登录超时后仍停留在登录页，不再返回以免退出应用；公开主界面未能进入",
                        ))
                        termination = {
                            "kind": "login_gate_unresolved",
                            "reason": "登录超时且未能进入无需登录的主界面，已停止在登录门禁",
                        }
                        break
                    try:
                        login_exit_decision = login_exit.decision()
                        perform_action(login_exit_decision)
                        if login_exit.action == "click":
                            state.commit_target(page, login_exit.target)
                        state.record_action(page, login_exit.action, login_exit.target)
                        if login_exit.action == "back":
                            ctx.runtime["login_skip_back_done"] = True
                        ctx.runtime["last_appium_action"] = {
                            "action": login_exit.action, "target": login_exit.target,
                            "declined_privacy": False, "login_skip": True,
                        }
                        evidence.append(record_event(
                            ctx, "appium", login_exit.event_type, activity=activity,
                            action=login_exit.action, target=login_exit.target,
                            reason=str(login_exit.event_meta.get("reason") or login_exit.reason),
                        ))
                    except ExplorationError as exc:
                        evidence.append(record_event(ctx, "appium", "action_failed", activity=activity,
                                                     action=login_exit.action, target=login_exit.target,
                                                     error=str(exc)[:300]))
                        if login_exit.action == "back":
                            termination = {"kind": "login_path_return_failed", "reason": "登录超时后无法安全返回应用路径"}
                            break
                    continue
                if (
                    login_surface
                    and ctx.runtime.get("manual_login_verified")
                    and current_page_semantics.role is not PageRole.DOCUMENT_BODY
                    and not current_page_semantics.has_overlay
                    and document_key is None
                ):
                    evidence.append(record_event(
                        ctx, "appium", "login_form_left_after_verified", activity=activity,
                        reason="已确认登录成功，离开登录表单继续检测",
                    ))
                    try:
                        perform_action({"action": "back", "target": "", "reason": "登录成功后离开登录页"})
                        state.record_action(page, "back")
                    except ExplorationError as exc:
                        evidence.append(record_event(
                            ctx, "appium", "action_failed", activity=activity, action="back",
                            error=str(exc)[:300],
                        ))
                    continue
                _maybe_enter_sdk_observation_phase(ctx, activity, page.elements, evidence, self.client)
                frontier_recommendation = None
                customer_probe_target = None
                media_assist_proposal = None
                customer_service_exhausted_proposal = None
                combined_document_proposal = None
                already_read_hub_proposal = None
                already_read_consent_proposal = None
                logout_observation_proposal = None
                deny_session_boundary_proposal = None
                destructive_confirmation_proposal = None
                logout_confirmation_proposal = None
                repeated_logout_proposal = None
                sensitive_media_candidates: list[str] = []
                redress_surface = _is_redress_interaction_surface(activity, page_text)
                # Legacy local name is kept for event/report compatibility;
                # the detector itself is generic across complaint, feedback,
                # support, work-order, report and customer-service flows.
                customer_service_surface = redress_surface
                probe_context = f"{activity.lower()}|{state.route_context(page)}"
                probe_targets_by_context = ctx.runtime.setdefault(
                    "sensitive_permission_probe_targets_by_context", {},
                )
                attempted_targets = probe_targets_by_context.setdefault(probe_context, set())
                unread_document = None
                low_value_budget_decision = None
                directive_token = ""
                directive_selection.discard()
                decision_locked = bool(low_value_surface_kind)
                if low_value_surface_kind:
                    low_value_budget_decision = surface_budget.leave_low_value(
                        surface_key=page.surface_fingerprint,
                        surface_kind=low_value_surface_kind,
                        is_root=state.is_root_page(page),
                    )
                    decision = {
                        "action": low_value_budget_decision.action,
                        "target": "",
                        "reason": low_value_budget_decision.reason,
                    }
                    decision_source = "coverage_pruning"
                llm_proposed = None
                proposal_source = None
                sdk_dwell_pending = not ctx.runtime.get("sdk_observation_dwell_done")
                document_surface = (
                    current_page_semantics.role is PageRole.DOCUMENT_BODY
                    and not customer_service_surface
                )
                hub_pending = _hub_scenarios_outstanding(scenario_frontier)
                # Deep mode explores the whole privacy/account/redress hub even
                # after one scenario has already obtained evidence. Otherwise a
                # camera probe can close 4.2 and starve 客服/反馈, or one policy
                # path can prevent 个人信息/账号安全 sibling traversal.
                permission_only_phase = bool(ctx.runtime.get("permission_only_phase"))
                permission_items_pending = bool(
                    {"2.3", "3.3", "3.9", "4.1", "4.4", "4.6", "5.1"}
                    & set(scenario_frontier.snapshot().get("remaining_items") or [])
                )
                hub_audit_active = bool(
                    hub_pending
                    or (ctx.task.mode == "deep" and not permission_only_phase)
                    or (permission_only_phase and permission_items_pending)
                )
                # ``DOCUMENT_HUB`` also covers a simple policy-entry page.
                # Only an adjudicated privacy/account hub may consume the
                # bounded logout/authorization DFS scroll budget.
                settings_hub = current_page_semantics.privacy_hub or (
                    current_page_semantics.role is PageRole.LOGGED_OUT_PROFILE
                )
                sdk_dwell_eligible = (
                    sdk_dwell_pending
                    and not low_value_surface_kind
                    and bool(ctx.runtime.get("sdk_observation_permissions_granted"))
                    and not current_page_semantics.has_overlay
                    and not document_surface
                    and not _external_navigation_surface(activity, page.elements)
                    and current_page_semantics.role is not PageRole.LOGIN_GATE
                )
                content_tab = _main_content_tab_target(page.elements) if sdk_dwell_eligible else None
                unread_on_shell = _unread_for_page(
                    ctx, page.elements, state.targets_visited_on(page),
                ) if sdk_dwell_eligible else None
                profile_chrome = bool(sdk_dwell_eligible and _authenticated_session_visible(page.elements) and any(
                    term.lower() in " ".join(
                        str(item.get(key) or "") for item in page.elements
                        for key in ("text", "content_desc", "resource_id")
                    ).lower() for term in _AUTHENTICATED_LOGOUT_TERMS
                ))
                quiet_main = bool(
                    sdk_dwell_eligible
                    and _looks_like_main_content_surface(
                        activity, page.elements, str(getattr(ctx.apk, "package_name", "") or ""),
                    )
                    and not (content_tab and (unread_on_shell or profile_chrome))
                    and not (
                        ctx.runtime.get("consent_dialog_seen")
                        and not ctx.runtime.get("consent_accepted")
                    )
                )
                dwell = max(0.0, float(ctx.cfg.get("detection", {}).get("sdk_observation_dwell_seconds", 15)))
                sdk_directive = sdk_observation_decisions.propose(SdkObservationInput(
                    pending=sdk_dwell_pending,
                    eligible=sdk_dwell_eligible,
                    content_tab=content_tab or "",
                    quiet_main=quiet_main,
                    settings_hub=settings_hub,
                    is_root=state.is_root_page(page),
                    back_attempts=int(ctx.runtime.get("sdk_observe_backs", 0)),
                    wait_attempts=int(ctx.runtime.get("sdk_observe_waits", 0)),
                    dwell_seconds=dwell,
                    armed=bool(ctx.runtime.get("sdk_observation_dwell_armed")),
                ))
                sdk_dwell_gate = False
                if sdk_directive is not None:
                    sdk_effects = sdk_directive.effects
                    if "continue_loop" in sdk_effects:
                        # This directive bypasses arbitration entirely, so its
                        # side effects commit at the legacy pre-loop timing.
                        sdk_proposal = directive_selection.add(sdk_directive)
                        directive_selection.commit_token(
                            sdk_proposal.token, activity=activity,
                        )
                        if not directive_selection.preview.runtime_view.get(
                            "sdk_observation_dwell_armed",
                        ):
                            ctx.runtime.pop("sdk_observation_dwell_armed", None)
                        if "perform_sdk_dwell" in sdk_effects:
                            if dwell:
                                time.sleep(dwell)
                        continue
                    sdk_proposal = directive_selection.add(sdk_directive)
                    decision = sdk_proposal.as_decision()
                    decision_source = sdk_directive.source
                    if "no_action" in sdk_effects:
                        # Terminal gate declaration: never competes for
                        # execution, so it commits at the legacy timing too.
                        directive_selection.commit_token(
                            sdk_proposal.token, activity=activity,
                        )
                    else:
                        directive_token = sdk_proposal.token
                        decision_locked = True
                        sdk_dwell_gate = True
                    if not directive_selection.preview.runtime_view.get(
                        "sdk_observation_dwell_armed",
                    ):
                        ctx.runtime.pop("sdk_observation_dwell_armed", None)
                if (
                    not _external_navigation_surface(activity, page.elements)
                    and not document_key
                    and not credential_login_surface
                    and _document_probe_allowed_for_role(current_page_semantics.role)
                ):
                    unread_document = _unread_for_page(ctx, page.elements, state.targets_visited_on(page))
                profile_login_entry = _profile_login_entry(
                    page.elements, extra_text=str(ocr_blob or ctx.runtime.get("last_screen_text") or ""),
                )
                consent_dialog = current_page_semantics.has_overlay
                retry_document_target = _pending_document_route_retry(ctx.runtime)
                retry_document_forced = False
                if consent_dialog and retry_document_target:
                    catalog_retry_target = _catalog_document_target(
                        current_page_semantics, retry_document_target, ctx=ctx,
                    )
                    candidate_retry_target = catalog_retry_target or retry_document_target
                    if _target_is_visible(candidate_retry_target, page.elements):
                        unread_document = candidate_retry_target
                        retry_document_forced = True
                guest_entry_target = (
                    _entry_choice_bypass_target(page.elements)
                    if not consent_dialog else None
                )
                if not decision_locked and guest_entry_target:
                    guest_directive = login_decisions.propose_guest_entry(
                        target=guest_entry_target,
                        already_visited=state.target_visited(page, guest_entry_target),
                    )
                    if guest_directive is not None:
                        guest_proposal = directive_selection.add(guest_directive)
                        decision = guest_proposal.as_decision()
                        decision_source = guest_directive.source
                        directive_token = guest_proposal.token
                        decision_locked = True
                if not decision_locked and not sdk_dwell_gate:
                    rationale_target = _in_app_permission_rationale_continue_target(page.elements)
                    rationale_decision = None
                    if rationale_target and not _permission_prompt(activity, page.elements) and not consent_dialog:
                        rationale_decision = _permission_rationale_decision(
                            ctx, state, page, rationale_target,
                        )
                    directive = permission_decisions.propose(PermissionDecisionInput(
                        rationale_target=rationale_target or "",
                        rationale_decision=rationale_decision,
                        consent_dialog=consent_dialog,
                    ))
                    consent_target = (
                        _catalog_target_for_role(current_page_semantics, "consent")
                        or _explicit_consent_target(page.elements)
                    )
                    consent_target_blocked = bool(consent_target) and action_effects.is_blocked(
                        _global_target_key(activity, consent_target, page.elements)
                    )
                    consent_document_target = _catalog_document_target(
                        current_page_semantics, unread_document or "", ctx=ctx,
                    ) if consent_dialog else ""
                    consent_document_label = _catalog_label_for_target(
                        current_page_semantics, consent_document_target,
                    )
                    if consent_document_target:
                        unread_document = consent_document_target
                    if directive is None:
                        directive = consent_decisions.propose(ConsentDecisionInput(
                            unread_document=unread_document or "",
                            document_kind=_required_document_kind(
                                consent_document_label or unread_document or "",
                            ) or "",
                            consent_dialog=consent_dialog,
                            consent_accepted=bool(ctx.runtime.get("consent_accepted")),
                            document_target_visited=bool(
                                unread_document
                                and not retry_document_forced
                                and state.target_visited(page, unread_document)
                            ),
                            checkbox_target=_unchecked_consent_checkbox(page.elements) or "",
                            checkbox_clicks=int(ctx.runtime.get("consent_checkbox_clicks", 0)),
                            consent_target=consent_target or "",
                            consent_target_visited=bool(
                                consent_target and state.target_visited(page, consent_target)
                            ),
                            consent_button_retries=int(ctx.runtime.get("consent_button_retries", 0)),
                            consent_target_blocked=consent_target_blocked,
                        ))
                    if directive is not None:
                        def _on_consent_selected(
                            effects, consent_target=consent_target, page_text=page_text,
                        ):
                            if "remember_permission_rationale" in effects:
                                ctx.runtime["last_permission_rationale_text"] = page_text
                            if "forget_consent_target" in effects and consent_target:
                                state.forget_target(page, consent_target)

                        consent_proposal = directive_selection.add(
                            directive, on_selected=_on_consent_selected,
                        )
                        decision = consent_proposal.as_decision()
                        decision_source = directive.source
                        directive_token = consent_proposal.token
                        decision_locked = True
                if not decision_locked and not sdk_dwell_gate:
                    chooser_exclude = set(state.targets_visited_on(page))
                    capture_target = _media_capture_chooser_target(
                        page.elements, exclude=chooser_exclude,
                    )
                    album_target = _media_album_chooser_target(
                        page.elements, exclude=chooser_exclude,
                    )
                    remaining_items = set(
                        scenario_frontier.snapshot().get("remaining_items", [])
                    )
                    chooser_target = capture_target or album_target or ""
                    directive = permission_decisions.propose(PermissionDecisionInput(
                        capture_target=capture_target or "",
                        album_target=album_target or "",
                        prior_capture_target=capture_target or "",
                        prior_capture_visited=bool(
                            capture_target and state.target_visited(page, capture_target)
                        ),
                        consent_dialog=consent_dialog,
                        launch_gate=_is_launch_gate_activity(activity),
                        permission_scenarios_pending=bool({"2.3", "4.2"} & remaining_items),
                        media_family=_media_family_of(
                            _labels_for_media_identity(chooser_target, page.elements),
                        ) if chooser_target else "",
                    ))
                    if directive is not None:
                        def _on_chooser_selected(effects, activity=activity):
                            if "revoke_media_permissions" in effects:
                                _revoke_media_probe_permissions(ctx, evidence, activity, self.client)

                        chooser_proposal = directive_selection.add(
                            directive, on_selected=_on_chooser_selected,
                        )
                        decision = chooser_proposal.as_decision()
                        decision_source = directive.source
                        directive_token = chooser_proposal.token
                        decision_locked = True
                if decision_locked or sdk_dwell_gate:
                    pass
                else:
                    login_directive = login_decisions.propose_entry(
                        target=profile_login_entry or "",
                        already_visited=bool(
                            profile_login_entry and state.target_visited(page, profile_login_entry)
                        ),
                        logged_out=_logged_out_profile_visible(
                            page.elements,
                            extra_text=str(ocr_blob or ctx.runtime.get("last_screen_text") or ""),
                        ),
                    )
                    if login_directive is not None:
                        login_proposal = directive_selection.add(login_directive)
                        decision = login_proposal.as_decision()
                        decision_source = login_directive.source
                        directive_token = login_proposal.token
                        decision_locked = True
                if decision_locked or sdk_dwell_gate:
                    pass
                elif (
                    not current_page_semantics.has_overlay
                    and not _is_pre_app_entry_surface(activity, page.elements, ctx)
                    and not _is_customer_service_surface(activity, page_text, page.elements)
                    and (
                        ctx.task.mode == "deep"
                        or
                        "4.2" in scenario_frontier.snapshot().get("remaining_items", [])
                        or "2.3" in scenario_frontier.snapshot().get("remaining_items", [])
                        or "6.3" in scenario_frontier.snapshot().get("remaining_items", [])
                    )
                    and (
                        cs_entry := _redress_entry_target(
                            page.elements, state.targets_visited_on(page),
                        )
                    )
                    and (
                        (cs_entry_key := _global_target_key(activity, cs_entry, page.elements))
                        not in set(ctx.runtime.get("redress_entry_route_keys") or set())
                    )
                ):
                    directive = hub_decisions.propose_redress_entry(
                        target=cs_entry, route_key=cs_entry_key,
                    )
                    redress_proposal = directive_selection.add(directive)
                    decision = redress_proposal.as_decision()
                    decision_source = directive.source
                    directive_token = redress_proposal.token
                    decision_locked = True
                elif (
                    hub_audit_active
                    and not settings_hub
                    and (ctx.runtime.get("manual_login_verified") or ctx.runtime.get("consent_accepted"))
                    and not current_page_semantics.has_overlay
                    and current_page_semantics.role is not PageRole.LOGIN_GATE
                    and (hub_tab := _privacy_hub_tab_target(page.elements))
                    and not state.target_visited(page, hub_tab)
                    and hub_tab not in set(ctx.runtime.get("visited_privacy_hub_tabs") or set())
                ):
                    # Prefer bottom 我/设置 over home chrome (head_image) whenever
                    # 3.8/6.1 still need a hub — do not gate forever on privacy_hub_visited.
                    # Session-level tab memory prevents re-tapping the same 我 tab
                    # when page fingerprints churn (ads/OCR) and wipe per-page visited.
                    directive = hub_decisions.propose_hub_tab(target=hub_tab)
                    hub_tab_proposal = directive_selection.add(directive)
                    decision = hub_tab_proposal.as_decision()
                    decision_source = directive.source
                    directive_token = hub_tab_proposal.token
                    decision_locked = True
                elif (
                    settings_hub
                    and hub_audit_active
                    and not ctx.runtime.get("privacy_hub_search_exhausted")
                    and not current_page_semantics.has_overlay
                    and current_page_semantics.role is not PageRole.LOGIN_GATE
                ):
                    visited = state.targets_visited_on(page)
                    _observe_logout_rows_without_clicking(ctx, page.elements, evidence, activity)
                    media_probe = None
                    remaining = scenario_frontier.snapshot().get("remaining_items", [])
                    if "2.3" in remaining or "4.2" in remaining:
                        media_probe = (
                            _media_capture_chooser_target(page.elements)
                            or _media_album_chooser_target(page.elements)
                            or _hub_avatar_probe_target(page.elements, visited)
                        )
                        if media_probe and state.target_visited(page, media_probe):
                            media_probe = None
                    hub_row = _hub_privacy_action_target(ctx, page.elements, visited)
                    unread_on_hub = _unread_for_page(ctx, page.elements, visited)
                    drill_target = _hub_drill_target(page.elements, visited)
                    permission_drill_target = _permission_related_hub_drill_target(
                        page.elements, visited,
                    ) if permission_only_phase else None
                    logout_entry = _logout_entry_exploration_target(ctx, page.elements, visited)
                    deny_probe_outstanding = _permission_denial_probe_outstanding(
                        ctx, scenario_frontier,
                    )
                    hub_facts = HubDecisionInput(
                        permission_only_phase=permission_only_phase,
                        deny_probe_outstanding=deny_probe_outstanding,
                        media_probe=media_probe or "",
                        permission_drill_target=permission_drill_target or "",
                        unread_document=unread_on_hub or "",
                        document_kind=_required_document_kind(unread_on_hub or "") or "",
                        privacy_row=hub_row or "",
                        drill_target=drill_target or "",
                        logout_entry=logout_entry or "",
                        scrolls=int(ctx.runtime.get("hub_privacy_scrolls", 0)),
                        checklist_complete=_hub_checklist_complete(ctx),
                    )
                    directive = hub_decisions.propose(hub_facts, include_terminal=False)
                    if directive is not None:
                        def _on_hub_selected(effects, activity=activity):
                            if "revoke_media_permissions" in effects:
                                _revoke_media_probe_permissions(ctx, evidence, activity, self.client)

                        hub_proposal = directive_selection.add(
                            directive, on_selected=_on_hub_selected,
                        )
                        decision = hub_proposal.as_decision()
                        decision_source = directive.source
                        directive_token = hub_proposal.token
                        decision_locked = True
                    elif (
                        not media_probe
                        and not drill_target
                        and _scroll_hub_for_privacy_path(
                            self.client, ctx, state, page, activity, evidence,
                            "设置页尚未看到注销/授权撤回入口，先滚动再找",
                        )
                    ):
                        continue
                    else:
                        progress = None if permission_only_phase else _hub_progress_target(
                            ctx, page.elements, visited,
                        )
                        progress_is_media = bool(progress and progress in {
                            _media_capture_chooser_target(page.elements),
                            _media_album_chooser_target(page.elements),
                            _hub_avatar_probe_target(page.elements, visited),
                        })
                        terminal_facts = HubDecisionInput(
                            **{
                                **hub_facts.__dict__,
                                "progress_target": progress or "",
                                "progress_is_media": progress_is_media,
                                "progress_is_drill": bool(
                                    progress and progress in {
                                        drill_target, _hub_drill_target(page.elements, set()),
                                    }
                                ),
                            }
                        )
                        directive = hub_decisions.propose(terminal_facts)
                        if directive is not None:
                            directive_effects = directive.effects

                            def _on_hub_terminal_selected(effects, activity=activity):
                                if "revoke_media_permissions" in effects:
                                    _revoke_media_probe_permissions(ctx, evidence, activity, self.client)

                            terminal_proposal = directive_selection.add(
                                directive, on_selected=_on_hub_terminal_selected,
                            )
                            decision = terminal_proposal.as_decision()
                            decision_source = directive.source
                            if "no_action" in directive_effects:
                                # Hub exhaustion never competes for execution;
                                # commit at the legacy proposal timing so the
                                # search-exhausted flag survives LLM fallbacks.
                                directive_selection.commit_token(
                                    terminal_proposal.token, activity=activity,
                                )
                            else:
                                directive_token = terminal_proposal.token
                                decision_locked = True
                elif (
                    not sdk_dwell_gate
                    and not current_page_semantics.has_overlay
                    and not _is_pre_app_entry_surface(activity, page.elements, ctx)
                    and not (settings_hub and hub_pending)
                    and ctx.task.mode == "deep"
                    and (
                        "4.2" in scenario_frontier.snapshot()["remaining_items"]
                        or "2.3" in scenario_frontier.snapshot()["remaining_items"]
                    )
                ):
                    # 仅需 setdefault 建立集合；集合内容在后续候选构建时使用。
                    ctx.runtime.setdefault("sensitive_permission_probe_attempts", set())
                    exclude = set(state.targets_visited_on(page)) | set(attempted_targets) | set(
                        ctx.runtime.get("crash_skip_targets") or set()
                    )
                    for media_target in _iter_customer_service_media_targets(
                        activity, page.elements, page_text,
                    ):
                        if media_target not in exclude:
                            sensitive_media_candidates.append(media_target)
                    # Chooser sheets: keep camera/album families pollable via exclude.
                    for media_target in (
                        *_iter_media_capture_chooser_targets(page.elements, exclude=exclude),
                        *_iter_media_album_chooser_targets(page.elements, exclude=exclude),
                    ):
                        if media_target not in sensitive_media_candidates:
                            sensitive_media_candidates.append(media_target)
                    # Main-content home: do not treat head_image/history_image as 4.2 probes.
                    on_main = _looks_like_main_content_surface(
                        activity, page.elements, str(getattr(ctx.apk, "package_name", "") or ""),
                    )
                    if not on_main:
                        semantic = _semantic_sensitive_business_control(
                            page.elements, exclude=exclude | set(sensitive_media_candidates),
                            allow_nav_chrome=False,
                        )
                        if semantic and semantic not in sensitive_media_candidates:
                            sensitive_media_candidates.insert(0, semantic)
                    sensitive_media_candidates = sensitive_media_candidates[:16]
                    max_probes = max(6, int(ctx.cfg["detection"].get(
                        "max_sensitive_permission_probes_per_context",
                        ctx.cfg["detection"].get("max_sensitive_permission_probes", 8),
                    )))
                    if len(attempted_targets) >= max_probes:
                        sensitive_media_candidates = []
                    customer_probe_target = _next_media_family_candidate(
                        sensitive_media_candidates,
                        elements=page.elements,
                        attempted=set(attempted_targets),
                    )
                if decision_locked or sdk_dwell_gate or (
                    profile_login_entry and not state.target_visited(page, profile_login_entry)
                ):
                    # Document/consent/login entry decisions are final for this page.
                    # SDK dwell gate also blocks hub/cs/LLM clicks until observation finishes.
                    pass
                else:
                    try:
                        llm_calls += 1
                        llm_page = page.llm_payload()
                        llm_page["elements"] = _llm_catalog_elements(current_page_semantics)
                        annotate_elements(llm_page["elements"])
                        frontier_recommendation = scenario_frontier.recommend(
                            page.elements, state.targets_visited_on(page)
                        )
                        if current_page_semantics.has_overlay:
                            # Splash: never follow rule-guided 《政策/协议》 links.
                            frontier_recommendation = None
                        if frontier_recommendation and _identity_is_hub_distractor(
                            str(frontier_recommendation.get("target") or "")
                        ):
                            frontier_recommendation = None
                        llm_page["outstanding_rule_scenarios"] = [
                            {
                                "item": row["item"], "goal": row["goal"], "state": row["state"],
                            }
                            for row in scenario_frontier.snapshot()["items"]
                            if row["state"] not in {"evidence_observed", "requires_server_audit", "not_applicable"}
                        ]
                        llm_page["rule_guided_target"] = frontier_recommendation
                        unread_now = _unread_for_page(ctx, page.elements, state.targets_visited_on(page))
                        read_kinds_now = _read_document_kinds(ctx)
                        llm_page["page_role"] = current_page_semantics.legacy_role
                        llm_page["page_role_evidence"] = [
                            {
                                "role": item.role.value,
                                "source": item.source.value,
                                "strength": item.strength,
                                "hits": list(item.hits),
                            }
                            for item in current_page_semantics.evidence
                        ]
                        llm_page["blocked_roles"] = [
                            item.value for item in current_page_semantics.blocked_roles
                        ]
                        # Splash consent: never advertise 《政策/协议》 as clickable
                        # unread links — that pushes the model back into Chrome.
                        if current_page_semantics.has_overlay:
                            llm_page["unread_document_links"] = []
                        else:
                            llm_page["unread_document_links"] = [unread_now] if unread_now else []
                            remaining_titles = sorted(
                                title for title in _visible_required_document_titles(page.elements)
                                if not _document_title_already_read(title, _read_document_titles(ctx))
                            )
                            if remaining_titles:
                                llm_page["unread_document_links"] = remaining_titles
                        if frontier_recommendation and _already_read_document_target(
                            ctx, str(frontier_recommendation.get("target") or ""), page.elements,
                        ):
                            frontier_recommendation = None
                            llm_page["rule_guided_target"] = None
                        llm_page["read_documents"] = sorted(_read_document_titles(ctx))
                        llm_page["read_document_kinds"] = sorted(read_kinds_now)
                        llm_page["privacy_documents_read"] = "privacy_policy" in read_kinds_now
                        llm_page["privacy_dialog"] = current_page_semantics.has_overlay
                        llm_page["audited_package"] = str(getattr(ctx.apk, "package_name", "") or "")
                        llm_page["audited_app_name"] = str(getattr(ctx.apk, "app_name", "") or "")
                        llm_page["already_inside_audited_app"] = _activity_belongs_to_package(
                            activity, str(getattr(ctx.apk, "package_name", "") or ""),
                        ) and not _is_launcher_activity(activity)
                        if str(getattr(self.client, "last_package", "") or ""):
                            fg = str(self.client.last_package)
                            pkg = str(getattr(ctx.apk, "package_name", "") or "")
                            if fg and pkg and (fg == pkg or pkg in fg):
                                llm_page["already_inside_audited_app"] = not _is_launcher_activity(activity)
                        screen_text = str(
                            ocr_blob or ctx.runtime.get("last_screen_text") or ""
                        ).strip()
                        if not screen_text:
                            screen_text = _page_visible_text(page.elements)
                        if screen_text:
                            llm_page["screen_text"] = screen_text[:1500]
                        screenshot_path = str(
                            (page_screenshot or {}).get("path")
                            or (ctx.runtime.get("screenshot_by_surface") or {}).get(page.surface_fingerprint)
                            or ""
                        )
                        if screenshot_path:
                            llm_page["screenshot_path"] = screenshot_path
                        if sensitive_media_candidates:
                            llm_page["sensitive_media_candidates"] = list(sensitive_media_candidates)
                            llm_page["sensitive_media_families"] = [
                                {
                                    "target": item,
                                    "family": _media_family_of(
                                        _labels_for_media_identity(item, page.elements),
                                    ),
                                }
                                for item in sensitive_media_candidates
                            ]
                        required_catalog_targets = {
                            target
                            for target in (
                                _catalog_execution_target(
                                    current_page_semantics,
                                    str((frontier_recommendation or {}).get("target") or ""),
                                ),
                                *(
                                    _catalog_execution_target(current_page_semantics, str(item))
                                    for item in sensitive_media_candidates
                                ),
                            )
                            if target
                        }
                        annotate_elements(llm_page["elements"])
                        allowed_targets = {}
                        for item in current_page_semantics.targets:
                            for alias in (
                                item.target, item.target_id, item.label, item.resource_id,
                            ):
                                if alias:
                                    # A catalog alias is safe only because it
                                    # was emitted by the adjudicated catalog.
                                    # Preserve ordinary native label/id aliases
                                    # for the Appium executor, which can resolve
                                    # either representation; consent overlay
                                    # labels deliberately map to their bounded
                                    # coordinate target to prevent a background
                                    # node with the same text being clicked.
                                    allowed_targets[str(alias)] = (
                                        item.target if item.coordinate_only else str(alias)
                                    )
                        for required_target in required_catalog_targets:
                            allowed_targets[required_target] = required_target
                        proposal_result = llm_proposals.propose(
                            llm_page,
                            visited=state.targets_visited_on(page),
                            allowed_targets=allowed_targets,
                        )
                        performance_budget.record("llm", proposal_result.trace.latency_ms)
                        evidence.append(record_event(
                            ctx, "llm", "llm_action_proposed",
                            activity=activity,
                            prompt_version=proposal_result.trace.prompt_version,
                            prompt_fingerprint=proposal_result.trace.prompt_fingerprint,
                            # 请求快照随事件归档：离线回放才能重现模型当时看到的
                            # 输入（已由 adapter 完成设备号/凭据脱敏）。
                            request=proposal_result.trace.request,
                            status=proposal_result.trace.status,
                            latency_ms=proposal_result.trace.latency_ms,
                            fallback_reason=proposal_result.fallback_reason,
                            response=proposal_result.trace.response,
                            allowed_target_count=len(allowed_targets),
                            page_role=current_page_semantics.legacy_role,
                            role_correction=proposal_result.role_correction,
                        ))
                        if proposal_result.role_correction and (
                            proposal_result.role_correction != current_page_semantics.legacy_role
                        ):
                            evidence.append(record_event(
                                ctx, "llm", "llm_role_correction_observed",
                                activity=activity,
                                adjudicated_role=current_page_semantics.legacy_role,
                                suggested_role=proposal_result.role_correction,
                                reason="模型角色异议仅记录；下一稳定观测由确定性仲裁重新判定",
                            ))
                        llm_effectiveness.record_proposal(
                            status=proposal_result.trace.status,
                            fallback_reason=proposal_result.fallback_reason,
                        )
                        # A model may challenge the deterministic role but it
                        # must never turn that challenge into an executable
                        # action.  Re-observe exactly once; the next stable
                        # frame is adjudicated from UI/route/checkpoint
                        # evidence again.  This is deliberately bounded so a
                        # bad model response cannot create an idle loop.
                        if proposal_result.fallback_reason == "role_correction_only":
                            correction_key = (
                                f"{page.surface_fingerprint}:"
                                f"{current_page_semantics.legacy_role}->"
                                f"{proposal_result.role_correction}"
                            )
                            correction_attempts = ctx.runtime.setdefault(
                                "role_correction_reobserve_attempts", {},
                            )
                            if int(correction_attempts.get(correction_key, 0)) < 1:
                                correction_attempts[correction_key] = 1
                                evidence.append(record_event(
                                    ctx, "appium", "role_conflict_reobserve",
                                    activity=activity,
                                    surface_id=page.surface_fingerprint,
                                    adjudicated_role=current_page_semantics.legacy_role,
                                    suggested_role=proposal_result.role_correction,
                                    reason="模型角色异议；重新读取稳定页面并由仲裁器复核",
                                ))
                                continue
                            evidence.append(record_event(
                                ctx, "appium", "role_conflict_unconfirmed",
                                activity=activity,
                                surface_id=page.surface_fingerprint,
                                adjudicated_role=current_page_semantics.legacy_role,
                                suggested_role=proposal_result.role_correction,
                                reason="已重观测一次，未取得可改变固定优先级的新证据",
                            ))
                        if proposal_result.proposal is None:
                            raise ValueError(
                                f"llm proposal rejected:{proposal_result.fallback_reason}"
                            )
                        decision = proposal_result.proposal.as_decision()
                        decision_source = "llm"
                        proposal_source = "llm"
                        llm_proposed = dict(decision)
                        chosen = str(decision.get("target") or "")
                        if (
                            decision.get("action") == "click"
                            and chosen
                            and chosen in sensitive_media_candidates
                        ):
                            probe_key = f"{page.surface_fingerprint}::{chosen}"
                            ctx.runtime.setdefault("sensitive_permission_probe_attempts", set()).add(probe_key)
                            ctx.runtime.setdefault("sensitive_permission_probe_targets", set()).add(chosen)
                            attempted_targets.add(chosen)
                            evidence.append(record_event(
                                ctx, "appium", "sensitive_business_permission_probe_started",
                                activity=activity, target=chosen, scenario_item="4.2",
                                media_family=_media_family_of(
                                    _labels_for_media_identity(chosen, page.elements),
                                ),
                                probe_mode=(
                                    "screen_recipe" if chosen.startswith("relative:")
                                    else "accessibility_target"
                                ),
                                probes_attempted=len(attempted_targets),
                                probe_context=probe_context,
                                via="llm",
                            ))
                        elif (
                            sensitive_media_candidates
                            and decision.get("action") in {"stop", "wait", "back"}
                        ):
                            # A confirmed redress composer must exhaust its bounded
                            # media families before leaving, even if the model backs
                            # out early. False WebActivity matches are prevented by
                            # the positive title+interaction surface requirement.
                            customer_probe_target = _prefer_labeled_media_probe(
                                sensitive_media_candidates,
                                preferred=_next_media_family_candidate(
                                    sensitive_media_candidates,
                                    elements=page.elements,
                                    attempted=set(attempted_targets),
                                ) or sensitive_media_candidates[0],
                                attempted=set(attempted_targets),
                                require_cs_for_relative=True,
                                activity=activity,
                                page_text=page_text,
                            )
                            if customer_probe_target:
                                directive = RedressMediaProbePolicy().early_exit_directive(
                                    action=str(decision.get("action") or ""),
                                    candidates=(customer_probe_target,),
                                    attempted_targets=set(attempted_targets),
                                )
                                if directive is not None:
                                    def _on_media_assist_selected(
                                        effects, *, target=customer_probe_target,
                                    ):
                                        if "record_media_probe" not in effects:
                                            return
                                        probe_key = f"{page.surface_fingerprint}::{target}"
                                        ctx.runtime.setdefault(
                                            "sensitive_permission_probe_attempts", set(),
                                        ).add(probe_key)
                                        ctx.runtime.setdefault(
                                            "sensitive_permission_probe_targets", set(),
                                        ).add(target)
                                        attempted_targets.add(target)
                                        evidence.append(record_event(
                                            ctx, "appium", "sensitive_business_permission_probe_started",
                                            activity=activity, target=target, scenario_item="4.2",
                                            media_family=_media_family_of(
                                                _labels_for_media_identity(target, page.elements),
                                            ),
                                            probe_mode=(
                                                "screen_recipe" if target.startswith("relative:")
                                                else "accessibility_target"
                                            ),
                                            probes_attempted=len(attempted_targets),
                                            probe_context=probe_context,
                                            via="llm_pass_assist",
                                        ))

                                    media_assist_proposal = directive_selection.add(
                                        directive, on_selected=_on_media_assist_selected,
                                    )
                        if (
                            customer_service_surface
                            and decision.get("action") in {"stop", "wait", "back"}
                            and not customer_probe_target
                        ):
                            directive = RedressMediaProbePolicy().exhausted_directive(
                                action=str(decision.get("action") or ""),
                            )
                            if directive is not None:
                                def _on_customer_service_exhausted_selected(
                                    effects, *, reason=directive.reason,
                                ):
                                    if "record_customer_service_exhausted" not in effects:
                                        return
                                    evidence.append(record_event(
                                        ctx, "appium", "customer_service_surface_exhausted",
                                        activity=activity,
                                        attempted=sorted(attempted_targets),
                                        probe_context=probe_context,
                                        reason=reason,
                                    ))

                                customer_service_exhausted_proposal = directive_selection.add(
                                    directive,
                                    on_selected=_on_customer_service_exhausted_selected,
                                )
                    except Exception as exc:
                        customer_probe_target = _prefer_labeled_media_probe(
                            sensitive_media_candidates,
                            preferred=_next_media_family_candidate(
                                sensitive_media_candidates,
                                elements=page.elements,
                                attempted=set(attempted_targets),
                            ) if sensitive_media_candidates else None,
                            attempted=set(attempted_targets),
                            require_cs_for_relative=True,
                            activity=activity,
                            page_text=page_text,
                        ) if sensitive_media_candidates else None
                        if customer_probe_target:
                            probe_key = f"{page.surface_fingerprint}::{customer_probe_target}"
                            ctx.runtime.setdefault("sensitive_permission_probe_attempts", set()).add(probe_key)
                            ctx.runtime.setdefault("sensitive_permission_probe_targets", set()).add(
                                customer_probe_target,
                            )
                            attempted_targets.add(customer_probe_target)
                            decision = {
                                "action": "click", "target": customer_probe_target,
                                "reason": "LLM 不可用时按形态族回退点击媒体候选以核验 2.3/4.2",
                            }
                            decision_source = "fallback"
                            evidence.append(record_event(
                                ctx, "appium", "sensitive_business_permission_probe_started",
                                activity=activity, target=customer_probe_target, scenario_item="4.2",
                                media_family=_media_family_of(
                                    _labels_for_media_identity(customer_probe_target, page.elements),
                                ),
                                probe_mode=(
                                    "screen_recipe" if customer_probe_target.startswith("relative:")
                                    else "accessibility_target"
                                ),
                                probes_attempted=len(attempted_targets),
                                probe_context=probe_context,
                                via="llm_unavailable_fallback",
                            ))
                        else:
                            decision = _call_llm_fallback(
                                llm, page.elements, state.targets_visited_on(page),
                                page_role=current_page_semantics.legacy_role,
                                sdk_dwell_pending=sdk_dwell_pending,
                                hub_pending=bool(settings_hub and hub_pending),
                                consent_dialog=current_page_semantics.has_overlay,
                            )
                            decision_source = "fallback"
                        ctx.runtime.setdefault("llm_fallbacks", []).append(type(exc).__name__)
                if llm_proposed is None and decision_source in {"llm", "fallback"}:
                    proposal_source = decision_source
                    llm_proposed = dict(decision)
                # Deterministic scenarios are generated from the current UI,
                # but an Android transition can race the decision by a frame.
                # Never replay a target from the previous App page on a file
                # picker, Custom Tab, or a freshly redrawn page.
                target = str(decision.get("target") or "")
                unread_document = unread_document or _unread_for_page(
                    ctx, page.elements, state.targets_visited_on(page),
                )
                unread_inline = _unread_inline_titles_for_target(ctx, target, page.elements) if target else []
                if (
                    decision.get("action") == "click"
                    and target
                    and unread_inline
                    and _normalize_document_title(target) not in {
                        _normalize_document_title(item) for item in unread_inline
                    }
                    and not current_page_semantics.has_overlay
                ):
                    directive = CombinedDocumentRedirectPolicy().directive(
                        action=str(decision.get("action") or ""),
                        target=target,
                        unread_titles=unread_inline,
                        has_overlay=current_page_semantics.has_overlay,
                    )
                    if directive is not None:
                        def _on_combined_document_selected(
                            _effects, *, original_target=target, preferred=directive.target,
                        ):
                            evidence.append(record_event(
                                ctx, "appium", "combined_document_redirected", activity=activity,
                                original_target=original_target, target=preferred,
                                reason="合并文案中仍有未阅读的独立条款，改开该书名号",
                            ))

                        combined_document_proposal = directive_selection.add(
                            directive, on_selected=_on_combined_document_selected,
                        )
                if (
                    decision.get("action") == "click"
                    and _is_splash_deferred_document_target(str(decision.get("target") or ""), page.elements)
                    and decision_source != "deterministic_document"
                ):
                    consent_gate = _unchecked_consent_checkbox(page.elements)
                    consent_target = (
                        _catalog_target_for_role(current_page_semantics, "consent")
                        or _explicit_consent_target(page.elements)
                    )
                    original_doc = str(decision.get("target") or "")
                    directive = consent_decisions.defer_splash_document(
                        original_target=original_doc,
                        checkbox_target=consent_gate or "",
                        checkbox_clicks=int(ctx.runtime.get("consent_checkbox_clicks", 0)),
                        consent_target=consent_target or "",
                    )

                    def _on_splash_defer_selected(effects, consent_target=consent_target):
                        if "forget_consent_target" in effects and consent_target:
                            state.forget_target(page, consent_target)

                    defer_proposal = directive_selection.add(
                        directive, on_selected=_on_splash_defer_selected,
                    )
                    decision = defer_proposal.as_decision()
                    decision_source = directive.source
                    directive_token = defer_proposal.token
                    target = str(decision.get("target") or "")
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=llm_proposed,
                        new_decision=decision, source="splash_document_deferred",
                        reason="首次同意弹窗不展开外链条款",
                    )
                if (
                    decision.get("action") == "click"
                    and target
                    and _already_read_document_target(ctx, target, page.elements)
                ):
                    evidence.append(record_event(
                        ctx, "appium", "already_read_document_skipped", activity=activity,
                        target=target, reason="该隐私政策/协议/SDK目录已在本次检测中阅读，不再重复打开",
                    ))
                    unread_document = _unread_for_page(
                        ctx, page.elements, set(state.targets_visited_on(page)) | {target},
                    )
                    consent_target = (
                        _catalog_target_for_role(current_page_semantics, "consent")
                        or _explicit_consent_target(page.elements)
                        if current_page_semantics.has_overlay else None
                    )
                    if unread_document and unread_document != target and not _already_read_document_target(
                        ctx, unread_document, page.elements
                    ):
                        decision = {
                            "action": "click", "target": unread_document,
                            "reason": "改开尚未阅读的另一份条款",
                        }
                        decision_source = "deterministic_document"
                        target = unread_document
                    elif consent_target:
                        directive = hub_decisions.propose_consent_after_documents(
                            target=consent_target,
                        )
                        if directive is not None:
                            already_read_consent_proposal = directive_selection.add(directive)
                    else:
                        hub_row = (
                            _hub_privacy_action_target(
                                ctx, page.elements, set(state.targets_visited_on(page)) | {target},
                            )
                            if settings_hub and hub_pending else None
                        )
                        if hub_row:
                            directive = hub_decisions.propose_already_read_redirect(
                                target=hub_row,
                            )
                            if directive is not None:
                                already_read_hub_proposal = directive_selection.add(directive)
                        elif settings_hub and hub_pending and _scroll_hub_for_privacy_path(
                            self.client, ctx, state, page, activity, evidence,
                            "已读条款行不再打开，滚动设置页寻找注销/授权",
                        ):
                            continue
                        elif settings_hub and hub_pending and (
                            next_row := _next_hub_exploration_target(
                                page.elements, set(state.targets_visited_on(page)) | {target},
                                ctx=ctx,
                            )
                        ):
                            directive = hub_decisions.propose_next_hub_row(target=next_row)
                            if directive is not None:
                                already_read_hub_proposal = directive_selection.add(directive)
                        elif settings_hub and hub_pending:
                            if ctx.runtime.get("privacy_hub_search_exhausted"):
                                decision = {
                                    "action": "back" if not state.is_root_page(page) else "stop",
                                    "target": "",
                                    "reason": "枢纽搜索已耗尽且可见条款已读，离开当前页继续其它场景",
                                }
                                decision_source = "already_read_document"
                                target = ""
                            else:
                                decision = {
                                    "action": "wait", "target": "",
                                    "reason": "可见条款均已阅读，暂留设置页继续寻找注销/授权",
                                }
                                decision_source = "already_read_document"
                                target = ""
                        else:
                            decision = {
                                "action": "back" if not state.is_root_page(page) else "stop",
                                "target": "",
                                "reason": "可见条款均已阅读，不再重复点开同一份",
                            }
                            decision_source = "already_read_document"
                            target = ""
                if (
                    decision.get("action") == "click"
                    and _is_self_app_launch_click(
                        str(decision.get("target") or ""),
                        activity,
                        str(getattr(ctx.apk, "package_name", "") or ""),
                        str(getattr(ctx.apk, "app_name", "") or ""),
                    )
                ):
                    evidence.append(record_event(
                        ctx, "appium", "self_app_launch_click_ignored", activity=activity,
                        target=str(decision.get("target") or ""),
                        reason="已在被测应用内，不把应用名当成桌面图标再点一次",
                    ))
                    redirected = _redirect_after_ignored_app_icon(
                        ctx, state, page,
                        consent_accepted=bool(ctx.runtime.get("consent_accepted")),
                        settings_hub=settings_hub,
                        hub_pending=hub_pending,
                    )
                    decision = {
                        "action": redirected["action"],
                        "target": redirected.get("target") or "",
                        "reason": redirected["reason"],
                    }
                    if redirected.get("source") and redirected["source"] != "wait":
                        decision_source = redirected["source"]
                    target = str(decision.get("target") or "")
                if (
                    decision.get("action") == "click"
                    and _is_foreign_app_launch_click(
                        str(decision.get("target") or ""),
                        activity,
                        str(getattr(ctx.apk, "package_name", "") or ""),
                        str(getattr(ctx.apk, "app_name", "") or ""),
                        page.elements,
                        foreground_package=str(getattr(self.client, "last_package", "") or ""),
                    )
                ):
                    evidence.append(record_event(
                        ctx, "appium", "foreign_app_launch_click_ignored", activity=activity,
                        target=str(decision.get("target") or ""),
                        audited_app_name=str(getattr(ctx.apk, "app_name", "") or ""),
                        reason="已在被测应用内，禁止点击其它应用图标/名称以免串测",
                    ))
                    redirected = _redirect_after_ignored_app_icon(
                        ctx, state, page,
                        consent_accepted=bool(ctx.runtime.get("consent_accepted")),
                        settings_hub=settings_hub,
                        hub_pending=hub_pending,
                    )
                    decision = {
                        "action": redirected["action"],
                        "target": redirected.get("target") or "",
                        "reason": redirected["reason"],
                    }
                    if redirected.get("source") and redirected["source"] != "wait":
                        decision_source = redirected["source"]
                    target = str(decision.get("target") or "")
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=llm_proposed,
                        new_decision=decision, source="foreign_app",
                        reason="已在被测应用内，禁止点击其它应用图标/名称以免串测",
                    )
                    if redirected.get("source") == "home_idle_exhausted":
                        evidence.append(record_event(
                            ctx, "appium", "home_idle_exhausted", activity=activity,
                            cycles=int(ctx.runtime.get("home_idle_cycles", 0)),
                            reason=redirected["reason"],
                        ))
                if (
                    decision.get("action") == "click"
                    and hub_pending
                    and _identity_is_hub_distractor(
                        f"{decision.get('target') or ''} "
                        f"{_labels_for_click_target(str(decision.get('target') or ''), page.elements)}"
                    )
                ):
                    evidence.append(record_event(
                        ctx, "appium", "hub_distractor_redirected", activity=activity,
                        original_target=str(decision.get("target") or ""),
                        reason="通知/推送/消息设置不是撤回同意或注销入口",
                    ))
                    hub_row = _hub_privacy_action_target(
                        ctx, page.elements, set(state.targets_visited_on(page)) | {
                            str(decision.get("target") or ""),
                        },
                    )
                    if hub_row:
                        decision = {
                            "action": "click", "target": hub_row,
                            "reason": "通知设置不能核验 3.8/6.1，改点注销或授权管理",
                        }
                        decision_source = "deterministic_privacy_hub"
                        target = hub_row
                    elif settings_hub and _scroll_hub_for_privacy_path(
                        self.client, ctx, state, page, activity, evidence,
                        "拦截通知设置后滚动寻找注销/授权",
                    ):
                        continue
                    elif settings_hub and (
                        next_row := _next_hub_exploration_target(
                            page.elements,
                            set(state.targets_visited_on(page)) | {str(decision.get("target") or "")},
                        )
                    ):
                        decision = {
                            "action": "click", "target": next_row,
                            "reason": "通知设置不能核验 3.8/6.1，改点设置页其他未访问行",
                        }
                        decision_source = "deterministic_privacy_hub"
                        target = next_row
                    elif settings_hub:
                        # Stay on the hub. Backing out caused endless 我的↔设置 loops.
                        decision = {
                            "action": "wait", "target": "",
                            "reason": "拦截通知设置后暂留设置页，等待滚动或其它入口出现",
                        }
                        decision_source = "deterministic_privacy_hub"
                        target = ""
                        if int(ctx.runtime.get("hub_privacy_scrolls", 0)) >= 6:
                            ctx.runtime["privacy_hub_search_exhausted"] = True
                    else:
                        login_now = _profile_login_entry(
                            page.elements, extra_text=str(ctx.runtime.get("last_screen_text") or ""),
                        )
                        if (
                            login_now
                            and not ctx.runtime.get("manual_login_verified")
                            and not state.target_visited(page, login_now)
                        ):
                            decision = {
                                "action": "click", "target": login_now,
                                "reason": "未登录时无法核验注销，先进入登录入口",
                            }
                            decision_source = "deterministic_login_entry"
                            target = login_now
                        else:
                            recovery_target = _privacy_hub_tab_target(page.elements)
                            if recovery_target and not state.target_visited(page, recovery_target):
                                decision = {
                                    "action": "click", "target": recovery_target,
                                    "reason": "通知设置不能核验 3.8/6.1，改回设置/我的",
                                }
                                decision_source = "deterministic_privacy_hub"
                                target = recovery_target
                            else:
                                decision = {
                                    "action": "wait", "target": "",
                                    "reason": "通知设置不能核验撤回或注销，暂留当前页另寻路径",
                                }
                                target = ""
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=llm_proposed,
                        new_decision=decision, source="hub_distractor",
                        reason="通知/推送/消息设置不是撤回同意或注销入口",
                    )
                if (
                    decision.get("action") == "click"
                    and _is_document_body_hyperlink(str(decision.get("target") or ""), activity, page.elements)
                    and not (document_key and state.document_is_complete(document_key))
                ):
                    evidence.append(record_event(
                        ctx, "appium", "document_body_hyperlink_deferred", activity=activity,
                        target=str(decision.get("target") or ""),
                        reason="父条款尚未滚完，内嵌清单等读完后再打开，避免漏读或点崩无障碍服务",
                    ))
                    decision = {
                        "action": "wait", "target": "",
                        "reason": "先读完当前条款正文，再打开内嵌的收集/共享清单",
                    }
                    target = ""
                if (
                    decision.get("action") == "click"
                    and unread_document
                    and _is_consent_click(target, page.elements)
                    and not current_page_semantics.has_overlay
                    and ctx.runtime.get("consent_accepted")
                ):
                    # Post-entry hub pages may still require reading a visible
                    # policy row before treating a mis-labeled Agree as done.
                    # Splash consent never uses this path (docs deferred to hub).
                    evidence.append(record_event(
                        ctx, "appium", "consent_blocked_until_documents_read",
                        activity=activity, original_target=target, target=unread_document,
                        reason="枢纽页可见条款尚未阅读，不能先点同意类按钮",
                    ))
                    decision = {
                        "action": "click", "target": unread_document,
                        "reason": "同意前先打开当前页尚未阅读的隐私政策/用户协议/收集清单",
                    }
                    decision_source = "deterministic_document"
                    target = unread_document
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=llm_proposed,
                        new_decision=decision, source="consent_blocked",
                        reason="枢纽页可见条款尚未阅读，不能先点同意类按钮",
                    )
                blocked_document_targets = ctx.runtime.get("blocked_document_targets") or set()
                blocked_kinds = _blocked_document_kinds(ctx)
                target_kind = _infer_document_kind(target, "") if target else None
                if (
                    decision.get("action") == "click"
                    and target
                    and _target_is_document_route(target)
                    and (
                        target in blocked_document_targets
                        or (target_kind and target_kind in blocked_kinds)
                    )
                ):
                    # The same policy route already opened a Custom Tab whose
                    # body never became readable. Reopening it only repeats
                    # the browser round-trip and can starve all other routes;
                    # preserve the coverage gap and return to the app.
                    evidence.append(record_event(
                        ctx, "appium", "blocked_document_reopen_prevented",
                        activity=activity, target=target, document_kind=target_kind,
                        reason="外部条款正文未加载，跳过重复打开并继续其他页面",
                    ))
                    decision = {
                        "action": "back", "target": "",
                        "reason": "外部条款正文不可用，返回继续其他合规路径",
                    }
                    decision_source = "coverage_recovery"
                crash_skip_targets = ctx.runtime.get("crash_skip_targets") or set()
                if (
                    decision.get("action") == "click"
                    and target
                    and target in crash_skip_targets
                ):
                    evidence.append(record_event(
                        ctx, "appium", "crash_route_skipped",
                        activity=activity, target=target,
                        reason="该入口曾导致应用崩溃，改走其它路径",
                    ))
                    # A root-level "pending document" redirect runs later in
                    # the decision chain.  Mark this exact route blocked now,
                    # otherwise that redirect immediately selects the same
                    # crash-inducing title again.
                    state.mark_target(page, target)
                    if _target_is_document_route(target):
                        ctx.runtime.setdefault("blocked_document_targets", set()).add(target)
                    recovery_target = _privacy_hub_tab_target(page.elements) or _main_content_tab_target(page.elements)
                    if (
                        recovery_target
                        and recovery_target not in crash_skip_targets
                        and not state.target_visited(page, recovery_target)
                    ):
                        decision = {
                            "action": "click", "target": recovery_target,
                            "reason": "跳过已崩溃入口，改走设置/主内容继续检测",
                        }
                        decision_source = "crash_route_recovery"
                        target = recovery_target
                    else:
                        decision = {
                            "action": "back", "target": "",
                            "reason": "跳过已崩溃入口，返回寻找其它路径",
                        }
                        decision_source = "crash_route_recovery"
                        target = ""
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=llm_proposed,
                        new_decision=decision, source="crash_route",
                        reason="该入口曾导致应用崩溃，改走其它路径",
                    )
                if (
                    decision.get("action") == "click"
                    and target
                    and not target.startswith("relative:")
                    and not _target_is_visible(target, page.elements)
                ):
                    evidence.append(record_event(
                        ctx, "appium", "stale_action_blocked", activity=activity,
                        target=target, decision_source=decision_source,
                    ))
                    decision = {"action": "back", "target": "", "reason": "目标已不在当前页面，返回重读页面"}
                    decision_source = "stale_action_recovery"
                final_candidate = str(decision.get("target") or "")
                if (
                    decision.get("action") == "click"
                    and final_candidate
                    and _is_low_audit_value_route(final_candidate, page.elements)
                ):
                    visited_without_marketing = set(state.targets_visited_on(page))
                    visited_without_marketing.add(final_candidate)
                    useful_sibling = _next_safe_deep_target(
                        page.elements, visited_without_marketing, ctx=ctx,
                    )
                    original_low_value = dict(decision)
                    decision = surface_budget.route_replacement(useful_sibling=useful_sibling or "")
                    decision_source = "coverage_pruning"
                    target = str(decision.get("target") or "")
                    evidence.append(record_event(
                        ctx, "appium", "low_audit_value_route_pruned",
                        activity=activity,
                        target=final_candidate,
                        replacement_action=decision["action"],
                        replacement_target=target,
                        reason="该入口不推进隐私政策、权限、撤回/注销或投诉反馈规则覆盖",
                    ))
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=original_low_value,
                        new_decision=decision, source="coverage_pruning",
                        reason=str(decision.get("reason") or "")[:300],
                    )
                if low_value_surface_kind:
                    original_low_value_surface = dict(decision)
                    budget_decision = low_value_budget_decision or surface_budget.leave_low_value(
                        surface_key=page.surface_fingerprint, surface_kind=low_value_surface_kind,
                        is_root=state.is_root_page(page),
                    )
                    decision = {
                        "action": budget_decision.action,
                        "target": "",
                        "reason": budget_decision.reason,
                    }
                    decision_source = "coverage_pruning"
                    target = ""
                    evidence.append(record_event(
                        ctx, "appium", "low_audit_value_surface_pruned",
                        activity=activity, surface_kind=low_value_surface_kind,
                        first_observation=budget_decision.first_observation,
                        original_action=original_low_value_surface.get("action"),
                        original_target=original_low_value_surface.get("target"),
                        replacement_action=decision["action"],
                        reason="页面未提供明确投诉/反馈、隐私、权限、授权撤回或账号控制入口",
                    ))
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=original_low_value_surface,
                        new_decision=decision, source="coverage_pruning",
                        reason=str(decision.get("reason") or "")[:300],
                    )
                # Record ``decision`` only after overrides below, so the timeline
                # matches the action that is actually performed.
                if (
                    decision["action"] == "stop"
                    and _stop_override_allowed(decision_source)
                ):
                    unread_after = _unread_for_page(ctx, page.elements, state.targets_visited_on(page))
                    if unread_after:
                        evidence.append(record_event(
                            ctx, "appium", "early_stop_overridden", activity=activity,
                            original_reason=str(decision.get("reason") or "")[:300], target=unread_after,
                            override_kind="unread_required_document",
                        ))
                        decision = {
                            "action": "click", "target": unread_after,
                            "reason": "仍有未阅读的隐私政策/用户协议，不能结束遍历",
                        }
                        decision_source = "deterministic_document"
                        _record_decision_override(
                            ctx, evidence, activity=activity, original=llm_proposed,
                            new_decision=decision, source="early_stop_overridden",
                            reason="仍有未阅读的隐私政策/用户协议，不能结束遍历",
                        )
                    else:
                        if frontier_recommendation:
                            fallback = {
                                "action": "click", "target": frontier_recommendation["target"],
                                "reason": frontier_recommendation["reason"],
                            }
                        else:
                            try:
                                fallback = _call_llm_fallback(
                                    llm, page.elements, state.targets_visited_on(page),
                                    page_role=current_page_semantics.legacy_role,
                                    sdk_dwell_pending=sdk_dwell_pending,
                                    hub_pending=bool(settings_hub and hub_pending),
                                    consent_dialog=current_page_semantics.has_overlay,
                                )
                            except Exception:
                                fallback = {"action": "back", "target": "", "reason": "fallback unavailable"}
                        target = str(fallback.get("target") or "")
                        required_target = _is_required_exploration_target(target, page.elements)
                        deep_probe_limit = max(6, min(30, int(limits["max_pages"]) // 6))
                        safe_deep_target = (
                            ctx.task.mode == "deep"
                            and deep_probe_count < deep_probe_limit
                            and _is_safe_deep_probe_target(target, page.elements)
                        )
                        if (
                            fallback.get("action") == "click"
                            and target
                            and not state.target_visited(page, target)
                            and (required_target or safe_deep_target)
                        ):
                            if safe_deep_target and not required_target:
                                deep_probe_count += 1
                            evidence.append(record_event(
                                ctx, "appium", "early_stop_overridden", activity=activity,
                                original_reason=str(decision.get("reason") or "")[:300], target=target,
                                override_kind="required_rule_route" if required_target else "bounded_deep_business_route",
                            ))
                            decision = {
                                "action": "click", "target": target,
                                "reason": (
                                    "深度遍历守则：优先核验当前页未访问的隐私相关入口"
                                    if required_target else
                                    "深度遍历守则：核验当前页未访问的安全业务入口及其权限行为"
                                ),
                            }
                            decision_source = (
                                "deterministic_document" if required_target else "deterministic_scenario"
                            )
                            _record_decision_override(
                                ctx, evidence, activity=activity, original=llm_proposed,
                                new_decision=decision, source="early_stop_overridden",
                                reason=str(decision.get("reason") or "")[:300],
                            )
                        elif _page_is_loading_shell(page, state) and settle_attempts < settle_retries:
                            evidence.append(record_event(
                                ctx, "appium", "page_loading_wait_instead_of_stop",
                                activity=activity, attempt=settle_attempts + 1,
                                original_reason=str(decision.get("reason") or "")[:300],
                            ))
                            decision = {
                                "action": "wait", "target": "",
                                "reason": "页面仍在加载，等待可点击控件出现后再继续",
                            }
                            decision_source = "deterministic_wait_break"
                        else:
                            # P0: fallback may return wait on hub/consent/sdk_dwell to
                            # avoid grabbing settings clicks. That must not let stop
                            # terminate while those surfaces still need work.
                            visited_now = state.targets_visited_on(page)
                            progress_target = None
                            progress_reason = ""
                            progress_source = "deterministic_privacy_hub"
                            if current_page_semantics.has_overlay:
                                progress_target = (
                                    _unread_for_page(ctx, page.elements, visited_now)
                                    or _catalog_target_for_role(current_page_semantics, "consent")
                                    or _explicit_consent_target(page.elements)
                                    or _unchecked_consent_checkbox(page.elements)
                                )
                                progress_reason = "同意弹窗未完成，不能因 LLM stop 结束遍历"
                                progress_source = "deterministic_consent"
                            elif settings_hub and hub_pending and not ctx.runtime.get("privacy_hub_search_exhausted"):
                                _observe_logout_rows_without_clicking(ctx, page.elements, evidence, activity)
                                progress_target = _hub_progress_target(ctx, page.elements, visited_now)
                                progress_reason = "设置枢纽仍有 3.8/6.1/协议/头像待办，不能因 LLM stop 结束遍历"
                            if not progress_target and ctx.task.mode == "deep":
                                progress_target = _next_top_level_audit_target(
                                    page.elements,
                                    set(ctx.runtime.get("visited_top_level_route_keys") or ()),
                                )
                                if progress_target:
                                    progress_reason = "当前分支已完成，按深度优先回溯继续探索其它顶层合规分支"
                                    progress_source = "deterministic_top_level_dfs"
                            if progress_target and not state.target_visited(page, progress_target):
                                evidence.append(record_event(
                                    ctx, "appium", "early_stop_overridden", activity=activity,
                                    original_reason=str(decision.get("reason") or "")[:300],
                                    target=progress_target, override_kind="pending_surface_progress",
                                ))
                                decision = {
                                    "action": "click", "target": progress_target,
                                    "reason": progress_reason,
                                }
                                decision_source = progress_source
                                _record_decision_override(
                                    ctx, evidence, activity=activity, original=llm_proposed,
                                    new_decision=decision, source="early_stop_overridden",
                                    reason=progress_reason,
                                )
                            elif current_page_semantics.has_overlay or sdk_dwell_gate:
                                original_stop_reason = str(
                                    (llm_proposed or decision).get("reason") or ""
                                )[:300]
                                decision = {
                                    "action": "wait", "target": "",
                                    "reason": "同意弹窗或 SDK 观察未完成，将 stop 改为 wait 避免早停",
                                }
                                decision_source = "deterministic_wait_break"
                                evidence.append(record_event(
                                    ctx, "appium", "early_stop_overridden", activity=activity,
                                    original_reason=original_stop_reason,
                                    override_kind="stop_to_wait",
                                    replacement="wait",
                                ))
                                _record_decision_override(
                                    ctx, evidence, activity=activity, original=llm_proposed,
                                    new_decision=decision, source="early_stop_overridden",
                                    reason=str(decision.get("reason") or "")[:300],
                                )
                            elif settings_hub and hub_pending and not ctx.runtime.get("privacy_hub_search_exhausted"):
                                original_stop_reason = str(
                                    (llm_proposed or decision).get("reason") or ""
                                )[:300]
                                # No clickable hub progress remains. Mark exhausted
                                # and allow stop — do not rewrite to back (fingerprint
                                # shifts after denial would loop back→permission).
                                ctx.runtime["privacy_hub_search_exhausted"] = True
                                next_top = _next_top_level_audit_target(
                                    page.elements,
                                    set(ctx.runtime.get("visited_top_level_route_keys") or ()),
                                )
                                decision = {
                                    "action": (
                                        "click" if next_top else (
                                            "stop" if ctx.runtime.get("manual_login_timed_out")
                                            else ("back" if not state.is_root_page(page) else "stop")
                                        )
                                    ),
                                    "target": next_top or "",
                                    "reason": (
                                        "设置分支已完成，按深度优先回溯继续其它顶层分支"
                                        if next_top else "设置枢纽已无更多可推进入口，返回继续其它合规路径"
                                    ),
                                }
                                decision_source = "deterministic_top_level_dfs" if next_top else "deterministic_privacy_hub"
                                evidence.append(record_event(
                                    ctx, "appium", "early_stop_overridden", activity=activity,
                                    original_reason=original_stop_reason,
                                    override_kind="hub_stop_resolve",
                                    replacement=decision["action"],
                                ))
                                _record_decision_override(
                                    ctx, evidence, activity=activity, original=llm_proposed,
                                    new_decision=decision, source="early_stop_overridden",
                                    reason=str(decision.get("reason") or "")[:300],
                                )
                    repeated_business_target = str(decision.get("target") or "")
                    remaining_items = scenario_frontier.snapshot().get("remaining_items", [])
                    permission_probe_pending = any(item in remaining_items for item in ("2.3", "4.2"))
                    business_retries = ctx.runtime.setdefault("business_trigger_retry_attempts", {})
                    retry_key = f"{page.surface_fingerprint}:{repeated_business_target}"
                    retry_count = int(business_retries.get(retry_key, 0))
                    retry_target = _bounds_click_target_for(repeated_business_target, page.elements)
                    if (
                        permission_probe_pending
                        and retry_count < 1
                        and retry_target
                        and _is_business_trigger_action(
                            repeated_business_target, page.elements, str(decision.get("reason") or ""),
                        )
                    ):
                        business_retries[retry_key] = retry_count + 1
                        evidence.append(record_event(
                            ctx, "appium", "business_trigger_retry_without_transition",
                            activity=activity, original_target=repeated_business_target,
                            target=retry_target,
                            reason="首次点击敏感业务入口未触发页面/权限变化，改用当前控件坐标有界重试一次",
                        ))
                        decision = {
                            "action": "click", "target": retry_target,
                            "reason": "首次点击敏感业务入口未触发页面/权限变化，改用当前控件坐标有界重试一次",
                        }
                        decision_source = "deterministic_business_retry"
                if decision["action"] == "click" and state.target_visited(page, decision["target"]):
                    # A duplicate policy link must never make a generic fallback
                    # click a consent/decline button whose semantics were not
                    # selected by the model from its visible text.
                    # On the first-run consent dialog, unfinished document kinds
                    # always win over "already visited short title → checkbox".
                    reopen_target = str(decision.get("target") or "")
                    if (
                        decision_source == "llm"
                        and _hub_scenarios_outstanding(scenario_frontier)
                        and _target_is_hub_reentry(reopen_target, page.elements)
                        and not settings_hub
                        and not ctx.runtime.get("privacy_hub_search_exhausted")
                        and int(ctx.runtime.get("hub_reentry_honors", 0)) < 3
                    ):
                        logged_out_now = _logged_out_profile_visible(
                            page.elements,
                            extra_text=str(ctx.runtime.get("last_screen_text") or ""),
                        )
                        login_now = _profile_login_entry(
                            page.elements,
                            extra_text=str(ctx.runtime.get("last_screen_text") or ""),
                        )
                        if (
                            logged_out_now
                            and login_now
                            and not ctx.runtime.get("manual_login_verified")
                            and not state.target_visited(page, login_now)
                        ):
                            decision = {
                                "action": "click", "target": login_now,
                                "reason": "未登录时反复进设置找不到注销，改点登录入口",
                            }
                            decision_source = "deterministic_login_entry"
                            evidence.append(record_event(
                                ctx, "appium", "logged_out_login_prioritized", activity=activity,
                                target=login_now, original_target=reopen_target,
                            ))
                        else:
                            ctx.runtime["hub_reentry_honors"] = int(ctx.runtime.get("hub_reentry_honors", 0)) + 1
                            state.forget_target(page, reopen_target)
                            evidence.append(record_event(
                                ctx, "appium", "llm_hub_reentry_honored", activity=activity,
                                target=reopen_target,
                                reason="撤回/注销场景尚未完成，沿用模型选择的设置/我的入口，不改成返回",
                            ))
                    elif (
                        any(item in scenario_frontier.snapshot().get("remaining_items", []) for item in ("2.3", "4.2"))
                        and _is_business_trigger_action(
                            reopen_target, page.elements, str(decision.get("reason") or ""),
                        )
                        and (retry_target := _bounds_click_target_for(reopen_target, page.elements))
                        and int(
                            (ctx.runtime.setdefault("business_trigger_retry_attempts", {})).get(
                                f"{page.surface_fingerprint}:{reopen_target}", 0,
                            )
                        ) < 1
                    ):
                        retry_key = f"{page.surface_fingerprint}:{reopen_target}"
                        ctx.runtime["business_trigger_retry_attempts"][retry_key] = 1
                        evidence.append(record_event(
                            ctx, "appium", "business_trigger_retry_without_transition",
                            activity=activity, original_target=reopen_target,
                            target=retry_target,
                            reason="首次点击敏感业务入口未触发页面/权限变化，改用当前控件坐标有界重试一次",
                        ))
                        decision = {
                            "action": "click", "target": retry_target,
                            "reason": "首次点击敏感业务入口未触发页面/权限变化，改用当前控件坐标有界重试一次",
                        }
                        decision_source = "deterministic_business_retry"
                    elif (
                        settings_hub
                        and _hub_scenarios_outstanding(scenario_frontier)
                        and (
                            _target_is_hub_reentry(reopen_target, page.elements)
                            or _identity_is_hub_distractor(
                                f"{reopen_target} {_labels_for_click_target(reopen_target, page.elements)}"
                            )
                        )
                    ):
                        hub_row = _hub_privacy_action_target(
                            ctx, page.elements, set(state.targets_visited_on(page)) | {reopen_target},
                        )
                        if hub_row:
                            decision = {
                                "action": "click", "target": hub_row,
                                "reason": "已在设置枢纽内且 3.8/6.1 未完成，改点注销/授权而不是重复入口",
                            }
                            decision_source = "deterministic_privacy_hub"
                            evidence.append(record_event(
                                ctx, "appium", "privacy_path_row_prioritized",
                                activity=activity, target=hub_row, original_target=reopen_target,
                            ))
                        elif _scroll_hub_for_privacy_path(
                            self.client, ctx, state, page, activity, evidence,
                            "枢纽入口已访问，滚动设置页继续找注销/授权",
                        ):
                            continue
                        elif next_row := _next_hub_exploration_target(
                            page.elements, set(state.targets_visited_on(page)) | {reopen_target},
                        ):
                            decision = {
                                "action": "click", "target": next_row,
                                "reason": "枢纽入口已访问，改点其他未访问的隐私相关行",
                            }
                            decision_source = "deterministic_privacy_hub"
                        else:
                            unread_after = _unread_for_page(ctx, page.elements, state.targets_visited_on(page))
                            if unread_after:
                                decision = {
                                    "action": "click", "target": unread_after,
                                    "reason": "当前目标已访问，改为打开尚未阅读的政策/协议链接",
                                }
                            else:
                                decision = {
                                    "action": "wait", "target": "",
                                    "reason": "设置枢纽内暂无新的注销/授权入口，暂留观察",
                                }
                            evidence.append(record_event(
                                ctx, "appium", "loop_prevented", activity=activity,
                                reason="duplicate_hub_entry", replacement=decision["action"],
                                next_target=str(decision.get("target") or ""),
                            ))
                    elif (
                        _click_reopens_incomplete_document(ctx, reopen_target)
                        and int(ctx.runtime.get("incomplete_document_reopens", 0)) < 2
                    ):
                        ctx.runtime["incomplete_document_reopens"] = int(
                            ctx.runtime.get("incomplete_document_reopens", 0)
                        ) + 1
                        state.forget_target_everywhere(reopen_target)
                        evidence.append(record_event(
                            ctx, "appium", "incomplete_document_reopened", activity=activity,
                            target=reopen_target,
                            reason="条款正文上次未验证读完，允许换入口或再打开一次",
                        ))
                    else:
                        alternative = _call_llm_fallback(
                            llm, page.elements, state.targets_visited_on(page), False,
                            page_role=current_page_semantics.legacy_role,
                            sdk_dwell_pending=sdk_dwell_pending,
                            hub_pending=bool(settings_hub and hub_pending),
                            consent_dialog=current_page_semantics.has_overlay,
                        )
                        unread_after = _unread_for_page(ctx, page.elements, state.targets_visited_on(page))
                        if unread_after:
                            alternative = {
                                "action": "click", "target": unread_after,
                                "reason": "当前目标已访问，改为打开尚未阅读的政策/协议链接",
                            }
                        elif current_page_semantics.has_overlay:
                            still = _unread_for_page(ctx, page.elements, set())
                            if still:
                                alternative = {
                                    "action": "click", "target": still,
                                    "reason": "同意弹窗上仍有未真正打开的条款书名号，优先继续打开",
                                }
                            elif (consent_gate := _unchecked_consent_checkbox(page.elements)):
                                alternative = {
                                    "action": "click", "target": consent_gate,
                                    "reason": "同意未生效，先勾选阅读并同意后再进入应用",
                                }
                            else:
                                consent_target = (
                                    _catalog_target_for_role(current_page_semantics, "consent")
                                    or _explicit_consent_target(page.elements)
                                )
                                if consent_target:
                                    alternative = {
                                        "action": "click", "target": consent_target,
                                        "reason": "已完成政策阅读，点击文字明确的同意按钮进入应用",
                                    }
                        elif (consent_gate := _unchecked_consent_checkbox(page.elements)):
                            alternative = {
                                "action": "click", "target": consent_gate,
                                "reason": "同意未生效，先勾选阅读并同意后再进入应用",
                            }
                        elif alternative["action"] != "click":
                            consent_target = (
                                _catalog_target_for_role(current_page_semantics, "consent")
                                or _explicit_consent_target(page.elements)
                            )
                            if (
                                consent_target
                                and consent_target not in state.targets_visited_on(page)
                                and current_page_semantics.has_overlay
                            ):
                                alternative = {
                                    "action": "click", "target": consent_target,
                                    "reason": "已完成政策阅读，点击文字明确的同意按钮进入应用",
                                }
                        if settings_hub and hub_pending:
                            _observe_logout_rows_without_clicking(ctx, page.elements, evidence, activity)
                            progress = _hub_progress_target(
                                ctx, page.elements, state.targets_visited_on(page),
                            )
                            if progress:
                                alternative = {
                                    "action": "click", "target": progress,
                                    "reason": "当前目标已访问，改为同页其它合规入口（头像/协议/注销等）",
                                }
                            elif _identity_is_hub_distractor(
                                f"{alternative.get('target') or ''} "
                                f"{_labels_for_click_target(str(alternative.get('target') or ''), page.elements)}"
                            ):
                                alternative = {
                                    "action": "back" if not state.is_root_page(page) else "stop",
                                    "target": "",
                                    "reason": "通知/推送设置不是撤回或注销入口",
                                }
                        decision = alternative if alternative["action"] == "click" else {
                            "action": "back" if not state.is_root_page(page) else "stop",
                            "target": "", "reason": "已访问当前目标，避免重复点击",
                        }
                        evidence.append(record_event(ctx, "appium", "loop_prevented", activity=activity,
                                                     reason="duplicate_target", replacement=decision["action"],
                                                     next_target=str(decision.get("target") or "")))
                declined_privacy = decision["action"] == "click" and _is_privacy_dialog_decline(
                    str(decision.get("target") or ""), page_text, page.elements
                )
                if declined_privacy:
                    evidence.append(record_event(
                        ctx, "appium", "unsafe_privacy_decline_blocked", activity=activity,
                        target=decision.get("target"), reason="拒绝/退出按钮不是允许的自动化同意动作",
                    ))
                    unread_after = _unread_for_page(ctx, page.elements, state.targets_visited_on(page))
                    consent_target = (
                        _catalog_target_for_role(current_page_semantics, "consent")
                        or _explicit_consent_target(page.elements)
                    )
                    if unread_after:
                        decision = {
                            "action": "click", "target": unread_after,
                            "reason": "已拦截拒绝/退出，改为打开尚未阅读的条款",
                        }
                        decision_source = "deterministic_document"
                    elif consent_target and not _target_has_decline_semantics(consent_target, page.elements):
                        decision = {
                            "action": "click", "target": consent_target,
                            "reason": "已拦截拒绝/退出，改为点击明确同意按钮",
                        }
                        decision_source = "deterministic_consent"
                    else:
                        decision = {
                            "action": "back" if not state.is_root_page(page) else "wait",
                            "target": "",
                            "reason": "已拦截拒绝/退出，继续寻找可阅读条款或同意按钮",
                        }
                        decision_source = "coverage_recovery"
                session_boundary_target = str(decision.get("target") or "")
                logout_observation_only = bool(
                    decision.get("action") == "click"
                    and _is_authenticated_logout_target(session_boundary_target, page.elements)
                    and not bool((ctx.cfg.get("detection") or {}).get(
                        "explore_logout_confirmation", False,
                    ))
                )
                if logout_observation_only:
                    # Enforce the observation-only default after every proposal
                    # source (LLM, frontier and deterministic fallbacks), not only
                    # in the hub picker.  Otherwise an LLM click can bypass the
                    # setting and immediately destroy authentication state.
                    replacement = _sensitive_business_control(
                        activity, page.elements, page_text,
                        exclude=set(state.targets_visited_on(page)) | {session_boundary_target},
                    ) or _next_safe_deep_target(
                        page.elements, set(state.targets_visited_on(page)) | {session_boundary_target},
                        ctx=ctx,
                    )
                    directive = SessionBoundaryPolicy().observation_only_directive(
                        action=str(decision.get("action") or ""),
                        target=session_boundary_target,
                        is_logout_target=True,
                        explore_confirmation=False,
                        replacement=replacement or "",
                    )
                    if directive is not None:
                        def _on_logout_observation_selected(
                            effects, *, original_target=session_boundary_target,
                            replacement_action=directive.action, replacement_target=directive.target,
                        ):
                            if "mark_session_boundary_observed" not in effects:
                                return
                            state.mark_target(page, original_target)
                            evidence.append(record_event(
                                ctx, "appium", "logout_entry_observation_only",
                                activity=activity, target=original_target,
                                replacement_action=replacement_action,
                                replacement_target=replacement_target,
                            ))

                        logout_observation_proposal = directive_selection.add(
                            directive, on_selected=_on_logout_observation_selected,
                        )
                defer_session_boundary = bool(
                    decision.get("action") == "click"
                    and logout_observation_proposal is None
                    and _permission_denial_probe_outstanding(ctx, scenario_frontier)
                    and (
                        _is_authenticated_logout_target(session_boundary_target, page.elements)
                        or _click_matches_privacy_path(session_boundary_target, page.elements, "delete")
                    )
                )
                if defer_session_boundary:
                    # Logout and some delete-account rows can destroy the very
                    # authenticated state needed to reach camera/upload/location
                    # services.  Defer that boundary until the deny probe is
                    # conclusive, and prefer another visible sensitive control.
                    alternative = _sensitive_business_control(
                        activity, page.elements, page_text,
                        exclude=set(state.targets_visited_on(page)) | {session_boundary_target},
                    )
                    directive = SessionBoundaryPolicy().defer_for_deny_probe(
                        action=str(decision.get("action") or ""),
                        target=session_boundary_target,
                        deny_probe_outstanding=True,
                        is_session_boundary=True,
                        replacement=alternative or "",
                    )
                    if directive is not None:
                        def _on_deny_session_boundary_selected(
                            effects, *, original_target=session_boundary_target,
                            replacement_action=directive.action, replacement_target=directive.target,
                        ):
                            if "mark_session_boundary_deferred" not in effects:
                                return
                            state.mark_target(page, original_target)
                            evidence.append(record_event(
                                ctx, "appium", "session_boundary_deferred_for_permission_probe",
                                activity=activity, target=original_target,
                                replacement_action=replacement_action,
                                replacement_target=replacement_target, scenario_item="4.2",
                            ))

                        deny_session_boundary_proposal = directive_selection.add(
                            directive, on_selected=_on_deny_session_boundary_selected,
                        )
                if (
                    decision["action"] == "click"
                    and logout_observation_proposal is None
                    and deny_session_boundary_proposal is None
                    and _is_destructive_confirmation(
                    str(decision.get("target") or ""), page.elements
                    )
                ):
                    directive = SessionBoundaryPolicy().destructive_confirmation_directive(
                        action=str(decision.get("action") or ""),
                        target=str(decision.get("target") or ""),
                        is_destructive_confirmation=True,
                    )
                    if directive is not None:
                        def _on_destructive_confirmation_selected(
                            effects, *, target=str(decision.get("target") or ""),
                        ):
                            if "record_destructive_confirmation_blocked" not in effects:
                                return
                            evidence.append(record_event(
                                ctx, "appium", "destructive_confirmation_blocked", activity=activity,
                                target=target, reason="自动化只检查流程，不提交注销或删除请求",
                            ))

                        destructive_confirmation_proposal = directive_selection.add(
                            directive, on_selected=_on_destructive_confirmation_selected,
                        )
                logout_entry_target = (
                    logout_observation_proposal is None
                    and deny_session_boundary_proposal is None
                    and destructive_confirmation_proposal is None
                    and _is_authenticated_logout_target(
                    str(decision.get("target") or ""), page.elements
                    )
                )
                logout_confirm_target = (
                    destructive_confirmation_proposal is None
                    and logout_confirmation
                    and _is_logout_confirmation_target(
                    str(decision.get("target") or ""), page.elements
                    )
                )
                if decision["action"] == "click" and logout_confirm_target:
                    # Never submit the affirmative button on a logout dialog.
                    directive = SessionBoundaryPolicy().logout_confirmation_directive(
                        action=str(decision.get("action") or ""),
                        target=str(decision.get("target") or ""),
                        is_logout_confirmation=True,
                    )
                    if directive is not None:
                        def _on_logout_confirmation_selected(
                            effects, *, target=str(decision.get("target") or ""),
                        ):
                            if "record_logout_confirmation_blocked" not in effects:
                                return
                            evidence.append(record_event(
                                ctx, "appium", "logout_action_blocked", activity=activity,
                                target=target,
                                reason="退出登录确认按钮仅观察，不提交退出",
                            ))

                        logout_confirmation_proposal = directive_selection.add(
                            directive, on_selected=_on_logout_confirmation_selected,
                        )
                elif (
                    decision["action"] == "click"
                    and logout_entry_target
                    and logout_confirmation_proposal is None
                    and ctx.runtime.get("logout_entry_explored")
                    and decision_source not in {
                        "deterministic_privacy_hub", "deterministic_scenario",
                    }
                ):
                    # Already opened the logout entry once; do not re-enter / submit.
                    directive = SessionBoundaryPolicy().repeated_logout_directive(
                        action=str(decision.get("action") or ""),
                        target=str(decision.get("target") or ""),
                        is_logout_target=True,
                        already_explored=True,
                        source=str(decision_source or ""),
                    )
                    if directive is not None:
                        def _on_repeated_logout_selected(
                            effects, *, target=str(decision.get("target") or ""),
                        ):
                            if "record_repeated_logout_blocked" not in effects:
                                return
                            evidence.append(record_event(
                                ctx, "appium", "logout_action_blocked", activity=activity,
                                target=target,
                                reason="退出登录入口已探索过一次，避免重复进入或误提交",
                            ))

                        repeated_logout_proposal = directive_selection.add(
                            directive, on_selected=_on_repeated_logout_selected,
                        )
                elif decision["action"] == "click" and logout_entry_target:
                    # First exploration click into the logout confirm surface.
                    evidence.append(record_event(
                        ctx, "appium", "logout_entry_exploration_allowed", activity=activity,
                        target=decision.get("target"),
                        reason="允许点开退出登录确认框核验；不会点击确认退出",
                    ))
                root_override_proposal = None
                if decision["action"] == "back" and state.is_root_page(page) and frontier_recommendation:
                    frontier_target = str(frontier_recommendation["target"] or "")
                    route_key = _root_route_key(activity, frontier_target)
                    root_route_attempts = ctx.runtime.setdefault("root_route_attempts", {})
                    document_blocked = (
                        _target_is_document_route(frontier_target)
                        and (
                            frontier_target in (ctx.runtime.get("blocked_document_targets") or set())
                            or (
                                (_infer_document_kind(frontier_target, "") or "")
                                in _blocked_document_kinds(ctx)
                            )
                        )
                    )
                    if not document_blocked and root_route_attempts.get(route_key, 0) < 1:
                        # The legacy click guards ran on the rewritten decision;
                        # as a candidate the frontier click must carry their
                        # verdict itself or the guarded boundary stays blind.
                        if _is_app_exit_confirmation(frontier_target, page.elements, page_text):
                            evidence.append(record_event(
                                ctx, "appium", "app_exit_confirmation_blocked",
                                activity=activity, target=frontier_target,
                                reason="退出应用确认框不会点击确定，避免被送回系统桌面",
                            ))
                        elif (
                            _is_authenticated_logout_target(frontier_target, page.elements)
                            and ctx.runtime.get("logout_entry_explored")
                        ):
                            evidence.append(record_event(
                                ctx, "appium", "logout_action_blocked", activity=activity,
                                target=frontier_target,
                                reason="退出登录入口已探索过一次，避免重复进入或误提交",
                            ))
                            root_override_proposal = ActionProposal(
                                action="back", target="",
                                reason="退出登录边界已核验，保留会话并返回继续检测",
                                source=str(decision_source or "unknown"), priority=200,
                            )
                        if root_override_proposal is None and not _is_app_exit_confirmation(
                            frontier_target, page.elements, page_text,
                        ):
                            evidence.append(record_event(
                                ctx, "appium", "root_back_overridden", activity=activity,
                                target=frontier_target,
                                scenario_items=frontier_recommendation["scenario_items"],
                            ))
                            # E.1/E.3: the root frontier override is a pipeline
                            # candidate. Attribution keeps the legacy inherited
                            # decision source (the old rewrite never mutated it),
                            # and priority 200 wins over the base back exactly as
                            # the pre-pipeline rewrite used to.
                            root_override_proposal = ActionProposal(
                                action="click", target=frontier_target,
                                reason=frontier_recommendation["reason"],
                                source=str(decision_source or "unknown"), priority=200,
                            )
                            if _is_authenticated_logout_target(frontier_target, page.elements):
                                evidence.append(record_event(
                                    ctx, "appium", "logout_entry_exploration_allowed", activity=activity,
                                    target=frontier_target,
                                    reason="允许点开退出登录确认框核验；不会点击确认退出",
                                ))
                            _record_decision_override(
                                ctx, evidence, activity=activity, original=llm_proposed,
                                new_decision=root_override_proposal.as_decision(), source="root_back_overridden",
                                reason=str(frontier_recommendation.get("reason") or "")[:300],
                            )
                    else:
                        evidence.append(record_event(
                            ctx, "appium", "root_route_revisit_blocked", activity=activity,
                            target=frontier_target,
                            reason=(
                                "外部条款正文不可用，根页面不再重复打开"
                                if document_blocked else
                                "根页面入口已尝试过，避免返回后重复打开同一路径"
                            ),
                        ))
                if (
                    decision["action"] == "back"
                    and state.is_root_page(page)
                    and root_override_proposal is None
                ):
                    root_fallback = _call_llm_fallback(
                        llm, page.elements, state.targets_visited_on(page),
                        page_role=current_page_semantics.legacy_role,
                        sdk_dwell_pending=sdk_dwell_pending,
                        hub_pending=bool(settings_hub and hub_pending),
                        consent_dialog=current_page_semantics.has_overlay,
                    )
                    root_target = str(root_fallback.get("target") or "")
                    if (
                        ctx.runtime.get("logout_confirmation_observed")
                        and any(term.lower() in root_target.lower() for term in _AUTHENTICATED_LOGOUT_TERMS)
                    ):
                        root_fallback = {"action": "back", "target": "", "reason": "退出登录确认已核验，跳过重复认证边界"}
                        root_target = ""
                    route_key = _root_route_key(activity, root_target)
                    root_route_attempts = ctx.runtime.setdefault("root_route_attempts", {})
                    document_blocked = (
                        _target_is_document_route(root_target)
                        and (
                            root_target in (ctx.runtime.get("blocked_document_targets") or set())
                            or (
                                (_infer_document_kind(root_target, "") or "")
                                in _blocked_document_kinds(ctx)
                            )
                        )
                    )
                    if (
                        ctx.task.mode == "deep"
                        and root_fallback.get("action") == "click"
                        and root_target
                        and not state.target_visited(page, root_target)
                        and _is_safe_deep_probe_target(root_target, page.elements)
                        and not document_blocked
                        and root_route_attempts.get(route_key, 0) < 1
                    ):
                        # E.1/E.3: bounded deep business route stays a candidate;
                        # the old rewrite inherited the decision source.
                        root_override_proposal = ActionProposal(
                            action="click", target=root_target,
                            reason="深度遍历守则：返回根页面前继续核验未访问的安全业务入口",
                            source=str(decision_source or "unknown"), priority=200,
                        )
                        evidence.append(record_event(
                            ctx, "appium", "root_back_overridden", activity=activity,
                            target=root_target, override_kind="bounded_deep_business_route",
                        ))
                    elif (
                        root_fallback.get("action") == "wait"
                        or (settings_hub and hub_pending and not ctx.runtime.get("privacy_hub_search_exhausted"))
                        or current_page_semantics.has_overlay
                        or sdk_dwell_gate
                    ):
                        # P0: do not turn root back into stop when those surfaces still need work.
                        visited_now = state.targets_visited_on(page)
                        progress_target = None
                        if current_page_semantics.has_overlay:
                            progress_target = (
                                _unread_for_page(ctx, page.elements, visited_now)
                                or _catalog_target_for_role(current_page_semantics, "consent")
                                or _explicit_consent_target(page.elements)
                            )
                        elif settings_hub and hub_pending:
                            _observe_logout_rows_without_clicking(ctx, page.elements, evidence, activity)
                            progress_target = _hub_progress_target(ctx, page.elements, visited_now)
                        if progress_target and not state.target_visited(page, progress_target):
                            root_override_proposal = ActionProposal(
                                action="click", target=progress_target,
                                reason="根页仍有待办入口，将 back 改为继续核验",
                                source="deterministic_privacy_hub", priority=200,
                            )
                        elif current_page_semantics.has_overlay or sdk_dwell_gate:
                            # Root waits stay imperative: the downstream
                            # consecutive-wait circuit breaker and the hub-wait
                            # redirects still key on the decision being a wait.
                            decision = {
                                "action": "wait", "target": "",
                                "reason": "根页同意弹窗或 SDK 观察未完成，暂留而非结束遍历",
                            }
                            decision_source = "deterministic_wait_break"
                        elif settings_hub and hub_pending:
                            ctx.runtime["privacy_hub_search_exhausted"] = True
                            next_top = _next_top_level_audit_target(
                                page.elements,
                                set(ctx.runtime.get("visited_top_level_route_keys") or ()),
                            )
                            root_override_proposal = ActionProposal(
                                action="click" if next_top else "stop",
                                target=next_top or "",
                                reason=(
                                    "根页当前分支已完成，按深度优先继续其它顶层分支"
                                    if next_top else "根页所有安全顶层分支均已探索，结束遍历"
                                ),
                                source="deterministic_top_level_dfs" if next_top else "deterministic_privacy_hub",
                                priority=200 if next_top else 150,
                            )
                        else:
                            decision = {
                                "action": "wait", "target": "",
                                "reason": "根页暂留，避免在待办未完成时直接结束",
                            }
                            decision_source = "deterministic_wait_break"
                        effective_override = (
                            root_override_proposal.as_decision()
                            if root_override_proposal is not None else decision
                        )
                        evidence.append(record_event(
                            ctx, "appium", "root_back_overridden", activity=activity,
                            override_kind="pending_surface_wait_or_click",
                            replacement=str(effective_override.get("action") or ""),
                            target=str(effective_override.get("target") or ""),
                        ))
                        _record_decision_override(
                            ctx, evidence, activity=activity, original=llm_proposed,
                            new_decision=effective_override, source="root_back_overridden",
                            reason=str(effective_override.get("reason") or "")[:300],
                        )
                    else:
                        if root_fallback.get("action") == "click" and root_target and (
                            root_route_attempts.get(route_key, 0) >= 1 or document_blocked
                        ):
                            evidence.append(record_event(
                                ctx, "appium", "root_route_revisit_blocked", activity=activity,
                                target=root_target,
                                reason=(
                                    "外部条款正文不可用，根页面不再重复打开"
                                    if document_blocked else
                                    "根页面入口已尝试过，避免返回后重复打开同一路径"
                                ),
                            ))
                        # The legacy stop-handling re-attributed a root llm stop
                        # before the pipeline saw it; carry that outcome on the
                        # candidate. Priority stays below the deep-search
                        # sibling candidate, which the old cascade let override
                        # this stop.
                        stop_source = str(decision_source or "unknown")
                        stop_reason = "已回到首个页面，无未访问入口"
                        if stop_source == "llm":
                            remaining_for_stop = scenario_frontier.snapshot().get("remaining_items") or []
                            stop_reason = (
                                "根页面已无可安全进入的未访问路径，保留未完成场景并结束"
                                if remaining_for_stop else
                                "确定性场景前沿已经完成且当前页无未访问安全入口"
                            )
                            stop_source = (
                                "deterministic_frontier_incomplete" if remaining_for_stop
                                else "deterministic_frontier_exhausted"
                            )
                        root_override_proposal = ActionProposal(
                            action="stop", target="", reason=stop_reason,
                            source=stop_source, priority=150,
                        )
                    replacement_action = (
                        root_override_proposal.action
                        if root_override_proposal is not None
                        else str(decision.get("action") or "")
                    )
                    evidence.append(record_event(ctx, "appium", "loop_prevented", activity=activity,
                                                 reason="back_from_root",
                                                 replacement=replacement_action))
                if (
                    decision["action"] in {"back", "stop"}
                    and current_page_semantics.has_overlay
                    and root_override_proposal is None
                ):
                    consent_gate = _unchecked_consent_checkbox(page.elements)
                    consent_target = (
                        _catalog_target_for_role(current_page_semantics, "consent")
                        or _explicit_consent_target(page.elements)
                    )
                    directive = consent_decisions.force_progress(
                        checkbox_target=consent_gate or "",
                        consent_target=consent_target or "",
                        consent_target_visited=bool(
                            consent_target and state.target_visited(page, consent_target)
                        ),
                        consent_target_blocked=bool(consent_target) and action_effects.is_blocked(
                            _global_target_key(activity, consent_target, page.elements)
                        ),
                    )
                    if directive is not None:
                        def _on_force_progress_selected(effects, consent_target=consent_target):
                            if "forget_consent_target" in effects and consent_target:
                                state.forget_target(page, consent_target)

                        force_proposal = directive_selection.add(
                            directive, on_selected=_on_force_progress_selected,
                        )
                        decision = force_proposal.as_decision()
                        decision_source = directive.source
                        directive_token = force_proposal.token
                llm_back_deferred_proposal = None
                if (
                    root_override_proposal is None
                    and decision["action"] == "back"
                    and decision_source == "llm"
                    and current_page_semantics.role is PageRole.DOCUMENT_BODY
                    and "privacy_policy" not in _read_document_kinds(ctx)
                    and any(term in page_text for term in ("隐私政策", "隐私协议", "privacy policy", "privacy statement"))
                    and int(ctx.runtime.get("document_body_back_deferred", 0)) < 2
                ):
                    ctx.runtime["document_body_back_deferred"] = int(
                        ctx.runtime.get("document_body_back_deferred", 0)
                    ) + 1
                    # E.1/E.3: the document-body back deferral is a pipeline
                    # candidate layered above the LLM proposal, not a rewrite.
                    llm_back_deferred_proposal = ActionProposal(
                        action="wait", target="",
                        reason="隐私政策正文尚未读完，等待继续滚动而不是返回",
                        source="llm", priority=150,
                    )
                    evidence.append(record_event(
                        ctx, "appium", "llm_document_back_deferred", activity=activity,
                        reason="隐私政策正文尚未读完，等待继续滚动而不是返回",
                    ))
                # Root/frontier recovery above may replace an LLM ``back``
                # with a deterministic click.  Run the destructive/session
                # safety gate one final time immediately before execution so
                # that a generated rule target can never bypass it.
                final_document_target = str(decision.get("target") or "")
                final_document_kind = _infer_document_kind(final_document_target, "")
                blocked_reopen_proposal = None
                transaction_proposal = None
                if (
                    decision["action"] == "click"
                    and final_document_target
                    and _target_is_document_route(final_document_target)
                    and (
                        final_document_target in (ctx.runtime.get("blocked_document_targets") or set())
                        or (
                            final_document_kind
                            and final_document_kind in _blocked_document_kinds(ctx)
                        )
                    )
                ):
                    evidence.append(record_event(
                        ctx, "appium", "blocked_document_reopen_prevented",
                        activity=activity, target=final_document_target,
                        document_kind=final_document_kind,
                        reason="最终执行前发现条款入口已失败或已重定向，禁止确定性兜底再次打开",
                    ))
                    # E.1/E.3: blocked-route blocking is a pipeline candidate
                    # layered above the already-read guard (priority 10_000).
                    blocked_reopen_proposal = ActionProposal(
                        action="back", target="",
                        reason="该条款入口已核验失败或指向其它正文，返回继续其它合规路径",
                        source="coverage_recovery", priority=10_001,
                    )
                    decision_source = "coverage_recovery"
                if decision["action"] == "click" and _is_transaction_target(
                    str(decision.get("target") or ""), page.elements
                ):
                    evidence.append(record_event(
                        ctx, "appium", "transaction_action_blocked", activity=activity,
                        target=decision.get("target"),
                        reason="交易/支付/下单入口仅观察，不执行可能产生订单或扣款的操作",
                    ))
                    # E.1/E.3: transaction blocking is a pipeline candidate, not
                    # a pre-decision rewrite; the legacy rewrite survives as the
                    # candidate's action/target/reason/source.
                    transaction_proposal = ActionProposal(
                        action="back", target="",
                        reason="交易入口仅观察，返回继续检查其它合规路径",
                        source="safety_boundary", priority=200,
                    )
                third_party_proposal = None
                exit_proposal = None
                destructive_proposal = None
                logout_proposal = None
                if decision["action"] == "click":
                    final_target = str(decision.get("target") or "")
                    if ctx.runtime.get("skip_third_party_channel_login") and _is_third_party_channel_login_target(final_target, page.elements):
                        evidence.append(record_event(
                            ctx, "appium", "third_party_channel_login_skipped",
                            activity=activity, target=final_target,
                            reason="QQ/微信未安装，不再重复点击第三方登录",
                        ))
                        recovery_target = _privacy_hub_tab_target(page.elements) or _main_content_tab_target(page.elements)
                        if recovery_target and not state.target_visited(page, recovery_target):
                            third_party_proposal = ActionProposal(
                                action="click", target=recovery_target,
                                reason="第三方登录不可用，改走设置/主内容继续检测",
                                source="frontier_recovery", priority=150,
                            )
                        else:
                            third_party_proposal = ActionProposal(
                                action="back", target="",
                                reason="第三方登录不可用，返回寻找其它入口",
                                source="frontier_recovery", priority=150,
                            )
                    elif _is_app_exit_confirmation(final_target, page.elements, page_text):
                        cancel = next(
                            (
                                str(item.get("resource_id") or item.get("text") or "")
                                for item in page.elements
                                if item.get("clickable")
                                and any(
                                    term in " ".join(
                                        str(item.get(key) or "") for key in ("text", "content_desc", "resource_id")
                                    ).lower()
                                    for term in ("取消", "cancel", "btncancel", "btn_cancel")
                                )
                            ),
                            "",
                        )
                        evidence.append(record_event(
                            ctx, "appium", "app_exit_confirmation_blocked",
                            activity=activity, target=final_target,
                            reason="退出应用确认框不会点击确定，避免被送回系统桌面",
                        ))
                        if ctx.runtime.get("app_exit_cancel_done"):
                            recovery_target = _privacy_hub_tab_target(page.elements) or _main_content_tab_target(page.elements)
                            if recovery_target and not state.target_visited(page, recovery_target):
                                exit_proposal = ActionProposal(
                                    action="click", target=recovery_target,
                                    reason="退出确认已取消过一次，改走设置/主内容继续检测",
                                    source="safety_boundary", priority=150,
                                )
                            else:
                                # Wait rewrites stay imperative while the
                                # consecutive-wait breaker keys on the decision.
                                decision = {
                                    "action": "wait", "target": "",
                                    "reason": "退出确认已取消过一次，等待弹窗消失后继续检测",
                                }
                                decision_source = "safety_boundary"
                        elif cancel:
                            ctx.runtime["app_exit_cancel_done"] = True
                            exit_proposal = ActionProposal(
                                action="click", target=cancel,
                                reason="退出应用确认框选择取消，留在应用内继续检测",
                                source="safety_boundary", priority=150,
                            )
                        else:
                            decision = {
                                "action": "wait", "target": "",
                                "reason": "退出应用确认框已拦截，等待弹窗消失后继续检测",
                            }
                            decision_source = "safety_boundary"
                    elif _is_destructive_confirmation(final_target, page.elements):
                        evidence.append(record_event(
                            ctx, "appium", "destructive_confirmation_blocked",
                            activity=activity, target=final_target,
                            reason="自动化只检查流程，不提交注销或删除请求",
                        ))
                        destructive_proposal = ActionProposal(
                            action="back", target="",
                            reason="已到达注销/删除确认页，按无损策略返回",
                            source=str(decision_source or "unknown"), priority=150,
                        )
                    else:
                        final_logout_entry = _is_authenticated_logout_target(final_target, page.elements)
                        final_logout_confirm = logout_confirmation and _is_logout_confirmation_target(
                            final_target, page.elements
                        )
                        if final_logout_confirm:
                            evidence.append(record_event(
                                ctx, "appium", "logout_action_blocked", activity=activity,
                                target=final_target,
                                reason="退出登录确认按钮仅观察，不提交退出",
                            ))
                            logout_proposal = ActionProposal(
                                action="back", target="",
                                reason="已观察退出登录确认边界，保留当前会话并返回继续检测",
                                source=str(decision_source or "unknown"), priority=150,
                            )
                            ctx.runtime["logout_confirmation_observed"] = True
                            ctx.runtime["logout_entry_explored"] = True
                        elif final_logout_entry and ctx.runtime.get("logout_entry_explored"):
                            evidence.append(record_event(
                                ctx, "appium", "logout_action_blocked", activity=activity,
                                target=final_target,
                                reason="退出登录入口已探索过一次，避免重复进入或误提交",
                            ))
                            logout_proposal = ActionProposal(
                                action="back", target="",
                                reason="退出登录边界已核验，保留会话并返回继续检测",
                                source=str(decision_source or "unknown"), priority=150,
                            )
                        elif final_logout_entry:
                            evidence.append(record_event(
                                ctx, "appium", "logout_entry_exploration_allowed", activity=activity,
                                target=final_target,
                                reason="允许点开退出登录确认框核验；不会点击确认退出",
                            ))
                generic_role = current_page_semantics.legacy_role
                generic_target = _next_safe_deep_target(
                    page.elements, state.targets_visited_on(page), ctx=ctx,
                ) if not document_key and not low_value_surface_kind else ""
                # The deep search must evaluate the decision state the legacy
                # cascade produced: the last pending candidate stands in for
                # the rewrite it mirrors, while imperative waits and the raw
                # decision flow through unchanged.
                deep_search_action = str(decision.get("action") or "")
                deep_search_source = str(decision_source or "")
                for pending in (
                    third_party_proposal, exit_proposal, destructive_proposal,
                    logout_proposal, root_override_proposal,
                ):
                    if pending is not None:
                        deep_search_action = pending.action
                        deep_search_source = pending.source
                deep_directive = dfs_navigation.decide(DfsNavigationInput(
                    deep_mode=ctx.task.mode == "deep",
                    current_action=deep_search_action,
                    role=generic_role,
                    decision_source=deep_search_source,
                    sibling_target=generic_target,
                    consent_blocked=_deep_search_consent_blocked(
                        bool(consent_dialog), ctx.runtime.get("consent_dialog_seen"),
                    ),
                    pre_app_entry=_is_pre_app_entry_surface(activity, page.elements, ctx),
                    settings_hub=settings_hub,
                ))
                sibling_proposal = None
                if deep_directive.step is DfsNavigationStep.EXPLORE_SIBLING:
                    original_deep_exit = dict(decision)
                    # E.1/E.3: the deep-search sibling exploration is a pipeline
                    # candidate ranked above the root stop/wait candidates,
                    # matching the legacy cascade where it rewrote their output.
                    sibling_proposal = ActionProposal(
                        action="click", target=deep_directive.target,
                        reason=deep_directive.reason,
                        source="deterministic_deep_search", priority=300,
                    )
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=original_deep_exit,
                        new_decision=sibling_proposal.as_decision(), source="generic_safe_sibling",
                        reason=deep_directive.reason,
                    )
                if (
                    sibling_proposal is None
                    and not document_key
                    and not low_value_surface_kind
                ):
                    scroll_route = f"{activity.lower()}|{generic_role}"
                    attempts = ctx.runtime.setdefault("generic_scroll_attempts", {})
                    exhausted = ctx.runtime.setdefault("generic_scroll_exhausted", set())
                    max_scrolls = max(1, int(ctx.cfg.get("detection", {}).get(
                        "max_generic_page_scrolls", 4,
                    )))
                    scroll_directive = dfs_navigation.decide(DfsNavigationInput(
                        deep_mode=ctx.task.mode == "deep",
                        current_action=deep_search_action,
                        role=generic_role,
                        decision_source=deep_search_source,
                        can_scroll=_generic_page_may_need_swipe(page, page_role=generic_role),
                        scroll_attempts=(
                            max_scrolls if scroll_route in exhausted
                            else int(attempts.get(scroll_route, 0))
                        ),
                        max_scrolls=max_scrolls,
                        consent_blocked=_deep_search_consent_blocked(
                            bool(consent_dialog), ctx.runtime.get("consent_dialog_seen"),
                        ),
                        pre_app_entry=_is_pre_app_entry_surface(activity, page.elements, ctx),
                        settings_hub=settings_hub,
                    ))
                    if scroll_directive.step is DfsNavigationStep.SCROLL:
                        try:
                            moved = bool(self.client.scroll_down())
                        except ExplorationError as exc:
                            moved = False
                            evidence.append(record_event(
                                ctx, "appium", "generic_page_scroll_failed",
                                activity=activity, route=scroll_route, error=str(exc)[:300],
                            ))
                        attempts[scroll_route] = int(attempts.get(scroll_route, 0)) + 1
                        if moved:
                            state.record_action(page, "scroll")
                            evidence.append(record_event(
                                ctx, "appium", "generic_page_scrolled",
                                activity=activity, route=scroll_route,
                                attempt=attempts[scroll_route],
                                reason=scroll_directive.reason,
                            ))
                            continue
                        exhausted.add(scroll_route)
                        evidence.append(record_event(
                            ctx, "appium", "generic_page_scroll_exhausted",
                            activity=activity, route=scroll_route,
                            attempts=attempts[scroll_route],
                            reason="滚动未产生新视口，当前列表已到达底部或不可滚动",
                        ))
                # A sibling candidate stands in for the sibling rewrite that
                # used to convert this wait into a sibling click upstream of
                # the consecutive-wait circuit breaker.
                # E.1/E.3: the consecutive-wait breaker now runs on the
                # effective action (the last pending candidate stands in for
                # the wait the legacy cascade produced), and its rewrites are
                # pipeline candidates ranked above the wait they replace.
                wait_effective_action = deep_search_action
                if sibling_proposal is not None:
                    wait_effective_action = sibling_proposal.action
                wait_breaker_proposal = None
                if wait_effective_action == "wait":
                    fingerprint = str(getattr(page, "surface_fingerprint", "") or activity)
                    last_fp = str(ctx.runtime.get("consecutive_wait_fingerprint") or "")
                    count = int(ctx.runtime.get("consecutive_waits", 0))
                    count = count + 1 if last_fp == fingerprint else 1
                    ctx.runtime["consecutive_wait_fingerprint"] = fingerprint
                    ctx.runtime["consecutive_waits"] = count
                    same_page_wait_limit = max(1, int(ctx.cfg.get("detection", {}).get("same_page_wait_limit", 1)))
                    hub_wait_budget = max(same_page_wait_limit, int(
                        ctx.cfg.get("detection", {}).get("hub_same_page_wait_limit", 4)
                    ))
                    if count > same_page_wait_limit:
                        if _document_wait_should_be_kept(
                            current_page_semantics.role,
                            document_key,
                            state,
                        ):
                            evidence.append(record_event(
                                ctx, "appium", "document_wait_kept", activity=activity,
                                waits=count,
                                reason="条款正文尚未读完，连续等待交给滚动而不是返回",
                            ))
                        elif settings_hub and hub_pending:
                            if _scroll_hub_for_privacy_path(
                                self.client, ctx, state, page, activity, evidence,
                                "设置枢纽连续等待后滚动寻找注销/授权",
                            ):
                                continue
                            next_row = _hub_progress_target(
                                ctx, page.elements, state.targets_visited_on(page),
                            )
                            if next_row:
                                evidence.append(record_event(
                                    ctx, "appium", "hub_wait_redirected", activity=activity,
                                    waits=count, target=next_row,
                                    reason="设置枢纽连续等待无新入口，改点其它未访问行而不是返回",
                                ))
                                wait_breaker_proposal = ActionProposal(
                                    action="click", target=next_row,
                                    reason="设置枢纽暂留后改点其它未访问隐私相关行",
                                    source="deterministic_privacy_hub", priority=160,
                                )
                                _record_decision_override(
                                    ctx, evidence, activity=activity, original=llm_proposed,
                                    new_decision=wait_breaker_proposal.as_decision(), source="hub_wait_redirected",
                                    reason="设置枢纽暂留后改点其它未访问隐私相关行",
                                )
                            elif count <= hub_wait_budget:
                                evidence.append(record_event(
                                    ctx, "appium", "hub_wait_kept", activity=activity,
                                    waits=count, budget=hub_wait_budget,
                                    reason="拦截通知设置或枢纽探查中的等待，不因此退出设置页",
                                ))
                            else:
                                ctx.runtime["privacy_hub_search_exhausted"] = True
                                evidence.append(record_event(
                                    ctx, "appium", "hub_wait_exhausted", activity=activity,
                                    waits=count,
                                    reason="设置枢纽多次等待仍无注销/授权入口，离开当前页避免死循环",
                                ))
                                wait_breaker_proposal = ActionProposal(
                                    action="back" if not state.is_root_page(page) else "stop",
                                    target="",
                                    reason="设置枢纽搜索无进展，返回继续其它合规路径",
                                    source="deterministic_wait_break", priority=160,
                                )
                                _record_decision_override(
                                    ctx, evidence, activity=activity, original=llm_proposed,
                                    new_decision=wait_breaker_proposal.as_decision(), source="hub_wait_exhausted",
                                    reason="设置枢纽搜索无进展，返回继续其它合规路径",
                                )
                        else:
                            redirected = _redirect_after_ignored_app_icon(
                                ctx, state, page,
                                consent_accepted=bool(ctx.runtime.get("consent_accepted")),
                                settings_hub=settings_hub,
                                hub_pending=hub_pending,
                            )
                            if redirected.get("source") in {
                                "deterministic_document", "deterministic_privacy_hub", "home_idle_exhausted",
                            }:
                                wait_breaker_proposal = ActionProposal(
                                    action=str(redirected["action"]),
                                    target=str(redirected.get("target") or ""),
                                    reason=str(redirected["reason"]),
                                    source=str(redirected["source"]), priority=160,
                                )
                                evidence.append(record_event(
                                    ctx, "appium", "wait_loop_home_redirected", activity=activity,
                                    waits=count, target=wait_breaker_proposal.target,
                                    reason=redirected["reason"],
                                ))
                                _record_decision_override(
                                    ctx, evidence, activity=activity, original=llm_proposed,
                                    new_decision=wait_breaker_proposal.as_decision(), source="wait_loop_home_redirected",
                                    reason=redirected["reason"],
                                )
                            else:
                                evidence.append(record_event(
                                    ctx, "appium", "wait_loop_broken", activity=activity,
                                    waits=count, original_reason=str(decision.get("reason") or "")[:300],
                                    reason="同一页面连续等待不会让已加载条款变成可点击控件，改为返回继续检测",
                                ))
                                wait_breaker_proposal = ActionProposal(
                                    action="back", target="",
                                    reason="同一页面连续等待无进展，返回应用继续检测",
                                    source="deterministic_wait_break", priority=160,
                                )
                                _record_decision_override(
                                    ctx, evidence, activity=activity, original=llm_proposed,
                                    new_decision=wait_breaker_proposal.as_decision(), source="wait_loop_broken",
                                    reason="同一页面连续等待无进展，返回应用继续检测",
                                )
                else:
                    ctx.runtime["consecutive_waits"] = 0
                    ctx.runtime["consecutive_wait_fingerprint"] = ""
                # A sibling candidate stands in for the sibling rewrite that
                # used to pre-empt this stop re-attribution.
                if sibling_proposal is None and decision.get("action") == "stop" and decision_source == "llm":
                    remaining_for_stop = scenario_frontier.snapshot().get("remaining_items") or []
                    original_stop = dict(decision)
                    if remaining_for_stop and not state.is_root_page(page):
                        decision = {
                            "action": "back", "target": "",
                            "reason": "当前分支无更多安全入口，返回父页面继续未完成场景的深度搜索",
                        }
                        decision_source = "deterministic_deep_search"
                    else:
                        decision = {
                            "action": "stop", "target": "",
                            "reason": (
                                "根页面已无可安全进入的未访问路径，保留未完成场景并结束"
                                if remaining_for_stop else
                                "确定性场景前沿已经完成且当前页无未访问安全入口"
                            ),
                        }
                        decision_source = (
                            "deterministic_frontier_incomplete"
                            if remaining_for_stop else "deterministic_frontier_exhausted"
                        )
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=original_stop,
                        new_decision=decision, source=decision_source,
                        reason=decision["reason"],
                        remaining_items=list(remaining_for_stop),
                    )
                # Generic deep-search and late safety rewrites run after the
                # earlier document guard. Revalidate here so a completed route
                # cannot be reopened through a different decision layer.
                late_document_target = str(decision.get("target") or "")
                arbitration_proposals = []
                # The late already-read guard must adjudicate the pending click
                # candidates too: a root-override or sibling candidate stands in
                # for the click the legacy cascade fed through this guard, and
                # its 10_000 proposal out-ranks the click it vetoes.
                late_click_candidates = []
                if (
                    decision.get("action") == "click"
                    and logout_observation_proposal is None
                    and late_document_target
                    and already_read_hub_proposal is None
                ):
                    late_click_candidates.append(late_document_target)
                for pending_candidate in (
                    third_party_proposal, exit_proposal, destructive_proposal,
                    logout_proposal, media_assist_proposal,
                    customer_service_exhausted_proposal, combined_document_proposal,
                    already_read_hub_proposal, already_read_consent_proposal,
                    logout_observation_proposal,
                    deny_session_boundary_proposal,
                    destructive_confirmation_proposal, logout_confirmation_proposal,
                    repeated_logout_proposal,
                    root_override_proposal,
                    sibling_proposal, wait_breaker_proposal,
                ):
                    if (
                        pending_candidate is not None
                        and pending_candidate.action == "click"
                        and pending_candidate.target
                    ):
                        late_click_candidates.append(pending_candidate.target)
                if blocked_reopen_proposal is None:
                    for guarded_target in dict.fromkeys(late_click_candidates):
                        if not _already_read_document_target(ctx, guarded_target, page.elements):
                            continue
                        evidence.append(record_event(
                            ctx, "appium", "blocked_document_reopen_prevented",
                            activity=activity, target=guarded_target,
                            document_kind=_infer_document_kind(
                                guarded_target,
                                _labels_for_click_target(guarded_target, page.elements),
                            ),
                            reason="该条款路线已完成或已按实际正文记账，禁止后置深搜再次打开",
                        ))
                        state.mark_target(page, guarded_target)
                        # E.1/E.3: the late already-read guard is a pipeline candidate
                        # with its own source and priority, not a mutation of the
                        # base decision.
                        arbitration_proposals.append(ActionProposal(
                            action="stop" if state.is_root_page(page) else "back",
                            target="",
                            reason="已完成条款路线不再重复打开，继续其它未覆盖路径",
                            source="already_read_document",
                            priority=10_000,
                        ))
                        if guarded_target == late_document_target and decision.get("action") == "click":
                            decision_source = "already_read_document"
                arbitration_proposals.append(ActionProposal(
                    action=str(decision.get("action") or "wait"),
                    target=str(decision.get("target") or ""),
                    reason=str(decision.get("reason") or ""),
                    source=str(decision_source or "unknown"),
                    priority=100,
                    token=str(directive_token or ""),
                ))
                if llm_back_deferred_proposal is not None:
                    arbitration_proposals.append(llm_back_deferred_proposal)
                if blocked_reopen_proposal is not None:
                    arbitration_proposals.append(blocked_reopen_proposal)
                if transaction_proposal is not None:
                    arbitration_proposals.append(transaction_proposal)
                if third_party_proposal is not None:
                    arbitration_proposals.append(third_party_proposal)
                if exit_proposal is not None:
                    arbitration_proposals.append(exit_proposal)
                if destructive_proposal is not None:
                    arbitration_proposals.append(destructive_proposal)
                if logout_proposal is not None:
                    arbitration_proposals.append(logout_proposal)
                if media_assist_proposal is not None:
                    arbitration_proposals.append(media_assist_proposal)
                if customer_service_exhausted_proposal is not None:
                    arbitration_proposals.append(customer_service_exhausted_proposal)
                if combined_document_proposal is not None:
                    arbitration_proposals.append(combined_document_proposal)
                if already_read_hub_proposal is not None:
                    arbitration_proposals.append(already_read_hub_proposal)
                if already_read_consent_proposal is not None:
                    arbitration_proposals.append(already_read_consent_proposal)
                if logout_observation_proposal is not None:
                    arbitration_proposals.append(logout_observation_proposal)
                if deny_session_boundary_proposal is not None:
                    arbitration_proposals.append(deny_session_boundary_proposal)
                if destructive_confirmation_proposal is not None:
                    arbitration_proposals.append(destructive_confirmation_proposal)
                if logout_confirmation_proposal is not None:
                    arbitration_proposals.append(logout_confirmation_proposal)
                if repeated_logout_proposal is not None:
                    arbitration_proposals.append(repeated_logout_proposal)
                if root_override_proposal is not None:
                    arbitration_proposals.append(root_override_proposal)
                if sibling_proposal is not None:
                    arbitration_proposals.append(sibling_proposal)
                if wait_breaker_proposal is not None:
                    arbitration_proposals.append(wait_breaker_proposal)
                pre_safety_decision = dict(decision)
                if llm_proposed and (
                    llm_proposed.get("action") != decision.get("action")
                    or str(llm_proposed.get("target") or "") != str(decision.get("target") or "")
                ):
                    arbitration_proposals.append(ActionProposal.from_decision(
                        llm_proposed, source=str(proposal_source or "llm"), priority=10,
                    ))
                def target_safety_validator(proposal: ActionProposal) -> ActionProposal | None:
                    safe_decision, reason = _enforce_final_action_safety(
                        proposal.as_decision(),
                        activity=activity,
                        elements=page.elements,
                        low_value_surface_kind=low_value_surface_kind,
                        audited_package=str(getattr(ctx.apk, "package_name", "") or ""),
                        audited_app_name=str(getattr(ctx.apk, "app_name", "") or ""),
                        foreground_package=str(getattr(self.client, "last_package", "") or ""),
                        is_root=state.is_root_page(page),
                    )
                    if not reason:
                        return None
                    return ActionProposal.from_decision(
                        safe_decision, source="safety_boundary", priority=10_000,
                    )

                final_action = action_pipeline.choose(
                    arbitration_proposals,
                    semantics=current_page_semantics,
                    is_root=state.is_root_page(page),
                    safety_validator=target_safety_validator,
                )
                # The global revisit veto runs after arbitration so it gates the
                # click that will actually execute; the proposal-is-None gates
                # keep the legacy skip semantics while those guard sites are
                # being converted into pipeline candidates. External-exit,
                # launcher and low-value winners are already back/wait by the
                # arbiter, so a veto replacement here never bypasses safety.
                if (
                    final_action.action == "click"
                    and blocked_reopen_proposal is None
                    and transaction_proposal is None
                ):
                    global_target = str(final_action.target or "")
                    skip_global = (
                        final_action.source in {"safety_boundary", "deterministic_consent"}
                        or _click_reopens_incomplete_document(ctx, global_target)
                    )
                    if global_target and not global_target.startswith("relative:") and not skip_global:
                        global_key = _global_target_key(activity, global_target, page.elements)
                        global_attempts = ctx.runtime.setdefault("global_target_attempts", {})
                        global_count = int(global_attempts.get(global_key, 0))
                        global_limit = 2 if _is_required_exploration_target(
                            global_target, page.elements,
                        ) else 1
                        if (
                            _target_is_hub_reentry(global_target, page.elements)
                            and _hub_scenarios_outstanding(scenario_frontier)
                        ):
                            global_limit = 3
                        if global_count >= global_limit:
                            evidence.append(record_event(
                                ctx, "appium", "global_target_revisit_blocked",
                                activity=activity, target=global_target,
                                attempts=global_count, max_attempts=global_limit,
                                reason="同一语义入口跨页面重复出现，改走其它安全路径而不是无意义循环",
                            ))
                            logged_out_now = _logged_out_profile_visible(
                                page.elements,
                                extra_text=str(ctx.runtime.get("last_screen_text") or ""),
                            )
                            login_now = _profile_login_entry(
                                page.elements,
                                extra_text=str(ctx.runtime.get("last_screen_text") or ""),
                            )
                            if (
                                _target_is_hub_reentry(global_target, page.elements)
                                and _hub_scenarios_outstanding(scenario_frontier)
                                and logged_out_now
                                and login_now
                                and not ctx.runtime.get("manual_login_verified")
                                and not state.target_visited(page, login_now)
                            ):
                                final_action = replace(
                                    final_action,
                                    action="click", target=login_now,
                                    reason="设置入口已重复尝试且页面未登录，改走登录后再核验注销",
                                    source="deterministic_login_entry",
                                )
                            elif (
                                settings_hub
                                and _hub_scenarios_outstanding(scenario_frontier)
                                and _scroll_hub_for_privacy_path(
                                    self.client, ctx, state, page, activity, evidence,
                                    "跨页入口已重复，改在设置页内滚动寻找注销/授权",
                                )
                            ):
                                continue
                            elif (
                                settings_hub
                                and (next_row := _next_hub_exploration_target(
                                    page.elements, state.targets_visited_on(page),
                                ))
                            ):
                                final_action = replace(
                                    final_action,
                                    action="click", target=next_row,
                                    reason="跨页入口已重复，改点设置页其他未访问行",
                                    source="deterministic_privacy_hub",
                                )
                            elif settings_hub and _hub_scenarios_outstanding(scenario_frontier):
                                # Stay on the hub: do not convert a privacy search into back.
                                if int(ctx.runtime.get("hub_privacy_scrolls", 0)) >= 6:
                                    ctx.runtime["privacy_hub_search_exhausted"] = True
                                final_action = replace(
                                    final_action,
                                    action="wait", target="",
                                    reason="同一入口已重复，暂留设置页继续寻找注销/授权，不因此返回",
                                    source="deterministic_privacy_hub",
                                )
                            else:
                                if (
                                    _target_is_hub_reentry(global_target, page.elements)
                                    and int(ctx.runtime.get("hub_privacy_scrolls", 0)) >= 6
                                ):
                                    ctx.runtime["privacy_hub_search_exhausted"] = True
                                main_tab = _main_content_tab_target(page.elements)
                                if main_tab and not state.target_visited(page, main_tab):
                                    final_action = replace(
                                        final_action,
                                        action="click", target=main_tab,
                                        reason="同一入口已反复尝试，改走主内容路径避免无进展循环",
                                        source="frontier_recovery",
                                    )
                                elif (
                                    final_action.source == "llm"
                                    and (
                                        _target_is_hub_reentry(global_target, page.elements)
                                        or _click_matches_privacy_path(global_target, page.elements, "delete")
                                        or _click_matches_privacy_path(global_target, page.elements, "withdraw")
                                    )
                                ):
                                    final_action = replace(
                                        final_action,
                                        action="wait", target="",
                                        reason="隐私相关安全点击已达跨页上限，暂留观察而不是改成返回",
                                        source="frontier_recovery",
                                    )
                                else:
                                    final_action = replace(
                                        final_action,
                                        action="back", target="",
                                        reason="同一语义入口已跨页面重复尝试，停止循环并返回其它路径",
                                        source="frontier_recovery",
                                    )
                        else:
                            # The attempt is committed only after perform()
                            # succeeds; transient locator failures must remain
                            # eligible for a bounded retry.
                            pass
                # Exactly the pipeline-selected directive commits its legacy
                # pre-execute side effects; replaced candidates leave nothing.
                directive_selection.commit(final_action, activity=activity)
                if (
                    final_action.action != pre_safety_decision.get("action")
                    or final_action.target != str(pre_safety_decision.get("target") or "")
                    or final_action.source != str(decision_source or "unknown")
                ):
                    decision = final_action.as_decision()
                    decision_source = final_action.source
                    evidence.append(record_event(
                        ctx, "appium", "action_arbitrated",
                        activity=activity,
                        page_role=current_page_semantics.legacy_role,
                        original_action=pre_safety_decision.get("action"),
                        original_target=pre_safety_decision.get("target"),
                        replacement_action=decision.get("action"),
                        replacement_target=decision.get("target"),
                        proposal_count=len(arbitration_proposals),
                        rejected_sources=[item.source for item in final_action.rejected],
                        duplicate_sources=list(final_action.duplicate_sources),
                        reason=final_action.safety_reason,
                    ))
                else:
                    decision = final_action.as_decision()
                    decision_source = final_action.source
                if final_action.safety_reason:
                    evidence.append(record_event(
                        ctx, "appium", "final_action_safety_blocked",
                        activity=activity,
                        original_action=pre_safety_decision.get("action"),
                        original_target=pre_safety_decision.get("target"),
                        replacement_action=decision.get("action"),
                        reason=final_action.safety_reason,
                    ))
                    _record_decision_override(
                        ctx, evidence, activity=activity, original=pre_safety_decision,
                        new_decision=decision, source="final_action_safety",
                        reason=final_action.safety_reason,
                    )
                audit = DecisionAudit.finalize(
                    activity=activity,
                    decision=decision,
                    decision_source=str(decision_source or "unknown"),
                    proposed=llm_proposed,
                    proposal_source=proposal_source,
                    context={
                        "page_role": current_page_semantics.legacy_role,
                        "surface_id": page.surface_fingerprint,
                        "execution_layer": (
                            "overlay" if current_page_semantics.has_overlay else "page"
                        ),
                    },
                )
                decision_source = audit.source
                # 唯一的最终决策出口：按真实生效来源归账，fallback 占比由此可见。
                llm_effectiveness.record_final_decision(source=str(decision_source))
                record = audit.record
                replay_writer.write({
                    "type": "page",
                    "facts": replay_facts_for_semantics(current_page_semantics),
                    "resolved_page": replay_semantics_for_resolved(current_page_semantics),
                    "is_root": state.is_root_page(page),
                    "proposals": [{
                        "action": item.action, "target": item.target,
                        "reason": item.reason, "source": item.source,
                        "priority": item.priority,
                        "scenario_items": list(item.scenario_items),
                    } for item in arbitration_proposals],
                })
                if llm_proposed:
                    if audit.proposal_changed:
                        # Catch-all for override sites that did not call the helper explicitly.
                        recent = evidence[-12:] if evidence else []
                        already = any(
                            isinstance(row, dict)
                            and (row.get("meta") or {}).get("event_type") == "llm_decision_overridden"
                            and (row.get("meta") or {}).get("original_action") == llm_proposed.get("action")
                            and str((row.get("meta") or {}).get("original_target") or "")
                            == str(llm_proposed.get("target") or "")
                            and (row.get("meta") or {}).get("new_action") == decision.get("action")
                            and str((row.get("meta") or {}).get("new_target") or "")
                            == str(decision.get("target") or "")
                            for row in recent
                        )
                        if not already:
                            _record_decision_override(
                                ctx, evidence, activity=activity, original=llm_proposed,
                                new_decision=decision, source=str(decision_source or "override"),
                                reason=str(decision.get("reason") or "")[:300],
                            )
                evidence.append(record_event(
                    ctx,
                    "appium" if decision_source != "llm" else "llm",
                    "decision", **record,
                ))
                if decision["action"] == "stop":
                    remaining_items = scenario_frontier.snapshot().get("remaining_items") or []
                    termination = {
                        "kind": "frontier_incomplete" if remaining_items else "safe_frontier_exhausted",
                        "reason": str(decision.get("reason") or "当前页面没有可安全继续访问的未覆盖入口"),
                        "remaining_items": list(remaining_items),
                    }
                    break
                if decision["action"] == "click":
                    # Consent-dialog 《隐私政策》 taps are provisional: a miss-tap
                    # must not permanently consume the unread slot.
                    provisional_document = (
                        decision_source == "deterministic_document"
                        and _is_overlay_catalog_target(
                            current_page_semantics,
                            str(decision.get("target") or ""),
                            "document",
                        )
                    )
                    state.schedule_target(page, decision["target"])
                    action_scenarios = _scenario_items_for_action(
                        decision["target"], page.elements,
                    )
                    if frontier_recommendation and decision["target"] == frontier_recommendation["target"]:
                        action_scenarios.update(
                            str(item) for item in frontier_recommendation["scenario_items"]
                        )
                    if action_scenarios:
                        scenario_frontier.mark_attempted(
                            decision["target"], sorted(action_scenarios),
                        )
                        evidence.append(record_event(
                            ctx, "appium", "scenario_target_attempted", activity=activity,
                            target=decision["target"], scenario_items=sorted(action_scenarios),
                            decision_source=decision_source,
                        ))
                action_token = performance_budget.begin("appium_action")
                try:
                    execution = action_executor.execute_and_record(
                        final_action,
                        page=page,
                        state=state,
                        commit_target=(decision["action"] == "click" and not provisional_document),
                    )
                    performance_budget.finish(action_token)
                    if not execution.succeeded:
                        raise ExplorationError(execution.error)
                    # This counter is a consecutive-failure circuit breaker.
                    # A successful action proves the driver is responsive and
                    # must clear it; otherwise unrelated failures accumulate
                    # across the whole audit and terminate a healthy traversal.
                    interaction_failures = 0
                    record_action(ctx)
                    target_text = str(decision.get("target") or "")
                    if decision.get("action") == "click" and target_text:
                        if not target_text.startswith("relative:") and decision_source not in {
                            "safety_boundary", "deterministic_consent",
                        } and not _click_reopens_incomplete_document(ctx, target_text):
                            surface_budget.record_global_target_attempt(
                                _global_target_key(activity, target_text, page.elements),
                            )
                        if state.is_root_page(page):
                            surface_budget.record_root_route_attempt(
                                _root_route_key(activity, target_text),
                            )
                        hub_target = _privacy_hub_tab_target(page.elements)
                        if hub_target and target_text == hub_target:
                            ctx.runtime.setdefault("visited_privacy_hub_tabs", set()).add(target_text)
                        if _is_top_level_navigation_target(target_text, page.elements) or any(
                            target_text in {
                                str(item.get("target") or ""), str(item.get("resource_id") or ""),
                                str(item.get("text") or ""), str(item.get("content_desc") or ""),
                            }
                            and (
                                any(token in str(item.get("resource_id") or "").lower() for token in (
                                    "tab_", "rb_", "navi_", "bottom_nav", "bottomnav", "main_tab", "ll_tab",
                                ))
                                or _is_bottom_nav_hub_tab(item, page.elements)
                            )
                            for item in page.elements
                        ):
                            ctx.runtime.setdefault("visited_top_level_route_keys", set()).add(
                                _global_target_key("", target_text, page.elements)
                            )
                        if _is_authenticated_logout_target(target_text, page.elements):
                            ctx.runtime["logout_entry_explored"] = True
                        for path_kind in ("delete", "withdraw", "complaint"):
                            if _click_matches_privacy_path(target_text, page.elements, path_kind):
                                ctx.runtime.setdefault("privacy_path_route_keys", set()).add(
                                    _global_target_key("", target_text, page.elements),
                                )
                                break
                        if _click_matches_privacy_path(target_text, page.elements, "complaint"):
                            ctx.runtime.setdefault("redress_entry_route_keys", set()).add(
                                _global_target_key(activity, target_text, page.elements),
                            )
                            evidence.append(record_event(
                                ctx, "appium", "redress_entry_explored", activity=activity,
                                target=target_text,
                                route_kind="complaint_feedback_support_ticket_or_customer_service",
                            ))
                        if _click_matches_privacy_path(target_text, page.elements, "delete"):
                            scenario_frontier.mark_completed(["6.1"], evidence_source="delete_entry_found")
                            evidence.append(record_event(
                                ctx, "appium", "privacy_path_verified", activity=activity,
                                path_kind="delete", target=target_text,
                                evidence_source="delete_entry_found",
                            ))
                        elif _click_matches_privacy_path(target_text, page.elements, "withdraw"):
                            transition = scenario_controller.observe(
                                "withdraw_entry_observed", item="3.8", target=target_text,
                                source="withdraw_entry_found",
                            )
                            if transition.accepted:
                                scenario_frontier.mark_completed(["3.8"], evidence_source="withdraw_entry_found")
                                evidence.append(record_event(
                                    ctx, "appium", "privacy_path_verified", activity=activity,
                                    path_kind="withdraw", target=target_text,
                                    evidence_source="withdraw_entry_found",
                                ))
                    if decision_source == "deterministic_sdk_observe" and decision.get("action") == "click":
                        # Dwell happens next loop on main content; avoid observe-while-clicking.
                        ctx.runtime["sdk_observation_dwell_armed"] = True
                    if (
                        decision.get("action") == "click"
                        and decision_source == "deterministic_document"
                        and _is_overlay_catalog_target(
                            current_page_semantics,
                            str(decision.get("target") or ""),
                            "document",
                        )
                    ):
                        # Verify the short-title tap actually left the dialog /
                        # opened a Custom Tab.  ClickableSpan often needs a short
                        # settle window; poll instead of a single snapshot.
                        opened = False
                        verify_activity = activity
                        verify_page = page
                        poll_rounds = max(3, int(float(ctx.cfg.get("detection", {}).get(
                            "inline_document_open_polls", 6,
                        ))))
                        poll_wait = max(0.25, float(ctx.cfg.get("detection", {}).get(
                            "inline_document_open_poll_seconds", 0.5,
                        )))
                        for _round in range(poll_rounds):
                            time.sleep(poll_wait)
                            try:
                                verify_activity, verify_xml = self.client.page()
                                verify_page = parse_page(verify_activity, verify_xml)
                            except ExplorationError:
                                continue
                            opened = _inline_document_open_succeeded(
                                activity, verify_activity, verify_page.elements
                            )
                            if opened:
                                break
                        if opened:
                            state.commit_target(page, target_text)
                            evidence.append(record_event(
                                ctx, "appium", "inline_document_opened", activity=activity,
                                target=target_text, next_activity=verify_activity,
                                document_kind=_required_document_kind(
                                    _catalog_label_for_target(current_page_semantics, target_text)
                                    or target_text,
                                ),
                            ))
                        else:
                            state.fail_target(page, target_text, transient=True)
                            kind = _note_failed_inline_document(
                                ctx,
                                _catalog_label_for_target(current_page_semantics, target_text)
                                or target_text,
                            )
                            attempts = int((ctx.runtime.get("inline_document_open_attempts") or {}).get(kind or "", 0))
                            if attempts >= 2:
                                state.mark_target(page, target_text)
                            ctx.runtime["last_appium_action"] = {
                                "action": decision["action"], "target": target_text,
                                "declined_privacy": False, "is_business_action": False,
                            }
                            evidence.append(record_event(ctx, "appium", "action_completed", activity=activity, **decision))
                            evidence.append(record_event(
                                ctx, "appium", "inline_document_open_failed", activity=activity,
                                target=target_text, next_activity=verify_activity,
                                document_kind=kind,
                                attempt=attempts,
                                reason="点击书名号后仍停留在同意弹窗，未打开可读正文",
                            ))
                            # Stay on this page for an immediate retry with a
                            # fresh multipoint probe before ticking the checkbox.
                            continue
                    declined_privacy = decision["action"] == "click" and (
                        _is_overlay_catalog_target(
                            current_page_semantics, target_text, "decline",
                        )
                        or _is_privacy_dialog_decline(target_text, page_text, page.elements)
                    )
                    is_business_action = decision["action"] == "click" and _is_business_trigger_action(
                        target_text, page.elements, str(decision.get("reason") or ""),
                    )
                    permission_observation = permission_decisions.observe_action_result(
                        execution,
                        rationale_source=decision_source == "deterministic_permission_rationale",
                        media_source=decision_source in {
                            "deterministic_media_capture", "deterministic_media_album",
                        },
                        business_action=is_business_action,
                        business_target=target_text,
                        activity=activity,
                        sequence=int(ctx.runtime.get("business_action_sequence") or 0) + 1,
                    )
                    ctx.runtime["last_appium_action"] = {
                        "action": decision["action"], "target": target_text,
                        "declined_privacy": declined_privacy,
                        "is_business_action": is_business_action,
                    }
                    if permission_observation.business_trigger_record:
                        ctx.runtime["business_action_sequence"] = int(
                            permission_observation.business_trigger_record["sequence"]
                        )
                        ctx.runtime["last_business_trigger_action"] = dict(
                            permission_observation.business_trigger_record,
                        )
                    if (
                        decision["action"] == "click"
                        and customer_service_surface
                        and target_text in _iter_customer_service_media_targets(
                            activity, page.elements, page_text,
                        )
                    ):
                        ctx.runtime["pending_deep_probe"] = {
                            "surface": page.surface_fingerprint,
                            "activity": activity,
                            "target": target_text,
                        }
                    consent_accept_action = decision["action"] == "click" and (
                        _is_overlay_catalog_target(
                            current_page_semantics, target_text, "consent",
                        )
                        or _is_privacy_dialog_decision(target_text, page_text, page.elements)
                    ) and not declined_privacy
                    consent_observation = consent_decisions.observe_action_result(
                        execution,
                        consent_action=bool(consent_accept_action),
                        declined_privacy=bool(declined_privacy),
                    )
                    if consent_observation.accept_attempted:
                        evidence.append(record_event(
                            ctx, "appium", "privacy_consent_action_attempted", activity=activity, target=target_text,
                            recognition="privacy_page_context_and_button_id",
                        ))
                    elif decision["action"] == "click" and ctx.runtime.get("consent_timestamp_ms"):
                        if is_business_action:
                            business_actions_after_consent += 1
                        elif _is_onboarding_transition(target_text, page.elements, str(decision.get("reason") or "")):
                            evidence.append(record_event(
                                ctx, "appium", "post_consent_onboarding_transition",
                                activity=activity, target=target_text,
                                note="引导跳转不计为业务功能触发",
                            ))
                    if (
                        decision["action"] == "click"
                        and target_text
                        and (
                            decision_source not in {"deterministic_document", "safety_boundary"}
                            or current_page_semantics.has_overlay
                        )
                    ):
                        action_effects.schedule(
                            surface=page.surface_fingerprint,
                            activity=activity,
                            target=target_text,
                            global_key=_global_target_key(
                                activity, target_text, page.elements,
                            ),
                            is_business_action=is_business_action,
                            coordinate_retry=(
                                decision_source == "deterministic_business_retry"
                                or target_text.startswith("bounds:")
                            ),
                            execution_layer=(
                                "overlay" if current_page_semantics.has_overlay else "page"
                            ),
                            page_role=current_page_semantics.legacy_role,
                            consent_action=consent_observation.accept_attempted,
                        )
                    evidence.append(record_event(ctx, "appium", "action_completed", activity=activity, **decision))
                except ExplorationError as exc:
                    performance_budget.finish(action_token)
                    evidence.append(record_event(ctx, "appium", "action_failed", activity=activity, error=str(exc)[:300], **decision))
                    failed_target = str(decision.get("target") or "")
                    if decision.get("action") == "click" and failed_target:
                        state.fail_target(page, failed_target, transient=True)
                    if (
                        decision_source == "deterministic_document"
                        and _is_overlay_catalog_target(
                            current_page_semantics, failed_target, "document",
                        )
                    ):
                        kind = _note_failed_inline_document(
                            ctx,
                            _catalog_label_for_target(current_page_semantics, failed_target)
                            or failed_target,
                        )
                        attempts = int((ctx.runtime.get("inline_document_open_attempts") or {}).get(kind or "", 0))
                        if attempts >= 2:
                            state.mark_target(page, failed_target)
                        evidence.append(record_event(
                            ctx, "appium", "inline_document_open_failed", activity=activity,
                            target=failed_target, document_kind=kind, attempt=attempts,
                            reason="书名号点击定位失败，未打开可读正文", error=str(exc)[:200],
                        ))
                        continue
                    if (
                        decision.get("action") == "click"
                        and failed_target
                        and _target_is_document_route(failed_target)
                        and not _click_failed_due_to_missing_element(str(exc))
                    ):
                        # The tap itself may fail when UiAutomator2 dies just
                        # before the Custom Tab is created.  Preserve the
                        # intended route even though last_appium_action is
                        # updated only after a successful perform call.
                        ctx.runtime["external_document_interrupted_target"] = failed_target
                        evidence.append(record_event(
                            ctx, "appium", "external_document_interrupted",
                            activity=activity, target=failed_target,
                            reason="条款入口点击阶段 UiAutomator2 会话丢失，保留一次恢复后重试",
                        ))
                    # 页面可能在模型决策返回前发生跳转或渲染变化。此类单次定位失败
                    # 不是检测失败：保留时间线并转向下一轮页面采集；连续失败才停止遍历。
                    interaction_failures += 1
                    ctx.runtime.setdefault("interaction_failures", []).append(str(exc)[:300])
                    if (
                        decision.get("action") == "click"
                        and failed_target
                        and not _target_is_document_route(failed_target)
                    ):
                        failure_key = _global_target_key(activity, failed_target, page.elements)
                        target_failures = ctx.runtime.setdefault("target_interaction_failures", {})
                        target_failure_count = int(target_failures.get(failure_key, 0)) + 1
                        target_failures[failure_key] = target_failure_count
                        if target_failure_count >= 2:
                            state.mark_target(page, failed_target)
                            surface_budget.raise_global_target_floor(failure_key, minimum=2)
                            evidence.append(record_event(
                                ctx, "appium", "target_interaction_retry_exhausted",
                                activity=activity, target=failed_target,
                                attempts=target_failure_count,
                                reason="同一控件连续定位/点击失败，标记该语义入口并继续探索同级其它目标",
                            ))
                    if interaction_failures >= 5:
                        termination = {"kind": "interaction_retry_exhausted", "reason": "连续页面操作失败达到安全阈值，已停止重复动作"}
                        break
                    continue
                if not permission_prompt:
                    prior_app_page_text = page_text
                    prior_app_screenshot = page_screenshot
                if not is_new:
                    if current_page_semantics.has_overlay:
                        evidence.append(record_event(
                            ctx, "appium", "same_surface_continued", activity=activity,
                            action=decision["action"],
                            reason="仍在首次同意弹窗，继续处理未读条款或勾选，不是改道跳过",
                        ))
                    elif decision_source == "deterministic_document":
                        evidence.append(record_event(
                            ctx, "appium", "same_surface_continued", activity=activity,
                            action=decision["action"],
                            reason="条款入口点击后页面指纹未变，继续核验是否真正打开正文",
                        ))
                    else:
                        evidence.append(record_event(
                            ctx, "appium", "duplicate_page_handled", activity=activity,
                            action=decision["action"],
                            reason="再次观察到已访问过的页面指纹，继续处理未访问目标，不是跳过关键步骤",
                        ))
            ctx.runtime["seen_text"] = seen_text
            ctx.runtime["pages_covered"] = len(state.covered_pages)
            if termination is None:
                if last_step >= int(limits["max_pages"]):
                    termination = {"kind": "page_limit_reached", "reason": "已达到本次模式的页面安全上限"}
                else:
                    termination = {"kind": "safe_frontier_exhausted", "reason": "已穷尽当前可安全访问的页面路径"}
            press_home = getattr(self.client, "press_home", None)
            if (
                callable(press_home)
                and termination.get("kind") not in {"paused", "canceled", "terminated"}
                and not ctx.runtime.get("background_probe_started_ms")
            ):
                try:
                    ctx.runtime["background_probe_started_ms"] = int(time.time() * 1000)
                    press_home()
                    seconds = float(ctx.cfg.get("detection", {}).get("background_probe_seconds", 8))
                    time.sleep(seconds)
                    evidence.append(record_event(ctx, "appium", "background_probe_started", seconds=seconds))
                except ExplorationError as exc:
                    evidence.append(record_event(ctx, "appium", "background_probe_failed", error=str(exc)[:300]))
            if ctx.runtime.get("privacy_hub_visited") and (
                ctx.runtime.get("privacy_hub_search_exhausted")
                or _hub_checklist_complete(ctx)
            ):
                ctx.runtime["privacy_hub_audit_complete"] = True
            if not ctx.runtime.get("third_party_app_gate_seen"):
                scenario_frontier.mark_blocked(
                    ["5.3"], "not_applicable",
                    "本次未出现接入第三方应用并提供个人信息的场景",
                )
            ctx.runtime["scenario_completed_items"] = sorted(scenario_frontier.completed_items)
            ctx.runtime["scenario_coverage"] = scenario_frontier.snapshot()
            def _save_pause_checkpoints(final_termination: dict) -> None:
                checkpoint = TraversalCheckpointRepository(ctx.data_dir, ctx.runtime).traversal_path
                if str((final_termination or {}).get("kind")) == "paused":
                    saved = _save_traversal_checkpoint(ctx, state, findings, evidence)
                    _save_navigation_replay_checkpoint(ctx, state)
                    evidence.append(record_event(
                        ctx, "appium", "traversal_checkpoint_saved", path=str(saved),
                        read_document_kinds=sorted(_read_document_kinds(ctx)),
                        read_document_titles=sorted(_read_document_titles(ctx)),
                    ))
                elif checkpoint.exists():
                    checkpoint.unlink(missing_ok=True)
                if str((final_termination or {}).get("kind")) != "paused":
                    TraversalCheckpointRepository(ctx.data_dir, ctx.runtime).navigation_path.unlink(missing_ok=True)

            return run_finalizer.finalize(
                ctx, termination=termination, state=state, evidence=evidence, findings=findings,
                scenario_snapshot=ctx.runtime["scenario_coverage"],
                permission_prompts=permission_prompts, login_gate_seen=login_gate_seen,
                active_permission_probe=bool(permission_probes.active),
                pending_action_validation=action_effects.pending,
                current_activity=activity, llm_calls=llm_calls, last_step=last_step,
                save_pause_checkpoints=_save_pause_checkpoints,
            )
        finally:
            self.client.close()
            cleanup_error = str(getattr(self.client, "last_cleanup_error", "") or "")
            if cleanup_error:
                record_event(
                    ctx, "appium", "session_cleanup_deferred",
                    reason=cleanup_error,
                )
