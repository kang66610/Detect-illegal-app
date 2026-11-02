"""Role-scoped semantic catalog for visible Appium targets."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class TargetKind(str, Enum):
    DOCUMENT = "document"
    PROFILE_HUB = "profile_hub"
    SETTINGS_HUB = "settings_hub"
    PRIVACY_GOVERNANCE = "privacy_governance"
    REDRESS = "redress"
    MEDIA_ENTRY = "media_entry"
    WITHDRAW_CONSENT = "withdraw_consent"
    ACCOUNT_DELETE = "account_delete"
    LOGIN = "login"
    LOW_VALUE_COMMERCIAL = "low_value_commercial"
    BUSINESS_ACTION = "business_action"
    CONSENT = "consent"
    DECLINE = "decline"


@dataclass(frozen=True)
class TargetCandidate:
    """One executable target from the currently adjudicated interaction surface."""

    target: str
    kind: TargetKind
    label: str
    resource_id: str = ""
    priority: int = 0
    target_id: str = ""
    bounds: str = ""
    execution_layer: str = "page"
    coordinate_only: bool = False
    surface_id: str = "page"


@dataclass(frozen=True)
class TargetCatalogView:
    """Role-scoped lookup API for every consumer of resolved targets."""

    targets: tuple[TargetCandidate, ...]
    has_overlay: bool = False

    def target_for_kind(self, kind: TargetKind, *, label: str = "") -> str | None:
        expected = _normalised_label(label)
        for item in self.targets:
            if item.kind is not kind:
                continue
            candidate = _normalised_label(item.label)
            if not expected or expected in candidate or candidate in expected:
                return item.target
        return None

    def label_for_target(self, target: str) -> str:
        return next((item.label for item in self.targets if item.target == str(target or "")), "")

    def kind_for_target(self, target: str) -> TargetKind | None:
        return next((item.kind for item in self.targets if item.target == str(target or "")), None)

    def resolve(self, value: str) -> str | None:
        raw = str(value or "")
        for item in self.targets:
            if raw in {item.target, item.target_id, item.label, item.resource_id}:
                return item.target
        return None

    def is_overlay_target(self, target: str, kind: TargetKind) -> bool:
        return bool(self.has_overlay and self.kind_for_target(target) is kind)


_TERMS: tuple[tuple[TargetKind, tuple[str, ...], int], ...] = (
    (TargetKind.ACCOUNT_DELETE, ("注销账号", "账号注销", "删除账号", "delete account", "unregister"), 95),
    (TargetKind.WITHDRAW_CONSENT, ("撤回同意", "撤销同意", "撤回授权", "撤销授权", "授权管理", "manage consent"), 95),
    (TargetKind.MEDIA_ENTRY, ("头像", "拍照", "相机", "相册", "图库", "添加图片", "上传图片", "上传附件", "添加附件", "camera", "album", "gallery", "attachment", "avatar"), 90),
    (TargetKind.REDRESS, ("投诉", "举报", "客服", "反馈", "联系我们", "帮助中心", "工单", "申诉", "support", "feedback", "complaint", "contact us", "ticket"), 85),
    (TargetKind.PRIVACY_GOVERNANCE, ("隐私设置", "权限管理", "个人信息", "账号与安全", "隐私中心", "privacy", "permission"), 80),
    (TargetKind.DOCUMENT, ("隐私政策", "隐私声明", "用户协议", "服务协议", "第三方sdk", "收集清单", "privacy policy", "terms of service"), 75),
    (TargetKind.SETTINGS_HUB, ("设置", "setting"), 65),
    (TargetKind.PROFILE_HUB, ("我的", "个人中心", "用户中心", "账户中心", "账号中心", "profile", "account", "mine"), 60),
    (TargetKind.LOGIN, ("登录", "注册", "sign in", "log in"), 45),
    (TargetKind.LOW_VALUE_COMMERCIAL, ("购买", "会员", "充值", "续费", "邀请好友", "红包", "付费刷新", "buy", "vip", "subscribe"), -100),
)
_CONSENT_TERMS = ("同意", "接受", "agree", "accept")
_DECLINE_TERMS = ("不同意", "拒绝", "暂不", "取消", "退出", "decline", "not now", "cancel", "exit")
_DOCUMENT_TERMS = ("隐私政策", "隐私声明", "隐私协议", "用户协议", "服务协议", "服务条款", "privacy policy", "terms of service")
_BOUNDS = re.compile(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$")
_QUOTED_DOCUMENT_TITLE = re.compile(r"《([^》]{1,24})》")


def _identity(element: dict) -> tuple[str, str, str, str]:
    label = " ".join(
        str(element.get(key) or "").strip() for key in ("text", "content_desc")
        if str(element.get(key) or "").strip()
    )
    resource_id = str(element.get("resource_id") or "").strip()
    target = str(element.get("target") or resource_id or label or "").strip()
    compact = re.sub(r"\s+", "", f"{label} {resource_id} {target}").lower()
    return target, label, resource_id, compact


def _bounds(value: str) -> tuple[int, int, int, int] | None:
    match = _BOUNDS.fullmatch(str(value or "").strip())
    if not match:
        return None
    left, top, right, bottom = (int(item) for item in match.groups())
    return (left, top, right, bottom) if right > left and bottom > top else None


def _normalised_label(label: str) -> str:
    return re.sub(r"\s+", "", str(label or "")).lower()


def _consent_kind(label: str) -> TargetKind | None:
    compact = _normalised_label(label)
    if not compact or len(compact) > 32:
        return None
    if any(term in compact for term in _DECLINE_TERMS):
        return TargetKind.DECLINE
    if any(term in compact for term in _DOCUMENT_TERMS):
        return TargetKind.DOCUMENT
    if any(term in compact for term in _CONSENT_TERMS):
        return TargetKind.CONSENT
    return None


def _target_id(*, role: str, kind: TargetKind, label: str, resource_id: str) -> str:
    identity = _normalised_label(label) or _normalised_label(resource_id)
    return f"{role}:{kind.value}:{identity}"


def _normal_candidates(elements: list[dict] | tuple[dict, ...]) -> list[TargetCandidate]:
    candidates: list[TargetCandidate] = []
    seen: set[tuple[str, TargetKind]] = set()
    for element in elements:
        if not element.get("clickable") or not element.get("displayed", True):
            continue
        target, label, resource_id, identity = _identity(element)
        if not target:
            continue
        matched = next((
            (kind, priority)
            for kind, terms, priority in _TERMS
            if any(_normalised_label(term) in identity for term in terms)
        ), (TargetKind.BUSINESS_ACTION, 10))
        key = (target, matched[0])
        if key in seen:
            continue
        seen.add(key)
        candidates.append(TargetCandidate(
            target=target, kind=matched[0], label=label, resource_id=resource_id,
            priority=matched[1],
            target_id=_target_id(role="page", kind=matched[0], label=label, resource_id=resource_id),
            surface_id="page",
        ))
    return candidates


def _consent_candidates(elements: list[dict] | tuple[dict, ...]) -> list[TargetCandidate]:
    """Create targets only for the adjudicated consent overlay.

    WebView text controls require a bounded coordinate tap. Native dialog
    controls remain normal accessibility targets, even when a lightweight UI
    tree omits their bounds.  Neither representation admits background-page
    nodes because this function only recognizes consent/document semantics.
    """
    candidates: list[TargetCandidate] = []
    seen: set[str] = set()
    for element in elements:
        if not element.get("displayed", True):
            continue
        _target, label, resource_id, _identity_value = _identity(element)
        kind = _consent_kind(label)
        bounds = str(element.get("bounds") or "").strip()
        if kind is None:
            continue
        bounded = _bounds(bounds)
        if bounded is None and not element.get("clickable"):
            continue
        target_id = _target_id(role="consent_dialog", kind=kind, label=label, resource_id=resource_id)
        if target_id in seen:
            continue
        seen.add(target_id)
        candidates.append(TargetCandidate(
            target=(f"bounds:{bounds}" if bounded else _target),
            kind=kind, label=label, resource_id=resource_id,
            priority={TargetKind.CONSENT: 100, TargetKind.DECLINE: 95, TargetKind.DOCUMENT: 90}[kind],
            target_id=target_id, bounds=bounds, execution_layer="overlay",
            coordinate_only=bool(bounded),
            surface_id="consent_dialog",
        ))
    # Some native splash dialogs expose only a single non-clickable sentence
    # containing ClickableSpan titles. They are still semantic overlay routes,
    # but only quoted/known document titles are admitted; ordinary prose never
    # becomes an executable coordinate target.
    for element in elements:
        if not element.get("displayed", True):
            continue
        label = " ".join(
            str(element.get(key) or "").strip() for key in ("text", "content_desc")
            if str(element.get(key) or "").strip()
        )
        for inner in _QUOTED_DOCUMENT_TITLE.findall(label):
            title = f"《{inner}》"
            kind = _consent_kind(title)
            if kind is not TargetKind.DOCUMENT:
                continue
            target_id = _target_id(
                role="consent_dialog", kind=kind, label=title, resource_id="",
            )
            if target_id in seen:
                continue
            seen.add(target_id)
            candidates.append(TargetCandidate(
                target=title, kind=kind, label=title, priority=90,
                target_id=target_id, execution_layer="overlay", surface_id="consent_dialog",
            ))
    return candidates


def build_target_catalog(
    elements: list[dict] | tuple[dict, ...], *, role: str = "app_page",
) -> tuple[TargetCandidate, ...]:
    """Return only targets executable on the selected page role's surface."""
    candidates = _consent_candidates(elements) if str(role) == "consent_dialog" else _normal_candidates(elements)
    return tuple(sorted(candidates, key=lambda item: (-item.priority, item.target_id, item.target)))


