import pytest

from agent.ai_explorer.llm_controller import LLMController
from agent.ai_explorer.page_state import NavigationGraph, PageState, parse_page
from agent.ai_explorer.explorer_engine import _page_is_loading_shell
from agent.rule_engine.scenario_plan import ScenarioFrontier
from backend.app.config import load_config


_XML = '''<hierarchy><node text="设置" resource-id="com.demo:id/settings" clickable="true" class="android.widget.TextView"/><node text="普通文本" clickable="false"/></hierarchy>'''


def test_page_parser_and_fingerprint_are_stable():
    page = parse_page(".MainActivity", _XML)
    assert page.elements[0]["resource_id"] == "com.demo:id/settings"
    state = PageState()
    assert state.is_new(page)
    assert not state.is_new(parse_page(".MainActivity", _XML))


def test_bare_framelayout_is_a_loading_shell_but_home_and_policy_are_not():
    loading = parse_page(
        ".MainActivity",
        '<hierarchy><node class="android.widget.FrameLayout" clickable="false" resource-id="android:id/content" bounds="[0,0][1080,2400]"/></hierarchy>',
    )
    home = parse_page(
        ".MainActivity",
        '<hierarchy><node text="首页" resource-id="home" clickable="false"/><node text="设置" resource-id="settings" clickable="true"/></hierarchy>',
    )
    policy = parse_page(
        ".WebViewActivity",
        '<hierarchy><node text="隐私政策 第一部分" clickable="false" class="android.widget.TextView"/></hierarchy>',
    )
    chrome_terms = parse_page(
        "org.chromium.chrome.browser.ChromeTabbedActivity",
        '<hierarchy><node class="android.webkit.WebView" clickable="false" scrollable="true" bounds="[0,0][1080,2200]"/></hierarchy>',
    )
    webview_body = parse_page(
        ".module.web.AgreementActivity",
        '<hierarchy><node class="android.webkit.WebView" clickable="false" scrollable="true"/></hierarchy>',
    )
    assert _page_is_loading_shell(loading)
    assert not _page_is_loading_shell(home)
    assert not _page_is_loading_shell(policy)
    assert not _page_is_loading_shell(chrome_terms)
    assert not _page_is_loading_shell(webview_body)
    active = PageState()
    active.active_document = ".WebViewActivity:document:服务协议"
    assert not _page_is_loading_shell(
        parse_page(".WebViewActivity", '<hierarchy><node class="android.widget.FrameLayout" clickable="false"/>'),
        active,
    )


def test_page_parser_preserves_checked_state_for_consent_controls():
    page = parse_page(".PrivacyActivity", '''<hierarchy><node text="同意隐私政策" resource-id="agree" checked="true" clickable="true" class="android.widget.CheckBox"/></hierarchy>''')

    assert page.elements[0]["checked"] is True


def test_page_state_captures_each_document_view_once_and_bounds_scrolling():
    page = parse_page(".PrivacyActivity", _XML)
    state = PageState()
    state.is_new(page)
    state.start_document(".PrivacyActivity:privacy")

    assert state.should_capture(page)
    assert not state.should_capture(page)
    assert state.can_scroll_document(".PrivacyActivity:privacy", 2)
    assert state.mark_document_scrolled(".PrivacyActivity:privacy") == 1
    assert state.should_capture(page)  # same XML, but a different scrolled viewport
    assert state.mark_document_scrolled(".PrivacyActivity:privacy") == 2
    assert not state.can_scroll_document(".PrivacyActivity:privacy", 2)


def test_page_state_scopes_repeated_resource_ids_to_the_current_screen():
    state = PageState()
    first = parse_page(".FirstActivity", _XML)
    second = parse_page(".SecondActivity", _XML)

    state.mark_target(first, "com.demo:id/continue")

    assert state.target_visited(first, "com.demo:id/continue")
    assert not state.target_visited(second, "com.demo:id/continue")


def test_same_layout_with_different_business_state_is_not_collapsed_as_one_surface():
    first = parse_page(".MainActivity", '''<hierarchy><node text="首页" resource-id="tab" class="android.widget.TextView"/><node text="待处理" resource-id="status" class="android.widget.TextView"/></hierarchy>''')
    second = parse_page(".MainActivity", '''<hierarchy><node text="我的" resource-id="tab" class="android.widget.TextView"/><node text="已登录" resource-id="status" class="android.widget.TextView"/></hierarchy>''')

    assert first.surface_fingerprint != second.surface_fingerprint


def test_main_tab_variants_are_all_roots_but_keep_independent_targets():
    state = PageState()
    home = parse_page(".MainTabActivity", '''<hierarchy><node text="首页" resource-id="tab" clickable="true" class="android.widget.TextView"/></hierarchy>''')
    profile = parse_page(".MainTabActivity", '''<hierarchy><node text="我的" resource-id="tab" clickable="true" class="android.widget.TextView"/></hierarchy>''')
    state.anchor_root(home)
    state.anchor_root(profile)
    state.mark_target(home, "tab")

    assert state.is_root_page(home) and state.is_root_page(profile)
    assert not state.target_visited(profile, "tab")


