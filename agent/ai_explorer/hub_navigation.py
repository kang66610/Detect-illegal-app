"""Settings-hub navigation: tabs, drill rows and bounded top-level DFS.

Owns the hub-shape vocabulary (main tabs, hub distractors, exploration rows),
the 我的/设置 tab and drill-row selectors, the deterministic hub progress
candidate assembly and the bounded top-level DFS picker. The explorer loop
consumes these helpers through alias imports; the hub navigation surface has
exactly one owner — this module.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from agent.ai_explorer.action_safety_checks import (
    NON_AUDIT_MAINTENANCE_TERMS,
    bounds_tuple,
)
from agent.ai_explorer.consent_vocabulary import (
    AUTHENTICATED_LOGOUT_TERMS,
    authenticated_logout_target,
)
from agent.ai_explorer.document_state import (
    already_read_document_target,
    unread_for_page,
)
from agent.ai_explorer.hub_decision import HubProgressCandidates, SettingsHubNavigator
from agent.ai_explorer.redress_media_probe import (
    EXPLICIT_REDRESS_ACTION_TERMS,
    _media_album_chooser_target,
    _media_capture_chooser_target,
    _semantic_sensitive_business_control,
    privacy_path_observations as _privacy_path_observations,
)
from agent.ai_explorer.target_catalog import (
    element_semantic_identity,
    global_target_key,
    required_document_kind,
)
from agent.common.event_log import record_event
from agent.detection_engines.base import DetectionContext
from agent.detection_engines.ui_roles import roles_for_element
from agent.rule_engine.scenario_plan import ScenarioFrontier

HUB_DISTRACTOR_TERMS = (
    "通知设置", "推送设置", "消息设置", "消息通知", "推送通知",
    "notification settings", "push settings",
)
_PERSONALIZED_RECOMMENDATION_TERMS = (
    "个性精准推荐", "个性化推荐", "精准推荐", "推荐管理",
    "personalized recommendation", "targeted recommendation",
)
MAIN_CONTENT_TAB_TERMS = (
    "书城", "书架", "首页", "精选", "发现", "推荐", "地图", "出行", "导航", "附近", "周边",
    "library", "bookstore", "bookshelf", "discover", "map", "nearby", "transit",
)
MAIN_CONTENT_TAB_PRIORITY = (
    "地图", "出行", "书城", "书架", "library", "bookstore", "bookshelf", "map",
)
HUB_EXPLORATION_ROW_TERMS = (
    "注销", "删除账号", "撤回", "授权管理", "权限管理", "权限", "隐私", "账号", "账户", "个人",
    "关于", "协议", "政策", "收集清单", "sdk", "编辑", "exit", "edit",
    "设置", "更多设置", "账号设置", "隐私设置", "安全设置", "账号与安全",
    "手机号", "手机", "account", "privacy", "delete", "withdraw", "settings",
)
SETTINGS_HUB_NAVIGATOR = SettingsHubNavigator()


def identity_is_hub_distractor(identity: str) -> bool:
    """通知/推送设置 look like 设置 but are not 3.8/6.1 routes."""
    lowered = str(identity or "").lower()
    return any(
        term.lower() in lowered
        for term in (*HUB_DISTRACTOR_TERMS, *NON_AUDIT_MAINTENANCE_TERMS)
    )


def _is_personalized_recommendation_row(identity: str) -> bool:
    """Recommendation settings are 3.6 evidence, not 3.8/6.1 hub navigation."""
    lowered = str(identity or "").lower()
    return any(term.lower() in lowered for term in _PERSONALIZED_RECOMMENDATION_TERMS)


def hub_privacy_action_target(
    ctx: DetectionContext, elements: list[dict], visited_targets: set[str],
) -> str | None:
    """Prefer a visible 注销/授权 row on the settings hub over random 设置 children."""
    visited = set(visited_targets)
    attempted_routes = set(ctx.runtime.get("privacy_path_route_keys") or set())
    observations = _privacy_path_observations(elements, "")
    # Deleting an account can immediately invalidate the authenticated session
    # in some Apps instead of opening a reversible explanation page.  During a
    # deny profile, preserve the session until the permission-dependent business
    # probe has run.  Withdraw/authorization-management rows remain safe and are
    # still eligible; delete-account rows are deferred, not globally hard-coded.
    groups = [list(observations.get("withdraw_targets") or [])]
    if not permission_denial_probe_outstanding(ctx):
        groups.insert(0, list(observations.get("delete_targets") or []))
    for target in [item for group in groups for item in group]:
        route_key = global_target_key("", target, elements) if target else ""
        if target and target not in visited and route_key not in attempted_routes:
            return target
    return None


def permission_denial_probe_outstanding(
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


def logout_entry_exploration_target(
    ctx: DetectionContext, elements: list[dict], visited_targets: set[str] | None = None,
) -> str | None:
    """Click 退出登录 once to open the confirm dialog; never submit logout."""
    # A row labelled “退出登录” is not guaranteed to open a confirmation; some
    # Apps invalidate the session immediately.  Observation is therefore the
    # safe default.  Even an explicit opt-in is postponed while deny/4.2 is due.
    if not bool((ctx.cfg.get("detection") or {}).get("explore_logout_confirmation", False)):
        return None
    if permission_denial_probe_outstanding(ctx):
        return None
    if ctx.runtime.get("logout_entry_explored"):
        return None
    visited = set(visited_targets or ())
    for element in elements:
        if not element.get("clickable"):
            continue
        target = str(
            element.get("target") or element.get("resource_id")
            or element.get("text") or element.get("content_desc") or ""
        )
        if not target or target in visited:
            continue
        if authenticated_logout_target(target, elements):
            return target
        # Label may sit on a non-clickable child inside the row.
        identity = element_semantic_identity(element, elements)
        if any(term.lower() in identity.lower() for term in AUTHENTICATED_LOGOUT_TERMS):
            if "注销" in identity and "登录" not in identity:
                continue
            return target
    return None


def hub_avatar_probe_target(elements: list[dict], visited_targets: set[str]) -> str | None:
    """Avatar/upload row on a profile hub — 2.3/4.2 probe, not a home chrome icon."""
    return _semantic_sensitive_business_control(
        elements, exclude=set(visited_targets), allow_nav_chrome=False, require_avatar_or_upload=True,
    )


def observe_logout_rows_without_clicking(
    ctx: DetectionContext, elements: list[dict], evidence: list, activity: str,
) -> None:
    """Mark visible logout rows so progress can continue after one exploration click."""
    observed = ctx.runtime.setdefault("logout_entries_observed", set())
    for element in elements:
        if not element.get("clickable"):
            continue
        target = str(
            element.get("target") or element.get("resource_id")
            or element.get("text") or element.get("content_desc") or ""
        )
        if not target or target in observed:
            continue
        if not authenticated_logout_target(target, elements):
            identity = element_semantic_identity(element, elements)
            if not any(term.lower() in identity.lower() for term in AUTHENTICATED_LOGOUT_TERMS):
                continue
        observed.add(target)
        evidence.append(record_event(
            ctx, "appium", "logout_entry_observed", activity=activity, target=target,
            reason="已看见退出登录入口；默认仅记录，不假设该入口一定存在可安全返回的确认框",
        ))


def hub_progress_target(
    ctx: DetectionContext, elements: list[dict], visited_targets: set[str],
) -> str | None:
    """Next deterministic action on a settings/profile hub after docs may already be read.

    Order: 媒体来源 → 注销/授权 → 设置/关于钻取 → 未读条款 →
    deny阶段头像/上传 → 可选退出登录确认 → 其它行。
    """
    visited = set(visited_targets)
    if ctx.runtime.get("logout_entry_explored"):
        visited |= set(ctx.runtime.get("logout_entries_observed") or ())
    capture = _media_capture_chooser_target(elements)
    album = _media_album_chooser_target(elements)
    return SETTINGS_HUB_NAVIGATOR.next_target(HubProgressCandidates(
        capture=capture if capture not in visited else "",
        album=album if album not in visited else "",
        privacy=hub_privacy_action_target(ctx, elements, visited) or "",
        drill=hub_drill_target(elements, visited) or "",
        unread=unread_for_page(ctx, elements, visited) or "",
        avatar=hub_avatar_probe_target(elements, visited) or "",
        logout=logout_entry_exploration_target(ctx, elements, visited) or "",
        fallback=next_hub_exploration_target(elements, visited, ctx=ctx) or "",
        deny_probe_outstanding=permission_denial_probe_outstanding(ctx),
    ))


def next_hub_exploration_target(
    elements: list[dict], visited_targets: set[str], *, ctx: DetectionContext | None = None,
) -> str | None:
    """Pick the next non-distractor settings row while hunting 3.8/6.1."""
    visited = set(visited_targets)
    if ctx is not None and ctx.runtime.get("logout_entry_explored"):
        visited |= set(ctx.runtime.get("logout_entries_observed") or ())
    ranked: list[tuple[int, str]] = []
    for element in elements:
        if not element.get("clickable"):
            continue
        values = (
            str(element.get("target") or ""),
            str(element.get("resource_id") or ""),
            str(element.get("text") or ""),
            str(element.get("content_desc") or ""),
        )
        target = next((value for value in values if value), "")
        if not target or target in visited:
            continue
        identity = element_semantic_identity(element, elements) or " ".join(values)
        if identity_is_hub_distractor(identity):
            continue
        if _is_personalized_recommendation_row(identity):
            continue
        roles = roles_for_element(element)
        # Skip only bottom-nav 我/设置 tabs — list-row「设置/关于我们」must still drill in.
        if roles & {"privacy_hub_entry", "settings_entry"} and is_bottom_nav_hub_tab(element, elements):
            continue
        if roles & {"business_trigger"} and not (
            roles & {"delete_control", "withdraw_control", "document_link", "settings_entry"}
        ):
            continue
        # Kind already read at splash — do not burn steps reopening Chrome/WebView.
        if ctx is not None and already_read_document_target(ctx, target, elements):
            continue
        if any(term.lower() in identity.lower() for term in HUB_EXPLORATION_ROW_TERMS):
            # Prefer 注销/授权/设置 drill-downs over incidental 个人 rows.
            priority = 0
            if any(term in identity for term in ("注销", "删除账号", "撤回", "授权管理")):
                priority = 0
            elif any(term in identity for term in ("设置", "更多设置", "关于", "settings", "about")):
                priority = 1
            else:
                priority = 2
            ranked.append((priority, target))
        elif roles & {
            "document_link", "withdraw_control", "delete_control", "complaint_control",
        }:
            ranked.append((1, target))
    ranked.sort()
    return ranked[0][1] if ranked else None


def target_is_hub_reentry(target: str, elements: list[dict]) -> bool:
    """Settings/我的/更多设置 remain valid while 3.8/6.1 still need a page."""
    raw = str(target or "")
    if not raw:
        return False
    for element in elements:
        values = (
            str(element.get("target") or ""),
            str(element.get("resource_id") or ""),
            str(element.get("text") or ""),
            str(element.get("content_desc") or ""),
        )
        if raw not in values:
            continue
        identity = " ".join(values)
        if identity_is_hub_distractor(identity):
            continue
        if _is_personalized_recommendation_row(identity):
            continue
        if roles_for_element(element) & {"privacy_hub_entry", "settings_entry"}:
            return True
    return False


def hub_drill_target(elements: list[dict], visited_targets: set[str]) -> str | None:
    """List-row「设置/更多设置/关于我们」on a profile shell — not the bottom tab."""
    visited = set(visited_targets)
    ranked: list[tuple[int, str]] = []
    for element in elements:
        if not element.get("clickable"):
            continue
        if is_bottom_nav_hub_tab(element, elements):
            continue
        # Use the row's own label/id.  A broad clickable profile container can
        # geometrically contain unrelated labels such as “设置”, which used to
        # turn birthday/location rows into fake settings drills.
        identity = " ".join(
            str(element.get(key) or "")
            for key in ("target", "resource_id", "text", "content_desc")
        )
        if identity_is_hub_distractor(identity):
            continue
        if _is_personalized_recommendation_row(identity):
            continue
        target = str(
            element.get("target") or element.get("resource_id")
            or element.get("text") or element.get("content_desc") or ""
        )
        if not target or target in visited:
            continue
        compact = re.sub(r"\s+", "", identity).lower()
        if any(term in compact for term in ("更多设置", "账号设置", "隐私设置", "安全设置", "账号与安全")):
            ranked.append((0, target))
        elif any(term in compact for term in ("设置", "settings")) and "通知" not in compact and "推送" not in compact:
            ranked.append((1, target))
        elif any(term in compact for term in ("关于我们", "about us", "关于")):
            ranked.append((2, target))
    ranked.sort()
    return ranked[0][1] if ranked else None


def main_content_tab_target(elements: list[dict]) -> str | None:
    """Pick a visible bottom/main tab that is the app's content home, not 我的/设置."""
    ranked: list[tuple[int, str]] = []
    for element in elements:
        if not element.get("clickable"):
            continue
        label = " ".join(str(element.get(key) or "") for key in ("text", "content_desc")).strip()
        resource_id = str(element.get("resource_id") or "")
        if len(label) > 8:
            continue
        identity = f"{label} {resource_id}".lower()
        if required_document_kind(label) or any(term in identity for term in ("设置", "我的", "profile", "setting", "mine")):
            continue
        if not any(term.lower() in identity for term in MAIN_CONTENT_TAB_TERMS):
            continue
        target = resource_id or label or str(element.get("target") or "")
        if not target:
            continue
        priority = 0 if any(term.lower() in identity for term in MAIN_CONTENT_TAB_PRIORITY) else 1
        ranked.append((priority, target))
    ranked.sort()
    return ranked[0][1] if ranked else None