def matching_elements(target: str, elements: list[dict]) -> list[dict]:
    raw = str(target or "").strip()
    if not raw:
        return []
    semantic = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", raw).lower()
    rows = []
    for element in elements:
        if not element.get("displayed", True):
            continue
        values = tuple(str(element.get(key) or "") for key in ("target", "resource_id", "text", "content_desc"))
        normalized = {re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).lower() for value in values if value}
        if raw in values or (semantic and semantic in normalized):
            rows.append(element)
    return rows


def _contains(parent: tuple[int, int, int, int], child: tuple[int, int, int, int]) -> bool:
    return (
        parent[0] <= child[0] and parent[1] <= child[1]
        and parent[2] >= child[2] and parent[3] >= child[3]
    )


def tightest_clickable_host(
    elements: list[dict], child: dict, *, is_unsafe_host=None,
) -> dict | None:
    child_rect = _bounds(str(child.get("bounds") or ""))
    if not child_rect:
        return None
    best = None
    best_area = None
    for item in elements:
        if item is child or not item.get("clickable"):
            continue
        if is_unsafe_host is not None and is_unsafe_host(item):
            continue
        parent_rect = _bounds(str(item.get("bounds") or ""))
        if not parent_rect or not _contains(parent_rect, child_rect):
            continue
        area = (parent_rect[2] - parent_rect[0]) * (parent_rect[3] - parent_rect[1])
        if best_area is None or area < best_area:
            best, best_area = item, area
    return best