def test_navigation_graph_tracks_same_activity_child_and_verified_return():
    home = parse_page(
        ".MainActivity",
        '<hierarchy><node text="首页" resource-id="home" clickable="true" bounds="[0,2200][360,2400]"/></hierarchy>',
    )
    child = parse_page(
        ".MainActivity",
        '<hierarchy><node text="账号与安全" resource-id="title" clickable="false"/>'
        '<node text="注销账号" resource-id="row" clickable="true" bounds="[0,400][1080,560]"/></hierarchy>',
    )
    graph = NavigationGraph()
    graph.observe(home)
    graph.anchor_root(home)
    graph.action_succeeded(home, "home-settings")
    graph.observe(child)

    assert graph.depth == 1
    assert not graph.is_root(child)
    assert graph.edge_status(home, "home-settings") == "descended"

    graph.back_succeeded(child)
    graph.observe(home)
    assert graph.depth == 0
    assert graph.current_node == home.surface_fingerprint


def test_duplicate_resource_ids_are_bound_to_distinct_visible_instances():
    page = parse_page(
        ".MainActivity",
        '''<hierarchy>
          <node text="关于我们" resource-id="row" clickable="true" bounds="[0,300][1080,450]"/>
          <node text="账号注销" resource-id="row" clickable="true" bounds="[0,500][1080,650]"/>
        </hierarchy>''',
    )

    assert [item["target"] for item in page.elements] == [
        "bounds:[0,300][1080,450]", "bounds:[0,500][1080,650]",
    ]
    assert {item["locator"] for item in page.elements} == {"row"}


def test_page_state_only_commits_target_after_execution_success():
    page = parse_page(".MainActivity", _XML)
    state = PageState()
    state.is_new(page)
    state.schedule_target(page, "com.demo:id/settings")
    state.fail_target(page, "com.demo:id/settings", transient=True)
    assert not state.target_visited(page, "com.demo:id/settings")

    state.schedule_target(page, "com.demo:id/settings")
    state.commit_target(page, "com.demo:id/settings")
    assert state.target_visited(page, "com.demo:id/settings")


def test_probe_route_context_distinguishes_identical_feedback_forms_from_different_parents():
    parent_a = parse_page(".MainActivity", '<hierarchy><node text="帮助中心" clickable="true"/></hierarchy>')
    parent_b = parse_page(".MainActivity", '<hierarchy><node text="订单投诉" clickable="true"/></hierarchy>')
    form = parse_page(
        ".WebActivity",
        '<hierarchy><node text="意见反馈 请描述问题" clickable="false"/><node text="上传图片" resource-id="upload" clickable="true"/></hierarchy>',
    )
    state = PageState()
    state.is_new(parent_a)
    state.anchor_root(parent_a)
    state.commit_target(parent_a, "help")
    state.is_new(form)
    first_context = state.route_context(form)
    state.record_action(form, "back")
    state.is_new(parent_a)
    state.is_new(parent_b)
    state.commit_target(parent_b, "complaint")
    state.is_new(form)
    second_context = state.route_context(form)

    assert first_context != second_context


def test_llm_action_context_uses_one_action_id_namespace():
    page = {
        "elements": [
            {"target": "settings", "text": "设置", "clickable": True, "roles": ["settings_entry"]},
            {"target": "camera", "text": "拍照", "clickable": True, "roles": ["media_capture"]},
        ],
        "rule_guided_target": {"target": "camera", "scenario_items": ["2.3", "4.2"]},
        "sensitive_media_families": [{"target": "camera", "family": "camera"}],
    }

    catalog, context = LLMController._action_context(page, {"settings"})

    assert [item["action_id"] for item in catalog] == ["a000", "a001"]
    assert context["visited_actions"] == ["a000"]
    assert context["rule_guided_action"]["action_id"] == "a001"
    assert context["sensitive_media_actions"] == [{"action_id": "a001", "family": "camera"}]
    assert catalog[1]["recommended_for"] == ["2.3", "4.2"]


def test_llm_user_content_includes_numbered_viewport_image_when_available(tmp_path):
    screenshot = tmp_path / "viewport.png"
    screenshot.write_bytes(b"fake-png-for-request-shape")

    content = LLMController._user_content(
        {"untrusted_page_data": {"elements": [{"action_id": "a000", "bounds": "[0,0][100,100]"}]}},
        str(screenshot),
    )

    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_llm_payload_keeps_actionable_controls_beyond_raw_tree_prefix():
    context_nodes = "".join(
        f'<node text="说明{i}" clickable="false"/>' for i in range(100)
    )
    page = parse_page(
        ".ComposeActivity",
        f'<hierarchy>{context_nodes}<node text="投诉反馈" resource-id="feedback" clickable="true"/></hierarchy>',
    )

    payload = page.llm_payload()
    assert payload["elements"][0]["target"] == "feedback"


