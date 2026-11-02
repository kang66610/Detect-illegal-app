"""操作历史的后端语义化描述：时间线事件必须带可读中文 text 字段。"""
from backend.app.services.timeline_text import describe_event


def test_document_read_complete_names_the_document_and_marks_full_read():
    text = describe_event({
        "event_type": "document_read_complete",
        "document": ".WebViewActivity:document:隐私政策",
        "document_kind": "privacy_policy",
        "scrolls": 0,
    })

    assert "隐私政策" in text
    assert "已全部阅读" in text


def test_external_browser_read_complete_reports_browser_and_scrolls():
    text = describe_event({
        "event_type": "external_document_read_complete",
        "origin_target": "《隐私政策》",
        "target": "隐私政策",
        "scrolls": 52,
    })

    assert "《隐私政策》" in text
    assert "浏览器" in text
    assert "52" in text


def test_inline_document_open_and_splash_probe_describe_intent():
    opened = describe_event({
        "event_type": "inline_document_opened",
        "target": "《隐私政策》",
        "document_kind": "privacy_policy",
    })
    probe = describe_event({
        "event_type": "splash_document_probe_started",
        "target": "《服务协议》",
    })

    assert "打开" in opened and "《隐私政策》" in opened
    assert "探测" in probe and "《服务协议》" in probe


def test_llm_override_shows_proposed_vs_executed_decision():
    text = describe_event({
        "event_type": "llm_decision_overridden",
        "original_action": "wait",
        "original_target": "",
        "new_action": "click",
        "new_target": "Appium Settings",
        "override_source": "generic_safe_sibling",
    })

    assert "模型" in text
    assert "等待" in text
    assert "Appium Settings" in text


def test_action_failed_reports_readable_target_without_raw_resource_id_noise():
    text = describe_event({
        "event_type": "action_failed",
        "action": "click",
        "target": "com.example.flowers:id/tv_about_us",
        "error": "执行遍历操作 click 失败：未找到包含文本的控件：com.example.flowers:id/tv_about_us",
    })

    assert "tv_about_us" in text
    assert "com.example.flowers:id/" not in text


def test_document_kind_mismatch_explains_clicked_vs_actual():
    text = describe_event({
        "event_type": "document_kind_mismatch",
        "target": "《隐私政策》",
        "expected": "privacy_policy",
        "observed": "service_terms",
    })

    assert "《隐私政策》" in text
    assert "服务协议" in text
    assert "隐私政策" in text


def test_already_read_skip_and_consent_and_scroll_events():
    assert "跳过" in describe_event({
        "event_type": "document_already_read_skip",
        "document_kind": "privacy_policy",
    })
    assert "同意" in describe_event({"event_type": "privacy_consent_clicked"})
    assert "第 7 屏" in describe_event({
        "event_type": "external_document_scrolled", "scroll_index": 7,
    })


def test_final_click_actions_are_described_with_clean_targets():
    text = describe_event({
        "event_type": "action_completed",
        "action": "click",
        "target": "com.example.flowers:id/tv_about_us",
    })

    assert "点击" in text
    assert "tv_about_us" in text
    assert "com.example.flowers:id/" not in text


def test_unknown_or_empty_events_degrade_to_empty_string_not_crash():
    assert describe_event({"event_type": "totally_new_event"}) == ""
    assert describe_event({}) == ""
    assert describe_event({"event_type": "document_read_complete"}) != ""