def bounds_retry_target(target: str, elements: list[dict], *, is_unsafe_host=None) -> str:
    raw = str(target or "").strip()
    if not raw or raw.startswith(("bounds:", "relative:")):
        return ""
    child = None
    for item in matching_elements(raw, elements):
        bounds = str(item.get("bounds") or "")
        if item.get("clickable") and _bounds(bounds):
            return f"bounds:{bounds}"
        child = child or item
    host = tightest_clickable_host(elements, child, is_unsafe_host=is_unsafe_host) if child else None
    bounds = str((host or {}).get("bounds") or "")
    return f"bounds:{bounds}" if _bounds(bounds) else ""


def labels_for_target(target: str, elements: list[dict], *, label_for_element) -> str:
    matched = matching_elements(target, elements)
    labels = [label_for_element(item) for item in matched]
    for item in elements:
        host = tightest_clickable_host(elements, item)
        if host is None:
            continue
        values = {
            str(host.get("target") or ""), str(host.get("resource_id") or ""),
            str(host.get("text") or ""), str(host.get("content_desc") or ""),
        }
        if str(target or "") in values:
            labels.append(label_for_element(item))
    return " ".join(part for part in labels if part) or str(target or "")


def identity_values_for_target(target: str, elements: list[dict]) -> list[str]:
    """Return page-local visible identity, including children of a bounds row."""
    raw = str(target or "")
    values = [raw]
    bounds = raw[len("bounds:"):].strip() if raw.startswith("bounds:") else ""
    target_rect = _bounds(bounds) if bounds else None
    for item in elements:
        item_values = [str(item.get(key) or "") for key in ("target", "resource_id", "text", "content_desc")]
        item_bounds = str(item.get("bounds") or "")
        item_rect = _bounds(item_bounds) if target_rect else None
        contained = bool(target_rect and item_rect and _contains(target_rect, item_rect))
        if raw and (raw in item_values or (bounds and bounds == item_bounds) or contained):
            values.extend(item_values)
    return values