def test_scenario_frontier_keeps_an_item_open_until_evidence_completion():
    frontier = ScenarioFrontier([{"item": "1.1", "goal": "读取隐私政策", "signals": ("隐私",)}])
    first_elements = [{"resource_id": "privacy", "text": "隐私政策", "content_desc": "", "clickable": True}]
    recommendation = frontier.recommend(first_elements, set())
    frontier.mark_attempted(recommendation["target"], recommendation["scenario_items"])

    assert frontier.snapshot()["remaining_items"] == ["1.1"]
    # An identical resource-id on a semantically different page remains a
    # valid route.  The caller supplies the current page's visited set, so a
    # global target blacklist would incorrectly collapse legitimate repeats.
    assert frontier.recommend(first_elements, set())["target"] == "privacy"
    frontier.mark_completed(["1.1"], evidence_source="policy_document_read")
    assert frontier.snapshot()["remaining_items"] == []


def test_phase_local_frontier_ignores_completion_for_item_outside_active_plan():
    """A shared explorer callback must not crash a reduced allow-phase plan."""
    frontier = ScenarioFrontier([
        {"item": "4.2", "goal": "拒绝权限后的业务可用性", "signals": ("客服",)},
    ])

    frontier.mark_attempted("first-run", ["1.2"])
    frontier.mark_completed(["1.2"], evidence_source="first_run_notice_observed")

    snapshot = frontier.snapshot()
    assert snapshot["attempted_items"] == []
    assert snapshot["completed_items"] == []
    assert snapshot["remaining_items"] == ["4.2"]


def test_page_state_detects_a_back_action_that_did_not_leave_the_page():
    page = parse_page(".MainActivity", _XML)
    state = PageState()
    state.is_new(page)
    state.record_action(page, "back")

    assert state.back_made_no_progress(page)
    assert state.is_root_page(page)


def test_llm_decision_restricts_target_to_current_page():
    elements = parse_page(".MainActivity", _XML).elements
    decision = LLMController.parse_decision('{"action":"click","target":"设置","reason":"进入设置"}', elements)
    assert decision["target"] == "设置"
    with pytest.raises(ValueError, match="白名单"):
        LLMController.parse_decision('{"action":"click","target":"//*[@text=\\\"危险\\\"]"}', elements)


def test_llm_fallback_prefers_privacy_related_clickable_element():
    action = LLMController.fallback_action([
        {"text": "首页", "content_desc": "", "resource_id": "home", "clickable": True},
        {"text": "设置", "content_desc": "", "resource_id": "settings", "clickable": True},
        {"text": "隐私政策", "content_desc": "", "resource_id": "privacy", "clickable": True},
    ], set())
    assert action["action"] == "click"
    # Splash/hub document links are not fallback clicks; prefer 设置 hub entry.
    assert action["target"] == "settings"


def test_llm_decision_only_accepts_exact_clickable_action_ids():
    elements = [
        {"target": "settings-row", "resource_id": "settings-row", "text": "设置中心", "content_desc": "", "clickable": True},
        {"target": "policy-copy", "resource_id": "policy-copy", "text": "隐私政策正文", "content_desc": "", "clickable": False},
    ]

    assert LLMController.parse_decision(
        '{"action":"click","target":"settings-row","reason":"进入设置"}', elements,
    )["target"] == "settings-row"
    with pytest.raises(ValueError, match="可点击"):
        LLMController.parse_decision(
            '{"action":"click","target":"policy-copy","reason":"点正文"}', elements,
        )
    with pytest.raises(ValueError, match="精确"):
        LLMController.parse_decision(
            '{"action":"click","target":"settings","reason":"模糊点设置"}', elements,
        )


def test_llm_fallback_never_clicks_credentials_or_account_submission_controls():
    """A duplicate policy link must not turn into a login attempt.

    This is the exact safe-fallback seam used after the model picks an already
    visited privacy link on a login page.
    """
    action = LLMController.fallback_action([
        {"text": "", "content_desc": "", "resource_id": "com.demo:id/tv_privacy", "clickable": True},
        {"text": "", "content_desc": "", "resource_id": "com.demo:id/et_password", "clickable": True},
        {"text": "登录", "content_desc": "", "resource_id": "com.demo:id/btn_login", "clickable": True},
        {"text": "发送验证码", "content_desc": "", "resource_id": "com.demo:id/tv_send_code", "clickable": True},
    ], {"com.demo:id/tv_privacy"})

    assert action["action"] == "back"


