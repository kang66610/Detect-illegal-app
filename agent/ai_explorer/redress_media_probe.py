"""Generic redress/customer-support media probe selection."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from agent.ai_explorer.action_safety_checks import (
    DESTRUCTIVE_CONFIRM_TERMS as _DESTRUCTIVE_CONFIRM_TERMS,
    bounds_tuple as _bounds_tuple,
)
from agent.ai_explorer.decision_directive import DecisionDirective
from agent.ai_explorer.document_state import tightest_enclosing_clickable as _tightest_enclosing_clickable
from agent.ai_explorer.target_catalog import (
    document_body_kind_from_text as _document_body_kind_from_text,
    element_locator as _element_locator,
    element_semantic_identity as _element_semantic_identity,
    labels_for_click_target as _labels_for_click_target,
)
from agent.detection_engines.ui_roles import roles_for_element as _roles_for_element

COMPLAINT_TERMS = (
    "投诉", "举报", "客服", "联系我们", "意见反馈", "反馈", "帮助与支持", "帮助中心",
    "工单", "报料", "问题申诉", "在线支持", "售后支持",
    "complaint", "feedback", "customer service", "contact us", "help center", "support", "ticket", "appeal",
)
DELETE_TERMS = ("注销", "删除账号", "删除个人信息")
WITHDRAW_TERMS = (
    "撤回同意", "撤回授权", "撤销同意", "撤销授权", "关闭授权",
    "授权管理", "管理授权", "撤回个人信息",
)
DELETE_OBSTACLE_TERMS = ("线下", "收费", "付费", "身份证", "人脸", "人工审核", "联系客服", "邮寄")
EXPLICIT_REDRESS_ACTION_TERMS = (
    "投诉", "举报", "意见反馈", "问题反馈", "提交反馈", "反馈内容", "工单",
    "申诉", "报料", "complaint", "feedback", "report abuse", "ticket", "appeal",
)


class RedressSurfaceDetector:
    """Detect interactive complaint/feedback/support surfaces, never policy prose."""

    _TITLES = (
        "客服", "投诉", "举报", "反馈", "意见", "帮助与支持", "帮助中心", "联系我们",
        "工单", "报料", "问题申诉", "在线支持", "售后支持", "customer service",
        "feedback", "complaint", "report abuse", "help center", "contact us", "support",
        "ticket", "appeal",
    )
    _INTERACTIONS = (
        "请输入", "咨询", "自助工单", "电话客服", "欢迎咨询", "描述您的问题", "发送",
        "按住说话", "说点什么", "输入消息", "问题描述", "投诉内容", "反馈内容",
        "提交反馈", "提交投诉", "上传凭证", "添加图片", "添加附件", "上传附件",
        "联系方式", "在线工单", "创建工单", "please enter", "consult", "how can we help",
        "send", "hold to talk", "type a message", "describe your issue", "submit feedback",
        "submit complaint", "attach evidence", "support ticket",
    )
    _ACTIONS = (
        "拍照", "相机", "相册", "图片", "上传", "附件", "语音", "麦克风",
        "camera", "album", "gallery", "upload", "attach", "voice", "microphone",
        "提交反馈", "提交投诉", "发送",
    )

    @staticmethod
    def _identity(item: dict) -> str:
        return " ".join(str(item.get(key) or "") for key in (
            "target", "resource_id", "text", "content_desc",
        )).lower()

    def __init__(self, *, document_detector: Callable[[str], bool] | None = None) -> None:
        self.document_detector = document_detector or (lambda _text: False)

    @staticmethod
    def _bounds(value: str) -> tuple[int, int, int, int] | None:
        import re
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", str(value or ""))
        if not match:
            return None
        left, top, right, bottom = (int(item) for item in match.groups())
        return (left, top, right, bottom) if right > left and bottom > top else None

    def matches(self, activity: str, page_text: str, elements: list[dict] | None = None) -> bool:
        text = str(page_text or "")
        lowered = text.lower()
        controls = list(elements or ())
        titled = any(term.lower() in lowered for term in self._TITLES)
        interaction_copy = any(term.lower() in lowered for term in self._INTERACTIONS)
        editable = any(
            item.get("displayed", True) and (
                item.get("editable") or "edittext" in str(item.get("class_name") or "").lower()
                or "input" in str(item.get("class_name") or "").lower()
            ) for item in controls
        )
        action = any(
            item.get("clickable") and any(term in self._identity(item) for term in self._ACTIONS)
            for item in controls
        )
        visible_bounds = [
            self._bounds(str(item.get("bounds") or ""))
            for item in controls if item.get("displayed", True)
        ]
        visible_bounds = [bounds for bounds in visible_bounds if bounds]
        page_height = max((bounds[3] for bounds in visible_bounds), default=0)
        page_width = max((bounds[2] for bounds in visible_bounds), default=0)
        bottom_icon = any(
            item.get("clickable")
            and (bounds := self._bounds(str(item.get("bounds") or ""))) is not None
            and page_height and page_width
            and (bounds[1] + bounds[3]) / 2 >= page_height * 0.72
            and (bounds[2] - bounds[0]) < page_width * 0.45
            for item in controls
        )
        compact = "".join(text.split()).lower()
        structural_title = any(
            not item.get("clickable")
            and (label := "".join(" ".join(
                str(item.get(key) or "") for key in ("text", "content_desc")
            ).split()).lower())
            and label in compact
            and any(term.lower() in label for term in self._TITLES)
            for item in controls if item.get("displayed", True)
        )
        structural = editable or action or bottom_icon
        # Policy prose frequently mentions complaint channels. Without a real
        # form/composer/action, text alone is not an interactive redress page.
        if not titled or (not interaction_copy and not (structural and structural_title)):
            return False
        if self.document_detector(text) and not (editable or action):
            return False
        return True


def media_family(identity: str) -> str:
    lowered = str(identity or "").lower()
    stripped = str(identity or "").strip()
    if any(term in lowered for term in ("拍照", "拍摄", "相机", "camera", "capture", "shutter", "photocapture")):
        return "camera"
    if any(term in lowered for term in ("相册", "图库", "图片", "照片", "gallery", "album", "photos", "tv_file", "oi_file")):
        return "album"
    if any(term in lowered for term in ("上传", "upload")):
        return "upload"
    if stripped in {"+", "＋"} or any(term in lowered for term in ("加号", "添加", "附件", "更多", "attach", "plus", "add", "more")):
        return "attach"
    if any(term in lowered for term in ("语音", "麦克风", "录音", "按住说话", "voice", "mic", "record", "speak", "hold to talk")):
        return "voice"
    if any(term in lowered for term in ("头像", "avatar")):
        return "avatar"
    return "other"


MEDIA_PROBE_PERMISSIONS = (
    "android.permission.CAMERA",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.READ_MEDIA_IMAGES",
    "android.permission.READ_MEDIA_VIDEO",
    "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
)


class MediaProbePermissionGuard:
    """Revoke camera/storage right before a media probe.

    SDK-observation grants only phone/location, but a prior run or OEM policy
    may still leave camera/storage granted; revoking again lets the system
    dialog (and the denial→block chain) appear during the probe.
    """

    def __init__(self, *, device, package_name: str) -> None:
        self.device = device
        self.package_name = str(package_name or "")

    def revoke(self) -> list[str]:
        revoke = getattr(self.device, "revoke_runtime_permissions", None)
        if not callable(revoke) or not self.package_name:
            return []
        return list(revoke(self.package_name, list(MEDIA_PROBE_PERMISSIONS)))


_REDRESS_SURFACE_DETECTOR = RedressSurfaceDetector(
    document_detector=lambda text: bool(_document_body_kind_from_text(text)),
)


def _is_redress_interaction_surface(
    activity: str, page_text: str, elements: list[dict] | None = None,
) -> bool:
    """Recognise an interactive redress/help surface across different Apps.

    The legal scenario is not tied to a page literally named ``客服``. Apps
    expose the same path as 投诉、举报、意见反馈、帮助与支持、工单、报料 or an
    online conversation. Require both a redress title and an interaction cue so
    a bottom-navigation label or policy sentence alone never triggers blind taps.
    """
    return _REDRESS_SURFACE_DETECTOR.matches(activity, page_text, elements)


def _is_customer_service_surface(
    activity: str, page_text: str, elements: list[dict] | None = None,
) -> bool:
    """Backward-compatible name for the generic redress interaction detector."""
    return _is_redress_interaction_surface(activity, page_text, elements)


_CS_MEDIA_LABEL_TERMS = (
    "语音", "麦克风", "录音", "按住说话", "说话", "voice", "microphone", "record", "hold to talk",
    "拍照", "拍摄", "相机", "camera", "photo", "capture", "shutter",
    "相册", "图片", "照片", "图库", "gallery", "album", "image", "picture",
    "上传", "附件", "文件", "添加图片", "插入图片", "upload", "attach", "file",
    "扫码", "scan",
)
_CS_MEDIA_ID_HINTS = (
    "voice", "mic", "record", "audio", "speak", "sound",
    "camera", "photo", "capture", "shutter",
    "album", "gallery", "image", "picture", "photo",
    "upload", "attach", "file", "plus", "add", "more", "expand",
)
_CS_ATTACH_LABEL_TERMS = ("+", "＋", "加号", "添加", "附件", "更多", "attach", "plus", "add", "more")


def _cs_media_priority(identity: str) -> int:
    """Lower is better: camera → album/upload → attach/+ → voice → unlabeled."""
    lowered = str(identity or "").lower()
    stripped = str(identity or "").strip()
    if any(term in lowered for term in ("拍照", "拍摄", "相机", "camera", "capture", "shutter")):
        return 0
    if any(term in lowered for term in ("相册", "图片", "照片", "gallery", "album", "image", "upload", "附件", "文件")):
        return 1
    # ``+``/更多 often expands to camera/album; try before microphone-only.
    if stripped in {"+", "＋"} or any(term in lowered for term in _CS_ATTACH_LABEL_TERMS):
        return 2
    if any(term in lowered for term in ("语音", "麦克风", "录音", "voice", "mic", "record", "speak", "hold to talk")):
        return 3
    return 4


def _media_family_of(identity: str) -> str:
    """Map a control identity to a 4.2 morphological family (not a single widget)."""
    return media_family(identity)


def _labels_for_media_identity(target: str, elements: list[dict]) -> str:
    blob = _labels_for_click_target(target, elements) if target else ""
    return f"{target} {blob}".strip()


def _next_media_family_candidate(
    candidates: list[str],
    *,
    elements: list[dict],
    attempted: set[str] | None = None,
) -> str | None:
    """Prefer an unused morphological family, then the next unused target."""
    return RedressMediaProbeExecutor(
        identity_resolver=lambda target: _labels_for_media_identity(target, elements),
    ).next_target(candidates, attempted=set(attempted or ()))


def _iter_customer_service_media_targets(
    activity: str, elements: list[dict], page_text: str,
) -> list[str]:
    """Ordered permission-related affordances on a customer-service chat surface.

    Chat toolbars vary: bottom-centre mic, left voice toggle, right ``+`` that
    opens album/camera, or an explicit 拍照/相册/上传 control. Never assume one
    fixed control or coordinate.
    """
    if not _is_customer_service_surface(activity, page_text, elements):
        return []
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(target: str) -> None:
        value = str(target or "").strip()
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)

    # 1) Explicit labeled / id-hinted media controls anywhere on the page.
    ranked_labeled: list[tuple[int, str]] = []
    for item in elements:
        if not item.get("clickable"):
            continue
        identity = " ".join(str(item.get(key) or "") for key in (
            "target", "resource_id", "text", "content_desc",
        ))
        lowered = identity.lower()
        if any(term in lowered for term in ("qq", "微信", "wechat", "weixin")) and "客服" not in identity:
            continue
        label_hit = any(term.lower() in lowered for term in _CS_MEDIA_LABEL_TERMS)
        id_hit = any(hint in lowered for hint in _CS_MEDIA_ID_HINTS)
        attach_hit = any(term.lower() in lowered for term in _CS_ATTACH_LABEL_TERMS) or identity.strip() in {"+", "＋"}
        if not (label_hit or id_hit or attach_hit):
            continue
        target = str(
            item.get("target") or item.get("resource_id")
            or item.get("text") or item.get("content_desc") or ""
        )
        if not target:
            continue
        ranked_labeled.append((_cs_media_priority(identity), target))
    for _priority, target in sorted(ranked_labeled):
        _add(target)

    # 2) Unlabeled chrome in the input toolbar band (bottom ~30%).
    clickable = [item for item in elements if item.get("clickable")]
    bounded = [(item, _bounds_tuple(str(item.get("bounds") or ""))) for item in clickable]
    bounded = [(item, bounds) for item, bounds in bounded if bounds]
    width = max((bounds[2] for _, bounds in bounded), default=0)
    height = max((bounds[3] for _, bounds in bounded), default=0)
    toolbar: list[tuple[int, float, float, str]] = []
    if width and height:
        for item, bounds in bounded:
            identity = " ".join(str(item.get(key) or "") for key in ("resource_id", "text", "content_desc")).strip()
            center_x = (bounds[0] + bounds[2]) / 2
            center_y = (bounds[1] + bounds[3]) / 2
            node_width, node_height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            if center_y < height * 0.68:
                continue
            # Skip the wide text-input field itself.
            if node_width >= width * 0.45:
                continue
            if node_height > height * 0.30:
                continue
            target = str(item.get("target") or item.get("resource_id") or "") or None
            if not target:
                continue
            # Prefer smaller icon-like nodes; bias right-side attach and centre mic.
            side_bias = abs(center_x / width - 0.85) if center_x > width * 0.65 else abs(center_x / width - 0.50)
            toolbar.append((_cs_media_priority(identity), side_bias, -center_y, target))
        for _prio, _side, _y, target in sorted(toolbar):
            _add(target)

    # 3) Last-resort recipes for WebViews that hide the toolbar entirely.
    # Only when the page also looks like a composer (input/send/hold-to-talk),
    # otherwise a false CS title match must not spray blind bottom taps.
    # Centre ≈ hold-to-talk / mic; right ≈ ``+``/attach; left ≈ voice toggle.
    composer_cues = (
        "请输入", "发送", "按住说话", "说点什么", "输入消息",
        "please enter", "send", "hold to talk", "type a message",
    )
    text_blob = str(page_text or "")
    text_lower = text_blob.lower()
    has_composer = any(cue.lower() in text_lower or cue in text_blob for cue in composer_cues)
    if not ordered and has_composer:
        for recipe in ("relative:0.50,0.88", "relative:0.88,0.88", "relative:0.12,0.88"):
            _add(recipe)
    return ordered


def _customer_service_sensitive_control(
    activity: str, elements: list[dict], page_text: str, *, exclude: set[str] | None = None,
) -> str | None:
    """Next unused media/permission affordance on a customer-service surface."""
    blocked = set(exclude or ())
    for target in _iter_customer_service_media_targets(activity, elements, page_text):
        if target not in blocked:
            return target
    return None


def _redress_sensitive_control(
    activity: str, elements: list[dict], page_text: str, *, exclude: set[str] | None = None,
) -> str | None:
    """Generic name for media/evidence controls on any redress surface."""
    return _customer_service_sensitive_control(
        activity, elements, page_text, exclude=exclude,
    )


def _prefer_labeled_media_probe(
    candidates: list[str],
    *,
    preferred: str | None,
    attempted: set[str] | None = None,
    require_cs_for_relative: bool = False,
    activity: str = "",
    page_text: str = "",
) -> str | None:
    """Prefer accessibility targets; relative recipes only on confirmed CS composers."""
    blocked = set(attempted or ())
    chosen = str(preferred or "").strip() or None
    if chosen and chosen.startswith("relative:"):
        labeled = next(
            (
                item for item in candidates
                if not str(item).startswith("relative:") and item not in blocked
            ),
            None,
        )
        if labeled:
            return labeled
        if require_cs_for_relative and not _is_customer_service_surface(activity, page_text):
            return None
    if chosen and chosen not in blocked:
        return chosen
    for item in candidates:
        if item in blocked:
            continue
        if str(item).startswith("relative:") and require_cs_for_relative:
            if not _is_customer_service_surface(activity, page_text):
                continue
        return item
    return None


def _semantic_sensitive_business_control(
    elements: list[dict],
    *,
    exclude: set[str] | None = None,
    allow_nav_chrome: bool = True,
    require_avatar_or_upload: bool = False,
) -> str | None:
    """Return a visible sensitive-feature action from any App surface.

    This is the general 4.2 entry point. It derives the target from the
    current accessibility tree rather than an app name, report baseline, or
    fixed coordinate. Customer-service surfaces add toolbar recipes separately.
    """
    blocked = set(exclude or ())
    sensitive_terms = (
        *_CS_MEDIA_LABEL_TERMS,
        "头像", "avatar",
    )
    if require_avatar_or_upload:
        sensitive_terms = (
            "头像", "avatar", "上传", "upload", "相册", "gallery", "拍照", "相机", "camera", "photo",
        )
    skip_terms = (
        "reading_record", "readingrecord", "oi_reading",
        ":id/qq", ":id/wechat", "oi_qq", "oi_wechat", "微信客服", "qq客服",
    )
    # Home chrome often uses *image ids (head_image/history_image) that wrongly
    # match the bare media token "image".
    nav_chrome_terms = (
        "head_image", "history_image", "resource_image", "banner", "tab_", "navi_",
        "bottom_nav", "home_image", "iv_home", "iv_mine",
    )
    # Accessibility trees frequently expose the “头像” label as a non-clickable
    # sibling and the actual ImageView only as ``head_image``.  On a profile
    # form that pairing is a business upload entry, while the same bare id on a
    # home toolbar remains navigation chrome.
    page_has_avatar_label = any(
        any(term in " ".join(str(item.get(key) or "") for key in ("text", "content_desc")).lower()
            for term in ("头像", "avatar"))
        for item in elements
    )
    clickable = [item for item in elements if item.get("clickable")]
    ranked: list[tuple[int, str]] = []
    for item in clickable:
        identity = " ".join(str(item.get(key) or "") for key in (
            "target", "resource_id", "text", "content_desc",
        )).lower()
        sibling_labeled_avatar = bool(
            require_avatar_or_upload
            and page_has_avatar_label
            and any(term in identity for term in ("head_image", "headimage", "avatar"))
        )
        if any(term in identity for term in skip_terms):
            continue
        if not allow_nav_chrome and any(term in identity for term in nav_chrome_terms):
            if not sibling_labeled_avatar:
                continue
        if allow_nav_chrome and any(term in identity for term in nav_chrome_terms):
            # Even when chrome is allowed globally, bare *image nav icons are not
            # permission probes unless they also look like avatar/upload.
            if not any(term in identity for term in ("头像", "avatar", "upload", "上传", "相册", "camera", "拍照")):
                continue
        visible_label = " ".join(
            str(item.get(key) or "") for key in ("text", "content_desc")
        ).strip().lower()
        resource_identity = " ".join(
            str(item.get(key) or "") for key in ("target", "resource_id")
        ).strip().lower()
        if any(term in identity for term in (
            "返回", "后退", "关闭", "取消", "back", "close", "cancel",
            "play", "pause", "refresh", "recommend", "history", "search",
            "播放", "暂停", "刷新", "推荐", "历史", "搜索",
        )):
            continue
        attach = (
            visible_label in {"+", "＋"}
            or any(term in visible_label for term in (
                "附件", "添加图片", "上传文件", "attach", "attachment", "upload",
            ))
            or any(term in resource_identity for term in (
                "attach", "attachment", "upload", "ic_plus", "btn_plus",
            ))
        )
        strong_label = any(term.lower() in visible_label for term in sensitive_terms)
        strong_resource = any(term in resource_identity for term in (
            "camera", "capture", "shutter", "microphone", "record_audio",
            "voice", "album", "gallery", "upload", "attachment", "avatar",
            "head_image", "photocapture",
        ))
        if not attach and not sibling_labeled_avatar and not strong_label and not strong_resource:
            continue
        # Bare substring "image"/"picture" on resource ids is too broad.
        if not require_avatar_or_upload:
            label_ok = any(
                term.lower() in identity for term in sensitive_terms
                if term.lower() not in {"image", "picture"}
            ) or any(term in identity for term in ("头像", "avatar"))
            if not attach and not label_ok and ("image" in identity or "picture" in identity):
                continue
        target = str(item.get("target") or item.get("resource_id") or item.get("text") or item.get("content_desc") or "")
        if not target or target in blocked:
            continue
        ranked.append((_cs_media_priority(identity), target))
    ranked.sort()
    return ranked[0][1] if ranked else None


def _iter_media_capture_chooser_targets(
    elements: list[dict], *, exclude: set[str] | None = None,
) -> list[str]:
    """All camera/take-photo controls on a media-source sheet (multi-candidate)."""
    capture_terms = (
        "拍照", "拍摄照片", "拍摄", "照相机", "take photo", "take picture", "take a photo",
        "shutter", "capture", "photocapture", "ic_camera", "tv_camera", "oi_camera",
        ":id/camera", "/camera", "camera",
    )
    skip_terms = ("相册", "gallery", "photos", "album", "文件", "documents", "tv_file", "oi_file")
    blocked = set(exclude or ())
    ordered: list[str] = []
    seen: set[str] = set()
    for item in elements:
        if not item.get("clickable"):
            continue
        identity = " ".join(
            str(item.get(key) or "") for key in ("target", "resource_id", "text", "content_desc")
        ).lower()
        if any(term in identity for term in skip_terms) and not any(term in identity for term in capture_terms):
            continue
        if not (
            any(term in identity for term in capture_terms)
            or identity.strip() in {"相机", "camera", "照相机"}
        ):
            continue
        target = str(
            item.get("target") or item.get("resource_id") or item.get("text") or item.get("content_desc") or ""
        )
        if not target or target in blocked or target in seen:
            continue
        seen.add(target)
        ordered.append(target)
    return ordered


def _media_capture_chooser_target(
    elements: list[dict], *, exclude: set[str] | None = None,
) -> str | None:
    """Prefer a visible camera/take-photo control over the album picker.

    Android 13+ photo pickers often skip the runtime permission dialog.  The
    camera option is the path that still produces a 2.3 purpose-inform check.
    Match a family of labels/ids (照相机/拍照/tv_camera/…), not one vendor string.
    """
    targets = _iter_media_capture_chooser_targets(elements, exclude=exclude)
    return targets[0] if targets else None


def _iter_media_album_chooser_targets(
    elements: list[dict], *, exclude: set[str] | None = None,
) -> list[str]:
    """All album/file picker controls on a media-source sheet (multi-candidate)."""
    album_terms = (
        "相册", "图库", "从相册", "选择图片", "本地相册", "gallery", "photos", "album",
        "tv_file", "oi_file", "tv_album", "oi_album", ":id/album", "/album",
    )
    skip_terms = ("拍照", "拍摄", "照相机", "camera", "capture", "shutter")
    blocked = set(exclude or ())
    ordered: list[str] = []
    seen: set[str] = set()
    for item in elements:
        if not item.get("clickable"):
            continue
        identity = " ".join(
            str(item.get(key) or "") for key in ("target", "resource_id", "text", "content_desc")
        ).lower()
        if any(term in identity for term in skip_terms) and not any(term in identity for term in album_terms):
            continue
        if not any(term in identity for term in album_terms):
            continue
        target = str(
            item.get("target") or item.get("resource_id") or item.get("text") or item.get("content_desc") or ""
        )
        if not target or target in blocked or target in seen:
            continue
        seen.add(target)
        ordered.append(target)
    return ordered


def _media_album_chooser_target(
    elements: list[dict], *, exclude: set[str] | None = None,
) -> str | None:
    """Album/file picker on a media-source sheet — storage/4.2 probe family."""
    targets = _iter_media_album_chooser_targets(elements, exclude=exclude)
    return targets[0] if targets else None


def _file_picker_camera_target(elements: list[dict]) -> str | None:
    return _media_capture_chooser_target(elements)


def _sensitive_business_control(
    activity: str, elements: list[dict], page_text: str, *, exclude: set[str] | None = None,
) -> str | None:
    """Find the next safe, generic 4.2 permission-dependent feature."""
    blocked = set(exclude or ())
    return _semantic_sensitive_business_control(elements, exclude=blocked) or _customer_service_sensitive_control(
        activity, elements, page_text, exclude=blocked,
    )


class RedressMediaProbeExecutor:
    """DFS over permission-trigger families, avoiding equivalent repeat clicks."""

    def __init__(self, *, identity_resolver: Callable[[str], str] | None = None) -> None:
        self.identity_resolver = identity_resolver or (lambda target: target)

    def next_target(self, candidates: Iterable[str], *, attempted: set[str] | None = None) -> str | None:
        blocked = set(attempted or ())
        remaining = [target for target in candidates if target and target not in blocked]
        if not remaining:
            return None
        tried_families = {media_family(self.identity_resolver(target)) for target in blocked}
        for target in remaining:
            family = media_family(self.identity_resolver(target))
            if family not in tried_families or family == "other":
                return target
        return remaining[0]


class RedressMediaProbePolicy:
    """Build side-effect-free candidates for media probes on redress surfaces."""

    _EARLY_EXIT_ACTIONS = frozenset({"stop", "wait", "back"})

    def early_exit_directive(
        self,
        *,
        action: str,
        candidates: Iterable[str],
        attempted_targets: set[str] | None = None,
    ) -> DecisionDirective | None:
        """Prefer the next media family when a prior proposal leaves too early."""
        if str(action or "") not in self._EARLY_EXIT_ACTIONS:
            return None
        target = RedressMediaProbeExecutor().next_target(
            candidates, attempted=set(attempted_targets or ()),
        )
        if not target:
            return None
        return DecisionDirective(
            action="click",
            target=target,
            reason="LLM 试图提前离开客服页，按深度优先顺序轮询未访问的语音/拍照/相册/上传/加号按钮",
            source="deterministic_scenario",
            priority=150,
            effects=("record_media_probe",),
        )

    def exhausted_directive(self, *, action: str) -> DecisionDirective | None:
        """Leave a confirmed redress surface only after its probe choices are exhausted."""
        if str(action or "") not in self._EARLY_EXIT_ACTIONS:
            return None
        return DecisionDirective(
            action="back",
            target="",
            reason="客服页安全按钮已穷尽或均无效果，返回上一级继续深度探索其它入口",
            source="deterministic_deep_search",
            priority=150,
            effects=("record_customer_service_exhausted",),
        )


def redress_entry_target(elements: list[dict], visited_targets: set[str] | None = None) -> str | None:
    """Visible complaint/feedback/help/ticket/support entry for 4.2/6.x."""
    visited = set(visited_targets or ())
    ranked: list[tuple[int, str]] = []
    for element in elements:
        if not element.get("clickable"):
            continue
        roles = _roles_for_element(element)
        identity = " ".join(
            str(element.get(key) or "") for key in ("text", "content_desc", "resource_id", "target")
        )
        lowered = identity.lower()
        is_cs = bool(roles & {"complaint_control"}) or any(
            term.lower() in lowered for term in COMPLAINT_TERMS
        )
        if not is_cs:
            continue
        # Avoid destructive / offline-channel copy that is not a live CS entry.
        if any(term in identity for term in ("暂不", "取消注销", "确认注销")):
            continue
        target = str(
            element.get("target") or element.get("resource_id")
            or element.get("text") or element.get("content_desc") or ""
        )
        if not target or target in visited:
            continue
        label = re.sub(r"\s+", "", f"{element.get('text') or ''}{element.get('content_desc') or ''}")
        # Prefer short tab/row labels (客服) over long FAQ sentences.
        priority = 0 if 0 < len(label) <= 6 else 1
        if any(term in label for term in ("客服", "投诉", "举报")):
            priority = 0
        ranked.append((priority, target))
    ranked.sort()
    return ranked[0][1] if ranked else None


def complaint_or_cs_entry_target(elements: list[dict], visited_targets: set[str] | None = None) -> str | None:
    """Backward-compatible alias for the generic redress entry selector."""
    return redress_entry_target(elements, visited_targets)


def page_visible_text(elements: list[dict]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for element in elements:
        if not element.get("displayed", True):
            continue
        for key in ("text", "content_desc"):
            value = str(element.get(key) or "").strip()
            if value and value not in seen:
                seen.add(value)
                parts.append(value)
    return " ".join(parts)


def privacy_path_observations(elements: list[dict], page_text: str) -> dict:
    """Find non-destructive privacy-service entries visible to the device.

    Discovery is evidence of an accessible route, not evidence that a backend
    deletion or complaint workflow completed successfully.
    """
    def targets_for(terms: tuple[str, ...]) -> list[str]:
        targets: list[str] = []
        seen: set[str] = set()

        def _add(target: str) -> None:
            value = str(target or "").strip()
            if value and value not in seen:
                seen.add(value)
                targets.append(value)

        for element in elements:
            identity = _element_semantic_identity(element, elements)
            if not any(term.lower() in identity.lower() for term in terms):
                continue
            if any(term.lower() in identity.lower() for term in _DESTRUCTIVE_CONFIRM_TERMS):
                continue
            if element.get("clickable"):
                _add(_element_locator(element))
                continue
            # Label on a non-clickable child → click the enclosing row.
            parent = _tightest_enclosing_clickable(elements, element)
            if parent is not None:
                _add(_element_locator(parent))
        return targets

    delete_targets = targets_for(DELETE_TERMS)
    complaint_targets = targets_for(COMPLAINT_TERMS)
    withdraw_targets = targets_for(WITHDRAW_TERMS)
    personalization_targets = [
        _element_locator(element)
        for element in elements
        if element.get("clickable") and "personalization_control" in _roles_for_element(element)
    ]
    personalization_targets = [target for target in personalization_targets if target]
    return {
        "delete_targets": delete_targets,
        "complaint_targets": complaint_targets,
        "withdraw_targets": withdraw_targets,
        "personalization_targets": personalization_targets,
        "delete_obstacle": bool(delete_targets) and any(term in page_text for term in DELETE_OBSTACLE_TERMS),
    }