def llm_catalog_elements(targets: tuple[TargetCandidate, ...]) -> list[dict]:
    """Project the already-adjudicated catalog into the LLM whitelist shape."""
    return [
        {
            "target": item.target,
            "text": item.label,
            "content_desc": item.label,
            "resource_id": item.resource_id,
            "bounds": item.bounds,
            "clickable": True,
            "displayed": True,
            "semantic_target_id": item.target_id,
            "execution_layer": item.execution_layer,
        }
        for item in targets
    ]


DOCUMENT_TITLE_GROUPS = (
    frozenset({
        "隐私政策", "隐私声明", "隐私协议",
        "privacypolicy", "privacystatement", "privacyagreement",
    }),
    frozenset({"用户协议", "用户服务协议", "useragreement"}),
    frozenset({"个人信息收集清单", "信息收集清单", "个人信息清单"}),
    frozenset({
        "第三方sdk目录", "sdk目录", "第三方sdk", "sdk清单",
        "第三方信息共享清单", "第三方信息共享",
    }),
)

REQUIRED_DOCUMENT_KIND_TERMS = (
    ("privacy_policy", (
        "隐私政策", "隐私声明", "隐私协议", "隐私条款",
        "privacy policy", "privacy statement", "privacy agreement", "privacy terms",
    )),
    ("user_agreement", ("用户服务协议", "用户协议", "user agreement", "user terms")),
    ("service_terms", (
        "服务协议", "服务条款", "使用条款", "使用协议",
        "terms of service", "terms of use", "service agreement",
    )),
    ("disclosure_list", (
        "个人信息收集清单", "信息收集清单", "个人信息清单", "收集个人信息清单",
        "第三方sdk目录", "第三方sdk清单", "第三方sdk", "sdk目录", "sdk清单", "sdk列表",
        "第三方信息共享", "第三方共享清单", "与第三方共享", "个人信息共享清单",
        "应用权限说明", "权限说明清单",
    )),
)

DOCUMENT_KIND_ID_HINTS = {
    "privacy_policy": ("privacy", "policy", "private", "yinsi", "yszc"),
    "user_agreement": ("useragree", "user_agree", "yhxy"),
    "service_terms": ("terms", "agreement", "protocol", "tos", "fwxy"),
    "disclosure_list": ("sdk", "third", "collect", "share", "qdml"),
}


def element_label(element: dict) -> str:
    return " ".join(str(element.get(key) or "") for key in ("text", "content_desc", "resource_id", "target"))


def labels_for_click_target(target: str, elements: list[dict]) -> str:
    """Include nested row titles: settings often put 服务协议 on a child TextView."""
    return labels_for_target(target, elements, label_for_element=element_label)