def test_llm_fallback_never_clicks_a_visible_privacy_decline_button():
    action = LLMController.fallback_action([
        {"text": "不同意", "content_desc": "", "resource_id": "com.demo:id/btn_positive", "clickable": True},
        {"text": "同意", "content_desc": "", "resource_id": "com.demo:id/btn_negative", "clickable": True},
    ], set(), False)

    assert action["action"] == "back"


def test_llm_fallback_never_clicks_a_consent_ok_button():
    action = LLMController.fallback_action([
        {"text": "同意", "content_desc": "", "resource_id": "com.example.reader:id/ok_btn", "clickable": True},
        {"text": "拒绝", "content_desc": "", "resource_id": "com.example.reader:id/cancel", "clickable": True},
    ], set(), False)

    assert action["action"] == "back"


def test_llm_fallback_waits_on_hub_consent_and_sdk_dwell_instead_of_grabbing_settings():
    elements = [
        {"text": "隐私政策", "content_desc": "", "resource_id": "privacy", "clickable": True},
        {"text": "设置", "content_desc": "", "resource_id": "settings", "clickable": True},
    ]
    assert LLMController.fallback_action(
        elements, set(), hub_pending=True, page_role="document_hub",
    )["action"] == "wait"
    assert LLMController.fallback_action(
        elements, set(), consent_dialog=True,
    )["action"] == "wait"
    assert LLMController.fallback_action(
        elements, set(), sdk_dwell_pending=True,
    )["action"] == "wait"


def test_login_success_copy_is_in_the_traversal_prompt():
    from agent.ai_explorer.llm_controller import SYSTEM_PROMPT

    assert "登录成功" in SYSTEM_PROMPT
    assert "服务条款" in SYSTEM_PROMPT or "使用条款" in SYSTEM_PROMPT
    assert "unread_document_links" in SYSTEM_PROMPT
    assert "禁止再点" in SYSTEM_PROMPT or "禁止点" in SYSTEM_PROMPT or "绝不点" in SYSTEM_PROMPT
    assert "没有检测到QQ" in SYSTEM_PROMPT or "QQ/微信" in SYSTEM_PROMPT
    assert "设置/我的" in SYSTEM_PROMPT
    assert "认定方法" in SYSTEM_PROMPT
    assert "Appium" in SYSTEM_PROMPT
    assert "already_inside_audited_app" in SYSTEM_PROMPT
    assert "audited_app_name" in SYSTEM_PROMPT
    assert "其它应用" in SYSTEM_PROMPT
    assert "splash_or_gate" in SYSTEM_PROMPT
    assert "logged_out_profile" in SYSTEM_PROMPT
    assert "screen_text" in SYSTEM_PROMPT
    assert "内嵌" in SYSTEM_PROMPT
    assert "启动页" in SYSTEM_PROMPT and ("外链" in SYSTEM_PROMPT or "书名号" in SYSTEM_PROMPT)
    assert "权限申请" in SYSTEM_PROMPT or "好的" in SYSTEM_PROMPT
    assert "consent_dialog" in SYSTEM_PROMPT
    assert "注销" in SYSTEM_PROMPT and "退出登录" in SYSTEM_PROMPT
    assert "不可信" in SYSTEM_PROMPT and "不得覆盖" in SYSTEM_PROMPT
    cfg = load_config(env={"PRIVACY_ENGINE_EXPLORER": "real", "PRIVACY_ENGINE_MONITOR": "real"})
    assert cfg["detection"]["engines"] == {"explorer": "real", "monitor": "real"}


def test_login_classifier_rejects_string_false(monkeypatch):
    import sys
    from types import SimpleNamespace

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"logged_in":"false"}'))],
    )
    completions = SimpleNamespace(create=lambda **_kwargs: response)
    fake_openai = SimpleNamespace(
        OpenAI=lambda **_kwargs: SimpleNamespace(chat=SimpleNamespace(
            completions=completions,
        )),
    )
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("TEST_LLM_KEY", "configured")
    controller = LLMController({"llm": {
        "api_key_env": "TEST_LLM_KEY", "base_url": "http://llm.invalid",
        "timeout_seconds": 1, "model": "test",
    }})

    assert controller.assess_login_state({"elements": [], "screen_text": ""}) is False


def test_llm_timeout_is_not_retried_as_unstructured_request(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise TimeoutError("request timed out")

    fake_openai = SimpleNamespace(
        OpenAI=lambda **_kwargs: SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )),
    )
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("TEST_LLM_KEY", "configured")
    controller = LLMController({"llm": {
        "api_key_env": "TEST_LLM_KEY", "base_url": "http://llm.invalid",
        "timeout_seconds": 1, "model": "test",
    }})

    with pytest.raises(TimeoutError):
        controller.choose_action({"elements": []}, set())
    assert len(calls) == 1
