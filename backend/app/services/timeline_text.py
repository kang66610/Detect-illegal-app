"""时间线事件的中文语义描述。

API 层为每条事件计算一次 ``text``，前端直接展示；无法识别的事件返回
空串、不注入字段，前端继续走本地映射。描述必须忠实于已发生的事实：
读了哪份条款、模型建议了什么、实际执行了什么、点击为什么失败。
"""
from __future__ import annotations

_ACTION_ZH = {
    "click": "点击",
    "back": "返回",
    "wait": "等待",
    "stop": "停止",
    "scroll": "下滑",
}

_KIND_ZH = {
    "privacy_policy": "隐私政策",
    "user_agreement": "用户协议",
    "service_terms": "服务协议",
    "disclosure_list": "收集清单",
    "sdk_directory": "SDK 目录",
    "child_policy": "儿童个人信息规则",
}


def _action_zh(action: object) -> str:
    return _ACTION_ZH.get(str(action or ""), str(action or "操作"))


def _short_target(target: object) -> str:
    """``com.pkg:id/tv_about_us`` → ``tv_about_us``；可见文本原样保留。"""
    raw = str(target or "")
    if ":id/" in raw:
        return raw.rsplit(":id/", 1)[-1] or raw
    if raw.startswith("pkg:"):
        return raw[4:]
    return raw


def _kind_zh(kind: object) -> str:
    return _KIND_ZH.get(str(kind or ""), str(kind or ""))


def _document_title(event: dict) -> str:
    """优先书名号入口名，其次事件里的文档键尾部，最后按 kind 推断。"""
    for key in ("origin_target", "target"):
        raw = str(event.get(key) or "").strip()
        if raw:
            return raw.strip("《》")
    marker = str(event.get("document") or "")
    if ":document:" in marker:
        tail = marker.rsplit(":document:", 1)[-1]
        if tail and tail != "body":
            return tail
    return _kind_zh(event.get("document_kind"))


def _document_display(event: dict) -> str:
    title = _document_title(event)
    return f"《{title}》" if title else "该条款"


def describe_event(event: dict) -> str:
    """返回一条事件的中文描述；无法识别时返回空串。"""
    event_type = str(event.get("event_type") or "")
    try:
        return _describe(event, event_type)
    except Exception:
        # 描述失败不能影响时间线接口本身。
        return ""


def _describe(event: dict, event_type: str) -> str:
    if event_type in {"action_completed", "decision"}:
        action = str(event.get("action") or "click")
        target = _short_target(event.get("target"))
        verb = _action_zh(action)
        if action == "click":
            return f"点击「{target}」" if target else "点击页面控件"
        if action == "back":
            return "返回上一页"
        if action == "wait":
            return "等待页面稳定"
        if action == "scroll":
            return "下滑阅读正文"
        if action == "stop":
            return "结束本页遍历"
        return verb

    if event_type == "llm_decision_overridden":
        proposed = f"{_action_zh(event.get('original_action'))}「{_short_target(event.get('original_target'))}」"
        executed = f"{_action_zh(event.get('new_action'))}「{_short_target(event.get('new_target'))}」"
        return f"模型建议{proposed.strip('「」') or '保持等待'}，按确定性策略改为执行{executed}"

    if event_type == "action_failed":
        target = _short_target(event.get("target"))
        error = str(event.get("error") or "")
        if "未找到" in error:
            return f"{_action_zh(event.get('action'))}「{target}」未找到对应控件，已跳过该入口"
        detail = error.split("：", 1)[-1][:80]
        return f"{_action_zh(event.get('action'))}「{target}」失败：{detail}"

    if event_type == "inline_document_opened":
        kind = _kind_zh(event.get("document_kind"))
        suffix = f"（{kind}）" if kind else ""
        return f"打开{event.get('target', '条款正文')}{suffix}"

    if event_type == "splash_document_probe_started":
        return f"探测同意弹窗上的独立条款入口：{event.get('target', '')}（验证能否打开）"

    if event_type == "external_document_read_complete":
        scrolls = int(event.get("scrolls") or 0)
        return f"{_document_display(event)}已在系统浏览器完整阅读（{scrolls} 屏）"

    if event_type == "document_read_complete":
        scrolls = int(event.get("scrolls") or 0)
        tail = f"{scrolls} 屏" if scrolls else "无需滚动"
        return f"{_document_display(event)}标记为已全部阅读（{tail}）"

    if event_type == "document_already_read_skip":
        return f"{_document_display(event)}此前已形成完整阅读证据，跳过重复阅读"

    if event_type == "document_kind_mismatch":
        clicked = _short_target(event.get("target"))
        observed = _kind_zh(event.get("observed")) or str(event.get("observed") or "")
        expected = _kind_zh(event.get("expected")) or str(event.get("expected") or "")
        return f"点击「{clicked}」打开的正文实际是{observed}（期望{expected}），已按正文实际条款记账"

    if event_type == "privacy_consent_clicked":
        return "已点击同意隐私政策"

    if event_type == "external_document_scrolled":
        return f"浏览器内阅读长文第 {int(event.get('scroll_index') or 1)} 屏"

    if event_type == "document_scrolled":
        return f"向下阅读长文第 {int(event.get('scroll_index') or 1)} 屏"

    if event_type == "document_blank_returned":
        return "条款正文加载为空白，已返回"

    if event_type == "document_content_unavailable":
        return "条款正文不可读取，已返回继续其它路径"

    if event_type == "document_read_incomplete":
        return f"长文未形成完整阅读证据（已下滑 {int(event.get('scrolls') or 0)} 屏）"

    if event_type == "screen_text_recovered":
        return "页面无可访问文本，已通过 OCR 恢复屏幕文字"

    if event_type == "llm_action_proposed":
        accepted = str(event.get("status") or "") == "accepted"
        verdict = "已采纳" if accepted else f"未采纳（{event.get('fallback_reason') or '无效输出'}）"
        return f"模型提案{verdict}，耗时 {int(event.get('latency_ms') or 0)}ms"

    if event_type == "llm_effectiveness_summary":
        total = int(event.get("decisions_total") or 0)
        fallback = int(event.get("fallback_decisions") or 0)
        ratio = event.get("fallback_ratio")
        ratio_text = f"，兜底占比 {ratio}" if ratio is not None else ""
        return f"本阶段最终动作 {total} 个，其中兜底决策 {fallback} 个{ratio_text}"

    if event_type == "document_scroll_aborted":
        return "条款滑动时会话断开且无法恢复，结束该正文"

    return ""