def privacy_hub_tab_target(elements: list[dict]) -> str | None:
    """Pick a visible 我的/设置 tab so login is followed by the privacy hub."""
    ranked: list[tuple[int, str]] = []
    for element in elements:
        if not element.get("clickable"):
            continue
        label = " ".join(str(element.get(key) or "") for key in ("text", "content_desc")).strip()
        resource_id = str(element.get("resource_id") or "")
        if len(label) > 10:
            continue
        identity = f"{label} {resource_id}".lower()
        if not any(term in identity for term in ("设置", "我的", "profile", "setting", "mine", "about")):
            continue
        if any(term in identity for term in ("qq", "微信", "wechat", "客服")):
            continue
        if any(term.lower() in identity for term in HUB_DISTRACTOR_TERMS):
            continue
        target = resource_id or label or str(element.get("target") or "")
        if not target:
            continue
        priority = 0 if any(term in identity for term in ("设置", "setting")) else 1
        ranked.append((priority, target))
    ranked.sort()
    if ranked:
        return ranked[0][1]
    # Fall back to a profile chrome avatar that opens 个人信息 — not a 4.2 media probe.
    for element in elements:
        if not element.get("clickable"):
            continue
        identity = " ".join(
            str(element.get(key) or "") for key in ("target", "resource_id", "text", "content_desc")
        ).lower()
        if any(term in identity for term in ("head_image", "headimage", "iv_avatar", "mine_avatar")):
            if any(term in identity for term in ("history", "reading", "book")):
                continue
            return str(
                element.get("target") or element.get("resource_id") or element.get("text") or ""
            ) or None
    return None


