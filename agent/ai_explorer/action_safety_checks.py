"""Pure safety predicates consumed by the final action safety policy.

Every predicate here is page-local and side-effect free: elements in, boolean
out.  Vocabulary that other exploration concerns share stays with its owner
and is injected through :class:`SafetyCheckFacts`; this module never imports
the Appium engine.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from agent.ai_explorer.target_catalog import identity_values_for_target


def bounds_tuple(value: str) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", str(value or ""))
    if not match:
        return None
    left, top, right, bottom = (int(item) for item in match.groups())
    return (left, top, right, bottom) if right > left and bottom > top else None


def is_transaction_target(target: str, elements: list[dict]) -> bool:
    """Identify payment/ordering controls that must remain observation-only."""
    identities = [str(target or "")]
    for element in elements:
        if target and target in (
            str(element.get("target") or ""),
            str(element.get("resource_id") or ""),
            str(element.get("text") or ""),
            str(element.get("content_desc") or ""),
        ):
            identities.extend(str(element.get(key) or "") for key in ("resource_id", "text", "content_desc"))
    normalized = " ".join(identities).lower()
    return any(term in normalized for term in (
        "支付", "付款", "立即支付", "确认订单", "下单", "购买", "充值", "开通会员",
        "payment", "checkout", "place order", "purchase", "top up",
    ))


DESTRUCTIVE_CONFIRM_TERMS = (
    "确认注销", "确定注销", "立即注销", "提交注销",
    "确认删除", "确定删除", "立即删除", "彻底删除", "提交删除",
    "确认清除",
)


def is_destructive_confirmation(target: str, elements: list[dict]) -> bool:
    identities = identity_values_for_target(target, elements)
    value = " ".join(identities).lower()
    return any(term.lower() in value for term in DESTRUCTIVE_CONFIRM_TERMS)


def is_stale_or_invisible_target(target: str, elements: list[dict]) -> bool:
    raw = str(target or "")
    if not raw:
        return False
    bounds_value = raw[len("bounds:"):] if raw.startswith("bounds:") else ""
    lowered = raw.lower()
    semantic = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", raw).lower()
    for item in elements:
        if not item.get("displayed", True):
            continue
        values = (
            str(item.get("target") or ""),
            str(item.get("resource_id") or ""),
            str(item.get("text") or ""),
            str(item.get("content_desc") or ""),
        )
        if raw in values:
            return True
        if semantic and semantic in {
            re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).lower()
            for value in values if value
        }:
            return True
        if bounds_value and bounds_value == str(item.get("bounds") or ""):
            return True
        if len(raw) >= 4 and any(lowered in str(value).lower() for value in values if value):
            return True
    return False


def is_unlabelled_structural_bounds_target(target: str, elements: list[dict]) -> bool:
    """Reject OCR/Compose containers that are screen chrome, not controls.

    An unlabeled full-screen scrim, toolbar or top-left back hitbox changes
    fingerprints and can trap DFS on the same screen.  The guard is geometry
    based and keeps small controls elsewhere (including media buttons) eligible.
    """
    raw = str(target or "")
    if not raw.startswith("bounds:"):
        return False
    bounds = bounds_tuple(raw[len("bounds:"):])
    if not bounds:
        return True
    matched = [
        item for item in elements
        if item.get("clickable")
        and str(item.get("bounds") or "") == raw[len("bounds:"):]
    ]
    if any(
        str(item.get("text") or "").strip()
        or str(item.get("content_desc") or "").strip()
        or str(item.get("resource_id") or "").strip()
        for item in matched
    ):
        return False
    all_bounds = [
        parsed for item in elements
        if (parsed := bounds_tuple(str(item.get("bounds") or "")))
    ]
    if not all_bounds:
        return True
    page_right = max(item[2] for item in all_bounds)
    page_bottom = max(item[3] for item in all_bounds)
    if page_right <= 0 or page_bottom <= 0:
        return True
    left, top, right, bottom = bounds
    width, height = right - left, bottom - top
    area_ratio = (width * height) / float(page_right * page_bottom)
    full_width_top = left <= page_right * 0.03 and right >= page_right * 0.97 and top <= page_bottom * 0.12
    top_left_chrome = (
        left <= page_right * 0.12 and top <= page_bottom * 0.12
        and width <= page_right * 0.22 and height <= page_bottom * 0.16
    )
    return area_ratio >= 0.25 or full_width_top or top_left_chrome


def is_low_audit_value_route(
    target: str,
    identity_blob: str,
    *,
    protected_terms: tuple[str, ...] = (),
    maintenance_terms: tuple[str, ...] = (),
    exempt_terms: tuple[str, ...] = (),
    low_value_terms: tuple[str, ...] = (),
) -> bool:
    """Classify generic marketing/commerce edges that should be pruned.

    The decision is semantic rather than App/page-name specific.  A route that
    also exposes a complaint/help, policy, permission or account-control goal
    remains eligible even when it is displayed inside a promotion page.
    """
    identity = f"{target} {identity_blob}".lower()
    # A compound label such as “官网隐私政策” remains a compliance route even
    # though it also contains a maintenance/metadata word.
    if any(term.lower() in identity for term in protected_terms):
        return False
    # Maintenance actions mutate counters/state but provide no privacy-rule
    # evidence. Prune them before the generic word "设置/settings" exemption.
    if any(term.lower() in identity for term in maintenance_terms):
        return True
    if any(term.lower() in identity for term in exempt_terms):
        return False
    return any(term.lower() in identity for term in low_value_terms)


@dataclass(frozen=True)
class SafetyCheckFacts:
    """Per-page inputs for assembling the bounded safety predicate mapping."""

    activity: str = ""
    audited_package: str = ""
    audited_app_name: str = ""
    foreground_package: str = ""
    elements: tuple[dict, ...] = ()
    label_blob_for: Callable[[str], str] | None = None
    foreign_app_launcher: Callable[[str], bool] | None = None
    protected_route_terms: tuple[str, ...] = ()
    maintenance_terms: tuple[str, ...] = ()
    exempt_route_terms: tuple[str, ...] = ()
    low_value_route_terms: tuple[str, ...] = ()
    extra_terms: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class SafetyChecks:
    """Assemble the safety predicate mapping for one page in CHECK_ORDER."""

    @staticmethod
    def for_page(facts: SafetyCheckFacts) -> dict[str, Callable[[str], bool]]:
        elements = list(facts.elements)
        label_blob_for = facts.label_blob_for or (lambda _target: "")
        foreign_app_launcher = facts.foreign_app_launcher or (lambda _target: False)
        return {
            "foreign_app_launch": foreign_app_launcher,
            "low_audit_value_route": lambda target: is_low_audit_value_route(
                target,
                label_blob_for(target),
                protected_terms=facts.protected_route_terms,
                maintenance_terms=facts.maintenance_terms,
                exempt_terms=facts.exempt_route_terms,
                low_value_terms=facts.low_value_route_terms,
            ),
            "transaction_boundary": lambda target: is_transaction_target(target, elements),
            "unlabelled_structural_container": lambda target: is_unlabelled_structural_bounds_target(
                target, elements,
            ),
            "destructive_confirmation": lambda target: is_destructive_confirmation(target, elements),
            "stale_or_invisible_target": lambda target: bool(
                target and not target.startswith("relative:")
                and not is_stale_or_invisible_target(target, elements)
            ),
        }


NON_AUDIT_MAINTENANCE_TERMS = (
    "清除缓存", "清理缓存", "缓存清理", "清空缓存", "clear cache", "clean cache",
    "检查更新", "版本更新", "软件更新", "check for updates", "software update",
    "版本说明", "版本信息", "更新日志", "changelog", "release notes",
    "主题色", "主题设置", "外观设置", "屏幕方向", "横屏设置", "竖屏设置",
    "深色模式", "夜间模式", "theme color", "appearance settings", "screen orientation", "dark mode",
    "官方网站", "官网", "备案号", "ICP备", "official website",
    "字数统计", "写作统计", "创作统计", "word count", "writing statistics",
    "给个好评", "去评分", "应用评分", "好评鼓励", "鼓励好评", "rate app", "review app",
)
