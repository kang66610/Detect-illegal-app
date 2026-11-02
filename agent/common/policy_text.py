"""Validation and source selection for privacy-policy text.

APK resource names are only hints.  A file whose name contains ``privacy`` can
still be compiled Android XML, an image, a protobuf or a layout.  Text rules
must never run until the payload itself looks like a readable policy.
"""
from __future__ import annotations

import re
import unicodedata


_POLICY_TERMS = (
    "隐私", "个人信息", "个人数据", "收集", "使用", "共享", "权限", "我们", "您",
    "privacy", "personal information", "personal data", "collect", "use", "share",
    "permission", "we", "you",
)
_COMPILED_RESOURCE_TERMS = (
    "linearlayout", "relativelayout", "constraintlayout", "textview", "imageview",
    "layout_width", "layout_height", "textsize", "textcolor", "resource map",
)


def policy_text_quality(value: str | bytes | None) -> dict:
    """Return a conservative, machine-readable readability assessment."""
    if isinstance(value, bytes):
        raw_bytes = value
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value or "")
        raw_bytes = text.encode("utf-8", errors="replace")
    stripped = text.strip()
    if not stripped:
        return {"valid": False, "reason": "empty", "text_length": 0}

    control_count = sum(
        1 for char in stripped
        if unicodedata.category(char) == "Cc" and char not in "\n\r\t"
    )
    replacement_count = stripped.count("\ufffd")
    visible_count = sum(
        1 for char in stripped
        if char.isprintable() or char in "\n\r\t"
    )
    visible_ratio = visible_count / max(1, len(stripped))
    compact = re.sub(r"\s+", " ", stripped).lower()
    policy_hits = sorted({term for term in _POLICY_TERMS if term in compact})
    resource_hits = sorted({term for term in _COMPILED_RESOURCE_TERMS if term in compact})
    has_binary_header = bool(raw_bytes.startswith((b"\x03\x00\x08\x00", b"\x00\x00\x00")))
    binary_like = (
        has_binary_header
        or control_count / max(1, len(stripped)) > 0.01
        or visible_ratio < 0.90
        or (len(resource_hits) >= 3 and len(policy_hits) < 3)
    )
    # Runtime OCR/WebView captures and compact test fixtures can be short.  Do
    # not require a particular language's keyword list here: the analyzer has
    # already selected a policy-looking resource/document, and keyword tables
    # can be mojibake when an APK mixes encodings.  The hard safety boundary is
    # payload readability plus a prose-like shape; compiled resources are still
    # rejected by the binary/control/resource checks above.
    prose_shape = any(char in stripped for char in ".。!?！？,，;；:\n\r\t ")
    semantic = (
        (len(compact) >= 4 and bool(policy_hits))
        or (len(compact) >= 8 and not resource_hits and prose_shape)
    )
    valid = bool(not binary_like and semantic)
    reason = "ok" if valid else ("binary_or_compiled_resource" if binary_like else "insufficient_policy_semantics")
    return {
        "valid": valid,
        "reason": reason,
        "text_length": len(stripped),
        "visible_ratio": round(visible_ratio, 4),
        "control_count": control_count,
        "replacement_count": replacement_count,
        "policy_terms": policy_hits,
        "compiled_resource_terms": resource_hits,
    }


def is_valid_policy_text(value: str | bytes | None) -> bool:
    return bool(policy_text_quality(value).get("valid"))