def is_bottom_nav_hub_tab(element: dict, elements: list[dict]) -> bool:
    """True for bottom-bar 我/设置 tabs, not a list-row drill-down into 设置."""
    label = re.sub(
        r"\s+", "",
        " ".join(str(element.get(key) or "") for key in ("text", "content_desc")),
    )
    resource_id = str(element.get("resource_id") or "").lower()
    if len(label) > 6:
        return False
    exact_labels = {
        "我", "我的", "设置", "个人中心", "用户中心", "账户中心", "账号中心",
        "mine", "profile", "account", "settings",
    }
    id_tokens = ("setting", "mine", "profile", "account", "user_center", "personal_center")
    if label.lower() not in exact_labels and not any(term in resource_id for term in id_tokens):
        return False
    # Explicit bottom-nav / radio-tab ids.
    if any(token in resource_id for token in (
        "tab_", "rb_", "navi_", "bottom_nav", "bottomnav", "main_tab", "ll_tab",
    )):
        return True
    bounds = bounds_tuple(str(element.get("bounds") or ""))
    if not bounds:
        return False
    page_bottom = max(
        (bounds_tuple(str(item.get("bounds") or "")) or (0, 0, 0, 0))[3]
        for item in elements
    ) or bounds[3]
    if page_bottom <= 0:
        return False
    # Bottom ~18% chrome is navigation; mid-screen list rows are drill-downs.
    return bounds[1] >= page_bottom * 0.82


