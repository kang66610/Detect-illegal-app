"""Deterministic policy-text checks used to automate former manual items.

The analyzer deliberately emits findings only after a policy source is known
to be complete (bundled policy text or an Appium document read to the bottom).
Missing text is a coverage gap, never evidence of a violation or compliance.
"""
from __future__ import annotations

import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from agent.common.policy_text import policy_text_quality
from agent.detection_engines.base import DetectionContext, Finding
from agent.detection_engines.sdk_detector import sdk_policy_aliases


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms)


_SENSITIVE_INFORMATION_FAMILIES = (
    ("identity", ("身份证号", "身份证")),
    ("biometric", ("生物识别", "人脸", "指纹", "声纹")),
    ("health", ("医疗健康", "病历")),
    ("financial", ("金融账户", "银行账号", "银行卡")),
    ("location", ("行踪轨迹", "精确定位")),
    ("religion", ("宗教信仰",)),
    ("specific_identity", ("特定身份",)),
    ("minor", ("不满十四周岁", "未成年人")),
)
_EMPHASIS_TAGS = {"b", "strong", "em", "u", "mark"}
_EMPHASIS_CLASS_RE = re.compile(r"(?:sensitive|highlight|emphasis|important|strong|bold|underline)", re.I)
_EMPHASIS_STYLE_RE = re.compile(
    r"(?:font-weight\s*:\s*(?:bold|[6-9]00)|text-decoration[^;]*(?:underline)|"
    r"background(?:-color)?\s*:|color\s*:\s*(?!#?(?:000|000000|333|333333|666|666666)\b))",
    re.I,
)


