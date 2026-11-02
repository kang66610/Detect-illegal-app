"""Safe semantic replay of a recorded in-app navigation breadcrumb.

The replay executor belongs to the navigation domain: it re-walks the
breadcrumb recorded before a runtime-session loss by re-resolving every
recorded semantic target against the freshly rendered page. Old bounds and
relative coordinates are never replayed. Safety predicates come from the
audited-app policy surface and are injected, so this module stays free of
explorer-internal helpers.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from agent.ai_explorer.page_state import NavigationReplayEdge, PageState, parse_page
from agent.common.event_log import record_event
from agent.common.exceptions import ExplorationError
from agent.detection_engines.base import DetectionContext


@dataclass(frozen=True)
class NavigationReplaySafety:
    """Injected safety predicates used to reject unsafe replay targets."""

    is_document_route: Callable[[str], bool]
    is_transaction_target: Callable[[str, list[dict]], bool]
    is_destructive_confirmation: Callable[[str, list[dict]], bool]
    is_app_exit_confirmation: Callable[[str, list[dict]], bool]
    is_logout_confirmation_target: Callable[[str, list[dict]], bool]
    is_consent_or_decline_control: Callable[[dict], bool]
    is_safe_deep_probe_target: Callable[[str, list[dict]], bool]
    is_launcher_activity: Callable[[str], bool]
    has_left_audited_package: Callable[..., bool]


def resolve_navigation_replay_target(
    edge: NavigationReplayEdge, elements: list[dict],
) -> str | None:
    """Resolve a recorded semantic target against the freshly rendered page.

    Old bounds and relative coordinates are never replayed.  A replay target
    must be rediscovered from current accessibility identity so layout changes
    after reboot cannot turn a safe breadcrumb into an arbitrary tap.
    """
    identity = dict(edge.target_identity or {})
    original = str(edge.target or "")
    candidates: list[tuple[int, int, str]] = []
    for index, item in enumerate(elements):
        if not item.get("clickable") or not item.get("enabled", True) or not item.get("displayed", True):
            continue
        target = str(
            item.get("target") or item.get("resource_id") or item.get("text")
            or item.get("content_desc") or ""
        )
        if not target:
            continue
        score = 0
        resource_id = str(item.get("resource_id") or "")
        text = str(item.get("text") or "")
        content_desc = str(item.get("content_desc") or "")
        if identity.get("resource_id") and resource_id == identity["resource_id"]:
            score += 120
        if identity.get("text") and text == identity["text"]:
            score += 90
        if identity.get("content_desc") and content_desc == identity["content_desc"]:
            score += 90
        if identity.get("class_name") and str(item.get("class_name") or "") == identity["class_name"]:
            score += 5
        if original and not original.startswith(("bounds:", "relative:")) and original in {
            target, resource_id, text, content_desc,
        }:
            score += 100
        if score:
            candidates.append((-score, index, target))
    candidates.sort()
    return candidates[0][2] if candidates else None


def navigation_replay_target_is_safe(target: str, page, safety: NavigationReplaySafety) -> bool:
    if not target or target.startswith("relative:"):
        return False
    if safety.is_document_route(target):
        return False
    if safety.is_transaction_target(target, page.elements):
        return False
    if safety.is_destructive_confirmation(target, page.elements):
        return False
    if safety.is_app_exit_confirmation(target, page.elements):
        return False
    if safety.is_logout_confirmation_target(target, page.elements):
        return False
    if any(
        safety.is_consent_or_decline_control(item)
        for item in page.elements
        if target in {
            str(item.get("target") or ""), str(item.get("resource_id") or ""),
            str(item.get("text") or ""), str(item.get("content_desc") or ""),
        }
    ):
        return False
    return safety.is_safe_deep_probe_target(target, page.elements)


def rollback_interrupted_navigation_attempts(
    ctx: DetectionContext, state: PageState, edges: list[NavigationReplayEdge],
) -> None:
    """Do not let pre-reboot counters block the route being restored once."""
    for edge in edges:
        state.visited_page_targets.discard(f"{edge.parent_surface}:{edge.target}")
        suffix = f":{edge.target}"
        if not any(item.endswith(suffix) for item in state.visited_page_targets):
            state.visited_targets.discard(edge.target)
        tokens = [
            str(edge.target_identity.get(key) or "").lower()
            for key in ("resource_id", "text", "content_desc")
            if edge.target_identity.get(key)
        ]
        activity_prefix = f"{str(edge.parent_activity or '').lower()}|"
        global_attempts = ctx.runtime.get("global_target_attempts") or {}
        for key in list(global_attempts):
            lowered = str(key).lower()
            if lowered.startswith(activity_prefix) and any(token in lowered for token in tokens):
                global_attempts.pop(key, None)
        root_attempts = ctx.runtime.get("root_route_attempts") or {}
        for key in list(root_attempts):
            lowered = str(key).lower()
            if lowered.startswith(f"{edge.parent_activity}|".lower()) and (
                str(edge.target or "").lower() in lowered
                or any(token in lowered for token in tokens)
            ):
                root_attempts.pop(key, None)


def replay_navigation_route(
    client, ctx: DetectionContext, state: PageState, evidence: list[dict],
    safety: NavigationReplaySafety,
) -> bool:
    """Safely replay the current semantic breadcrumb after a runtime reboot."""
    edges = state.navigation_replay.replay_edges()
    ctx.runtime["navigation_replay_required"] = bool(edges)
    if not edges:
        evidence.append(record_event(
            ctx, "appium", "navigation_replay_unavailable",
            reason="会话中断前尚未形成可验证的应用内导航链",
        ))
        return False
    rollback_interrupted_navigation_attempts(ctx, state, edges)
    evidence.append(record_event(
        ctx, "appium", "navigation_replay_started", edge_count=len(edges),
        destination_activity=edges[-1].child_activity or edges[-1].parent_activity,
    ))
    detection = ctx.cfg.get("detection", {})
    settle_retries = max(0, int(detection.get("runtime_replay_settle_retries", 12)))
    wait_seconds = max(0.0, float(detection.get(
        "runtime_replay_wait_seconds", ctx.cfg.get("appium", {}).get("page_wait_seconds", 1),
    )))
    page = None
    start_index = None
    for attempt in range(settle_retries + 1):
        try:
            activity, xml = client.page()
        except ExplorationError as exc:
            evidence.append(record_event(
                ctx, "appium", "navigation_replay_page_read_failed",
                attempt=attempt + 1, error=str(exc)[:300],
            ))
            return False
        page = parse_page(activity, xml)
        # Already at an observed child: continue with only the remaining edge.
        child_match = next((
            index for index in range(len(edges) - 1, -1, -1)
            if edges[index].child_surface == page.surface_fingerprint
        ), None)
        if child_match is not None:
            start_index = child_match + 1
            break
        parent_match = next((
            index for index, edge in enumerate(edges)
            if edge.parent_surface == page.surface_fingerprint
        ), None)
        if parent_match is not None:
            start_index = parent_match
            break
        # Fingerprints can change after a reboot; require both the expected
        # Activity and a newly resolved current-page control before accepting.
        semantic_match = next((
            index for index, edge in enumerate(edges)
            if str(edge.parent_activity or "") == activity
            and resolve_navigation_replay_target(edge, page.elements)
        ), None)
        if semantic_match is not None:
            start_index = semantic_match
            break
        if attempt < settle_retries and wait_seconds:
            time.sleep(wait_seconds)
    if page is None or start_index is None:
        evidence.append(record_event(
            ctx, "appium", "navigation_replay_root_unavailable",
            expected_activity=edges[0].parent_activity,
            reason="恢复后未回到导航链中的稳定页面，交回普通探索并保留覆盖缺口",
        ))
        return False

    replayed = 0
    for index in range(start_index, len(edges)):
        edge = edges[index]
        target = resolve_navigation_replay_target(edge, page.elements)
        if not target or not navigation_replay_target_is_safe(target, page, safety):
            evidence.append(record_event(
                ctx, "appium", "navigation_replay_edge_blocked",
                edge_index=index, activity=page.activity,
                recorded_target=edge.target, resolved_target=target or "",
                reason="旧坐标不复用，且当前页面未找到同一语义的安全可逆控件",
            ))
            return False
        try:
            client.perform({
                "action": "click", "target": target,
                "reason": "会话恢复：按当前页面语义回放已验证的安全导航路径",
            })
        except ExplorationError as exc:
            evidence.append(record_event(
                ctx, "appium", "navigation_replay_edge_failed",
                edge_index=index, activity=page.activity, target=target,
                error=str(exc)[:300],
            ))
            return False
        replayed += 1
        evidence.append(record_event(
            ctx, "appium", "navigation_replay_edge_completed",
            edge_index=index, activity=page.activity, target=target,
            expected_child_activity=edge.child_activity or "",
        ))
        if wait_seconds:
            time.sleep(wait_seconds)
        try:
            next_activity, next_xml = client.page()
        except ExplorationError as exc:
            evidence.append(record_event(
                ctx, "appium", "navigation_replay_edge_failed",
                edge_index=index, activity=page.activity, target=target,
                error=str(exc)[:300], reason="回放点击后无法读取子页面",
            ))
            return False
        next_page = parse_page(next_activity, next_xml)
        if safety.is_launcher_activity(next_activity) or safety.has_left_audited_package(
            next_activity,
            str(getattr(ctx.apk, "package_name", "") or ""),
            foreground_package=str(getattr(client, "last_package", "") or ""),
        ):
            evidence.append(record_event(
                ctx, "appium", "navigation_replay_edge_no_effect",
                edge_index=index, activity=page.activity, target=target,
                reason="回放点击再次离开被测应用，拒绝把外部页面当作成功子节点",
            ))
            return False
        if next_page.surface_fingerprint == page.surface_fingerprint:
            evidence.append(record_event(
                ctx, "appium", "navigation_replay_edge_no_effect",
                edge_index=index, activity=page.activity, target=target,
            ))
            return False
        page = next_page
    evidence.append(record_event(
        ctx, "appium", "navigation_replay_completed", replayed_edges=replayed,
        final_activity=page.activity,
        reason="已恢复到会话中断前最近的安全业务页面",
    ))
    return True