def document_kinds_in(label: str) -> list[str]:
    """Return families mentioned in a label without collapsing distinct titles.

    《用户服务协议》 contains the shorter token 服务协议; keep the longer match
    so one book-title is not counted as two families.
    """
    normalized = re.sub(r"\s+", "", str(label or "")).lower()
    if not normalized:
        return []
    spans: list[tuple[int, int, int, str]] = []
    for kind, terms in REQUIRED_DOCUMENT_KIND_TERMS:
        for term in terms:
            needle = term.lower()
            start = 0
            while True:
                index = normalized.find(needle, start)
                if index < 0:
                    break
                spans.append((len(needle), index, index + len(needle), kind))
                start = index + 1
    spans.sort(reverse=True)
    used: list[tuple[int, int]] = []
    found: list[str] = []
    for _length, start, end, kind in spans:
        if any(start < used_end and end > used_start for used_start, used_end in used):
            continue
        used.append((start, end))
        if kind not in found:
            found.append(kind)
    return found


def required_document_kind(label: str) -> str | None:
    # Compare compact forms on both sides.  English labels such as
    # ``Privacy Policy`` used to be compacted only on the page side, so the
    # space-containing term never matched and the same body received a raw
    # title key on the next viewport (causing duplicate reads).
    compact_label = re.sub(r"\s+", "", str(label or "")).lower()
    matched = [
        (kind, term)
        for kind, terms in REQUIRED_DOCUMENT_KIND_TERMS
        for term in terms
        if re.sub(r"\s+", "", term).lower() in compact_label
    ]
    if not matched:
        return None
    kind, _term = max(matched, key=lambda item: len(item[1]))
    return kind


def infer_document_kind(target: str, page_text: str = "") -> str | None:
    """Prefer on-screen labels over resource-id heuristics.

    Ids like ``oi_private`` must not override a visible “服务协议”/“用户协议”
    caption, otherwise already-read skips and timeline labels drift from what
    the tester actually saw.
    """
    kind = required_document_kind(page_text) or required_document_kind(target)
    if kind:
        return kind
    lowered = str(target or "").lower()
    ranked: list[tuple[int, str]] = []
    for kind_name, hints in DOCUMENT_KIND_ID_HINTS.items():
        for hint in hints:
            if hint in lowered:
                ranked.append((len(hint), kind_name))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    names = {item[1] for item in ranked}
    if "privacy_policy" in names:
        return "privacy_policy"
    return ranked[0][1]


def document_body_kind_from_text(page_text: str) -> str | None:
    """Infer the clause family from the opened body, not from the click label."""
    compact = re.sub(r"\s+", "", str(page_text or ""))
    if not compact:
        return None
    # Prefer an explicit book title near the start of the body.
    head = compact[:240]
    for kind, terms in REQUIRED_DOCUMENT_KIND_TERMS:
        for term in sorted(terms, key=len, reverse=True):
            needle = re.sub(r"\s+", "", term)
            if not needle:
                continue
            if f"《{needle}》" in head or head.startswith(needle) or needle in head[:80]:
                return kind
    return required_document_kind(head) or required_document_kind(compact[:400])


def preferred_inline_document_target(label: str, kind: str) -> str | None:
    """Return a short book-title / term to tap — never the whole consent sentence.

    First-run dialogs often embed 《隐私政策》 inside one TextView or checkbox
    caption.  Clicking that long caption toggles consent instead of opening the
    document; Appium must resolve the short title via textContains / bounds.
    """
    compact = re.sub(r"\s+", "", str(label or ""))
    if not compact:
        return None
    compact_lower = compact.lower()
    terms = sorted(dict(REQUIRED_DOCUMENT_KIND_TERMS).get(kind, ()), key=len, reverse=True)
    for term in terms:
        book = f"《{term}》"
        index = compact_lower.find(book.lower())
        if index >= 0:
            # Preserve on-screen casing (e.g. 《第三方SDK目录》 vs lowercased terms).
            return compact[index: index + len(book)]
    for term in terms:
        if compact_lower == term.lower() or compact_lower == f"《{term}》".lower():
            return compact
    for term in terms:
        if term.lower() in compact_lower and len(compact) <= len(term) + 6:
            if any(cue in compact for cue in ("我已阅读", "已阅读并同意", "已同意")):
                continue
            return term
    return None


