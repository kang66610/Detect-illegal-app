"""Consent surface vocabulary and pure dialog classifiers.

Owns the first-run consent detection cluster: the agree/decline vocabularies
and button-id hints, the explicit Agree target resolution, the
unchecked/pre-checked consent checkbox probes and the short decline-label
semantics. The explorer loop consumes these helpers through alias imports;
the vocabulary and the classifiers have exactly one owner — this module.
"""
from __future__ import annotations

import re

from agent.ai_explorer.action_safety_checks import bounds_tuple
from agent.ai_explorer.target_catalog import (
    document_kinds_in,
    element_label,
    identity_values_for_target,
    required_document_kind,
)
from agent.ai_explorer.login_session import LoginSurfaceClassifier

POLICY_TERMS = ("隐私", "privacy")
DOCUMENT_TERMS = (
    "隐私政策", "隐私声明", "隐私条款", "隐私协议", "用户服务协议", "服务协议", "服务条款", "使用条款", "用户协议",
    "privacy policy", "privacy statement", "privacy agreement", "terms of service", "terms of use",
)
CONSENT_TERMS = ("同意", "接受", "我已阅读", "我已知晓", "确认")
DECLINE_TERMS = ("不同意", "拒绝", "取消", "退出", "暂不", "以后再说", "decline", "not now", "cancel", "exit")
PRIVACY_DIALOG_BUTTON_IDS = (
    "btn_positive", "btn_negative", "btn_agree", "btn_confirm", "privacy_agree",
    "ok_btn", "btn_ok", "btnok", "agree_btn", "btn_accept",
)
CONSENT_BUTTON_IDS = (
    "btn_positive", "btn_agree", "btn_confirm", "privacy_agree",
    "ok_btn", "btn_ok", "btnok", "agree_btn", "btn_accept",
)
DECLINE_BUTTON_IDS = ("btn_negative", "btn_cancel", "btn_disagree", "cancel_btn", "btn_decline")
# Match short clickable labels only — never scan long policy paragraphs that
# routinely mention「个人信息」and would flip the dialog off.
CONSENT_DIALOG_HUB_EXCLUSION_TERMS = (
    "头像", "昵称", "退出登录", "关于我们", "个人资料", "性别", "账号管理",
    "avatar", "nickname", "log out", "sign out", "about us",
)
AUTHENTICATED_LOGOUT_TERMS = (
    "退出登录", "退出账号", "退出账户", "安全退出", "注销登录",
    "sign out", "log out", "logout",
)
LOGIN_SURFACE_CLASSIFIER = LoginSurfaceClassifier()


def resource_id_matches_hint(resource_id: str, hint: str) -> bool:
    """Match a button id as a token, not as a prefix of a longer word.

    ``privacy_agree`` must hit ``.../privacy_agree`` or ``btn_privacy_agree``,
    but must not treat a settings row ``cl_setting_privacy_agreement`` as the
    first-run Agree button.
    """
    rid = str(resource_id or "").lower()
    needle = str(hint or "").lower()
    if not rid or not needle:
        return False
    start = 0
    while True:
        index = rid.find(needle, start)
        if index < 0:
            return False
        end = index + len(needle)
        before = rid[index - 1] if index else ""
        after = rid[end] if end < len(rid) else ""
        if (not before.isalnum()) and (not after.isalnum()):
            return True
        start = index + 1


def id_matches_any_hint(value: str, hints: tuple[str, ...]) -> bool:
    return any(resource_id_matches_hint(value, hint) for hint in hints)


def is_checkbox_like(element: dict) -> bool:
    class_name = str(element.get("class_name") or "").lower()
    resource_id = str(element.get("resource_id") or "").lower()
    return bool(element.get("checkable")) or any(
        term in class_name for term in ("checkbox", "radiobutton", "compoundbutton")
    ) or any(term in resource_id for term in ("checkbox", "check_box", "cb_agree", "agree_check", "iv_check"))


