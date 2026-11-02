"""Document reading state: per-run ledgers and already-read truth.

Owns the runtime-keyed reading ledgers (read/failed/blocked titles and kinds)
and the "already read" adjudication used by the explorer loop, plus the unread
gap resolution that walks one page's clause links. The pure clause vocabulary
(kinds, titles, id hints) lives in target_catalog and the consent-control
predicates in consent_vocabulary; the ledgers have exactly one owner — this
module.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from agent.ai_explorer.consent_vocabulary import (
    consent_or_decline_control,
    is_checkbox_like,
)
from agent.ai_explorer.decision_directive import DecisionDirective
from agent.ai_explorer.page_state import PageState
from agent.ai_explorer.target_catalog import (
    DOCUMENT_KIND_ID_HINTS,
    # Re-exported for explorer_engine (`DOCUMENT_TITLE_GROUPS as _DOCUMENT_TITLE_GROUPS`).
    DOCUMENT_TITLE_GROUPS,
    REQUIRED_DOCUMENT_KIND_TERMS,
    document_body_kind_from_text,
    document_kinds_in,
    document_title_already_read,
    element_label,
    element_locator,
    infer_document_kind,
    inline_document_titles_in,
    labels_for_click_target,
    normalize_document_title,
    preferred_inline_document_target,
    required_document_kind,
    tightest_clickable_host,
)
from agent.detection_engines.base import DetectionContext


def schedule_document_route_retry(runtime: dict, target: str, *, retry_limit: int = 1) -> bool:
    """Queue one failed first-run document route for another attempt."""
    route = str(target or "").strip()
    if not route:
        return False
    attempts = runtime.setdefault("document_route_retry_attempts", {})
    count = max(0, int(attempts.get(route, 0) or 0))
    if count >= max(0, int(retry_limit)):
        return False
    attempts[route] = count + 1
    pending = runtime.setdefault("pending_document_route_retries", [])
    if route not in pending:
        pending.append(route)
    return True


def pending_document_route_retry(runtime: dict) -> str:
    """Return the oldest first-run clause that must be retried before consent."""
    pending = runtime.get("pending_document_route_retries") or []
    return next((str(target) for target in pending if str(target or "")), "")


def clear_document_route_retry(runtime: dict, target: str) -> None:
    """Forget a retry only after its own expected document body was verified."""
    route = str(target or "").strip()
    if not route:
        return
    runtime["pending_document_route_retries"] = [
        item for item in (runtime.get("pending_document_route_retries") or [])
        if str(item) != route
    ]


def _document_route_retry_limit(ctx: DetectionContext) -> int:
    return max(0, int(ctx.cfg.get("detection", {}).get("initial_document_route_retry_limit", 1)))


def handle_consent_document_crash_retry(
    ctx: DetectionContext,
    target: str,
    *,
    activity: str,
    step: int,
    reason: str,
    forget_target: Callable[[str], object],
    emit: Callable[..., object],
) -> bool:
    """Retry the exact first-run clause before marking a crash route skipped."""
    route = str(target or "")
    first_run = bool(
        route
        and not ctx.runtime.get("consent_accepted")
        and (infer_document_kind(route, "") or required_document_kind(route))
    )
    scheduled = bool(
        first_run
        and schedule_document_route_retry(
            ctx.runtime, route, retry_limit=_document_route_retry_limit(ctx),
        )
    )
    if scheduled:
        forget_target(route)
        emit(
            "consent_document_crash_retry_scheduled",
            activity=activity,
            target=route,
            step=step,
            reason="首次同意页条款点击后应用崩溃；重启后优先重新阅读同一条款",
        )
    if route and not scheduled:
        ctx.runtime.setdefault("crash_skip_targets", set()).add(route)
    if not scheduled and any(term in str(reason).lower() for term in ("webview", "inflateexception")):
        ctx.runtime["skip_in_app_webview"] = True
    if not scheduled:
        gap = f"应用发生崩溃后已尝试恢复（{str(reason)[:160]}）；相关入口已跳过"
        ctx.runtime.setdefault("rule_coverage_gaps", []).append(gap)
    return scheduled


def reconcile_document_completion_route(
    ctx: DetectionContext,
    completion: object,
    *,
    activity: str,
    page_text: str,
    forget_target: Callable[[str], object],
    emit: Callable[..., object],
) -> bool:
    """Requeue a route when its click opened a different document body."""
    entry_target = str(getattr(completion, "entry_target", "") or "")
    if not bool(getattr(completion, "mismatch", False)):
        clear_document_route_retry(ctx.runtime, entry_target)
        return False
    scheduled = schedule_document_route_retry(
        ctx.runtime, entry_target, retry_limit=_document_route_retry_limit(ctx),
    )
    if scheduled:
        forget_target(entry_target)
    expected = str(getattr(completion, "expected_kind", "") or "")
    observed = str(getattr(completion, "observed_kind", "") or "")
    emit(
        "document_kind_mismatch",
        activity=activity,
        target=entry_target,
        actual_target=str(getattr(completion, "actual_title", "") or ""),
        expected=expected,
        observed=observed,
        retry_scheduled=scheduled,
        reason=(
            "点击入口与实际正文不一致；正文按实际条款记账，并重新尝试原入口"
            if scheduled else "点击入口与实际正文不一致；原入口重试次数已耗尽"
        ),
    )
    if scheduled:
        emit(
            "document_route_retry_scheduled",
            activity=activity,
            target=entry_target,
            expected=expected,
            observed=observed,
            reason="原条款入口展示了另一份正文，返回首次同意页后优先重试原条款",
        )
    else:
        block_document_route(ctx, entry_target, page_text=page_text)
    return scheduled


class CombinedDocumentRedirectPolicy:
    """Build a candidate for the unread title embedded in a combined caption."""

    def directive(
        self,
        *,
        action: str,
        target: str,
        unread_titles: tuple[str, ...] | list[str],
        has_overlay: bool,
    ) -> DecisionDirective | None:
        titles = tuple(str(title or "") for title in unread_titles if str(title or ""))
        if (
            str(action or "") != "click"
            or not str(target or "")
            or not titles
            or bool(has_overlay)
        ):
            return None
        normalized_target = normalize_document_title(target)
        if normalized_target in {normalize_document_title(title) for title in titles}:
            return None
        return DecisionDirective(
            action="click",
            target=titles[0],
            reason="合并文案中仍有未阅读的独立条款，改开该书名号",
            source="deterministic_document",
            priority=150,
        )


def host_is_unsafe_document_click(element: dict) -> bool:
    return consent_or_decline_control(element) or is_checkbox_like(element)


def tightest_enclosing_clickable(elements: list[dict], child: dict) -> dict | None:
    return tightest_clickable_host(
        elements, child, is_unsafe_host=host_is_unsafe_document_click,
    )


def clickable_host_for_document_kind(elements: list[dict], kind: str, child: dict | None = None) -> dict | None:
    if child is not None:
        enclosed = tightest_enclosing_clickable(elements, child)
        if enclosed:
            return enclosed
    hints = DOCUMENT_KIND_ID_HINTS.get(kind) or ()
    for element in elements:
        if not element.get("clickable") or host_is_unsafe_document_click(element):
            continue
        resource_id = str(element.get("resource_id") or "").lower()
        if hints and any(hint in resource_id for hint in hints):
            return element
    return None


def quoted_or_exact_document_titles(label: str, kind: str) -> list[str]:
    """Only 《隐私政策》 style marks or a dedicated short label are tappable names."""
    compact = re.sub(r"\s+", "", str(label or ""))
    compact_lower = compact.lower()
    titles: list[str] = []
    for term in dict(REQUIRED_DOCUMENT_KIND_TERMS).get(kind, ()):
        book = f"《{term}》"
        index = compact_lower.find(book.lower())
        if index >= 0:
            titles.append(compact[index: index + len(book)])
        elif compact_lower == term.lower() or compact_lower == book.lower():
            titles.append(compact)
        elif f"《{term}》".lower() in compact_lower:
            # already handled by index; keep for symmetry
            pass
    titles.sort(key=len, reverse=True)
    return titles


def consent_instruction_label(label: str) -> bool:
    """Long 'please tick to agree …《隐私政策》…' captions are not document links."""
    compact = re.sub(r"\s+", "", str(label or ""))
    if len(compact) < 16:
        return False
    return any(
        cue in compact
        for cue in ("请勾选", "请阅读并同意", "阅读并同意", "勾选阅读", "请先阅读", "请仔细阅读并同意")
    ) and bool(document_kinds_in(compact))


def inline_document_title_is_safe(elements: list[dict], title: str) -> bool:
    """Do not fire textContains against a checkbox; that would toggle consent."""
    compact_title = re.sub(r"\s+", "", title).lower()
    if len(compact_title) < 4:
        return False
    hosts = [
        item for item in elements
        if compact_title in re.sub(r"\s+", "", element_label(item)).lower()
    ]
    if not hosts:
        return True
    return any(not is_checkbox_like(item) for item in hosts)


def kind_has_direct_clickable_entry(elements: list[dict], kind: str) -> bool:
    for element in elements:
        if kind not in document_kinds_in(element_label(element)):
            continue
        if element.get("clickable") and not host_is_unsafe_document_click(element):
            return True
        if not element.get("clickable") and clickable_host_for_document_kind(elements, kind, element) is not None:
            return True
    return False


def unread_inline_titles_for_target(
    ctx: DetectionContext, target: str, elements: list[dict],
) -> list[str]:
    """Unread 《书名号》 still sitting inside a combined caption or host id."""
    blob = labels_for_click_target(target, elements)
    read_titles = read_document_titles(ctx)
    return [
        short for short in inline_document_titles_in(blob)
        if not document_title_already_read(short, read_titles)
    ]


def unread_required_document_target(
    elements: list[dict], visited_targets: set[str], read_kinds: set[str] | None = None,
    *, failed_kinds: set[str] | None = None,
    read_titles: set[str] | None = None, failed_titles: set[str] | None = None,
    blocked_targets: set[str] | None = None,
    skip_kinds: set[str] | None = None,
) -> str | None:
    """Next privacy/terms/SDK link that this audit has not actually opened.

    Distinct on-screen titles are independent even when they share a family.
    Reading 《使用条款》 does not consume 《用户协议》. Kind-level ``read_kinds``
    only suppresses a family when no unread title of that family remains.
    ``skip_kinds`` defers families (e.g. disclosure_list on the consent sheet)
    to settings/profile/about hubs.
    """
    read_kinds = {str(kind) for kind in (read_kinds or set())}
    failed_kinds = {str(kind) for kind in (failed_kinds or set())}
    read_titles = {normalize_document_title(item) for item in (read_titles or set())}
    failed_titles = {normalize_document_title(item) for item in (failed_titles or set())}
    blocked_targets = {str(item) for item in (blocked_targets or set())}
    skip_kinds = {str(kind) for kind in (skip_kinds or set())}
    # Short titles are safe only when they can be resolved away from a checkbox;
    # first-run callers verify that the click really opened a document.
    allow_inline_titles = True
    candidates: list[tuple[int, int, str]] = []
    seen_targets: set[str] = set()

    def add_candidate(kind: str, target: str) -> None:
        if not target or target in visited_targets or target in seen_targets or target in blocked_targets:
            return
        if kind in skip_kinds:
            return
        seen_targets.add(target)
        priority = {"privacy_policy": 0, "user_agreement": 1, "service_terms": 1, "disclosure_list": 2}[kind]
        candidates.append((priority, -len(target), target))

    for element in elements:
        label = element_label(element)
        kinds = document_kinds_in(label)
        if not kinds:
            continue
        if consent_or_decline_control(element) and not is_checkbox_like(element):
            continue
        instruction = consent_instruction_label(label) or is_checkbox_like(element)
        raw_target = str(
            element.get("target") or element.get("resource_id") or element.get("text")
            or element.get("content_desc") or ""
        ).strip()
        clickable_link = (
            bool(element.get("clickable"))
            and not host_is_unsafe_document_click(element)
            and not instruction
        )
        for kind in kinds:
            short_title = preferred_inline_document_target(label, kind)
            visible_name = " ".join(
                str(element.get(key) or "") for key in ("text", "content_desc")
            ).strip()
            title_key = normalize_document_title(short_title or visible_name or raw_target)
            if title_key and (
                title_key in read_titles
                or title_key in failed_titles
                or document_title_already_read(title_key, read_titles)
            ):
                continue
            if visible_name and document_title_already_read(visible_name, read_titles):
                continue
            if raw_target and document_title_already_read(raw_target, read_titles):
                continue
            if kind in failed_kinds:
                continue
            options: list[str] = []
            if short_title and (allow_inline_titles or instruction or len(kinds) > 1):
                # Always prefer 《隐私政策》 over a long caption that merely mentions it.
                if inline_document_title_is_safe(elements, short_title):
                    options.append(short_title)
            if clickable_link:
                if raw_target and len(kinds) == 1 and not instruction and len(raw_target) <= 24:
                    options.append(raw_target)
                if short_title and short_title not in options:
                    options.append(short_title)
            else:
                host = clickable_host_for_document_kind(elements, kind, element)
                if host is not None and not instruction:
                    host_target = element_locator(host)
                    child_text = str(element.get("text") or element.get("content_desc") or "").strip()
                    preferred_child = preferred_inline_document_target(child_text, kind)
                    if preferred_child:
                        options.append(preferred_child)
                    elif child_text and len(child_text) <= 24 and quoted_or_exact_document_titles(child_text, kind):
                        options.append(child_text)
                    if host_target and len(host_target) <= 48:
                        options.append(host_target)
                elif (
                    allow_inline_titles
                    and not is_checkbox_like(element)
                    and not kind_has_direct_clickable_entry(elements, kind)
                    and short_title
                    and inline_document_title_is_safe(elements, short_title)
                ):
                    options.append(short_title)
            for target in options:
                add_candidate(kind, target)
    candidates.sort()
    return candidates[0][2] if candidates else None


def unread_for_page(ctx: DetectionContext, elements: list[dict], visited_targets: set[str]) -> str | None:
    visited = set(visited_targets)
    blocked = set(ctx.runtime.get("blocked_document_targets") or set())
    blocked_titles = set(ctx.runtime.get("blocked_document_titles") or set())
    while True:
        target = unread_required_document_target(
            elements, visited, read_document_kinds(ctx),
            failed_kinds=exhausted_document_kinds(ctx),
            read_titles=read_document_titles(ctx),
            failed_titles=failed_inline_document_titles(ctx) | blocked_titles,
            blocked_targets=blocked,
        )
        if not target:
            return None
        if already_read_document_target(ctx, target, elements):
            visited.add(target)
            blocked.add(target)
            continue
        return target


def click_reopens_incomplete_document(ctx: DetectionContext, target: str) -> bool:
    blob = normalize_document_title(target)
    if not blob:
        return False
    for item in ctx.runtime.get("incomplete_documents") or []:
        title = str((item or {}).get("document") or "").rsplit(":document:", 1)[-1]
        if title and normalize_document_title(title) in blob:
            return True
    return False


def consent_document_titles(ctx: DetectionContext) -> set[str]:
    raw = ctx.runtime.get("consent_document_titles")
    if isinstance(raw, list):
        raw = {normalize_document_title(item) for item in raw}
    elif not isinstance(raw, set):
        raw = set()
    ctx.runtime["consent_document_titles"] = raw
    return raw


def remember_consent_document_titles(ctx: DetectionContext, elements: list[dict]) -> None:
    """Keep first-run book titles even after the accessibility tree shrinks.

    Instruction captions are not themselves tappable entries, but the named
    《隐私政策》 / 《隐私协议》 / 《用户协议》 remain unread obligations until opened.
    """
    titles = consent_document_titles(ctx)
    for element in elements:
        label = element_label(element)
        for kind in document_kinds_in(label):
            short = preferred_inline_document_target(label, kind)
            if short:
                titles.add(normalize_document_title(short))


def unread_remembered_consent_title(ctx: DetectionContext, visited_targets: set[str]) -> str | None:
    read_titles = read_document_titles(ctx)
    failed_titles = failed_inline_document_titles(ctx)
    failed_kinds = failed_inline_document_kinds(ctx)
    pending: list[str] = []
    for title in consent_document_titles(ctx):
        if not title or document_title_already_read(title, read_titles):
            continue
        if normalize_document_title(title) in failed_titles:
            continue
        kind = required_document_kind(title)
        if kind and kind in failed_kinds:
            continue
        display = title if title.startswith("《") else f"《{title}》"
        if title in visited_targets or display in visited_targets:
            continue
        pending.append(title)
    if not pending:
        return None
    rank = {"privacy_policy": 0, "user_agreement": 1, "service_terms": 1, "disclosure_list": 2}

    def sort_key(title: str) -> tuple[int, int]:
        kind = required_document_kind(title) or ""
        return (rank.get(kind, 9), -len(title))

    best = sorted(pending, key=sort_key)[0]
    return best if best.startswith("《") else f"《{best}》"


def already_read_document_target(ctx: DetectionContext, target: str, elements: list[dict]) -> bool:
    """Settings rows reuse different ids for clauses already read on first-run.

    A combined caption that still names an unread book-title is not fully
    read.  Clicking that host must open the unread title, not skip the node.
    """
    if not target:
        return False
    completed_routes = {
        normalize_document_title(item)
        for item in (ctx.runtime.get("completed_document_routes") or set())
        if item
    }
    if normalize_document_title(target) in completed_routes:
        return True
    read_titles = read_document_titles(ctx)
    read_kinds = read_document_kinds(ctx)
    if not read_titles and not read_kinds:
        return False
    observed_routes = dict(ctx.runtime.get("document_route_observed_kinds") or {})
    route_aliases = {
        normalize_document_title(item)
        for item in (target, labels_for_click_target(target, elements)) if item
    }
    expected_kind = infer_document_kind(target, labels_for_click_target(target, elements))
    observed_kinds = {
        str(observed_routes.get(alias) or "")
        for alias in route_aliases
        if observed_routes.get(alias)
    }
    if any(kind in read_kinds for kind in observed_kinds):
        # A reused WebView may show 用户协议 after a 隐私政策 click. The actual
        # agreement is valid evidence for itself, but it must not consume the
        # privacy route: retry the visible clause before declaring it blocked.
        if expected_kind and any(kind != expected_kind for kind in observed_kinds):
            return False
        return True
    unread_inline = unread_inline_titles_for_target(ctx, target, elements)
    if unread_inline:
        return False
    blob = labels_for_click_target(target, elements)
    remembered_unread = [
        title for title in consent_document_titles(ctx)
        if title and not document_title_already_read(title, read_titles)
    ]
    if remembered_unread:
        node = normalize_document_title(f"{target} {blob}")
        if any(title in node or node in title for title in remembered_unread):
            return False
    if inline_document_titles_in(blob):
        return True
    compact = normalize_document_title(blob)
    if any(document_title_already_read(item, read_titles) for item in (target, blob, compact) if item):
        return True
    kind = infer_document_kind(target, blob)
    if kind and kind in read_kinds:
        # Same family, different on-screen titles stay independent: reading
        # 《服务协议》 must not consume 《使用条款》. Only unread titles that
        # actually appear on this node keep the target open.
        if kind == "service_terms":
            node_blob = normalize_document_title(f"{target} {blob}")
            unread_on_this_node = [
                title for title in visible_required_document_titles(elements)
                if required_document_kind(title) == "service_terms"
                and not document_title_already_read(title, read_titles)
                and normalize_document_title(title) in node_blob
            ]
            return not unread_on_this_node
        return True
    return False


def read_document_titles(ctx: DetectionContext) -> set[str]:
    raw = ctx.runtime.get("read_document_titles") or set()
    if isinstance(raw, list):
        raw = {normalize_document_title(item) for item in raw}
        ctx.runtime["read_document_titles"] = raw
    return raw


def failed_inline_document_titles(ctx: DetectionContext) -> set[str]:
    raw = ctx.runtime.get("failed_inline_document_titles")
    if isinstance(raw, list):
        raw = {normalize_document_title(item) for item in raw}
    elif not isinstance(raw, set):
        raw = set()
    ctx.runtime["failed_inline_document_titles"] = raw
    return raw


def visible_required_document_titles(elements: list[dict]) -> set[str]:
    titles: set[str] = set()
    for element in elements:
        label = element_label(element)
        for kind in document_kinds_in(label):
            short = preferred_inline_document_target(label, kind)
            if short:
                titles.add(normalize_document_title(short))
    return titles


def read_document_kinds(ctx: DetectionContext) -> set[str]:
    raw = ctx.runtime.get("read_document_kinds") or set()
    if isinstance(raw, list):
        raw = set(raw)
        ctx.runtime["read_document_kinds"] = raw
    return raw


def failed_inline_document_kinds(ctx: DetectionContext) -> set[str]:
    """Kinds whose consent-dialog links were tapped but never opened a document."""
    raw = ctx.runtime.get("failed_inline_document_kinds")
    if isinstance(raw, list):
        raw = set(raw)
    elif not isinstance(raw, set):
        raw = set()
    ctx.runtime["failed_inline_document_kinds"] = raw
    return raw


def blocked_document_kinds(ctx: DetectionContext) -> set[str]:
    """Kinds that already burned an open/scroll budget and must not be reopened."""
    raw = ctx.runtime.get("blocked_document_kinds")
    if isinstance(raw, list):
        raw = set(raw)
    elif not isinstance(raw, set):
        raw = set()
    ctx.runtime["blocked_document_kinds"] = raw
    return raw


def block_document_route(
    ctx: DetectionContext,
    target: str,
    *,
    kind: str | None = None,
    page_text: str = "",
) -> str | None:
    """Stop reopening the same clause via alternate ids/titles after a failed/capped read."""
    if target:
        ctx.runtime.setdefault("blocked_document_targets", set()).add(str(target))
    resolved = kind or infer_document_kind(target, page_text) or required_document_kind(target)
    if resolved:
        blocked_document_kinds(ctx).add(resolved)
    # Do not stamp as "read" — only remember titles so unread selection converges.
    blocked_titles = ctx.runtime.setdefault("blocked_document_titles", set())
    if not isinstance(blocked_titles, set):
        blocked_titles = set(blocked_titles or ())
        ctx.runtime["blocked_document_titles"] = blocked_titles
    for item in (target,):
        normalized = normalize_document_title(item)
        if normalized:
            blocked_titles.add(normalized)
    if resolved:
        for term in dict(REQUIRED_DOCUMENT_KIND_TERMS).get(resolved, ()):
            needle = normalize_document_title(term)
            if needle:
                blocked_titles.add(needle)
    return resolved


def exhausted_document_kinds(ctx: DetectionContext) -> set[str]:
    return failed_inline_document_kinds(ctx) | blocked_document_kinds(ctx)


def note_failed_inline_document(ctx: DetectionContext, target: str) -> str | None:
    kind = required_document_kind(target)
    if not kind:
        return None
    attempts = ctx.runtime.setdefault("inline_document_open_attempts", {})
    attempts[kind] = int(attempts.get(kind, 0)) + 1
    if attempts[kind] >= 2:
        failed = failed_inline_document_kinds(ctx)
        failed.add(kind)
        failed_inline_document_titles(ctx).add(normalize_document_title(target))
        gap = f"同意弹窗上的「{target}」已尝试点击但未打开可读正文，不认定该条款已阅读"
        gaps = ctx.runtime.setdefault("rule_coverage_gaps", [])
        if gap not in gaps:
            gaps.append(gap)
    return kind


def unread_document_gap_resolved(gap: str, read_kinds: set[str]) -> bool:
    """Drop first-run 'not read' warnings once the same clause is read later."""
    text = str(gap or "")
    if "不认定该条款已阅读" not in text and "不能认定条款已阅读" not in text:
        return False
    lowered = text.lower()
    if "首次同意弹窗" in text:
        return bool({"privacy_policy", "user_agreement", "service_terms"} & {str(kind) for kind in read_kinds})
    kind_tokens = (
        ("privacy_policy", ("隐私政策", "privacy policy")),
        ("user_agreement", ("用户协议", "用户服务协议")),
        ("service_terms", ("服务协议", "服务条款", "使用条款")),
        ("disclosure_list", ("sdk目录", "第三方sdk")),
    )
    for kind, tokens in kind_tokens:
        if kind in read_kinds and any(token in lowered for token in tokens):
            return True
    return False


def prune_unread_document_gaps(ctx: DetectionContext) -> None:
    read_kinds = {str(kind) for kind in read_document_kinds(ctx)}
    gaps = ctx.runtime.get("rule_coverage_gaps") or []
    ctx.runtime["rule_coverage_gaps"] = [
        gap for gap in gaps if not unread_document_gap_resolved(str(gap), read_kinds)
    ]


def document_session_already_read(
    ctx: DetectionContext, *, document_origin: str, page_text: str,
) -> str | None:
    """返回该文档对应的已读 kind；未读过或无法判定 kind 时返回 None。

    应用内 WebView 会话在入口处调用：同一 kind 已在外部浏览器或先前会话
    形成完整阅读证据时，禁止重新开卷（任务 281 中《隐私政策》被连读三遍）。
    """
    kind = infer_document_kind(document_origin, page_text) or document_body_kind_from_text(page_text)
    if not kind:
        return None
    return kind if kind in read_document_kinds(ctx) else None


def skip_already_read_document(state: PageState, document_key: str) -> bool:
    """闭合该已读文档的会话；返回是否为首次跳过。

    每个后续视口都必须持续跳过（kind 已读即不再开卷），但
    ``document_already_read_skip`` 事件每个文档键只发一次，避免刷屏。
    """
    first_skip = document_key not in state.documents.completed_keys()
    state.documents.finish(document_key, bottom_confirmed=True)
    return first_skip