def is_top_level_navigation_target(target: str, elements: list[dict]) -> bool:
    raw = str(target or "")
    if not raw:
        return False
    for item in elements:
        if raw not in {
            str(item.get("target") or ""), str(item.get("resource_id") or ""),
            str(item.get("text") or ""), str(item.get("content_desc") or ""),
        }:
            continue
        if is_bottom_nav_hub_tab(item, elements):
            return True
        label = " ".join(str(item.get(key) or "") for key in (
            "text", "content_desc", "resource_id",
        )).strip().lower()
        return label in {
            "首页", "我的", "消息", "发现", "home", "profile", "account", "tab_home", "tab_profile",
        }
    return False


def next_top_level_audit_target(
    elements: list[dict], visited_route_keys: set[str] | None = None,
    *, low_audit_route_check: Callable[[str, list[dict]], bool] | None = None,
) -> str | None:
    """Return the next unvisited top-level branch for bounded DFS backtracking.

    This is deliberately semantic and layout-based: Apps may name the same
    route 客服、投诉、反馈、我的、个人中心 or expose an icon-only tab. It never
    relies on one App's package/id and prunes commerce/maintenance branches.
    """
    visited = set(visited_route_keys or ())
    bounded = [
        (item, bounds_tuple(str(item.get("bounds") or "")))
        for item in elements if item.get("clickable") and item.get("displayed", True)
    ]
    bounded = [(item, bounds) for item, bounds in bounded if bounds]
    page_bottom = max((bounds[3] for _, bounds in bounded), default=0)
    ranked: list[tuple[int, float, str]] = []
    for item in elements:
        if not item.get("clickable") or not item.get("displayed", True) or item.get("selected"):
            continue
        target = str(
            item.get("target") or item.get("resource_id")
            or item.get("text") or item.get("content_desc") or ""
        )
        if not target:
            continue
        resource_id = str(item.get("resource_id") or "").lower()
        bounds = bounds_tuple(str(item.get("bounds") or ""))
        explicit_tab = any(token in resource_id for token in (
            "tab_", "rb_", "navi_", "bottom_nav", "bottomnav", "main_tab", "ll_tab",
        ))
        bottom_tab = bool(bounds and page_bottom and bounds[1] >= page_bottom * 0.80)
        if not (explicit_tab or bottom_tab or is_top_level_navigation_target(target, elements)):
            continue
        if low_audit_route_check is not None and low_audit_route_check(target, elements):
            continue
        route_key = global_target_key("", target, elements)
        if route_key in visited:
            continue
        identity = element_semantic_identity(item, elements).lower()
        roles = roles_for_element(item)
        if roles & {"complaint_control"} or any(
            term.lower() in identity for term in EXPLICIT_REDRESS_ACTION_TERMS
        ):
            priority = 0
        elif roles & {"privacy_hub_entry", "settings_entry"}:
            priority = 1
        elif any(term.lower() in identity for term in MAIN_CONTENT_TAB_TERMS):
            priority = 2
        else:
            priority = 3
        x = float(bounds[0]) if bounds else 0.0
        ranked.append((priority, x, target))
    ranked.sort()
    return ranked[0][2] if ranked else None