def normalize_document_title(value: str) -> str:
    return re.sub(r"[\s《》\"'“”]+", "", str(value or "")).lower()


def document_title_already_read(title: str, read_titles: set[str]) -> bool:
    """True when this on-screen name is the same clause already opened."""
    normalized = normalize_document_title(title)
    if not normalized:
        return False
    read_titles = {normalize_document_title(item) for item in read_titles}
    if normalized in read_titles:
        return True
    for group in DOCUMENT_TITLE_GROUPS:
        if normalized in group and (group & read_titles):
            return True
    return False


def inline_document_titles_in(blob: str) -> list[str]:
    """Independent book titles mentioned in one caption or settings row."""
    titles: list[str] = []
    seen: set[str] = set()
    for kind, _terms in REQUIRED_DOCUMENT_KIND_TERMS:
        short = preferred_inline_document_target(blob, kind)
        key = normalize_document_title(short or "")
        if short and key not in seen:
            seen.add(key)
            titles.append(short)
    return titles


def global_target_key(activity: str, target: str, elements: list[dict]) -> str:
    """Build a stable cross-page identity for a candidate click.

    Page fingerprints legitimately change after a WebView redraw or a tab
    switch, so page-local visited sets are not enough to stop a semantic route
    from cycling forever.  Resolve bounds targets to their visible child labels
    and strip coordinates/counters before counting the route globally.
    """
    identities = identity_values_for_target(target, elements)
    semantic = [value for value in identities if value and not value.lower().startswith("bounds:")]
    normalized = re.sub(r"\d+", "#", " ".join(semantic).lower())
    normalized = re.sub(r"(?:[a-z0-9_.]+:id/)", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    # Meaningful labels/resource suffixes identify the same route across
    # single-Activity redraws and vendor wrapper Activities. Generic dialog
    # actions remain activity-scoped so unrelated “确定/保存” buttons do not
    # collapse into one global edge.
    generic = {"", "确定", "取消", "保存", "返回", "关闭", "ok", "cancel", "back", "close"}
    if normalized not in generic and len(re.sub(r"\W+", "", normalized)) >= 3:
        return f"route|{normalized[:220]}"
    return f"{str(activity or '').strip().lower()}|{normalized[:220]}"


def element_locator(element: dict) -> str:
    target = str(element.get("target") or "").strip()
    if target:
        return target
    resource_id = str(element.get("resource_id") or "").strip()
    if resource_id:
        return resource_id
    text = str(element.get("text") or "").strip()
    if text:
        return text
    desc = str(element.get("content_desc") or "").strip()
    if desc:
        return desc
    bounds = str(element.get("bounds") or "").strip()
    if bounds:
        return f"bounds:{bounds}"
    return str(element.get("target") or "").strip()


def element_semantic_identity(element: dict, elements: list[dict] | None = None) -> str:
    """Identity for matching, including labels on non-clickable children in the row."""
    parts = [
        str(element.get(key) or "")
        for key in ("resource_id", "text", "content_desc", "target")
    ]
    parent_rect = _bounds(str(element.get("bounds") or ""))
    if elements and parent_rect and element.get("clickable"):
        for child in elements:
            if child is element or child.get("clickable"):
                continue
            child_rect = _bounds(str(child.get("bounds") or ""))
            if not child_rect:
                continue
            contained = (
                parent_rect[0] <= child_rect[0] and parent_rect[1] <= child_rect[1]
                and parent_rect[2] >= child_rect[2] and parent_rect[3] >= child_rect[3]
            )
            if contained:
                parts.extend(
                    str(child.get(key) or "") for key in ("text", "content_desc", "resource_id")
                )
    return " ".join(parts)