def consent_or_decline_control(element: dict) -> bool:
    label = " ".join(str(element.get(key) or "") for key in ("text", "content_desc"))
    resource_id = str(element.get("resource_id") or "").lower()
    if is_short_decline_label(label):
        return True
    if required_document_kind(label) and len(re.sub(r"\s+", "", label)) > 12:
        return False
    if id_matches_any_hint(resource_id, PRIVACY_DIALOG_BUTTON_IDS):
        return True
    if id_matches_any_hint(resource_id, DECLINE_BUTTON_IDS):
        return True
    compact = re.sub(r"\s+", "", label)
    return any(term in compact for term in CONSENT_TERMS) and len(compact) <= 12


def short_control_label(element: dict | None) -> str:
    if not element:
        return ""
    return " ".join(str(element.get(key) or "") for key in ("text", "content_desc")).strip()


def is_short_decline_label(label: str) -> bool:
    compact = re.sub(r"\s+", "", str(label or ""))
    if not compact or len(compact) > 12:
        return False
    lowered = compact.lower()
    if any(term.lower().replace(" ", "") in lowered for term in AUTHENTICATED_LOGOUT_TERMS):
        return False
    exact = {re.sub(r"\s+", "", term).lower() for term in DECLINE_TERMS}
    exact.update({"退出应用", "退出程序", "暂不使用", "暂不同意", "拒绝使用"})
    if lowered in exact:
        return True
    # Prefix only for clearly dialog-shaped refusals, never 退出登录 / 取消关注.
    return any(lowered.startswith(term) for term in ("不同意", "拒绝", "暂不", "以后再说", "notnow"))


def target_has_decline_semantics(target: str, elements: list[dict]) -> bool:
    """True only for a short 拒绝/退出 control, never a policy paragraph.

    First-run copy often says “拒绝后将无法使用”.  Matching 拒绝 inside that
    paragraph would abort the whole audit before any clause is opened.
    """
    matched = [
        item for item in elements
        if target and target in {
            str(item.get("resource_id") or ""),
            str(item.get("text") or ""),
            str(item.get("content_desc") or ""),
            str(item.get("target") or ""),
        }
    ]
    for element in matched:
        label = short_control_label(element)
        resource_id = str(element.get("resource_id") or "").lower()
        if is_short_decline_label(label):
            return True
        if id_matches_any_hint(resource_id, DECLINE_BUTTON_IDS) and (
            not label or is_short_decline_label(label)
        ):
            return True
        if any(term in label for term in CONSENT_TERMS) and not is_short_decline_label(label):
            return False
    compact_target = re.sub(r"\s+", "", str(target or ""))
    if is_short_decline_label(compact_target):
        return True
    if id_matches_any_hint(str(target or ""), DECLINE_BUTTON_IDS):
        if matched:
            return any(
                not short_control_label(item) or is_short_decline_label(short_control_label(item))
                for item in matched
            )
        return True
    return False


def explicit_consent_target(elements: list[dict]) -> str | None:
    """Return a visible, non-destructive consent button when its label is explicit.

    Prefer ``btn_positive`` / ``btn_agree`` style ids. A ``btn_negative`` id is
    only accepted when its *visible* label is clearly Agree and no positive-id
    candidate exists (some vendors invert Material positive/negative).
    """
    positive_id_hits: list[str] = []
    labeled_agree: list[str] = []
    inverted_decline_id: str | None = None
    for element in elements:
        if not element.get("clickable"):
            continue
        label = " ".join(str(element.get(key) or "") for key in ("text", "content_desc"))
        resource_id = str(element.get("resource_id") or "")
        widget_class = str(element.get("class_name") or "").lower()
        target = resource_id or str(element.get("text") or element.get("content_desc") or "")
        if not target:
            continue
        if is_short_decline_label(label):
            continue
        if required_document_kind(label):
            continue
        compact = re.sub(r"\s+", "", label)
        has_agree_text = bool(compact) and any(
            term in compact for term in ("同意", "接受", "agree", "accept")
        ) and "不同意" not in compact and "不接受" not in compact
        is_decline_id = id_matches_any_hint(resource_id, DECLINE_BUTTON_IDS)
        is_consent_id = id_matches_any_hint(resource_id, CONSENT_BUTTON_IDS)
        if is_decline_id:
            # Never treat an unlabeled / ambiguous decline id as Agree.
            if has_agree_text and inverted_decline_id is None:
                inverted_decline_id = target
            continue
        is_dialog_button = is_consent_id or "button" in widget_class or "textview" in widget_class
        if is_consent_id and (has_agree_text or not compact):
            positive_id_hits.append(target)
            continue
        if is_dialog_button and has_agree_text:
            labeled_agree.append(target)
            continue
        if (
            1 <= len(compact) <= 8
            and has_agree_text
        ):
            labeled_agree.append(target)
    if positive_id_hits:
        return positive_id_hits[0]
    if labeled_agree:
        return labeled_agree[0]
    # Last resort: vendor inverted btn_negative="同意" with no positive sibling.
    return inverted_decline_id


