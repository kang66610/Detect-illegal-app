"""UI 角色分类：词表只是弱先验，规则和遍历消费角色而不是某个 App 的文案。"""
from __future__ import annotations

ROLE_SCENARIOS: dict[str, tuple[str, ...]] = {
    "document_link": ("1.1", "1.2", "1.3", "1.4", "2.1"),
    "privacy_hub_entry": ("1.3", "3.8", "6.1"),
    "settings_entry": ("1.3", "3.8", "6.1"),
    "withdraw_control": ("3.8",),
    "delete_control": ("6.1", "6.2"),
    "complaint_control": (),
    "business_trigger": ("2.3", "4.1", "4.2", "4.6"),
    "consent_checkbox": ("3.4",),
    "personalization_control": ("3.6",),
}

_DOCUMENT = (
    "隐私政策", "隐私声明", "隐私协议", "用户协议", "服务协议", "服务条款",
    "privacy policy", "privacy agreement", "terms of service",
)
_DOCUMENT_LIST = ("个人信息收集清单", "第三方sdk", "sdk目录", "信息共享清单")
_SETTINGS = (
    "设置", "settings", "我", "我的", "个人中心", "用户中心", "账户中心", "账号中心",
    "个人主页", "个人信息", "账户信息", "账号管理", "安全中心", "profile", "account", "关于",
)
_SETTINGS_DISTRACTORS = (
    "通知设置", "推送设置", "消息设置", "消息通知", "推送通知",
    "notification settings", "push settings",
    "清除缓存", "清理缓存", "缓存清理", "清空缓存", "clear cache", "clean cache",
    "检查更新", "版本更新", "软件更新", "check for updates", "software update",
    "给个好评", "去评分", "应用评分", "rate app", "review app",
)
_WITHDRAW = ("撤回同意", "撤回授权", "撤销同意", "撤销授权", "关闭授权", "授权管理", "管理授权", "撤回个人信息")
_DELETE = ("注销账号", "账号注销", "删除账号", "删除个人信息", "注销")
_COMPLAINT = (
    "投诉", "举报", "客服", "联系我们", "意见反馈", "反馈", "帮助与支持", "帮助中心",
    "工单", "报料", "问题申诉", "在线支持", "售后支持",
    "complaint", "feedback", "customer service", "contact us", "help center", "support", "ticket", "appeal",
)
_BUSINESS = (
    "头像", "拍照", "相机", "相册", "上传", "附件", "凭证", "麦克风", "录音", "语音", "定位", "导航", "扫码",
    "avatar", "camera", "photo", "upload", "attach", "evidence", "microphone", "record", "scan",
)
_PERSONALIZATION = ("关闭个性化", "关闭定向", "非定向", "广告推荐管理", "个性化广告", "广告个性化", "关闭推荐")
_CONSENT_ACCEPT = ("同意并继续", "同意", "接受", "agree", "accept")
_CONSENT_DECLINE = ("不同意", "拒绝", "暂不", "decline")
_CHECKBOX_HINTS = ("checkbox", "check_box", "cb_agree", "agree_check", "iv_check")


def _identity(element: dict) -> str:
    return " ".join(
        str(element.get(key) or "") for key in ("resource_id", "text", "content_desc", "target", "class_name")
    ).lower()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms)


def roles_for_element(element: dict) -> set[str]:
    """Return zero or more semantic roles for one visible control."""
    if not element:
        return set()
    identity = _identity(element)
    roles: set[str] = set()
    class_name = str(element.get("class_name") or "").lower()
    if element.get("checkable") or any(hint in identity for hint in _CHECKBOX_HINTS) or "checkbox" in class_name:
        if _has_any(identity, ("同意", "隐私", "agree", "consent", "cb_agree", "checkbox", "check_box")):
            roles.add("consent_checkbox")
    if _has_any(identity, _DOCUMENT) or _has_any(identity, _DOCUMENT_LIST):
        roles.add("document_link")
    if _has_any(identity, _WITHDRAW):
        roles.add("withdraw_control")
    if _has_any(identity, _DELETE) and "登录" not in identity:
        roles.add("delete_control")
    if _has_any(identity, _COMPLAINT):
        roles.add("complaint_control")
    if _has_any(identity, _PERSONALIZATION):
        roles.add("personalization_control")
    if _has_any(identity, _SETTINGS):
        if _has_any(identity, _SETTINGS_DISTRACTORS):
            pass
        elif _has_any(identity, (
            "设置", "settings", "我的", "个人中心", "用户中心", "账户中心", "账号中心",
            "个人主页", "个人信息", "账户信息", "账号管理", "安全中心", "profile", "account", "关于",
        )):
            roles.add("settings_entry")
            roles.add("privacy_hub_entry")
    if _has_any(identity, _BUSINESS):
        roles.add("business_trigger")
    if element.get("clickable") and _has_any(identity, _CONSENT_ACCEPT) and not _has_any(identity, _CONSENT_DECLINE):
        if "协议" in identity or "隐私" in identity or _has_any(identity, ("agree", "accept", "同意")):
            roles.add("consent_accept")
    return roles


def scenarios_for_roles(roles: set[str] | tuple[str, ...] | list[str]) -> set[str]:
    items: set[str] = set()
    for role in roles or ():
        items.update(ROLE_SCENARIOS.get(str(role), ()))
    return items


def annotate_elements(elements: list[dict]) -> list[dict]:
    for element in elements:
        element["roles"] = sorted(roles_for_element(element))
    return elements


def forced_service_consent(page_text: str) -> bool:
    compact = "".join(str(page_text or "").split()).lower()
    service = any(term in compact for term in ("改善服务", "提升体验", "优化体验", "改善体验", "提升服务"))
    forced = any(term in compact for term in ("必须同意", "不同意将无法", "否则无法使用", "不授权无法", "不授权将无法"))
    return service and forced


def misleading_consent_copy(page_text: str, elements: list[dict]) -> bool:
    """True when a privacy gate disguises accept as a benefit / one-tap grant."""
    compact = "".join(str(page_text or "").split()).lower()
    if not any(term in compact for term in ("隐私", "个人信息", "privacy")):
        return False
    labels = " ".join(_identity(element) for element in elements if element.get("clickable")).lower()
    deceptive = any(term in labels for term in ("立即领取", "开启全部权限", "一键开启权限", "开启所有权限"))
    has_plain_agree = any(term in labels for term in ("同意并继续", "同意", "agree"))
    return deceptive and not has_plain_agree


def personalization_mentioned(text: str) -> bool:
    compact = str(text or "").lower()
    return any(term in compact for term in ("个性化推荐", "定向推送", "个性化广告", "广告个性化", "定向广告"))