class _SensitiveMarkupParser(HTMLParser):
    """Inspect emphasis semantics without treating unresolvable CSS as proof."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool, bool]] = []
        self.sensitive_terms: dict[str, str] = {}
        self.emphasized_terms: dict[str, str] = {}
        self.has_unknown_css = False
        self.has_resolvable_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        classes = values.get("class", "")
        style = values.get("style", "")
        explicit = (
            tag.lower() in _EMPHASIS_TAGS
            or bool(_EMPHASIS_CLASS_RE.search(classes))
            or bool(_EMPHASIS_STYLE_RE.search(style))
        )
        if explicit:
            self.has_resolvable_style = True
        unknown_css = bool(classes and not _EMPHASIS_CLASS_RE.search(classes))
        if tag.lower() == "link" and "stylesheet" in values.get("rel", "").lower():
            unknown_css = True
        if unknown_css:
            self.has_unknown_css = True
        inherited = any(item[1] for item in self.stack)
        inherited_unknown = any(item[2] for item in self.stack)
        self.stack.append((tag.lower(), explicit or inherited, unknown_css or inherited_unknown))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        wanted = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == wanted:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        found = _sensitive_terms_in_text(str(data or ""))
        if not found:
            return
        self.sensitive_terms.update(found)
        if any(item[1] for item in self.stack):
            self.emphasized_terms.update(found)


def _sensitive_terms_in_text(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for family, terms in _SENSITIVE_INFORMATION_FAMILIES:
        match = next((term for term in terms if term in str(text or "")), None)
        if match:
            found[family] = match
    return found


def sensitive_information_emphasis_status(raw: str) -> dict:
    """Conservatively assess whether sensitive categories are visually marked.

    A violation candidate requires preserved HTML, at least two distinct
    sensitive-information categories, and no unresolved external/class CSS.
    Plain Appium/OCR text cannot prove typography and stays inconclusive.
    """
    source = str(raw or "")
    visible = _sensitive_terms_in_text(source)
    visible_terms = sorted(visible.values())
    if len(visible) < 2:
        return {"status": "not_applicable", "sensitive_terms": visible_terms, "emphasized_terms": []}
    if not re.search(r"<\s*[a-zA-Z][^>]*>", source):
        return {"status": "style_unavailable", "sensitive_terms": visible_terms, "emphasized_terms": []}
    parser = _SensitiveMarkupParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        return {"status": "style_unavailable", "sensitive_terms": visible_terms, "emphasized_terms": []}
    parsed = parser.sensitive_terms or visible
    terms = sorted(parsed.values())
    emphasized = sorted(parser.emphasized_terms.values())
    if parser.has_unknown_css:
        status = "style_unavailable"
    elif set(parsed) <= set(parser.emphasized_terms):
        status = "emphasized"
    else:
        status = "not_emphasized"
    return {
        "status": status,
        "sensitive_terms": terms,
        "emphasized_terms": emphasized,
        "resolvable_style_present": parser.has_resolvable_style,
    }


def _complaint_windows(text: str) -> list[str]:
    """Keep only short spans that discuss complaint/report handling.

    Appium Custom Tab dumps often lose Chinese periods, so a 1.7 万字政策
    can become a single clause.  Retention “N个工作日” elsewhere must not
    satisfy rule 6.5.  Use punctuated sentences when present, otherwise a
    tight character window around 投诉/举报/申诉.
    """
    raw = str(text or "")
    windows: list[str] = []
    for clause in re.split(r"[。；;!？?\n]", raw):
        if _has_any(clause, ("投诉", "举报", "申诉")):
            windows.append(clause)
    compact = _compact(raw)
    for term in ("投诉", "举报", "申诉"):
        start = 0
        while True:
            index = compact.find(term, start)
            if index < 0:
                break
            windows.append(compact[max(0, index - 16): index + 72])
            start = index + len(term)
    return windows


def _window_has_deadline(text: str) -> bool:
    deadline_terms = (
        "处理时限", "处理时效", "处理期限", "反馈时限", "回复时限",
        "受理时限", "办理时限", "办理期限", "核查时限", "核查期限",
        "核查处理时间",
    )
    if _has_any(text, deadline_terms):
        return True
    has_duration = bool(re.search(
        r"\d+(?:\.\d+)?(?:个)?(?:工作日|日|天|小时|分钟|周|月)(?:内|以内|后)?",
        text,
        flags=re.IGNORECASE,
    )) or _has_any(text, ("工作日内", "小时内"))
    if not has_duration:
        return False
    return _has_any(text, ("处理", "反馈", "回复", "核查", "受理", "办理"))


def _has_processing_deadline(text: str) -> bool:
    """Return whether the complaint/report channel states an explicit deadline.

    A generic promise such as “we will reply” or a retention period such as
    “个人信息保存不超过15个工作日” is not a processing time limit.
    """
    return any(_window_has_deadline(window) for window in _complaint_windows(text))


def _invalid_contact_format(raw: str) -> bool:
    claimed = bool(re.search(r"电话|热线|邮箱|email", raw, flags=re.I))
    if not claimed:
        return False
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", raw, flags=re.I)
    numbers = [re.sub(r"\D", "", item) for item in re.findall(r"\d[\d\- ]{5,}\d", raw)]
    has_email = any("@" in item and "." in item.split("@")[-1] for item in emails)
    has_phone = any(len(item) in {8, 11, 12} for item in numbers)
    return not has_email and not has_phone


def _has_itemized_disclosure(text: str) -> bool:
    """Return whether the policy gives per-item purpose/method/scope detail.

    A generic sentence such as “we collect your personal information for
    service improvement; see the collection list” must not satisfy rule 2.1.
    We require at least two independent, data-bearing clauses that describe
    both what is collected and why/how it is used.  This keeps the check
    useful for arbitrary apps while avoiding a keyword-only false negative.
    """
    clauses = re.split(r"[。；;\n。]", text)
    informative = 0
    for clause in clauses:
        if len(clause) < 12:
            continue
        has_data = _has_any(clause, (
            "手机号", "电话号码", "设备信息", "设备标识", "位置信息", "通讯录",
            "相机", "麦克风", "存储", "照片", "账号", "日志", "个人信息",
        ))
        has_collection = _has_any(clause, ("收集", "获取", "访问", "调用", "上传", "传输"))
        has_purpose = _has_any(clause, ("用于", "用以", "为了", "目的", "以便", "实现"))
        has_scope = _has_any(clause, ("范围", "包括", "类型", "内容", "清单"))
        if has_data and has_collection and (has_purpose or has_scope):
            informative += 1
    return informative >= 2


def _sdk_named_in_policy(text: str, sdk: dict) -> bool:
    compact = _compact(text)
    for alias in sdk_policy_aliases(sdk, str(sdk.get("name") or "")):
        needle = _compact(alias)
        if len(needle) >= 2 and needle in compact:
            return True
    return False


def _undisclosed_embedded_sdks(text: str, sdk_list: list | None) -> list[str]:
    """SDK names present in the APK but not itemized in a complete policy.

    Weak permission-only matches are ignored; those are not proof the SDK
    is embedded.  This is rule 2.1 disclosure completeness, not 2.1_SDK
    runtime collection.
    """
    missing: list[str] = []
    for item in sdk_list or []:
        row = item or {}
        name = str(row.get("name") or "").strip()
        matched_by = [str(marker) for marker in (row.get("matched_by") or [])]
        weak_only = bool(matched_by) and all(marker.startswith("权限:") for marker in matched_by)
        if not name or weak_only:
            continue
        if not _sdk_named_in_policy(text, row):
            missing.append(name)
    return missing


def _uses_flutter(apk_path: Path | None) -> bool:
    """Detect Flutter packaging without relying on a vendor SDK registry."""
    if not apk_path or not apk_path.is_file():
        return False
    try:
        with zipfile.ZipFile(apk_path) as archive:
            names = {name.lower() for name in archive.namelist()}
        return any(
            name.endswith("libflutter.so") or "flutter_assets/" in name
            for name in names
        )
    except (OSError, zipfile.BadZipFile):
        return False


def _has_itemized_flutter_plugin_disclosure(text: str) -> bool:
    """Return whether Flutter third-party plugins are listed with purpose/scope.

    Mentioning that the app “uses Flutter” or a generic SDK table is not the
    same as listing each embedded Flutter plugin's collection purpose, method
    and scope, which is the manual 2.1 finding for this class of apps.
    """
    if not _has_any(text, ("flutter",)):
        return False
    if not _has_any(text, ("插件", "plugin")):
        return False
    clauses = re.split(r"[。；;\n、]", text)
    informative = 0
    for clause in clauses:
        if len(clause) < 8:
            continue
        has_plugin = _has_any(clause, ("插件", "plugin"))
        has_purpose = _has_any(clause, ("用于", "用以", "为了", "目的", "以便"))
        has_data = _has_any(clause, (
            "个人信息", "设备", "收集", "获取", "访问", "相册", "相机", "存储", "位置",
        ))
        if has_plugin and has_purpose and has_data:
            informative += 1
    return informative >= 2


def policy_discloses_withdraw_path(text: str) -> bool:
    """True only when the policy names a withdraw action and an in-app route."""
    compact = _compact(text)
    if not _has_any(compact, (
        "撤回同意", "撤回授权", "撤销同意", "撤销授权", "撤回个人信息",
    )):
        return False
    return _has_any(compact, ("设置", "点击", "路径", "系统设置", "应用内", "授权管理", "关闭授权"))


def _policy_source(ctx: DetectionContext) -> tuple[str, str, bool]:
    apk = getattr(ctx, "apk", None)
    bundled = str(getattr(apk, "policy_raw", None) or "")
    privacy = str(ctx.runtime.get("privacy_policy_text") or "")
    runtime = privacy or str(ctx.runtime.get("policy_text") or "")
    runtime_complete = bool(
        ctx.runtime.get("privacy_policy_read_complete")
        or (ctx.runtime.get("policy_document_read_complete") and bool(privacy))
        # Checkpoints produced before document-kind accounting existed have no
        # ledger. Preserve their compatibility; new runs always write kinds
        # and therefore cannot let a service agreement masquerade as policy.
        or (
            ctx.runtime.get("policy_document_read_complete")
            and not ctx.runtime.get("read_document_kinds")
            and bool(runtime)
        )
        or (
            ctx.runtime.get("policy_document_read_complete")
            and "privacy_policy" in set(ctx.runtime.get("read_document_kinds") or [])
        )
    )
    runtime_quality = policy_text_quality(runtime)
    bundled_quality = policy_text_quality(bundled)
    # Prefer the document actually rendered and read to the bottom.  A bundled
    # asset is only a fallback and must pass content validation; a privacy-like
    # filename is never proof that compiled Android XML is policy prose.
    ctx.runtime["policy_source_quality"] = {
        "appium_document": runtime_quality,
        "apk_bundle": bundled_quality,
    }
    if runtime_complete and runtime_quality["valid"]:
        return runtime, "appium_document", True
    if bundled_quality["valid"]:
        return bundled, "apk_bundle", True
    return runtime or bundled, "incomplete", False


def run_policy_audit(ctx: DetectionContext) -> tuple[list[Finding], list[dict], list[str]]:
    """Return static policy findings, scoped evidence, and coverage gaps."""
    raw, source, complete = _policy_source(ctx)
    ctx.runtime["policy_preserved_html"] = bool(
        complete and re.search(r"<\s*[a-zA-Z][^>]*>", str(raw or ""))
    )
    text = _compact(raw)
    findings: list[Finding] = []
    gaps: list[str] = []
    complaint_present: bool | None = None
    processing_deadline_present: bool | None = None
    complaint_windows: list[str] = []
    withdraw_path_disclosed: bool | None = None
    emphasis = sensitive_information_emphasis_status(raw) if complete else {
        "status": "not_checked", "sensitive_terms": [], "emphasized_terms": [],
    }
    if not complete:
        gaps.append("隐私政策正文尚未确认完整，暂不执行文本规则判定")
    else:
        purpose = _has_any(text, ("目的", "用于", "为了", "提供服务", "使用目的"))
        method = _has_any(text, ("收集", "获取", "访问", "调用", "上传", "传输"))
        scope = _has_any(text, ("范围", "包括", "个人信息", "信息类型", "数据类型"))
        missing_dimensions = [
            label for label, present in (("目的", purpose), ("方式", method), ("范围", scope)) if not present
        ]
        # The rule is conservative: a missing semantic dimension is a
        # candidate only when the complete document itself was available.
        # A linked list is not equivalent to displaying the list itself.  If
        # the captured document only contains a generic disclosure and a link
        # to the collection list, keep rule 2.1 as a deterministic finding so
        # the report does not silently call the app compliant.
        linked_collection_list = _has_any(text, (
            "个人信息收集清单", "信息收集清单", "个人信息清单",
        ))
        itemized = _has_itemized_disclosure(text)
        uses_flutter = _uses_flutter(ctx.apk_path)
        flutter_plugins_itemized = _has_itemized_flutter_plugin_disclosure(text)
        undisclosed_sdks = _undisclosed_embedded_sdks(text, getattr(ctx.apk, "sdk_list", None))
        if linked_collection_list and not itemized:
            missing_dimensions = ["逐项目的、方式和范围"]
        if uses_flutter and not flutter_plugins_itemized:
            # Flutter plugins are a common source of undisclosed collection.
            # Naming the engine, or a generic SDK table, does not list each
            # embedded plugin's purpose, method and scope.
            missing_dimensions = list(dict.fromkeys([*missing_dimensions, "第三方插件收集项"]))
        if undisclosed_sdks:
            missing_dimensions = list(dict.fromkeys([*missing_dimensions, "嵌入第三方SDK逐项披露"]))
        if missing_dimensions:
            findings.append(Finding(
                kind="purpose_not_disclosed", category=2,
                payload={
                    "missing_dimensions": missing_dimensions,
                    "policy_source": source,
                    "policy_length": len(raw),
                    "policy_document_complete": True,
                    "linked_collection_list": linked_collection_list,
                    "itemized_disclosure": itemized,
                    "uses_flutter": uses_flutter,
                    "flutter_plugin_disclosure": flutter_plugins_itemized,
                    "undisclosed_sdks": undisclosed_sdks,
                },
            ))

        withdraw_path_disclosed = policy_discloses_withdraw_path(raw)
        if emphasis["status"] == "not_emphasized":
            findings.append(Finding(
                kind="sensitive_information_not_emphasized", category=2,
                payload={
                    "policy_source": source,
                    "policy_document_complete": True,
                    "style_source": "preserved_html",
                    "sensitive_terms": emphasis["sensitive_terms"],
                    "emphasized_terms": emphasis["emphasized_terms"],
                    "unemphasized_terms": sorted(
                        set(emphasis["sensitive_terms"]) - set(emphasis["emphasized_terms"])
                    ),
                    "evidence_limit": "仅判定本次取得的保留样式隐私政策 HTML；不推断服务端展示或其他版本。",
                },
            ))
        elif emphasis["status"] == "style_unavailable":
            gaps.append("政策包含多类敏感个人信息，但当前证据未保留可解析样式，未对“是否显著标识”作违规推断")

        complaint = _has_any(text, ("投诉", "举报", "客服", "反馈", "联系我们", "邮箱", "电话"))
        complaint_windows = _complaint_windows(raw)
        processing_time = any(_window_has_deadline(window) for window in complaint_windows)
        complaint_present = complaint
        processing_deadline_present = processing_time
        if not complaint:
            findings.append(Finding(
                kind="no_complaint_channel", category=6,
                payload={"policy_source": source, "policy_length": len(raw), "policy_document_complete": True},
            ))
        else:
            if _invalid_contact_format(raw):
                findings.append(Finding(
                    kind="invalid_contact_format", category=6,
                    payload={"policy_source": source, "policy_length": len(raw), "policy_document_complete": True},
                ))
            if not processing_time:
                findings.append(Finding(
                    kind="complaint_processing_time_missing", category=6,
                    payload={
                        "policy_source": source,
                        "policy_length": len(raw),
                        "policy_document_complete": True,
                        "complaint_channel_present": True,
                    },
                ))
        policy_completions = []
        if complaint:
            policy_completions.append("complaint_channel_ok")
        if processing_time:
            policy_completions.append("complaint_deadline_disclosed")
        existing = ctx.runtime.setdefault("policy_audit_completions", [])
        for token in policy_completions:
            if token not in existing:
                existing.append(token)

    path = ctx.data_dir / "behavior" / "policy-audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source": source,
        "source_quality": dict(ctx.runtime.get("policy_source_quality") or {}),
        "complete": complete,
        "text_length": len(raw),
        "findings": [finding.kind for finding in findings],
        "complaint_channel_present": complaint_present,
        "complaint_processing_deadline_present": processing_deadline_present,
        "withdraw_path_disclosed": withdraw_path_disclosed,
        "sensitive_information_emphasis": emphasis,
        "complaint_windows": [window[:120] for window in (complaint_windows if complete else [])][:8],
        "missing_dimensions": (findings[0].payload.get("missing_dimensions", [])
                               if findings and findings[0].kind == "purpose_not_disclosed" else []),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence = [{
        "type": "policy", "path": str(path),
        "meta": {"finding_kinds": [finding.kind for finding in findings], "source": source, "complete": complete},
    }]
    return findings, evidence, gaps