def is_consent_dialog(elements: list[dict]) -> bool:
    """True for a first-run privacy popup, not a settings row that merely mentions a policy."""
    # A full-page “登录/注册 + 先逛逛/游客” choice can retain a privacy
    # checkbox in its footer.  Treating the footer as a modal consent dialog
    # blocks the public path and makes DFS repeatedly reopen policy links.
    if entry_choice_bypass_target(elements):
        return False
    page_text = " ".join(element_label(item) for item in elements)
    if not any(term in page_text for term in (*DOCUMENT_TERMS, *POLICY_TERMS)):
        return False
    # Only short *clickable* hub chrome can disprove a consent sheet. Long
    # policy copy often contains「个人信息」and must not flip this off.
    hub_hits = 0
    for item in elements:
        if not item.get("clickable"):
            continue
        label = re.sub(r"\s+", "", short_control_label(item) or element_label(item))
        if not label or len(label) > 12:
            continue
        if any(term.lower() in label.lower() for term in CONSENT_DIALOG_HUB_EXCLUSION_TERMS):
            hub_hits += 1
    if hub_hits >= 2:
        return False
    has_webview = any("webview" in str(item.get("class_name") or "").lower() for item in elements)
    # WebView consent sheets frequently expose their action text as
    # ``clickable=false`` accessibility nodes.  Bounds plus the paired
    # agree/decline semantics are sufficient *only inside this detected
    # overlay*; ordinary non-clickable page copy is never made executable.
    short_action_items = [
        item for item in elements
        if item.get("displayed", True)
        and len(short_control_label(item)) <= 12
        and (item.get("clickable") or bounds_tuple(str(item.get("bounds") or "")))
    ]
    short_actions = [short_control_label(item) for item in short_action_items]
    has_agree = any(
        any(term in label for term in ("同意", "接受", "agree", "accept"))
        for label in short_actions
    )
    has_decline = any(is_short_decline_label(label) for label in short_actions)
    if has_webview and not (has_agree and has_decline):
        return False
    if has_webview and has_agree and has_decline:
        paired_bounds = [
            bounds_tuple(str(item.get("bounds") or ""))
            for item in short_action_items
            if (
                any(term in short_control_label(item) for term in ("同意", "接受", "agree", "accept"))
                or is_short_decline_label(short_control_label(item))
            )
        ]
        paired_bounds = [item for item in paired_bounds if item]
        # If bounds are available, controls on opposite ends of a long body
        # are prose, not a local consent decision pair.  Legacy controls with
        # no bounds retain the existing explicit-button path below.
        if len(paired_bounds) >= 2:
            centers = [(item[1] + item[3]) / 2 for item in paired_bounds]
            page_height = max(
                (bounds[3] for bounds in (
                    bounds_tuple(str(item.get("bounds") or "")) for item in elements
                ) if bounds),
                default=0,
            )
            if max(centers) - min(centers) > max(120, page_height * 0.24):
                return False
    # Explicit Agree/Decline controls win over hub-wording noise.
    if explicit_consent_target(elements) is not None:
        return True
    if any(
        item.get("clickable")
        and id_matches_any_hint(str(item.get("resource_id") or ""), PRIVACY_DIALOG_BUTTON_IDS)
        for item in elements
    ):
        return True
    return has_agree or (has_decline and bool(document_kinds_in(page_text)))


def unchecked_consent_checkbox(elements: list[dict]) -> str | None:
    """Return an unchecked consent gate that must be ticked before Agree.

    Some reader apps keep the Agree button tappable but ignore the click
    until “请勾选阅读并同意” is checked. Clicking Agree first then treating
    it as a duplicate target leaves the audit on the splash dialog.
    """
    if not is_consent_dialog(elements):
        return None
    for element in elements:
        if not element.get("clickable") or element.get("checked"):
            continue
        if not is_checkbox_like(element):
            continue
        class_name = str(element.get("class_name") or "").lower()
        resource_id = str(element.get("resource_id") or "").lower()
        identity = re.sub(
            r"\s+", "",
            " ".join(str(element.get(key) or "") for key in (
                "text", "content_desc", "resource_id", "target",
            )),
        ).lower()
        consent_identity = any(term in identity for term in (
            "同意", "已阅读", "隐私", "协议", "consent", "agree",
            "cb_agree", "agree_check", "privacy_check", "protocol_check",
        ))
        # A consent sheet may contain unrelated radio choices (for example
        # sync mode).  Checkable alone is not evidence that a control owns the
        # agreement state; only an explicit consent identity is eligible.
        if "radiobutton" in class_name and not consent_identity:
            continue
        if not consent_identity and not any(
            hint in resource_id for hint in (
                "checkbox", "check_box", "cb_agree", "agree_check",
                "privacy_check", "protocol_check",
            )
        ):
            continue
        if "button" in class_name and id_matches_any_hint(resource_id, PRIVACY_DIALOG_BUTTON_IDS):
            continue
        target = str(element.get("target") or element.get("resource_id") or element.get("text") or element.get("content_desc") or "")
        if not target or target_has_decline_semantics(target, elements):
            continue
        if explicit_consent_target([element]):
            continue
        return target
    return None


def prechecked_consent_checkbox(
    elements: list[dict],
    page_text: str,
    *,
    initial_observation: bool = True,
    screenshot_available: bool = True,
) -> dict | None:
    """Return a pre-action, screenshot-backed default-consent observation.

    ``checked=true`` after an agreement click, route transition, or control
    reuse is not proof of a default selection.  RULE_3_4 therefore accepts
    only the first stable consent surface of a phase and requires a retained
    screenshot alongside the UI-tree attribute.
    """
    if not initial_observation or not screenshot_available:
        return None
    if not any(term in page_text for term in POLICY_TERMS):
        return None
    for element in elements:
        identity = " ".join(str(element.get(key) or "") for key in ("resource_id", "text", "content_desc")).lower()
        if element.get("checked") and any(term in identity for term in ("同意", "隐私", "agree", "consent", "checkbox", "check")):
            return {"target": element.get("resource_id") or element.get("text") or "consent_checkbox", "page_text": page_text[:500]}
    return None


def login_bypass_target(elements: list[dict]) -> str | None:
    """Guest/skip control that leaves a login form without submitting credentials."""
    return LOGIN_SURFACE_CLASSIFIER.bypass_target(elements)


def entry_choice_bypass_target(elements: list[dict]) -> str | None:
    """Return a guest/skip action on a first-run login-choice surface.

    A full-page entry choice frequently keeps a privacy-agreement checkbox in
    its footer.  It is not a consent dialog once both a login/register path
    and an explicit guest/skip path are visible; the public path must be
    explored before manual-login handling or settings traversal.
    """
    bypass = login_bypass_target(elements)
    if not bypass:
        return None
    for element in elements:
        if not element.get("clickable"):
            continue
        label = re.sub(r"\s+", "", " ".join(
            str(element.get(key) or "") for key in ("text", "content_desc")
        )).lower()
        if any(term in label for term in ("登录", "注册", "login", "sign in", "sign-up", "signup")):
            return bypass
    return None


def authenticated_logout_target(target: str, elements: list[dict]) -> bool:
    """Recognise an actual logout entry, not a generic back/close control.

    ``退出登录`` may be opened once to inspect the confirm dialog, but the
    affirmative confirm must never be submitted.  Account-deletion rows that
    reuse resource ids like ``*logout*`` for 「注销账号」 are not logout.
    """
    identities = identity_values_for_target(target, elements)
    value = " ".join(identities).strip().lower()
    if not value:
        return False
    # 注销账号 / delete-account rows often use English logout in the id.
    if any(term in value for term in (
        "注销账号", "账号注销", "删除账号", "删除个人信息", "delete account", "cancel account",
    )):
        return False
    if "注销" in value and "登录" not in value and "login" not in value:
        return False
    return any(term.lower() in value for term in AUTHENTICATED_LOGOUT_TERMS)
