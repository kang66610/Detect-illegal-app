from types import SimpleNamespace
import time

import pytest

import agent.ai_explorer.explorer_engine as explorer_module
from agent.common.exceptions import ExplorationError
from agent.ai_explorer.explorer_engine import AppiumExplorerEngine, _activity_belongs_to_package, _already_read_document_target, _append_policy_fragment, _associated_start_activity, _authenticated_session_visible, _channel_unavailable_dialog_dismiss_target, _click_matches_privacy_path, _complaint_or_cs_entry_target, _coverage_gaps, _customer_service_sensitive_control, _document_body_kind_from_text, _document_follow_target, _document_key, _document_title_already_read, _document_wait_should_be_kept, _explicit_consent_target, _external_document_body_visible, _frontier_recovery_attempt_allowed, _generic_page_may_need_swipe, _global_target_key, _has_left_audited_package, _hub_privacy_action_target, _infer_document_kind, _inline_document_open_succeeded, _is_allowed_non_audited_surface, _is_app_exit_confirmation, _is_authenticated_logout_target, _is_consent_click, _is_consent_dialog, _is_consent_or_decline_control, _is_customer_service_surface, _is_destructive_confirmation, _is_document_body_hyperlink, _is_foreign_app_launch_click, _is_login_gate, _is_logout_confirmation_target, _is_privacy_dialog_decline, _is_redress_interaction_surface, _is_safe_deep_probe_target, _is_self_app_launch_click, _is_short_decline_label, _is_transaction_target, _logged_out_profile_visible, _login_invitation_target, _looks_like_main_content_surface, _looks_like_main_surface, _looks_like_settings_or_profile, _low_audit_value_surface_kind, _main_content_tab_target, _mark_required_document_read, _needs_perception_ocr, _next_hub_exploration_target, _page_names_privacy_policy, _page_role, _page_semantics, _permission_prompt, _preferred_inline_document_target, _privacy_hub_tab_target, _privacy_path_observations, _privacy_path_verification_surface, _profile_login_entry, _read_document_kinds, _read_document_titles, _record_document_completion, _redress_sensitive_control, _remember_consent_document_titles, _required_document_kind, _resource_id_matches_hint, _sensitive_business_control, _should_anchor_root, _special_permission_page, _special_permission_state, _target_has_decline_semantics, _target_is_document_route, _target_is_hub_reentry, _unchecked_consent_checkbox, _unread_for_page, _unread_required_document_target, _visible_required_document_titles
from agent.detection_engines.base import DetectionContext
from agent.ai_explorer.page_state import PageState, parse_page
from agent.detection_engines.page_semantics import PageRole
from agent.rule_engine.rule_loader import load_rules
from agent.rule_engine.rule_matcher import match_rules


def test_login_register_with_guest_choice_is_not_misclassified_as_consent_dialog():
    """Task 291: a consent footer must not hide the public-entry choices."""
    page = parse_page(
        ".GuideActivity",
        '''<hierarchy>
          <node text="登录 / 注册" resource-id="login" clickable="true" class="android.widget.Button"/>
          <node text="先逛逛" resource-id="guest" clickable="true" class="android.widget.Button"/>
          <node text="我同意《用户协议》和《隐私政策》" clickable="false" class="android.widget.TextView"/>
          <node text="" resource-id="cb_agree" clickable="true" checkable="true" checked="false" class="android.widget.CheckBox"/>
        </hierarchy>''',
    )

    assert explorer_module._entry_choice_bypass_target(page.elements) == "guest"
    assert not _is_consent_dialog(page.elements)
    assert _page_semantics(page.activity, page.elements, PageState()).role is PageRole.SPLASH_OR_GATE


def test_prechecked_consent_rule_ignores_state_seen_after_any_entry_action():
    """A checked UI-tree value after a click is not proof of a default selection."""
    page = parse_page(
        ".GuideActivity",
        '''<hierarchy>
          <node text="我同意《用户协议》和《隐私政策》" clickable="false"/>
          <node text="" resource-id="cb_agree" clickable="true" checkable="true" checked="true" class="android.widget.CheckBox"/>
        </hierarchy>''',
    )

    assert explorer_module._prechecked_consent_checkbox(
        page.elements, "我同意隐私政策", initial_observation=True,
    )["target"] == "cb_agree"
    assert explorer_module._prechecked_consent_checkbox(
        page.elements, "我同意隐私政策", initial_observation=False,
    ) is None
    assert explorer_module._prechecked_consent_checkbox(
        page.elements, "我同意隐私政策", screenshot_available=False,
    ) is None


def test_guest_choice_enters_public_home_before_any_login_or_document_loop(tmp_path):
    """A first-run entry choice must take the public path, not re-open policy links."""
    entry = '''<hierarchy>
      <node text="登录 / 注册" resource-id="login" clickable="true" class="android.widget.Button"/>
      <node text="先逛逛" resource-id="guest" clickable="true" class="android.widget.Button"/>
      <node text="我同意《用户协议》和《隐私政策》" clickable="false"/>
      <node text="" resource-id="cb_agree" clickable="true" checkable="true" checked="false" class="android.widget.CheckBox"/>
    </hierarchy>'''
    home = '<hierarchy><node text="首页" clickable="false"/><node text="我的" resource-id="profile" clickable="true"/></hierarchy>'

    class GuestChoiceClient:
        def __init__(self):
            self.at_home = False
            self.actions = []

        def page(self):
            return (".HomeActivity", home) if self.at_home else (".GuideActivity", entry)

        def activate(self, _package):
            pass

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and decision.get("target") == "guest":
                self.at_home = True

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def close(self):
            pass

    class StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "home reached"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "home reached"}

    client = GuestChoiceClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "screen_ocr_enabled": False, "sdk_observation_dwell_seconds": 0,
            "page_settle_retries": 0, "mode_limits": {"fast": {"max_pages": 4}},
        }},
        data_dir=tmp_path,
    )

    engine.run(ctx)

    assert client.actions[0] == ("click", "guest")
    assert client.at_home is True


def test_explorer_honors_termination_request_before_reading_another_page(tmp_path):
    class TerminatingClient:
        def __init__(self):
            self.page_reads = 0

        def activate(self, _package):
            pass

        def page(self):
            self.page_reads += 1
            return ".HomeActivity", '<hierarchy><node text="首页"/></hierarchy>'

        def close(self):
            pass

    client = TerminatingClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "screen_ocr_enabled": False, "sdk_observation_dwell_seconds": 0,
            "page_settle_retries": 0, "mode_limits": {"fast": {"max_pages": 4}},
        }},
        data_dir=tmp_path,
        runtime={"is_terminated": lambda: True},
    )

    result = engine.run(ctx)

    assert result.stats["pages_covered"] == 0
    assert ctx.runtime["traversal_termination"]["kind"] == "terminated"


_ROOT = '''<hierarchy><node text="首页" resource-id="home" clickable="false" class="android.widget.TextView"/><node text="隐私政策" resource-id="privacy" clickable="true" class="android.widget.TextView"/></hierarchy>'''
_POLICY_TOP = '''<hierarchy><node text="隐私政策 第一部分" resource-id="policy-body" clickable="false" class="android.widget.TextView"/></hierarchy>'''
_POLICY_BOTTOM = '''<hierarchy><node text="隐私政策 第二部分 服务条款" resource-id="policy-body" clickable="false" class="android.widget.TextView"/></hierarchy>'''
_APP_FUNCTION = '''<hierarchy><node text="上传头像" resource-id="upload-avatar" clickable="true" class="android.widget.Button"/></hierarchy>'''
_CAMERA_PROMPT = '''<hierarchy><node text="允许 Demo 拍摄照片和录制视频吗？" resource-id="com.android.permissioncontroller:id/permission_message" clickable="false" class="android.widget.TextView"/><node text="不允许" resource-id="com.android.permissioncontroller:id/permission_deny_button" clickable="true" class="android.widget.Button"/></hierarchy>'''
_DENIED_FUNCTION = '''<hierarchy><node text="暂无相机权限，无法上传头像" resource-id="permission-result" clickable="false" class="android.widget.TextView"/></hierarchy>'''


def test_consent_dialog_not_flipped_by_personal_info_in_policy_copy():
    """Long splash copy mentioning「个人信息」must not be treated as a settings hub."""
    page = parse_page(
        ".SplashActivity",
        '''<hierarchy>
          <node text="为保障服务，我们将收集个人信息并用于改进体验。请阅读《隐私政策》和《用户协议》"
                clickable="false" class="android.widget.TextView"/>
          <node text="《隐私政策》" clickable="true"/>
          <node text="同意" resource-id="btn_agree" clickable="true" class="android.widget.Button"/>
          <node text="不同意" clickable="true" class="android.widget.Button"/>
        </hierarchy>''',
    )
    assert _is_consent_dialog(page.elements)
    assert _unread_for_page(
        DetectionContext(task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"), cfg={}, data_dir=None),
        page.elements, set(),
    ) == "《隐私政策》"


def test_internal_webview_completion_keeps_entry_identity_when_body_is_another_document():
    """Regression for task 290: a privacy link opened a user-agreement WebView."""
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )

    resolved = _record_document_completion(
        ctx,
        document_key=".WebActivity:document:用户协议",
        entry_target="《隐私政策》",
        page_text="用户协议 本协议适用于本平台提供的服务",
    )

    assert resolved.mismatch is True
    assert resolved.expected_kind == "privacy_policy"
    assert resolved.observed_kind == "user_agreement"
    assert ctx.runtime["document_route_observed_kinds"]["隐私政策"] == "user_agreement"
    assert ctx.runtime["completed_document_routes"] == set()
    assert "user_agreement" in ctx.runtime["read_document_kinds"]
    assert "privacy_policy" not in ctx.runtime["read_document_kinds"]


def test_read_user_agreement_is_skipped_even_while_privacy_policy_remains_unread():
    """An unread sibling must not reopen a separately completed agreement."""
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
        runtime={
            "read_document_titles": {"用户协议"},
            "read_document_kinds": {"user_agreement"},
            "consent_document_titles": {"用户协议", "隐私政策"},
        },
    )

    assert _already_read_document_target(ctx, "《用户协议》", []) is True


def test_document_wait_requires_an_active_unread_document_session():
    """A missing privacy policy cannot justify waiting forever in a read agreement."""
    key = ".WebActivity:document:用户协议"
    state = PageState()
    state.start_document(key)
    state.finish_document(key)

    assert _document_wait_should_be_kept(PageRole.DOCUMENT_BODY, key, state) is False
    assert _document_wait_should_be_kept(PageRole.DOCUMENT_BODY, "", state) is False


def test_main_activity_detail_surface_is_not_automatically_a_root():
    page = parse_page(
        ".MainActivity",
        '''<hierarchy>
          <node text="账号与安全" clickable="false"/>
          <node text="注销账号" resource-id="delete" clickable="true"/>
          <node text="首页" resource-id="tab_home" clickable="true" bounds="[0,2200][360,2400]"/>
          <node text="消息" resource-id="tab_message" clickable="true" bounds="[360,2200][720,2400]"/>
          <node text="我的" resource-id="tab_profile" clickable="true" bounds="[720,2200][1080,2400]"/>
        </hierarchy>''',
    )
    state = PageState()
    root = parse_page(".MainActivity", '<hierarchy><node text="首页" clickable="true"/></hierarchy>')
    state.is_new(root)
    state.anchor_root(root)
    state.schedule_target(root, "account-security")
    state.commit_target(root, "account-security")
    state.is_new(page)

    assert _looks_like_main_surface(page.activity, page.elements)
    assert not _should_anchor_root(state, page, "account-security")


def test_duplicate_list_row_ids_keep_privacy_routes_instance_specific():
    page = parse_page(
        ".AccountActivity",
        '''<hierarchy>
          <node text="关于我们" resource-id="row" clickable="true" bounds="[0,300][1080,450]"/>
          <node text="注销账号" resource-id="row" clickable="true" bounds="[0,500][1080,650]"/>
        </hierarchy>''',
    )
    observed = _privacy_path_observations(page.elements, "")
    assert observed["delete_targets"] == ["bounds:[0,500][1080,650]"]


@pytest.mark.parametrize("title, body", [
    ("意见反馈", "请描述遇到的问题 添加图片 提交反馈"),
    ("投诉举报", "填写投诉内容 上传凭证 联系方式"),
    ("帮助与支持", "在线工单 描述您的问题 添加附件"),
])
def test_redress_surface_and_sensitive_controls_are_generic(title, body):
    page = parse_page(
        ".GenericFormActivity",
        f'''<hierarchy>
          <node text="{title}" clickable="false"/>
          <node text="{body}" clickable="false"/>
          <node text="上传图片" resource-id="attachment" clickable="true" bounds="[800,1800][1040,2040]"/>
        </hierarchy>''',
    )
    text = " ".join(item["text"] for item in page.elements)
    assert _is_redress_interaction_surface(page.activity, text)
    assert _redress_sensitive_control(page.activity, page.elements, text) == "attachment"


def test_generic_deep_search_recognises_scrollable_business_lists():
    page = parse_page(
        ".FeatureActivity",
        '''<hierarchy>
          <node text="服务功能" class="android.widget.ScrollView" scrollable="true"/>
          <node text="功能一" clickable="true"/><node text="功能二" clickable="true"/>
        </hierarchy>''',
    )
    assert _generic_page_may_need_swipe(page, page_role="app_page")
    assert not _generic_page_may_need_swipe(page, page_role="consent_dialog")


def test_help_tutorial_webview_is_not_read_as_a_policy_document_or_generic_list():
    page = parse_page(
        ".module.webview.WebActivity",
        '''<hierarchy>
          <node text="书盘帮助" class="android.widget.TextView" clickable="false"/>
          <node text="如何上传资源 使用教程 常见问题" class="android.webkit.WebView" scrollable="true"/>
        </hierarchy>''',
    )
    state = PageState()

    assert _low_audit_value_surface_kind(page.activity, page.elements) == "help_tutorial"
    assert _document_key(page.activity, page.elements, state) is None
    role = _page_role(page.activity, page.elements, state)
    assert role == "low_value_help_tutorial"
    assert not _generic_page_may_need_swipe(page, page_role=role)


@pytest.mark.parametrize("title, empty_copy", [
    ("传文件", "没有发现下载书本"),
    ("最近阅读", "暂无阅读记录"),
    ("搜索", "没有搜索结果"),
])
def test_empty_state_surface_is_pruned_instead_of_read_as_a_document(title, empty_copy):
    page = parse_page(
        ".module.webview.WebActivity",
        f'''<hierarchy>
          <node text="{title}" clickable="false"/>
          <node text="{empty_copy}" class="android.webkit.WebView" scrollable="true"/>
          <node text="返回" resource-id="back" clickable="true"/>
        </hierarchy>''',
    )
    state = PageState()

    assert _low_audit_value_surface_kind(page.activity, page.elements) == "empty_state"
    assert _document_key(page.activity, page.elements, state) is None
    role = _page_role(page.activity, page.elements, state)
    assert role == "low_value_empty_state"
    assert not _generic_page_may_need_swipe(page, page_role=role)


def test_commercial_surface_is_pruned_but_explicit_feedback_form_is_not():
    paywall = parse_page(
        ".module.vip.VIPBuyActivity",
        '''<hierarchy>
          <node text="购买会员 享受更多资源" clickable="false"/>
          <node text="立即购买" resource-id="buy" clickable="true"/>
          <node text="联系客服" resource-id="customer_service" clickable="true"/>
        </hierarchy>''',
    )
    feedback = parse_page(
        ".FeedbackActivity",
        '''<hierarchy>
          <node text="意见反馈" clickable="false"/>
          <node text="请描述遇到的问题" clickable="false"/>
          <node text="上传凭证" resource-id="attachment" clickable="true"/>
        </hierarchy>''',
    )

    assert _low_audit_value_surface_kind(paywall.activity, paywall.elements) == "commercial"
    assert _low_audit_value_surface_kind(feedback.activity, feedback.elements) is None


def test_final_action_safety_cannot_be_overridden_on_low_value_or_foreign_routes():
    from agent.ai_explorer.explorer_engine import _enforce_final_action_safety

    page = parse_page(
        ".module.vip.VIPBuyActivity",
        '''<hierarchy>
          <node text="购买会员" clickable="false"/>
          <node text="立即购买" resource-id="buy" clickable="true"/>
          <node text="Appium Settings" resource-id="com.android.launcher3:id/icon" clickable="true"/>
        </hierarchy>''',
    )

    low_value, reason = _enforce_final_action_safety(
        {"action": "click", "target": "buy", "reason": "继续深搜"},
        activity=page.activity,
        elements=page.elements,
        low_value_surface_kind="commercial",
        audited_package="com.example.demo",
        audited_app_name="Demo",
        foreground_package="com.example.demo",
        is_root=False,
    )
    foreign, foreign_reason = _enforce_final_action_safety(
        {"action": "click", "target": "Appium Settings", "reason": "继续深搜"},
        activity=".HomeActivity",
        elements=page.elements,
        low_value_surface_kind=None,
        audited_package="com.example.demo",
        audited_app_name="Demo",
        foreground_package="com.example.demo",
        is_root=True,
    )

    assert low_value["action"] == "back"
    assert reason == "low_audit_value_surface"
    assert foreign["action"] == "stop"
    assert foreign_reason == "foreign_app_launch"


def test_stale_completed_external_body_is_not_credited_to_a_different_document_kind():
    from agent.ai_explorer.explorer_engine import _external_body_identity_status

    assert _external_body_identity_status(
        origin_target="第三方 SDK 目录",
        expected_kind="disclosure_list",
        observed_kind="user_agreement",
        viewport_fingerprint="same-user-agreement-body",
        completed_fingerprints={"same-user-agreement-body"},
        previous_origin_target="用户协议",
        previous_viewport_fingerprint="same-user-agreement-body",
    ) == "stale_mismatch"


def test_external_document_content_fingerprint_does_not_depend_on_stale_kind_label():
    body = "案例G隐私政策 本政策说明我们如何收集、使用和共享您的个人信息。"

    agreement_labeled = explorer_module._document_viewport_fingerprint(
        body, "user_agreement",
    )
    privacy_labeled = explorer_module._document_viewport_fingerprint(
        body, "privacy_policy",
    )

    assert agreement_labeled == privacy_labeled


def test_external_document_progress_key_separates_anonymous_bodies_by_observed_kind():
    runtime = {}

    agreement = explorer_module._external_document_progress_key(
        runtime, "custom_tab", "", "user_agreement",
    )
    agreement_footer = explorer_module._external_document_progress_key(
        runtime, "custom_tab", "", None,
    )
    privacy = explorer_module._external_document_progress_key(
        runtime, "custom_tab", "", "privacy_policy",
    )

    assert agreement_footer == agreement
    assert privacy != agreement


def test_mismatched_document_route_remains_retryable_after_its_actual_body_is_read(tmp_path):
    """A privacy entry that rendered the agreement must stay available for a retry."""
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=tmp_path,
    )
    elements = parse_page(
        ".SettingsActivity",
        '<hierarchy><node text="隐私政策" resource-id="privacy" clickable="true"/></hierarchy>',
    ).elements

    assert _mark_required_document_read(
        ctx, "隐私政策", page_text="《用户协议》\n欢迎使用本应用",
    ) == "user_agreement"

    assert _already_read_document_target(ctx, "隐私政策", elements) is False


def test_external_document_progress_key_normalizes_semantic_aliases():
    runtime = {}
    chinese = explorer_module._external_document_progress_key(
        runtime, "custom_tab", "用户协议", None,
    )
    english = explorer_module._external_document_progress_key(
        runtime, "custom_tab", "User Agreement", None,
    )
    resource_id = explorer_module._external_document_progress_key(
        runtime, "custom_tab", "row_user_agree", None,
    )

    assert chinese == english == resource_id


def test_navigation_replay_checkpoint_restores_recovery_budget(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=tmp_path,
        runtime={
            "runtime_session_recovery_attempted": True,
            "runtime_session_recovery_attempts": 2,
            "runtime_session_recoveries": 1,
            "runtime_session_recovery_status": "waiting",
            "runtime_checkpoint_replayed": False,
            "navigation_replay_required": True,
        },
    )
    original = PageState()
    explorer_module._save_navigation_replay_checkpoint(ctx, original)

    resumed = DetectionContext(
        task=ctx.task, apk=ctx.apk, cfg={}, data_dir=tmp_path,
        runtime={"resume_requested": True},
    )
    assert explorer_module._restore_navigation_replay_checkpoint(resumed, PageState()) is True
    assert resumed.runtime["runtime_session_recovery_attempts"] == 2
    assert resumed.runtime["runtime_session_recoveries"] == 1
    assert resumed.runtime["runtime_session_recovery_status"] == "waiting"


def test_document_route_is_never_promoted_to_business_retry_by_reason_copy():
    page = parse_page(
        ".MainActivity",
        '<hierarchy><node text="用户协议" resource-id="row_user_terms" '
        'clickable="true" bounds="[0,1390][1080,1513]"/></hierarchy>',
    )

    assert not explorer_module._is_business_trigger_action(
        "用户协议",
        page.elements,
        "设置/个人信息页条款可能已读，继续核验头像/上传或其它合规入口",
    )


def test_copy_confirmation_dialog_uses_exact_button_not_full_screen_container():
    page = parse_page(
        ".MainActivity",
        '''<hierarchy>
          <node text="邮箱地址已复制" clickable="false" bounds="[80,900][1000,1040]"/>
          <node text="请使用您自己的邮箱发送邮件联系我们。" clickable="false" bounds="[80,1040][1000,1160]"/>
          <node text="我知道了" clickable="true" bounds="[80,1160][1000,1320]"/>
          <node text="" clickable="true" bounds="[0,0][1080,2400]"/>
        </hierarchy>''',
    )

    assert explorer_module._transient_notice_dismiss_target(
        page.elements, "邮箱地址已复制 请使用您自己的邮箱发送邮件联系我们。 我知道了",
    ) == "我知道了"


def test_generic_success_dialog_uses_labelled_acknowledgement():
    page = parse_page(
        ".MainActivity",
        '''<hierarchy>
          <node text="一键备份成功" clickable="false" bounds="[80,900][1000,1040]"/>
          <node text="确定" resource-id="android:id/button1" clickable="true" bounds="[80,1160][1000,1320]"/>
          <node text="" clickable="true" bounds="[0,0][1080,2400]"/>
        </hierarchy>''',
    )
    assert explorer_module._transient_notice_dismiss_target(
        page.elements, "一键备份成功 确定",
    ) == "确定"


def test_spaced_overlay_settings_title_is_recognised_before_ocr_rows_are_clicked():
    page = parse_page(
        "com.android.settings.spa.SpaActivity",
        '''<hierarchy>
          <node text="显 示 在 其 他 应 用 的 上 层" clickable="false"/>
          <node text="佛 山 易 行  不 允 许" clickable="true" bounds="[0,500][1080,680]"/>
        </hierarchy>''',
    )

    assert _special_permission_page(page.activity, page.elements) == "overlay"
    assert _special_permission_state(page.elements) == "denied"


def test_generic_deep_probe_rejects_unlabelled_fullscreen_and_toolbar_bounds():
    page = parse_page(
        ".MainActivity",
        '''<hierarchy>
          <node text="设置" clickable="false" bounds="[0,0][1080,196]"/>
          <node text="" clickable="true" bounds="[0,0][1080,2400]"/>
          <node text="" clickable="true" bounds="[0,0][1080,196]"/>
          <node text="" clickable="true" bounds="[0,85][116,184]"/>
        </hierarchy>''',
    )

    assert not _is_safe_deep_probe_target("bounds:[0,0][1080,2400]", page.elements)
    assert not _is_safe_deep_probe_target("bounds:[0,0][1080,196]", page.elements)
    assert not _is_safe_deep_probe_target("bounds:[0,85][116,184]", page.elements)


def test_loading_shell_cold_restarts_once_then_continues(tmp_path):
    loading = '<hierarchy><node class="android.widget.FrameLayout" clickable="false"/></hierarchy>'
    home = '<hierarchy><node text="首页" resource-id="home" clickable="true"/></hierarchy>'

    class _LoadingClient:
        def __init__(self):
            self.restarts = 0
            self.loaded = False

        def activate(self, _package):
            pass

        def restart_app(self, _package):
            self.restarts += 1
            self.loaded = True

        def page(self):
            return ".MainActivity", home if self.loaded else loading

        def screenshot(self, _path):
            return False

        def perform(self, _decision):
            pass

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _LoadingClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "page_settle_retries": 1,
            "page_settle_wait_seconds": 0,
            "loading_shell_cold_restart_limit": 1,
            "sdk_observation_dwell_seconds": 0,
            "mode_limits": {"fast": {"max_pages": 3}},
        }},
        data_dir=tmp_path,
        runtime={"consent_accepted": True, "sdk_observation_dwell_done": True},
    )

    result = engine.run(ctx)
    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]

    assert client.restarts == 1
    assert "loading_shell_cold_restart_completed" in event_types



def test_frontier_recovery_route_is_bounded_across_redraws():
    runtime = {}

    assert _frontier_recovery_attempt_allowed(runtime, "home|head_image")
    assert not _frontier_recovery_attempt_allowed(runtime, "home|head_image")
    assert _frontier_recovery_attempt_allowed(runtime, "home|settings")


def test_generic_deep_search_scrolls_then_discovers_feedback_entry(tmp_path):
    top = '''<hierarchy>
      <node text="服务功能" class="android.widget.ScrollView" scrollable="true"/>
      <node text="首页内容" clickable="false"/>
    </hierarchy>'''
    bottom = '''<hierarchy>
      <node text="服务功能" class="android.widget.ScrollView" scrollable="true"/>
      <node text="意见反馈" resource-id="feedback" clickable="true" bounds="[0,1500][1080,1660]"/>
    </hierarchy>'''
    form = '''<hierarchy>
      <node text="意见反馈" clickable="false"/>
      <node text="请描述遇到的问题，可添加图片或附件" clickable="false"/>
      <node text="上传图片" resource-id="attachment" clickable="true" bounds="[800,1800][1040,2040]"/>
    </hierarchy>'''

    class _Client:
        def __init__(self):
            self.phase = "top"
            self.actions = []

        def activate(self, _package):
            pass

        def page(self):
            return ".HomeActivity", {"top": top, "bottom": bottom, "form": form}[self.phase]

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def scroll_down(self):
            if self.phase == "top":
                self.phase = "bottom"
                return True
            return False

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision.get("action") == "click" and decision.get("target") == "feedback":
                self.phase = "form"

        def close(self):
            pass

    class _BackLLM:
        def choose_action(self, *_args):
            return {"action": "back", "target": "", "reason": "当前页无入口"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "back", "target": "", "reason": "当前页无入口"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_BackLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo", app_name="Demo", permissions=[]),
        cfg={
            "appium": {"page_wait_seconds": 0},
            "detection": {
                "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
                "max_generic_page_scrolls": 2,
                "mode_limits": {"deep": {"max_pages": 5}},
            },
        },
        data_dir=tmp_path,
    )

    result = engine.run(ctx)
    event_types = {(item.get("meta") or {}).get("event_type") for item in result.evidence_files}

    assert "generic_page_scrolled" in event_types
    assert ("click", "feedback") in client.actions
    assert "redress_entry_explored" in event_types


def test_transient_feedback_entry_failure_is_retried_before_it_is_consumed(tmp_path):
    root = '''<hierarchy>
      <node text="首页" clickable="false"/>
      <node text="意见反馈" resource-id="feedback" clickable="true" bounds="[0,900][1080,1060]"/>
    </hierarchy>'''
    form = '''<hierarchy>
      <node text="意见反馈" clickable="false"/>
      <node text="请描述遇到的问题并添加附件" clickable="false"/>
    </hierarchy>'''

    class _Client:
        def __init__(self):
            self.failures = 0
            self.phase = "root"

        def activate(self, _package):
            pass

        def page(self):
            return ".HomeActivity", root if self.phase == "root" else form

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            if decision.get("action") == "click" and decision.get("target") == "feedback":
                self.failures += 1
                if self.failures == 1:
                    raise ExplorationError("stale element")
                self.phase = "form"

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "结束"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "结束"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo", app_name="Demo", permissions=[]),
        cfg={
            "appium": {"page_wait_seconds": 0},
            "detection": {
                "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
                "mode_limits": {"deep": {"max_pages": 4}},
            },
        }, data_dir=tmp_path,
    )

    engine.run(ctx)
    assert client.failures == 2
    assert any(
        "feedback" in key and count == 1
        for key, count in (ctx.runtime.get("global_target_attempts") or {}).items()
    )


def test_successful_driver_click_without_surface_change_is_recorded_as_no_effect(tmp_path):
    root = '''<hierarchy>
      <node text="首页" clickable="false"/>
      <node text="推荐" resource-id="recommend" clickable="true"/>
    </hierarchy>'''

    class _Client:
        def __init__(self):
            self.clicks = 0
            self.last_package = "com.demo"

        def activate(self, _package):
            pass

        def page(self):
            return ".HomeActivity", root

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            if decision.get("action") == "click":
                self.clicks += 1

        def close(self):
            pass

    class _LLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "recommend", "reason": "探索普通入口"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "结束"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_LLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo", app_name="Demo", permissions=[]),
        cfg={
            "appium": {"page_wait_seconds": 0},
            "detection": {
                "sdk_observation_dwell_seconds": 0,
                "page_settle_retries": 0,
                "max_generic_page_scrolls": 1,
                "mode_limits": {"deep": {"max_pages": 4}},
            },
        },
        data_dir=tmp_path,
    )

    result = engine.run(ctx)
    events = [
        (item.get("meta") or {}).get("event_type")
        for item in result.evidence_files
        if item.get("type") == "timeline"
    ]

    assert "action_no_effect" in events
    assert "target_no_effect_exhausted" in events
    assert client.clicks == 1


def test_second_probe_phase_reuses_installed_app_data_instead_of_reinstalling(tmp_path):
    class _Device:
        def __init__(self):
            self.revocations = 0

        def revoke_runtime_permissions(self, _package, _permissions):
            self.revocations += 1
            return []

    class _Client:
        def __init__(self):
            self.installs = 0
            self._device = _Device()

        def connect(self):
            pass

        def install(self, _apk_path, _package):
            self.installs += 1
            return True

    apk_path = tmp_path / "demo.apk"
    apk_path.write_bytes(b"apk")
    runtime = {}
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"detection": {"reset_runtime_permissions": True}},
        data_dir=tmp_path,
        runtime=runtime,
    )
    ctx.apk_path = apk_path

    first = _Client()
    second = _Client()
    AppiumExplorerEngine(client=first).prepare(ctx)
    AppiumExplorerEngine(client=second).prepare(ctx)

    assert first.installs == 1
    assert second.installs == 0
    assert first._device.revocations == 1
    assert second._device.revocations == 1
    assert runtime["apk_installed_for_task"] is True


def test_logout_confirmation_accepts_confirm_think_again_pair():
    from agent.ai_explorer.explorer_engine import _is_logout_confirmation_dialog

    assert _is_logout_confirmation_dialog("确定要退出登录吗？ 确认 再想想")
    assert _is_logout_confirmation_dialog("退出登录 确定 取消")
    assert not _is_logout_confirmation_dialog("设置 退出登录 关于我们")


def test_profile_shell_drills_settings_before_logout():
    from agent.ai_explorer.explorer_engine import _hub_drill_target, _hub_progress_target

    page = parse_page(
        ".MainTabActivity",
        '''<hierarchy>
          <node text="我的" clickable="false"/>
          <node text="消息中心" clickable="true"/>
          <node text="设置" resource-id="item_settings" clickable="true" bounds="[0,1400][1080,1550]"/>
          <node text="退出登录" resource-id="btn_logout" clickable="true" bounds="[0,1600][1080,1750]"/>
          <node text="我的" resource-id="rb_4" clickable="true" bounds="[810,2200][1080,2400]"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={"detection": {"explore_logout_confirmation": True}}, data_dir=None,
    )
    assert _hub_drill_target(page.elements, set()) == "item_settings"
    assert _hub_progress_target(ctx, page.elements, set()) == "item_settings"
    assert _hub_progress_target(ctx, page.elements, {"item_settings"}) == "btn_logout"
    elements = parse_page(
        ".ProfileActivity",
        '<hierarchy><node text="退出登录" resource-id="account_logout" clickable="true" class="android.widget.TextView"/></hierarchy>',
    ).elements

    assert _is_authenticated_logout_target("退出登录", elements)
    assert not _is_authenticated_logout_target("返回", elements)


def test_logout_entry_resolves_semantic_child_when_model_chooses_bounds():
    elements = [
        {
            "target": "bounds:[0,700][1080,820]", "bounds": "[0,700][1080,820]",
            "text": "", "content_desc": "", "resource_id": "row_logout", "clickable": True,
        },
        {
            "target": "退出登录", "bounds": "[80,730][300,790]",
            "text": "退出登录", "content_desc": "", "resource_id": "", "clickable": False,
        },
    ]
    assert _is_authenticated_logout_target("bounds:[0,700][1080,820]", elements)


def test_logout_confirmation_affirmative_button_is_also_blocked():
    elements = parse_page(
        ".ProfileActivity",
        '<hierarchy><node text="退出登录" clickable="false"/><node text="确定" resource-id="android:id/button1" clickable="true"/></hierarchy>',
    ).elements

    assert _is_logout_confirmation_target("确定", elements)
    assert not _is_logout_confirmation_target("取消", elements)


def test_account_deletion_confirmation_is_destructive_but_not_logout():
    elements = [{
        "target": "我已知晓风险，确定注销", "text": "我已知晓风险，确定注销",
        "content_desc": "", "resource_id": "", "clickable": True,
    }]
    assert _is_destructive_confirmation("我已知晓风险，确定注销", elements)
    assert not _is_authenticated_logout_target("账号注销", elements)


def test_delete_row_with_logout_resource_id_is_not_session_logout():
    elements = [{
        "target": "cl_setting_logout", "text": "注销账号", "content_desc": "",
        "resource_id": "cl_setting_logout", "clickable": True,
    }]
    assert not _is_authenticated_logout_target("cl_setting_logout", elements)
    assert _privacy_path_observations(elements, "")["delete_targets"] == ["cl_setting_logout"]


def test_profile_shell_with_settings_row_is_a_document_hub():
    page = parse_page(
        ".MainTabActivity",
        '''<hierarchy>
          <node text="我的" clickable="false"/>
          <node text="消息中心" clickable="true"/>
          <node text="我的报料" clickable="true"/>
          <node text="设置" resource-id="item_settings" clickable="true" bounds="[0,1400][1080,1550]"/>
          <node text="首页" clickable="true" bounds="[0,2200][270,2400]"/>
          <node text="我的" resource-id="rb_4" clickable="true" bounds="[810,2200][1080,2400]"/>
        </hierarchy>''',
    )
    assert _looks_like_settings_or_profile(page.activity, page.elements)
    assert _next_hub_exploration_target(page.elements, set()) == "item_settings"
    # Bottom-nav 我的 must not be preferred over the list-row 设置.
    assert _next_hub_exploration_target(page.elements, {"item_settings"}) != "rb_4"


def test_settings_page_prioritizes_delete_then_about_then_logout():
    from agent.ai_explorer.explorer_engine import _logout_entry_exploration_target, _hub_progress_target

    page = parse_page(
        ".SettingActivity",
        '''<hierarchy>
          <node text="推送广告" clickable="true"/>
          <node text="清除缓存" clickable="true"/>
          <node text="关于我们" clickable="true"/>
          <node text="注销账号" resource-id="btn_delete" clickable="true"/>
          <node text="退出登录" resource-id="btn_logout" clickable="true"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={"detection": {"explore_logout_confirmation": True}}, data_dir=None,
    )
    assert _hub_privacy_action_target(ctx, page.elements, set()) == "btn_delete"
    # After delete: drill 关于我们 before exploring logout.
    assert _hub_progress_target(ctx, page.elements, {"btn_delete"}) == "关于我们"
    assert _logout_entry_exploration_target(ctx, page.elements, {"btn_delete", "关于我们"}) == "btn_logout"
    assert _hub_progress_target(ctx, page.elements, {"btn_delete", "关于我们"}) == "btn_logout"


def test_privacy_path_route_is_not_reentered_after_page_redraw(tmp_path):
    page = parse_page(
        ".SettingsActivity",
        '<hierarchy><node text="注销账号" resource-id="btn_delete" clickable="true"/></hierarchy>',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=tmp_path,
    )
    first = _hub_privacy_action_target(ctx, page.elements, set())
    assert first == "btn_delete"
    ctx.runtime.setdefault("privacy_path_route_keys", set()).add(
        _global_target_key("", first, page.elements),
    )

    redrawn = parse_page(
        ".SettingsActivity",
        '<hierarchy><node text="注销账号" resource-id="btn_delete" clickable="true"/>'
        '<node text="版本 2" clickable="false"/></hierarchy>',
    )
    assert _hub_privacy_action_target(ctx, redrawn.elements, set()) is None


def test_delete_label_on_child_resolves_to_clickable_row():
    elements = [
        {
            "target": "row_delete", "bounds": "[0,900][1080,1050]",
            "text": "", "content_desc": "", "resource_id": "row_delete", "clickable": True,
        },
        {
            "target": "注销账号", "bounds": "[80,930][400,1020]",
            "text": "注销账号", "content_desc": "", "resource_id": "", "clickable": False,
        },
    ]
    assert _privacy_path_observations(elements, "")["delete_targets"] == ["row_delete"]
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )
    assert _hub_privacy_action_target(ctx, elements, set()) == "row_delete"


def test_root_frontier_cannot_rewrite_logout_back_into_a_click(tmp_path):
    page = '<hierarchy><node text="退出登录" resource-id="account_logout" clickable="true" class="android.widget.TextView"/></hierarchy>'

    class _LogoutRootClient:
        def __init__(self):
            self.actions = []

        def page(self):
            return ".MainActivity", page

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))

        def close(self):
            pass

    class _BackLLM:
        def choose_action(self, *_args):
            return {"action": "back", "target": "", "reason": "返回继续检查"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "完成"}

    client = _LogoutRootClient()
    engine = AppiumExplorerEngine(client=client, llm=_BackLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"mode_limits": {"fast": {"max_pages": 3}}}},
        data_dir=tmp_path, runtime={"manual_login_verified": True},
    )

    result = engine.run(ctx)

    assert all(target != "退出登录" for action, target in client.actions if action == "click")
    items = {row["item"]: row["state"] for row in (result.stats.get("scenario_coverage") or {}).get("items") or []}
    assert items.get("3.8") != "not_applicable"
    assert not any(
        item.get("meta", {}).get("event_type") == "root_back_overridden"
        and "退出登录" in str(item.get("meta", {}).get("target") or "")
        for item in result.evidence_files
    )


def test_explorer_waits_for_clickable_controls_instead_of_stopping_on_a_loading_frame(tmp_path):
    loading = '<hierarchy><node class="android.widget.FrameLayout" clickable="false" resource-id="android:id/content" bounds="[0,0][1080,2400]"/></hierarchy>'
    home = '<hierarchy><node text="设置" resource-id="settings" clickable="true" class="android.widget.TextView"/></hierarchy>'

    class _LoadingThenHomeClient:
        def __init__(self):
            self.reads = 0
            self.actions = []

        def page(self):
            self.reads += 1
            return ".MainActivity", loading if self.reads == 1 else home

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append(decision["action"])

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "只有 FrameLayout"}

        def fallback_action(self, elements, visited, *_args):
            from agent.ai_explorer.llm_controller import LLMController
            return LLMController.fallback_action(elements, visited)

    client = _LoadingThenHomeClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {"page_settle_retries": 3, "mode_limits": {"fast": {"max_pages": 4}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)
    event_types = {item.get("meta", {}).get("event_type") for item in result.evidence_files}

    assert client.reads >= 2
    assert "page_settle_retry" in event_types
    assert "page_settled" in event_types
    assert "click" in client.actions


def test_consent_dialog_is_not_treated_as_a_scrollable_policy_document():
    page = parse_page(
        ".SplashActivity",
        '<hierarchy>'
        '<node text="请仔细阅读《隐私政策》和《用户服务协议》" clickable="false" class="android.widget.TextView"/>'
        '<node text="《隐私政策》" clickable="true" class="android.widget.TextView"/>'
        '<node text="《用户服务协议》" clickable="true" class="android.widget.TextView"/>'
        '<node text="同意并继续" resource-id="com.example.reader:id/ok_btn" clickable="true" class="android.widget.Button"/>'
        '<node text="拒绝" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>',
    )
    assert _is_consent_dialog(page.elements)
    assert _document_key(page.activity, page.elements, PageState()) is None
    assert _unread_required_document_target(page.elements, set(), set()) == "《隐私政策》"
    assert _unread_required_document_target(page.elements, {"《隐私政策》"}, set()) == "《用户服务协议》"
    assert _unread_required_document_target(
        page.elements, set(), set(), blocked_targets={"《隐私政策》"},
    ) == "《用户服务协议》"
    assert _unread_required_document_target(
        page.elements, {"《隐私政策》", "《用户服务协议》"}, {"privacy_policy", "user_agreement"},
    ) is None
    assert _required_document_kind("《用户服务协议》") == "user_agreement"


def test_nonclickable_webview_consent_controls_are_adjudicated_before_background_navigation():
    page = parse_page(
        ".MainActivity",
        '''<hierarchy>
          <node text="用户协议和隐私政策" clickable="false" bounds="[60,220][360,300]" class="android.webkit.WebView"/>
          <node text="隐私政策" clickable="false" bounds="[80,310][220,350]" class="android.widget.TextView"/>
          <node text="不同意" clickable="false" bounds="[70,640][180,710]" class="android.widget.TextView"/>
          <node text="同意" clickable="false" bounds="[230,640][340,710]" class="android.widget.TextView"/>
          <node text="我的" clickable="true" bounds="[330,900][430,980]" class="android.widget.TextView"/>
        </hierarchy>''',
    )

    semantics = _page_semantics(page.activity, page.elements, PageState())

    assert semantics.role is PageRole.CONSENT_DIALOG
    assert semantics.requires_login_wait is False
    assert "我的" not in semantics.targets_by_label
    assert semantics.targets_by_label["同意"].target.startswith("bounds:")


def test_terms_of_use_and_user_agreement_are_independent_documents():
    page = parse_page(
        ".SplashActivity",
        '<hierarchy>'
        '<node text="请阅读并同意《使用条款》和《用户协议》" clickable="false"/>'
        '<node text="《使用条款》" clickable="true"/>'
        '<node text="《用户协议》" clickable="true"/>'
        '<node text="同意" resource-id="ok_btn" clickable="true"/>'
        '</hierarchy>',
    )
    assert _required_document_kind("《使用条款》") == "service_terms"
    assert _required_document_kind("《用户协议》") == "user_agreement"
    assert _unread_required_document_target(page.elements, {"《使用条款》"}, {"user_agreement", "service_terms"}) == "《用户协议》"
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )
    # Keep page_text free of the sibling title so marking one clause does not
    # accidentally stamp the other via body-kind inference.
    _mark_required_document_read(ctx, "《使用条款》", page_text="使用条款约定服务使用规则与限制。")
    still = _unread_required_document_target(
        page.elements, {"《使用条款》"}, _read_document_kinds(ctx),
        read_titles=_read_document_titles(ctx),
    )
    assert still == "《用户协议》"
    visible = _visible_required_document_titles(page.elements)
    assert "使用条款" in visible and "用户协议" in visible
    assert not (visible <= _read_document_titles(ctx))


def test_settings_rows_do_not_reopen_clauses_already_read_on_consent_dialog():
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.reader"),
        cfg={}, data_dir=None,
    )
    _mark_required_document_read(ctx, "《隐私政策》", page_text="隐私政策正文")
    _mark_required_document_read(ctx, "《服务协议》", page_text="服务协议正文")
    _mark_required_document_read(ctx, "《第三方SDK目录》", page_text="第三方SDK目录正文")
    hub = parse_page(
        ".UserInfoActivity",
        '''<hierarchy>
          <node text="隐私政策" resource-id="com.example.reader:id/oi_private" clickable="true"/>
          <node text="服务协议" resource-id="com.example.reader:id/oi_agreement" clickable="true"/>
          <node text="第三方SDK目录" resource-id="com.example.reader:id/oi_third_app_sdk" clickable="true"/>
          <node text="修改头像" resource-id="com.example.reader:id/oi_headimage" clickable="true"/>
        </hierarchy>''',
    )
    assert _unread_required_document_target(
        hub.elements, set(), _read_document_kinds(ctx),
        read_titles=_read_document_titles(ctx),
    ) is None
    assert _already_read_document_target(ctx, "com.example.reader:id/oi_private", hub.elements)
    assert _already_read_document_target(ctx, "com.example.reader:id/oi_third_app_sdk", hub.elements)
    assert _document_title_already_read("隐私声明", _read_document_titles(ctx))


def test_nested_settings_rows_are_not_reopened_after_splash_read():
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.reader"),
        cfg={}, data_dir=None,
    )
    _mark_required_document_read(ctx, "《隐私政策》", page_text="隐私政策正文")
    _mark_required_document_read(ctx, "《服务协议》", page_text="服务协议正文")
    _mark_required_document_read(ctx, "《第三方SDK目录》", page_text="第三方SDK目录正文")
    hub = parse_page(".module.setting.AvatarSettingActivity", _QIAN_PROFILE_HUB)
    assert _unread_for_page(ctx, hub.elements, set()) is None
    assert _already_read_document_target(ctx, "com.example.reader:id/oi_private", hub.elements)
    assert _already_read_document_target(ctx, "com.example.reader:id/oi_terms", hub.elements)


def test_combined_consent_caption_keeps_unread_privacy_policy_after_user_agreement():
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )
    _mark_required_document_read(ctx, "《用户协议》", page_text="用户协议正文")
    page = parse_page(
        ".SplashActivity",
        '''<hierarchy>
          <node text="请阅读《用户协议》和《隐私政策》" resource-id="com.demo:id/tv_privacy_content" clickable="true"/>
          <node text="同意" resource-id="com.demo:id/btn_agree" clickable="true"/>
        </hierarchy>''',
    )
    assert _already_read_document_target(ctx, "com.demo:id/tv_privacy_content", page.elements) is False
    # Consent sheets probe each independently visible clause with a bounded
    # open-verification step before falling back to hub/deferred bookkeeping.
    assert _unread_for_page(ctx, page.elements, set()) == "《隐私政策》"
    unread = _unread_required_document_target(
        page.elements, set(), _read_document_kinds(ctx),
        read_titles=_read_document_titles(ctx),
    )
    assert unread is not None
    assert "隐私政策" in unread
    assert _explicit_consent_target(page.elements) == "com.demo:id/btn_agree"


def test_combined_consent_caption_is_fully_read_only_when_every_title_was_opened():
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )
    _mark_required_document_read(ctx, "《用户协议》", page_text="用户协议正文")
    _mark_required_document_read(ctx, "《隐私政策》", page_text="隐私政策正文")
    page = parse_page(
        ".SplashActivity",
        '''<hierarchy>
          <node text="请阅读《用户协议》和《隐私政策》" resource-id="com.demo:id/tv_privacy_content" clickable="true"/>
          <node text="同意" resource-id="com.demo:id/btn_agree" clickable="true"/>
        </hierarchy>''',
    )
    assert _unread_for_page(ctx, page.elements, set()) is None
    assert _already_read_document_target(ctx, "com.demo:id/tv_privacy_content", page.elements)


def test_agree_textview_is_an_explicit_consent_target():
    page = parse_page(
        ".SplashActivity",
        '''<hierarchy>
          <node text="请阅读《用户协议》和《隐私政策》" resource-id="com.demo:id/tv_privacy_content" clickable="true"/>
          <node text="同意" resource-id="com.demo:id/tv_agree" clickable="true" class="android.widget.TextView"/>
        </hierarchy>''',
    )
    assert _is_consent_dialog(page.elements)
    assert _explicit_consent_target(page.elements) == "com.demo:id/tv_agree"


def test_remembered_consent_titles_survive_a_thin_accessibility_dump():
    from agent.ai_explorer.explorer_engine import _unread_remembered_consent_title

    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )
    full = parse_page(
        ".SplashActivity",
        '''<hierarchy>
          <node text="请阅读《用户协议》和《隐私政策》" resource-id="com.demo:id/tv_privacy_content" clickable="true"/>
          <node text="同意" resource-id="com.demo:id/tv_agree" clickable="true" class="android.widget.TextView"/>
        </hierarchy>''',
    )
    _remember_consent_document_titles(ctx, full.elements)
    _mark_required_document_read(ctx, "《用户协议》", page_text="用户协议正文")
    thin = parse_page(
        ".SplashActivity",
        '''<hierarchy>
          <node text="" resource-id="com.demo:id/tv_privacy_content" clickable="true"/>
          <node text="同意" resource-id="com.demo:id/tv_agree" clickable="true" class="android.widget.TextView"/>
        </hierarchy>''',
    )
    # Splash no longer opens remembered titles; memory still retains unread privacy.
    assert _unread_for_page(ctx, thin.elements, set()) is None
    unread = _unread_remembered_consent_title(ctx, set())
    assert unread is not None
    assert "隐私政策" in unread
    assert _already_read_document_target(ctx, "com.demo:id/tv_privacy_content", thin.elements) is False


def test_foreign_photos_home_is_not_the_audited_app_main_content():
    page = parse_page(
        "com.google.android.apps.photos.home.HomeActivity",
        '<hierarchy><node text="Photos" clickable="true"/><node text="Library" clickable="true"/></hierarchy>',
    )
    assert not _looks_like_main_content_surface(
        page.activity, page.elements, "com.example.smarthome",
    )


def test_sdk_observation_does_not_grant_before_consent_is_accepted():
    grants: list[str] = []

    class _Device:
        def grant_runtime_permissions(self, package, permissions):
            grants.extend(permissions)
            return list(permissions)

    engine = AppiumExplorerEngine(client=SimpleNamespace(_device=_Device()))
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo", permissions=["android.permission.READ_PHONE_STATE"]),
        cfg={"detection": {}}, data_dir=None,
    )
    ctx.runtime["consent_dialog_seen"] = True
    ctx.runtime["public_app_surface_seen"] = True
    explorer_module._maybe_enter_sdk_observation_phase(
        ctx, ".home.HomeActivity",
        [{"text": "Photos", "clickable": True, "resource_id": "", "content_desc": ""}],
        [], engine.client,
    )
    assert grants == []
    assert not ctx.runtime.get("sdk_observation_permissions_granted")


def test_consent_dialog_probes_documents_before_photos_and_consent(tmp_path):
    dialog = (
        '<hierarchy>'
        '<node text="请阅读《用户协议》和《隐私政策》" resource-id="com.demo:id/tv_privacy_content" clickable="true"/>'
        '<node text="Photos" clickable="true" class="android.widget.TextView"/>'
        '<node text="同意" resource-id="com.demo:id/tv_agree" clickable="true" class="android.widget.TextView"/>'
        '</hierarchy>'
    )
    home = (
        '<hierarchy><node text="首页" clickable="false"/>'
        '<node text="我的" resource-id="tab_me" clickable="true"/></hierarchy>'
    )

    class _Client:
        def __init__(self):
            self.phase = "dialog"
            self.actions = []

        def page(self):
            return (".SplashActivity", dialog) if self.phase == "dialog" else (".HomeActivity", home)

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and (
                "同意" in str(decision.get("target") or "") or "tv_agree" in str(decision.get("target") or "")
            ):
                self.phase = "home"

        def close(self):
            pass

    class _PhotosFirstLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "Photos", "reason": "4.2"}

        def fallback_action(self, *_args):
            return {"action": "click", "target": "Photos", "reason": "4.2"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_PhotosFirstLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
            "inline_document_open_polls": 2, "inline_document_open_poll_seconds": 0,
            "mode_limits": {"deep": {"max_pages": 8}},
        }},
        data_dir=tmp_path,
    )
    engine.run(ctx)
    clicks = [target for action, target in client.actions if action == "click"]
    assert clicks
    assert clicks[0] != "Photos"
    assert any(term in str(clicks[0]) for term in ("隐私政策", "用户协议"))
    assert ctx.runtime.get("consent_policy_docs_deferred_to_hub") is True


def test_unread_terms_title_is_kept_when_service_agreement_was_already_read():
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )
    _mark_required_document_read(ctx, "《服务协议》", page_text="服务协议正文")
    page = parse_page(
        ".SettingsActivity",
        '''<hierarchy>
          <node text="《使用条款》" clickable="true"/>
          <node text="服务协议" resource-id="oi_terms" clickable="true"/>
        </hierarchy>''',
    )
    assert _unread_for_page(ctx, page.elements, set()) == "《使用条款》"


def test_consent_checkbox_caption_is_not_used_as_document_click_target():
    """案例K-style dialog: links live in body/caption text, not as separate nodes."""
    page = parse_page(
        ".SplashActivity",
        '<hierarchy>'
        '<node text="请你务必审慎阅读、充分理解服务协议和隐私政策各条款。包括但不限于：为了向你提供服务，我们需要收集你的设备信息、操作日志等个人信息。你可阅读《服务协议》、《隐私政策》和《第三方SDK目录》了解详细信息。" '
        'clickable="false" class="android.widget.TextView"/>'
        '<node text="请勾选阅读并同意《服务协议》、《隐私政策》和《第三方SDK目录》" resource-id="com.demo:id/checkbox" '
        'checkable="true" checked="false" clickable="true" class="android.widget.CheckBox"/>'
        '<node text="拒绝" clickable="true" class="android.widget.Button"/>'
        '<node text="同意" resource-id="com.demo:id/ok_btn" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>',
    )
    assert _is_consent_dialog(page.elements)
    unread = _unread_required_document_target(page.elements, set(), set())
    assert unread == "《隐私政策》"
    assert "请勾选" not in (unread or "")
    after_privacy = _unread_required_document_target(page.elements, {unread}, {"privacy_policy"})
    assert after_privacy in {"《服务协议》", "《第三方SDK目录》", "《第三方sdk目录》"}
    assert after_privacy and "请勾选" not in after_privacy
    # Visited short titles must NOT fake-complete the kind — only read_kinds does.
    still_privacy = _unread_required_document_target(page.elements, {"《隐私政策》"}, set())
    assert still_privacy == "《服务协议》" or still_privacy == "《隐私政策》"
    assert _preferred_inline_document_target(
        "你可阅读《服务协议》、《隐私政策》和《第三方SDK目录》了解详细信息。", "disclosure_list",
    ) == "《第三方SDK目录》"


def test_explorer_probes_splash_documents_then_agrees_when_they_do_not_open(tmp_path):
    dialog = (
        '<hierarchy>'
        '<node text="请仔细阅读《隐私政策》和《用户服务协议》" clickable="false" class="android.widget.TextView"/>'
        '<node text="《隐私政策》" clickable="true" class="android.widget.TextView"/>'
        '<node text="《用户服务协议》" clickable="true" class="android.widget.TextView"/>'
        '<node text="同意并继续" resource-id="com.example.reader:id/ok_btn" clickable="true" class="android.widget.Button"/>'
        '<node text="拒绝" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>'
    )
    home = '<hierarchy><node text="首页" clickable="false"/><node text="设置" resource-id="settings" clickable="true" class="android.widget.TextView"/></hierarchy>'

    class _ConsentClient:
        def __init__(self):
            self.phase = "dialog"
            self.actions = []

        def page(self):
            if self.phase == "home":
                return ".MainActivity", home
            return ".SplashActivity", dialog

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and (
                "同意" in str(decision.get("target") or "")
                or "ok_btn" in str(decision.get("target") or "")
            ):
                self.phase = "home"

        def close(self):
            pass

    class _AgreeFirstLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "《隐私政策》", "reason": "先读条款"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _ConsentClient()
    engine = AppiumExplorerEngine(client=client, llm=_AgreeFirstLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "external_document_wait_retries": 0, "external_document_wait_seconds": 0,
            "inline_document_open_polls": 2, "inline_document_open_poll_seconds": 0,
            "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
            "mode_limits": {"fast": {"max_pages": 6}},
        }},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)
    clicks = [target for action, target in client.actions if action == "click"]
    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]
    assert clicks
    assert "《隐私政策》" in clicks
    assert "《用户服务协议》" in clicks
    assert any("同意" in str(target) or "ok_btn" in str(target) for target in clicks)
    assert "splash_document_probe_started" in event_types
    assert "inline_document_open_failed" in event_types
    assert ctx.runtime.get("consent_policy_docs_deferred_to_hub") is True


def test_splash_document_probe_and_consent_locks_do_not_hand_control_to_llm(tmp_path, monkeypatch):
    """Splash clauses are probed with a bound; consent never hands control to LLM."""
    dialog = (
        '<hierarchy>'
        '<node text="请阅读《隐私政策》与《用户协议》后继续" clickable="true"/>'
        '<node text="《隐私政策》" clickable="true"/>'
        '<node text="《用户协议》" clickable="true"/>'
        '<node text="同意" resource-id="btn_agree" clickable="true" class="android.widget.Button"/>'
        '<node text="不同意" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>'
    )
    page = parse_page(".WelcomeActivity", dialog)
    assert explorer_module._is_splash_deferred_document_target("《隐私政策》", page.elements)
    assert explorer_module._is_splash_deferred_document_target("《用户协议》", page.elements)
    assert not explorer_module._is_splash_deferred_document_target("同意", page.elements)
    assert not explorer_module._is_splash_deferred_document_target("btn_agree", page.elements)

    # Missing Agree → deterministic wait lock (not LLM), so splash docs cannot open.
    monkeypatch.setattr(explorer_module, "_explicit_consent_target", lambda elements: None)

    class _Client:
        def __init__(self):
            self.actions = []

        def page(self):
            return ".WelcomeActivity", dialog

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))

        def close(self):
            pass

    class _DocLLM:
        def choose_action(self, *_args):
            raise AssertionError("consent dialog must not call LLM")

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_DocLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
            "inline_document_open_polls": 2, "inline_document_open_poll_seconds": 0,
            "mode_limits": {"fast": {"max_pages": 3}},
        }},
        data_dir=tmp_path,
    )
    result = engine.run(ctx)
    clicks = [target for action, target in client.actions if action == "click"]
    assert "《隐私政策》" in clicks
    assert "《用户协议》" in clicks
    assert any(
        item.get("meta", {}).get("event_type") in {
            "consent_dialog_wait_for_agree", "splash_document_probe_started",
        }
        for item in result.evidence_files
    )

def test_consent_checkbox_is_ticked_before_agree_on_gated_splash_dialog(tmp_path):
    unchecked = (
        '<hierarchy>'
        '<node text="请勾选阅读并同意《服务协议》《隐私政策》" clickable="false" class="android.widget.TextView"/>'
        '<node text="" resource-id="com.example.reader:id/cb_agree" clickable="true" checkable="true" checked="false" class="android.widget.CheckBox"/>'
        '<node text="同意" resource-id="com.example.reader:id/ok_btn" clickable="true" class="android.widget.Button"/>'
        '<node text="拒绝" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>'
    )
    checked = unchecked.replace('checked="false"', 'checked="true"')
    home = '<hierarchy><node text="首页" clickable="false"/><node text="设置" resource-id="settings" clickable="true" class="android.widget.TextView"/></hierarchy>'

    class _GatedConsentClient:
        def __init__(self):
            self.checked = False
            self.actions = []

        def page(self):
            if self.checked and any(action == "click" and "ok_btn" in str(target) for action, target in self.actions):
                return ".MainActivity", home
            return ".SplashActivity", checked if self.checked else unchecked

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and "cb_agree" in str(decision.get("target") or ""):
                self.checked = True

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    page = parse_page(".SplashActivity", unchecked)
    assert _unchecked_consent_checkbox(page.elements) == "com.example.reader:id/cb_agree"

    client = _GatedConsentClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.reader"),
        cfg={"detection": {
            "inline_document_open_polls": 2,
            "inline_document_open_poll_seconds": 0,
            "mode_limits": {"fast": {"max_pages": 16}},
        }},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)
    clicks = [target for action, target in client.actions if action == "click"]
    assert all("请勾选" not in str(target) for target in clicks)
    assert "com.example.reader:id/cb_agree" in clicks
    agree_index = next(i for i, target in enumerate(clicks) if "ok_btn" in str(target) or target == "同意")
    doc_indices = [
        i for i, target in enumerate(clicks)
        if any(term in str(target) for term in ("隐私政策", "服务协议"))
    ]
    assert doc_indices
    assert max(doc_indices) < clicks.index("com.example.reader:id/cb_agree") < agree_index
    assert any(item.get("meta", {}).get("event_type") == "consent_checkbox_required" for item in result.evidence_files)
    assert not any(item.kind == "consent_checkbox_prechecked" for item in result.findings)
    assert ctx.runtime.get("all_consent_documents_read") is not True
    assert ctx.runtime.get("consent_policy_docs_deferred_to_hub") is True


def test_consent_dialog_with_inline_policy_names_is_opened_before_agree():
    hint = "请勾选阅读并同意《服务协议》《隐私政策》"
    page = parse_page(
        ".SplashActivity",
        '<hierarchy>'
        f'<node text="{hint}" clickable="false" class="android.widget.TextView"/>'
        '<node text="" resource-id="com.example.reader:id/cb_agree" clickable="true" checkable="true" checked="false" class="android.widget.CheckBox"/>'
        '<node text="同意" resource-id="com.example.reader:id/ok_btn" clickable="true" class="android.widget.Button"/>'
        '<node text="拒绝" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>',
    )
    assert _unread_required_document_target(page.elements, set(), set()) == "《隐私政策》"
    assert _unread_required_document_target(page.elements, {"《隐私政策》"}, {"privacy_policy"}) == "《服务协议》"
    assert _unread_required_document_target(
        page.elements, {"《隐私政策》", "《服务协议》"}, {"privacy_policy", "user_agreement"},
    ) is None
    assert _document_key(page.activity, page.elements, PageState()) is None


def test_later_settings_document_read_clears_first_run_unread_coverage_gaps():
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.reader", permissions=[]),
        cfg={},
        data_dir=None,
    )
    ctx.runtime["privacy_hub_visited"] = True
    ctx.runtime["withdraw_paths_observed"] = True
    ctx.runtime["policy_document_read_complete"] = True
    ctx.runtime["rule_coverage_gaps"] = [
        "同意弹窗上的「《隐私政策》」已尝试点击但未打开可读正文，不认定该条款已阅读",
        "同意弹窗上的「《服务协议》」已尝试点击但未打开可读正文，不认定该条款已阅读",
        "同意弹窗上的「《第三方SDK目录》」已尝试点击但未打开可读正文，不认定该条款已阅读",
        "首次同意弹窗未能打开可见的隐私政策/用户协议链接，不能认定条款已阅读",
        "已声明敏感权限，但本次可访问路径未触发系统授权提示",
    ]
    _mark_required_document_read(ctx, "《隐私政策》", page_text="我们如何收集和使用您的个人信息，详见本隐私政策全文。")
    _mark_required_document_read(ctx, "《服务协议》", page_text="本服务协议约定用户使用本应用服务时的权利义务。")
    _mark_required_document_read(ctx, "《第三方SDK目录》", page_text="第三方SDK目录列明了合作方名称、收集的信息类型及使用目的。")
    gaps = _coverage_gaps(ctx, permission_prompts=1, login_gate_seen=False, pages_covered=8)
    assert not any("不认定该条款已阅读" in gap for gap in gaps)
    assert not any("不能认定条款已阅读" in gap for gap in gaps)
    assert any("敏感权限" in gap for gap in gaps)


def test_coverage_gaps_include_unfinished_scenario_frontier():
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={}, data_dir=None,
        runtime={
            "policy_document_read_complete": True,
            "privacy_hub_visited": True,
            "withdraw_paths_observed": {"auth"},
        },
    )
    gaps = _coverage_gaps(
        ctx, permission_prompts=0, login_gate_seen=False, pages_covered=5,
        scenario_snapshot={"items": [
            {"item": "4.2", "state": "attempted"},
            {"item": "6.1", "state": "evidence_observed"},
        ]},
    )

    assert any("4.2" in gap and "场景义务" in gap for gap in gaps)


def test_consent_copy_mentioning_sdk_is_not_treated_as_a_sdk_directory_link():
    hint = "请勾选阅读并同意《服务协议》《隐私政策》，其中可能使用第三方SDK"
    page = parse_page(
        ".SplashActivity",
        '<hierarchy>'
        f'<node text="{hint}" clickable="false" class="android.widget.TextView"/>'
        '<node text="同意" resource-id="com.example.reader:id/ok_btn" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>',
    )
    unread = _unread_required_document_target(page.elements, set(), set())
    assert unread == "《隐私政策》"
    assert unread != "第三方sdk"
    assert "第三方sdk" not in (
        _unread_required_document_target(
            page.elements, {"《隐私政策》", "《服务协议》"}, {"privacy_policy", "user_agreement"},
        ) or ""
    )


def test_missed_inline_document_tap_does_not_suppress_other_kinds_or_force_checkbox(tmp_path):
    """同意弹窗同页是正常现象：点书名号未打开正文时，不能把同类条款当已读并跳去勾选。"""
    hint = (
        "你可阅读《服务协议》、《隐私政策》和《第三方SDK目录》了解详细信息。"
        "请勾选阅读并同意《服务协议》、《隐私政策》和《第三方SDK目录》"
    )
    dialog = (
        '<hierarchy>'
        f'<node text="{hint}" clickable="false" class="android.widget.TextView"/>'
        '<node text="请勾选阅读并同意《服务协议》、《隐私政策》和《第三方SDK目录》" '
        'resource-id="com.demo:id/checkbox" checkable="true" checked="false" '
        'clickable="true" class="android.widget.CheckBox"/>'
        '<node text="同意" resource-id="com.demo:id/ok_btn" clickable="true" class="android.widget.Button"/>'
        '<node text="拒绝" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>'
    )

    class _StuckOnDialogClient:
        def __init__(self):
            self.actions = []

        def page(self):
            return ".SplashActivity", dialog

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            # ClickableSpan miss: stay on the splash consent dialog.

        def close(self):
            pass

    class _CheckboxFirstLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "com.demo:id/checkbox", "reason": "先勾选"}

        def fallback_action(self, *_args):
            return {"action": "click", "target": "com.demo:id/checkbox", "reason": "fallback"}

    client = _StuckOnDialogClient()
    engine = AppiumExplorerEngine(client=client, llm=_CheckboxFirstLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo.app", permissions=[]),
        cfg={
            "appium": {"page_wait_seconds": 0},
            "detection": {
                "max_appium_steps": 8,
                "inline_document_open_polls": 2,
                "inline_document_open_poll_seconds": 0,
                "page_settle_retries": 0,
                "mode_limits": {"fast": {"max_pages": 12}},
            },
        },
        data_dir=tmp_path,
    )
    result = engine.run(ctx)
    doc_clicks = [
        target for action, target in client.actions
        if action == "click" and target and (
            "隐私政策" in target or "服务协议" in target or "第三方SDK" in target or "第三方sdk" in target
        ) and "请勾选" not in target and "checkbox" not in target.lower()
    ]
    checkbox_clicks = [
        target for action, target in client.actions
        if action == "click" and "checkbox" in str(target).lower()
    ]
    assert doc_clicks, "应优先点击书名号条款，而不是直接勾选"
    assert not any("请勾选" in t for t in doc_clicks)
    if checkbox_clicks:
        first_checkbox_idx = next(
            i for i, (action, target) in enumerate(client.actions)
            if action == "click" and "checkbox" in str(target).lower()
        )
        assert any(
            action == "click" and target in doc_clicks
            for action, target in client.actions[:first_checkbox_idx]
        )
    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]
    assert "inline_document_open_failed" in event_types
    assert "external_document_read_complete" not in event_types
    reasons = [
        str(item.get("meta", {}).get("reason") or "")
        for item in result.evidence_files
        if item.get("meta", {}).get("event_type") in {"duplicate_page_handled", "same_surface_continued"}
    ]
    assert "same_surface_continued" in event_types or all(
        "不是跳过" in reason or "继续" in reason for reason in reasons
    ) or not reasons


def test_explorer_enters_app_when_inline_policy_text_cannot_be_located(tmp_path):
    hint = "请勾选阅读并同意《服务协议》《隐私政策》"
    unchecked = (
        '<hierarchy>'
        f'<node text="{hint}" clickable="false" class="android.widget.TextView"/>'
        '<node text="" resource-id="com.example.reader:id/cb_agree" clickable="true" checkable="true" checked="false" class="android.widget.CheckBox"/>'
        '<node text="同意" resource-id="com.example.reader:id/ok_btn" clickable="true" class="android.widget.Button"/>'
        '<node text="拒绝" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>'
    )
    checked = unchecked.replace('checked="false"', 'checked="true"')
    home = '<hierarchy><node text="首页" clickable="false"/><node text="设置" resource-id="settings" clickable="true" class="android.widget.TextView"/></hierarchy>'

    class _MissingInlineLinkClient:
        def __init__(self):
            self.checked = False
            self.actions = []
            self.entered = False

        def page(self):
            if self.entered:
                return ".MainActivity", home
            return ".SplashActivity", checked if self.checked else unchecked

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            target = str(decision.get("target") or "")
            if decision["action"] == "click" and (
                hint in target or "隐私政策" in target or "服务协议" in target
            ):
                raise ExplorationError("执行遍历操作 click 失败：Message: An element could not be located on the page using the given search parameters.")
            if decision["action"] == "click" and "cb_agree" in target:
                self.checked = True
            if decision["action"] == "click" and ("ok_btn" in target or target == "同意"):
                self.entered = True

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _MissingInlineLinkClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.example.reader"),
        cfg={"detection": {"mode_limits": {"deep": {"max_pages": 12}}}},
        data_dir=tmp_path,
    )
    engine.run(ctx)
    clicks = [target for action, target in client.actions if action == "click"]
    assert "com.example.reader:id/cb_agree" in clicks
    assert any("ok_btn" in str(target) or target == "同意" for target in clicks)
    assert client.entered is True
    assert ctx.runtime.get("traversal_termination", {}).get("kind") != "safe_frontier_exhausted" or client.entered


def test_repeated_failed_target_is_abandoned_for_a_safe_sibling(tmp_path):
    page_xml = '''<hierarchy>
      <node text="无效入口" resource-id="bad_target" clickable="true"/>
      <node text="意见反馈" resource-id="safe_sibling" clickable="true"/>
    </hierarchy>'''

    class _FailOneTargetClient:
        def __init__(self):
            self.actions = []

        def activate(self, _package):
            pass

        def page(self):
            return ".MainActivity", page_xml

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            target = str(decision.get("target") or "")
            self.actions.append((decision.get("action"), target))
            if decision.get("action") == "click" and target == "bad_target":
                raise ExplorationError("element could not be located")

        def close(self):
            pass

    class _BadTargetLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "bad_target", "reason": "repeat stale target"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _FailOneTargetClient()
    engine = AppiumExplorerEngine(client=client, llm=_BadTargetLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "mode_limits": {"deep": {"max_pages": 7}},
        }},
        data_dir=tmp_path,
        runtime={"consent_accepted": True},
    )

    result = engine.run(ctx)

    clicked = [target for action, target in client.actions if action == "click"]
    assert clicked.count("bad_target") == 2
    assert "safe_sibling" in clicked
    event_types = {
        item.get("meta", {}).get("event_type") for item in result.evidence_files
    }
    assert "target_interaction_retry_exhausted" in event_types


_QIAN_PROFILE_HUB = '''<hierarchy>
<node text="个人信息" clickable="false" class="android.widget.TextView"/>
<node text="头像" clickable="false" class="android.widget.TextView"/>
<node text="" resource-id="com.example.reader:id/head_image" clickable="true" class="android.widget.ImageView"/>
<node text="昵称" clickable="false" class="android.widget.TextView"/>
<node text="467955_registered_reader_display_name" clickable="false" class="android.widget.TextView"/>
<node text="性别" clickable="false" class="android.widget.TextView"/>
<node text="未知" clickable="false" class="android.widget.TextView"/>
<node text="年龄" clickable="false" class="android.widget.TextView"/>
<node text="99岁11个月，用于展示个人资料字段，避免被当成协议正文" clickable="false" class="android.widget.TextView"/>
<node text="城市" clickable="false" class="android.widget.TextView"/>
<node text="未填写居住城市信息占位" clickable="false" class="android.widget.TextView"/>
<node text="账号" clickable="false" class="android.widget.TextView"/>
<node text="10008642" clickable="false" class="android.widget.TextView"/>
<node text="手机号" clickable="false" class="android.widget.TextView"/>
<node text="13800138000" clickable="false" class="android.widget.TextView"/>
<node resource-id="com.example.reader:id/oi_terms" clickable="true" bounds="[0,800][1080,880]" class="android.widget.LinearLayout">
  <node text="服务协议" clickable="false" bounds="[40,810][240,870]" class="android.widget.TextView"/>
</node>
<node resource-id="com.example.reader:id/oi_private" clickable="true" bounds="[0,880][1080,960]" class="android.widget.LinearLayout">
  <node text="隐私政策" clickable="false" bounds="[40,890][240,950]" class="android.widget.TextView"/>
</node>
<node resource-id="com.example.reader:id/oi_sdk" clickable="true" bounds="[0,960][1080,1040]" class="android.widget.LinearLayout">
  <node text="第三方SDK目录" clickable="false" bounds="[40,970][400,1030]" class="android.widget.TextView"/>
</node>
<node text="退出登录" clickable="true" class="android.widget.TextView"/>
</hierarchy>'''


def test_personal_info_hub_is_not_treated_as_a_scrollable_policy_document():
    page = parse_page(".module.setting.AvatarSettingActivity", _QIAN_PROFILE_HUB)
    assert _document_key(page.activity, page.elements, PageState()) is None
    state = PageState()
    state.active_document = ".module.setting.AvatarSettingActivity:document:服务协议"
    state.last_action = "scroll"
    assert _document_key(page.activity, page.elements, state) is None
    unread = _unread_required_document_target(page.elements, set(), set())
    assert unread in {"隐私政策", "com.example.reader:id/oi_private"}


def test_explorer_clicks_profile_policy_links_instead_of_scrolling_the_form(tmp_path):
    policy = (
        '<hierarchy><node text="隐私政策：我们会收集必要信息用于提供阅读服务。" clickable="false" '
        'class="android.widget.TextView"/><node text="正文" clickable="false" scrollable="true" '
        'class="android.webkit.WebView"/></hierarchy>'
    )

    class _ProfileHubClient:
        def __init__(self):
            self.phase = "hub"
            self.actions = []
            self.hub_scrolls = 0

        def page(self):
            if self.phase == "policy":
                return "org.chromium.chrome.browser.customtabs.CustomTabActivity", policy
            return ".module.setting.AvatarSettingActivity", _QIAN_PROFILE_HUB

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return False

        def scroll_down(self):
            if self.phase == "hub":
                self.hub_scrolls += 1
            return False

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and (
                decision.get("target") in {"隐私政策", "com.example.reader:id/oi_private"}
                or "private" in str(decision.get("target") or "").lower()
            ):
                self.phase = "policy"
            elif decision["action"] == "back":
                self.phase = "hub"

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _ProfileHubClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.reader"),
        cfg={"detection": {"mode_limits": {"fast": {"max_pages": 8}}}},
        data_dir=tmp_path,
    )
    engine.run(ctx)
    clicks = [target for action, target in client.actions if action == "click"]
    assert clicks
    assert clicks[0] in {"隐私政策", "com.example.reader:id/oi_private"}
    assert client.hub_scrolls == 0


def test_main_content_tab_is_preferred_over_profile_privacy_link():
    page = parse_page(
        ".module.home.HomeActivity",
        '<hierarchy>'
        '<node text="书城" resource-id="tab_library" clickable="true" class="android.widget.TextView"/>'
        '<node text="我的" resource-id="tab_mine" clickable="true" class="android.widget.TextView"/>'
        '<node text="隐私政策" resource-id="oi_private" clickable="true" class="android.widget.TextView"/>'
        '</hierarchy>',
    )
    assert _main_content_tab_target(page.elements) == "tab_library"


def test_explorer_opens_bookstore_tab_before_profile_policy_after_login(tmp_path):
    profile = (
        '<hierarchy>'
        '<node text="书城" resource-id="tab_library" clickable="true" class="android.widget.TextView"/>'
        '<node text="我的" resource-id="tab_mine" clickable="true" class="android.widget.TextView"/>'
        '<node text="隐私政策" resource-id="oi_private" clickable="true" class="android.widget.TextView"/>'
        '<node text="用户3367" clickable="false" class="android.widget.TextView"/>'
        '<node text="退出登录" clickable="true" class="android.widget.TextView"/>'
        '</hierarchy>'
    )
    bookstore = (
        '<hierarchy>'
        '<node text="书城" resource-id="tab_library" clickable="true" class="android.widget.TextView"/>'
        '<node text="我的" resource-id="tab_mine" clickable="true" class="android.widget.TextView"/>'
        '<node text="热门小说列表占位避免过短" clickable="false" class="android.widget.TextView"/>'
        '</hierarchy>'
    )

    class _PostLoginClient:
        def __init__(self):
            self.phase = "profile"
            self.actions = []

        def page(self):
            return (".module.home.HomeActivity", bookstore if self.phase == "store" else profile)

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and "tab_library" in str(decision.get("target") or ""):
                self.phase = "store"

        def close(self):
            pass

    class _PrivacyFirstLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "oi_private", "reason": "先读隐私政策"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _PostLoginClient()
    engine = AppiumExplorerEngine(client=client, llm=_PrivacyFirstLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"detection": {
            "sdk_observation_dwell_seconds": 0,
            "page_settle_retries": 0,
            "mode_limits": {"fast": {"max_pages": 6}},
        }},
        data_dir=tmp_path,
    )
    ctx.runtime["manual_login_verified"] = True
    ctx.runtime["consent_accepted"] = True
    result = engine.run(ctx)
    clicks = [target for action, target in client.actions if action == "click"]
    assert clicks[0] == "tab_library"
    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]
    assert "sdk_observation_tab_prioritized" in event_types
    assert "sdk_observation_dwelled" in event_types


def test_global_target_key_is_stable_across_repeated_semantic_route():
    elements = [{
        "target": "关于我们", "resource_id": "com.example:id/about",
        "text": "关于我们", "content_desc": "", "clickable": True,
        "bounds": "[0,100][400,200]",
    }]

    first = _global_target_key(".MainActivity", "关于我们", elements)
    second = _global_target_key(".MainActivity", "关于我们", elements)

    assert first == second
    assert first.startswith("route|")
    assert "关于我们" in first
    assert "100" not in first


def test_transaction_targets_are_observation_only():
    elements = [{
        "target": "立即支付", "text": "立即支付", "content_desc": "",
        "resource_id": "pay_now", "clickable": True,
    }]

    assert _is_transaction_target("立即支付", elements)
    assert not _is_transaction_target("关于我们", elements)


@pytest.mark.parametrize("label", [
    "邀请好友赚红包", "购买会员", "开通VIP", "刷新购买次数",
    "广告活动", "兑换奖励", "Invite friends", "Premium membership",
])
def test_deep_search_prunes_low_audit_value_marketing_targets(label):
    elements = [{
        "target": label, "text": label, "content_desc": "",
        "resource_id": "marketing-entry", "clickable": True,
    }]

    assert not _is_safe_deep_probe_target(label, elements)


@pytest.mark.parametrize("label", [
    "意见反馈", "投诉举报", "帮助与支持", "在线客服", "个性化广告推荐管理",
])
def test_deep_search_keeps_compliance_relevant_routes(label):
    elements = [{
        "target": label, "text": label, "content_desc": "",
        "resource_id": "redress-entry", "clickable": True,
    }]

    assert _is_safe_deep_probe_target(label, elements)


def test_global_revisit_block_cannot_be_undone_by_late_deep_search(tmp_path):
    class _RepeatedRouteClient:
        def __init__(self):
            self.phase = 0
            self.actions = []

        def page(self):
            return ".FeatureActivity", (
                '<hierarchy>'
                '<node text="书盘" resource-id="disk" clickable="true"/>'
                f'<node text="状态入口{self.phase}" resource-id="state-{self.phase}" clickable="true"/>'
                '</hierarchy>'
            )

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click":
                self.phase += 1

        def close(self):
            pass

    class _RepeatLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "disk", "reason": "继续进入同一入口"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "back", "target": "", "reason": "无其它入口"}

    client = _RepeatedRouteClient()
    engine = AppiumExplorerEngine(client=client, llm=_RepeatLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
            "mode_limits": {"deep": {"max_pages": 7}},
        }},
        data_dir=tmp_path,
        runtime={
            "consent_accepted": True, "sdk_observation_dwell_done": True,
            "privacy_hub_visited": True,
        },
    )

    result = engine.run(ctx)
    clicks = [target for action, target in client.actions if action == "click"]
    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]

    assert "global_target_revisit_blocked" in event_types
    assert clicks.count("disk") == 1


def test_document_kind_mismatch_marks_only_the_observed_body_title():
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={}, data_dir=None,
    )

    kind = _mark_required_document_read(
        ctx,
        "第三方SDK目录",
        page_text="服务协议 本协议说明账号服务、使用条件和双方权利义务。",
    )

    assert kind == "service_terms"
    assert "服务协议" in _read_document_titles(ctx)
    assert "第三方sdk目录" not in _read_document_titles(ctx)


def test_document_identity_uses_first_body_title_then_survives_footer_links():
    first = parse_page(
        ".WebViewActivity",
        '<hierarchy><node text="服务协议" clickable="false" class="android.webkit.WebView"/></hierarchy>',
    )
    state = PageState()
    assert _document_key(first.activity, first.elements, state).endswith(":document:服务协议")

    state.active_document = ".WebViewActivity:document:隐私政策"
    state.last_action = "scroll"
    later = parse_page(
        ".WebViewActivity",
        '<hierarchy><node text="更多信息请参见《服务协议》" clickable="false" class="android.webkit.WebView"/></hierarchy>',
    )
    assert _document_key(later.activity, later.elements, state) == state.active_document


def test_active_policy_scroll_is_not_reclassified_as_login_from_policy_copy():
    """A policy mentioning phone login must keep its established scroll session."""
    state = PageState()
    state.start_document(".CActivity:document:隐私政策")
    state.last_action = "scroll"
    policy_viewport = parse_page(
        ".CActivity",
        '''<hierarchy>
          <node text="隐私政策：账号可通过手机号和验证码注册登录；我们说明收集、使用个人信息的规则。"
                clickable="false" class="android.widget.TextView"/>
          <node text="手机号" resource-id="phone" clickable="false" class="android.widget.EditText"/>
          <node text="登录" resource-id="submit" clickable="true" class="android.widget.Button"/>
        </hierarchy>''',
    )

    assert _is_login_gate(policy_viewport.activity, policy_viewport.elements)
    assert _document_key(policy_viewport.activity, policy_viewport.elements, state) == state.active_document


def test_completed_policy_viewport_never_enters_manual_login_before_returning():
    """Even the final viewport remains a document until navigation leaves it."""
    policy_viewport = parse_page(
        ".CActivity",
        '''<hierarchy>
          <node text="隐私政策：账号可通过手机号和验证码注册登录。"
                clickable="false" class="android.widget.TextView"/>
          <node text="手机号" resource-id="phone" clickable="false" class="android.widget.EditText"/>
          <node text="登录" resource-id="submit" clickable="true" class="android.widget.Button"/>
        </hierarchy>''',
    )

    assert _is_login_gate(policy_viewport.activity, policy_viewport.elements)
    assert not explorer_module._credential_login_surface(
        policy_viewport.activity,
        policy_viewport.elements,
        document_key=".CActivity:document:隐私政策",
    )
    assert explorer_module._credential_login_surface(
        policy_viewport.activity,
        policy_viewport.elements,
        document_key=None,
    )


class _Client:
    def __init__(self):
        self.index = 0
        self.scroll_results = [True, False]
        self.performed = []
        self.screenshots = []

    def page(self):
        pages = [(".RootActivity", _ROOT), (".PrivacyActivity", _POLICY_TOP), (".PrivacyActivity", _POLICY_BOTTOM)]
        return pages[self.index]

    def activate(self, _package):
        pass

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        self.screenshots.append(path)
        return True

    def scroll_down(self):
        moved = self.scroll_results.pop(0)
        if moved:
            self.index = 2
        return moved

    def perform(self, decision):
        self.performed.append(decision["action"])
        if decision["action"] == "click":
            self.index = 1
        elif decision["action"] == "back":
            self.index = 0

    def close(self):
        pass


class _LLM:
    def choose_action(self, page, _visited):
        if page["activity"] == ".PrivacyActivity":
            return {"action": "back", "target": "", "reason": "政策已阅读完毕"}
        return {"action": "click", "target": "privacy", "reason": "进入隐私政策"}

    def fallback_action(self, _elements, _visited, *_args):
        return {"action": "stop", "target": "", "reason": "无未访问入口"}


class _DelayedWebViewClient:
    """A WebView may expose an empty accessibility tree immediately after click."""
    def __init__(self):
        self.phase = "root"
        self.empty_reads = 0

    def page(self):
        if self.phase == "root":
            return ".RootActivity", _ROOT
        if self.phase == "delayed_webview":
            self.empty_reads += 1
            if self.empty_reads == 1:
                return ".WebViewActivity", "<hierarchy/>"
            return ".WebViewActivity", _POLICY_TOP
        return ".WebViewActivity", _POLICY_TOP

    def activate(self, _package):
        pass

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return True

    def scroll_down(self):
        return False

    def perform(self, decision):
        if decision["action"] == "click":
            self.phase = "delayed_webview"
        elif decision["action"] == "back":
            self.phase = "root"

    def close(self):
        pass


def test_blank_terms_webview_is_recorded_as_unavailable_not_scrolled_or_read(tmp_path):
    terms = '''<hierarchy><node text="Terms of service" resource-id="title" clickable="false" class="android.widget.TextView"/></hierarchy>'''

    class _BlankTermsClient:
        def __init__(self):
            self.scroll_calls = 0
            self.actions = []

        def page(self):
            return ".WebViewActivity", terms

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return True

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def scroll_down(self):
            self.scroll_calls += 1
            return False

        def perform(self, decision):
            self.actions.append(decision["action"])

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _BlankTermsClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"document_blank_retries": 1, "mode_limits": {"fast": {"max_pages": 4}}}, "appium": {"page_wait_seconds": 0}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.scroll_calls == 0
    assert "back" in client.actions
    assert any(item.get("meta", {}).get("event_type") == "document_content_unavailable" for item in result.evidence_files)
    assert any(item.get("reason") == "visible_body_blank" for item in ctx.runtime["incomplete_documents"])


def test_document_scroll_socket_hang_soft_stops_instead_of_aborting_audit(tmp_path):
    """WebView swipe session loss must not kill the whole exploration."""
    terms = '''<hierarchy>
      <node text="隐私政策" clickable="false"/>
      <node text="本政策说明我们如何收集和使用个人信息。" clickable="false"/>
    </hierarchy>'''
    home = '''<hierarchy>
      <node text="《隐私政策》" resource-id="policy-link" clickable="true"/>
      <node text="首页" clickable="true"/>
    </hierarchy>'''

    class _HangOnScrollClient:
        def __init__(self):
            self.stage = "home"
            self.actions = []
            self.recover_calls = 0

        def page(self):
            if self.stage == "doc":
                return ".WebViewActivity", terms
            return ".MainActivity", home

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return False

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def scroll_down(self):
            raise ExplorationError("向下滚动页面失败：socket hang up")

        def recover_runtime_session(self, package_name, error):
            self.recover_calls += 1
            return False

        def perform(self, decision):
            self.actions.append(decision["action"])
            if decision.get("action") == "click" and "policy" in str(decision.get("target") or ""):
                self.stage = "doc"
            if decision.get("action") == "back":
                self.stage = "home"

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _HangOnScrollClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"mode_limits": {"fast": {"max_pages": 6}}}, "appium": {"page_wait_seconds": 0}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.recover_calls >= 1
    assert "back" in client.actions
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert "document_scroll_aborted" in event_types
    assert ctx.runtime.get("traversal_termination", {}).get("kind") != "exploration_error"
    assert any(item.get("reason") == "document_scroll_session_lost" for item in ctx.runtime.get("incomplete_documents", []))


def test_explorer_reads_policy_by_scrolling_once_per_view_and_stops_a_return_loop(tmp_path):
    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_LLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {"max_document_scrolls": 5, "mode_limits": {"fast": {"max_pages": 12}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.scroll_results == []
    assert client.performed == ["click", "back"]
    assert len(client.screenshots) == 3  # root + two genuinely different policy viewports
    assert result.stats["pages_covered"] == 2  # scrolling does not inflate App page coverage
    assert ctx.runtime["traversal_termination"]["kind"] == "frontier_incomplete"
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert {"document_scrolled", "document_read_complete", "already_read_document_skipped", "traversal_terminated"} <= event_types


def test_explorer_does_not_mark_a_document_complete_without_a_verified_scroll(tmp_path):
    client = _DelayedWebViewClient()
    engine = AppiumExplorerEngine(client=client, llm=_LLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={
            "appium": {"page_wait_seconds": 0},
            "detection": {"max_document_scrolls": 5, "mode_limits": {"fast": {"max_pages": 8}}},
        },
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.empty_reads >= 2
    assert result.stats["pages_covered"] == 2
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert {"page_content_retry", "page_content_recovered", "document_read_incomplete"} <= event_types
    assert "document_read_complete" not in event_types
    assert ctx.runtime.get("policy_document_read_complete") is not True
    assert any("隐私政策" in gap for gap in result.stats["coverage_gaps"])


def test_explorer_recovers_a_runtime_activity_disconnect_and_continues_the_same_audit(tmp_path):
    class _RuntimeLostClient:
        def __init__(self):
            self.reads = 0
            self.recovery_calls = []

        def activate(self, _package):
            pass

        def page(self):
            self.reads += 1
            if self.reads == 1:
                raise ExplorationError("无法读取当前页面：Could not retrieve the currently focused package and activity")
            return ".MainActivity", '<hierarchy><node text="首页" resource-id="home" clickable="false" class="android.widget.TextView"/></hierarchy>'

        def recover_runtime_session(self, package, error):
            self.recovery_calls.append((package, str(error)))
            return True

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _RuntimeLostClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {"mode_limits": {"fast": {"max_pages": 2}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.recovery_calls and client.recovery_calls[0][0] == "com.example.demo"
    assert result.stats["pages_covered"] == 1
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert "runtime_session_recovered" in event_types


def test_runtime_recovery_replays_safe_navigation_to_interrupted_business_surface(tmp_path):
    """A reboot after avatar click must replay root→profile→personal→avatar."""
    pages = {
        "root": (".HomeActivity", '''<hierarchy>
          <node text="首页" clickable="false"/>
          <node text="我的" resource-id="profile_entry" clickable="true"/>
        </hierarchy>'''),
        "profile": (".ProfileActivity", '''<hierarchy>
          <node text="我的" clickable="false"/>
          <node text="个人信息" resource-id="personal_info" clickable="true"/>
        </hierarchy>'''),
        "personal": (".PersonalInfoActivity", '''<hierarchy>
          <node text="个人信息" clickable="false"/>
          <node text="头像" resource-id="avatar_entry" clickable="true"/>
        </hierarchy>'''),
        "chooser": (".PersonalInfoActivity", '''<hierarchy>
          <node text="请选择图片来源" clickable="false"/>
          <node text="照相机" resource-id="camera_source" clickable="true"/>
          <node text="相册" resource-id="album_source" clickable="true"/>
        </hierarchy>'''),
    }

    class _RebootOnChooserClient:
        def __init__(self):
            self.phase = "root"
            self.recovered = False
            self.crashed = False
            self.actions = []

        def activate(self, _package):
            pass

        def page(self):
            if self.phase == "chooser" and not self.crashed:
                self.crashed = True
                raise ExplorationError(
                    "无法读取当前页面：Could not retrieve the currently focused package and activity"
                )
            return pages[self.phase]

        def recover_runtime_session(self, _package, _error):
            self.recovered = True
            self.phase = "root"
            return True

        def perform(self, decision):
            if decision.get("action") != "click":
                return
            target = str(decision.get("target") or "")
            self.actions.append((self.recovered, target))
            transitions = {
                ("root", "profile_entry"): "profile",
                ("profile", "personal_info"): "personal",
                ("personal", "avatar_entry"): "chooser",
            }
            self.phase = transitions.get((self.phase, target), self.phase)

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def close(self):
            pass

    class _PathLLM:
        def __init__(self, client):
            self.client = client

        def choose_action(self, *_args):
            if self.client.recovered:
                return {"action": "stop", "target": "", "reason": "recovery must replay"}
            targets = {
                "root": "profile_entry", "profile": "personal_info", "personal": "avatar_entry",
            }
            target = targets.get(self.client.phase)
            return (
                {"action": "click", "target": target, "reason": "build safe route"}
                if target else {"action": "stop", "target": "", "reason": "done"}
            )

        def fallback_action(self, *_args, **_kwargs):
            return self.choose_action()

    client = _RebootOnChooserClient()
    engine = AppiumExplorerEngine(client=client, llm=_PathLLM(client))
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={
            "appium": {"page_wait_seconds": 0},
            "detection": {"page_settle_retries": 0, "mode_limits": {"fast": {"max_pages": 8}}},
        },
        data_dir=tmp_path,
        runtime={"consent_accepted": True},
    )

    result = engine.run(ctx)

    replayed = [target for recovered, target in client.actions if recovered]
    assert replayed[:3] == ["profile_entry", "personal_info", "avatar_entry"]
    assert client.phase == "chooser"
    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]
    assert "navigation_replay_started" in event_types
    assert "navigation_replay_completed" in event_types


def test_navigation_replay_never_reuses_old_bounds_or_destructive_confirmation():
    old_page = parse_page(
        ".AccountActivity",
        '''<hierarchy>
          <node text="确认注销" resource-id="confirm_delete" clickable="true"
                bounds="[0,1800][1080,2000]"/>
        </hierarchy>''',
    )
    state = PageState()
    state.is_new(old_page)
    state.commit_target(old_page, "bounds:[0,1800][1080,2000]")
    edge = state.navigation_replay.replay_edges()[0]
    redrawn = parse_page(
        ".AccountActivity",
        '''<hierarchy>
          <node text="确认注销" resource-id="confirm_delete" clickable="true"
                bounds="[0,1500][1080,1700]"/>
        </hierarchy>''',
    )

    from agent.ai_explorer.navigation_replay import (
        NavigationReplaySafety, navigation_replay_target_is_safe,
        resolve_navigation_replay_target,
    )

    safety = NavigationReplaySafety(
        is_document_route=_target_is_document_route,
        is_transaction_target=_is_transaction_target,
        is_destructive_confirmation=_is_destructive_confirmation,
        is_app_exit_confirmation=_is_app_exit_confirmation,
        is_logout_confirmation_target=_is_logout_confirmation_target,
        is_consent_or_decline_control=_is_consent_or_decline_control,
        is_safe_deep_probe_target=_is_safe_deep_probe_target,
        is_launcher_activity=lambda _activity: False,
        has_left_audited_package=_has_left_audited_package,
    )

    resolved = resolve_navigation_replay_target(edge, redrawn.elements)

    assert resolved == "confirm_delete"
    assert resolved != edge.target
    assert not navigation_replay_target_is_safe(resolved, redrawn, safety)


def test_runtime_recovery_retries_interrupted_external_document_once(tmp_path):
    """A reboot between the policy tap and Custom Tab must not skip the link."""
    app_page = '<hierarchy><node text="隐私政策" resource-id="privacy" clickable="true" class="android.widget.TextView"/></hierarchy>'
    body_page = '<hierarchy><node text="隐私政策说明：我们会收集必要信息用于提供服务。" clickable="false" class="android.widget.TextView"/><node text="正文" clickable="false" scrollable="true" class="android.webkit.WebView"/></hierarchy>'

    class _InterruptedDocumentClient:
        def __init__(self):
            self.reads = 0
            self.phase = "app"
            self.recovery_calls = 0
            self.actions = []

        def activate(self, _package):
            pass

        def page(self):
            self.reads += 1
            if self.reads == 1:
                raise ExplorationError("UiAutomator session lost during Custom Tab launch")
            if self.reads == 2:
                return ".MainActivity", '<hierarchy><node resource-id="android:id/content" clickable="false" class="android.view.View"/></hierarchy>'
            if self.phase == "tab":
                return "org.chromium.chrome.browser.customtabs.CustomTabActivity", body_page
            return ".MainActivity", app_page

        def recover_runtime_session(self, _package, _error):
            self.recovery_calls += 1
            return True

        def document_body_is_blank(self):
            return False

        def scroll_down(self):
            return False

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and decision.get("target") == "隐私政策":
                self.phase = "tab"
            elif decision["action"] == "back":
                self.phase = "app"

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _InterruptedDocumentClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"detection": {"external_document_wait_retries": 0, "external_document_wait_seconds": 0,
                            "mode_limits": {"fast": {"max_pages": 5}}}},
        data_dir=tmp_path,
        runtime={"last_appium_action": {"action": "click", "target": "隐私政策"}},
    )

    result = engine.run(ctx)

    events = [item.get("meta", {}).get("event_type") for item in result.evidence_files]
    assert client.recovery_calls == 1
    assert ("click", "隐私政策") in client.actions
    assert "external_document_interrupted" in events
    assert "external_document_recovery_retry_wait" in events
    assert "external_document_recovery_retry" in events
    assert "external_document_read_complete" in events


def test_file_picker_is_returned_to_the_app_instead_of_aborting_the_traversal(tmp_path):
    """A safe import probe may open DocumentsUI; it is not an App page."""
    app_page = '''<hierarchy><node text="导入文件" resource-id="import-work" clickable="true" class="android.widget.Button"/></hierarchy>'''
    picker_page = '''<hierarchy><node text="Recent" resource-id="com.android.documentsui:id/toolbar" clickable="false" class="android.widget.TextView"/><node text="Documents" resource-id="com.android.documentsui:id/roots_list" clickable="true" class="android.widget.TextView"/></hierarchy>'''

    class _FilePickerClient:
        def __init__(self):
            self.phase = "app"
            self.actions = []

        def page(self):
            return (
                ("com.android.documentsui.picker.PickActivity", picker_page)
                if self.phase == "picker" else (".MainActivity", app_page)
            )

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click":
                self.phase = "picker"
            elif decision["action"] == "back":
                self.phase = "app"

        def close(self):
            pass

    class _StopAfterProbeLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "no further route"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "no further route"}

    client = _FilePickerClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopAfterProbeLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_sensitive_permission_probes": 3, "mode_limits": {"deep": {"max_pages": 5}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.actions[:2] == [("click", "import-work"), ("back", "")]
    assert any(
        item.get("meta", {}).get("event_type") == "external_surface_returned_to_app"
        for item in result.evidence_files
    )
    picker_event = next(
        item for item in result.evidence_files
        if item.get("meta", {}).get("event_type") == "scoped_media_picker_observed"
    )
    assert picker_event["meta"]["broad_permission_requested"] is False
    coverage = {row["item"]: row for row in result.stats["scenario_coverage"]["items"]}
    assert coverage["2.3"]["state"] == "not_applicable"
    assert coverage["4.2"]["state"] == "not_applicable"


def test_visible_profile_login_entry_is_prioritized_before_generic_exploration(tmp_path):
    profile_page = '''<hierarchy><node text="点击此处登录" resource-id="profile-login" clickable="true" class="android.widget.TextView"/></hierarchy>'''

    class _ProfileLoginClient:
        def __init__(self):
            self.phase = "profile"
            self.actions = []

        def page(self):
            if self.phase == "login":
                return ".LoginActivity", _LOGIN_PAGE
            return ".MainActivity", profile_page

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click":
                self.phase = "login"
            elif decision["action"] == "back":
                self.phase = "profile"

        def close(self):
            pass

    class _NoGenericLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "must not hide login entry"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def assess_login_state(self, _page):
            return False

    client = _ProfileLoginClient()
    engine = AppiumExplorerEngine(client=client, llm=_NoGenericLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"manual_login_wait_seconds": 0, "mode_limits": {"fast": {"max_pages": 5}}}},
        data_dir=tmp_path,
    )

    engine.run(ctx)

    assert client.actions[:2] == [("click", "profile-login"), ("back", "")]


def test_blank_external_privacy_tab_is_waited_then_recorded_as_unavailable(tmp_path):
    custom_tab = '''<hierarchy><node text="kdwrite.cn" resource-id="com.android.chrome:id/url_bar" clickable="true" class="android.widget.EditText"/></hierarchy>'''
    app_page = '''<hierarchy><node text="首页" resource-id="home" clickable="false" class="android.widget.TextView"/></hierarchy>'''

    class _CustomTabClient:
        def __init__(self):
            self.in_tab = True
            self.actions = []

        def page(self):
            return (
                ("org.chromium.chrome.browser.customtabs.CustomTabActivity", custom_tab)
                if self.in_tab else (".MainActivity", app_page)
            )

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append(decision["action"])
            if decision["action"] == "back":
                self.in_tab = False

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _CustomTabClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"external_document_wait_retries": 1, "external_document_wait_seconds": 0,
                           "mode_limits": {"fast": {"max_pages": 4}}}},
        data_dir=tmp_path,
        runtime={"last_appium_action": {"action": "click", "target": "《隐私政策》"}},
    )

    result = engine.run(ctx)

    events = {item.get("meta", {}).get("event_type") for item in result.evidence_files}
    assert {"external_document_loading_wait", "external_document_unavailable", "external_surface_returned_to_app"} <= events
    assert client.actions == ["back"]
    assert any("外部隐私/服务条款" in gap for gap in result.stats["coverage_gaps"])


def test_runtime_recovery_satisfies_external_return_from_recovered_checkpoint():
    """External Custom Tab return must recover instead of aborting the audit."""
    events = []

    class _DisconnectedBackClient:
        def __init__(self):
            self.back_attempts = 0
            self.recovery_calls = 0

        def perform(self, decision):
            assert decision["action"] == "back"
            self.back_attempts += 1
            if self.back_attempts == 1:
                raise ExplorationError("执行遍历操作 back 失败：socket hang up")

        def recover_runtime_session(self, package_name, error):
            assert package_name == "com.example.demo"
            assert "socket hang up" in str(error)
            self.recovery_calls += 1
            return True

    client = _DisconnectedBackClient()
    recovery = explorer_module.RuntimeRecoveryCoordinator(
        client=client,
        package_name="com.example.demo",
        runtime={},
        permission_probes=explorer_module.PermissionProbeLedger({}),
        save_checkpoint=lambda: "checkpoint.json",
        replay_navigation=lambda: True,
        is_document_target=lambda _target: False,
        emit=lambda event_type, **meta: events.append((event_type, meta)),
        note_recovery=lambda: None,
        permission_probe_steps=3,
    )

    assert recovery.perform_safe_action(
        4, {"action": "back", "target": ""}, recovery_kind="external_return",
    ) is True
    assert client.recovery_calls == 1
    assert client.back_attempts == 1
    assert [event[0] for event in events] == [
        "runtime_session_lost",
        "runtime_session_waiting_for_recovery",
        "runtime_session_recovered",
        "runtime_safe_action_satisfied_by_recovery",
    ]


def test_external_document_return_uses_runtime_recovery_instead_of_aborting(tmp_path):
    """The explorer must route Custom Tab back through the shared recovery seam."""
    custom_tab = '''<hierarchy><node text="policy.example" resource-id="com.android.chrome:id/url_bar" clickable="true" class="android.widget.EditText"/></hierarchy>'''
    app_page = '''<hierarchy><node text="首页" resource-id="home" clickable="false" class="android.widget.TextView"/></hierarchy>'''

    class _RecoveringCustomTabClient:
        def __init__(self):
            self.in_tab = True
            self.back_attempts = 0
            self.recovered = False

        def page(self):
            return (
                ("org.chromium.chrome.browser.customtabs.CustomTabActivity", custom_tab)
                if self.in_tab else (".MainActivity", app_page)
            )

        def perform(self, decision):
            if decision["action"] != "back":
                return
            self.back_attempts += 1
            if self.back_attempts == 1:
                raise ExplorationError("执行遍历操作 back 失败：socket hang up")
            self.in_tab = False

        def recover_runtime_session(self, _package, _error):
            self.recovered = True
            self.in_tab = False
            return True

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "app restored"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _RecoveringCustomTabClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"external_document_wait_retries": 1, "external_document_wait_seconds": 0,
                           "mode_limits": {"fast": {"max_pages": 4}}}},
        data_dir=tmp_path,
        runtime={"last_appium_action": {"action": "click", "target": "《隐私政策》"}},
    )

    result = engine.run(ctx)

    event_types = {item.get("meta", {}).get("event_type") for item in result.evidence_files}
    assert client.recovered is True
    assert client.back_attempts == 1
    assert {"runtime_session_lost", "runtime_session_waiting_for_recovery", "runtime_session_recovered"} <= event_types
    assert "external_surface_returned_to_app" in event_types


def test_unavailable_external_document_is_not_reopened_forever(tmp_path):
    """A blank Custom Tab must become a coverage gap, not a navigation loop."""
    custom_tab = '<hierarchy><node text="kdwrite.cn" resource-id="com.android.chrome:id/url_bar" clickable="true" class="android.widget.EditText"/></hierarchy>'
    app_page = '<hierarchy><node text="隐私政策" resource-id="privacy" clickable="true" class="android.widget.TextView"/><node text="设置" resource-id="settings" clickable="true" class="android.widget.TextView"/></hierarchy>'

    class _LoopingDocumentClient:
        def __init__(self):
            self.in_tab = False
            self.actions = []

        def page(self):
            return ("org.chromium.chrome.browser.customtabs.CustomTabActivity", custom_tab) if self.in_tab else (".MainActivity", app_page)

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return True

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and decision.get("target") == "隐私政策":
                self.in_tab = True
            elif decision["action"] == "back":
                self.in_tab = False

        def close(self):
            pass

    class _ReopeningLLM:
        def choose_action(self, page, _visited):
            if page["activity"] == ".MainActivity":
                return {"action": "click", "target": "隐私政策", "reason": "read policy"}
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _LoopingDocumentClient()
    engine = AppiumExplorerEngine(client=client, llm=_ReopeningLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"external_document_wait_retries": 1, "external_document_wait_seconds": 0,
                           "mode_limits": {"fast": {"max_pages": 6}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    events = [item.get("meta", {}).get("event_type") for item in result.evidence_files]
    assert "blocked_document_reopen_prevented" in events
    assert client.actions.count(("click", "隐私政策")) == 1


def test_document_keeps_scrolling_past_legacy_limit_until_bottom_is_observed(tmp_path):
    class _LongDocumentClient(_StopBeforePolicyClient):
        def __init__(self):
            super().__init__()
            self.scrolls = 0

        def scroll_down(self):
            self.scrolls += 1
            return self.scrolls <= 6

    client = _LongDocumentClient()
    engine = AppiumExplorerEngine(client=client, llm=_AlwaysStopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {"max_document_scrolls": 5, "mode_limits": {"deep": {"max_pages": 12}}}}, data_dir=tmp_path,
    )

    engine.run(ctx)

    assert client.scrolls == 7
    assert ctx.runtime["policy_document_read_complete"] is True


def test_in_app_document_reads_past_old_24_viewport_cap_until_bottom(tmp_path):
    class _VeryLongDocumentClient(_StopBeforePolicyClient):
        def __init__(self):
            super().__init__()
            self.scrolls = 0

        def scroll_down(self):
            self.scrolls += 1
            return self.scrolls <= 25

    client = _VeryLongDocumentClient()
    engine = AppiumExplorerEngine(client=client, llm=_AlwaysStopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "max_in_app_document_scrolls": 24,
            "mode_limits": {"deep": {"max_pages": 34}},
        }}, data_dir=tmp_path,
    )

    result = engine.run(ctx)
    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]

    assert client.scrolls == 26
    assert ctx.runtime["policy_document_read_complete"] is True
    assert "document_scroll_capped" not in event_types


def test_external_document_reads_past_old_20_viewport_cap_and_uses_body_identity(tmp_path):
    body = (
        '<hierarchy><node text="服务协议" clickable="false"/>'
        '<node text="本协议说明账号服务、使用条件和双方权利义务。" clickable="false"/>'
        '<node text="正文" clickable="false" scrollable="true" class="android.webkit.WebView"/>'
        '</hierarchy>'
    )
    root = (
        '<hierarchy><node text="首页" clickable="false"/>'
        '<node text="第三方SDK目录" resource-id="sdk-entry" clickable="true"/>'
        '</hierarchy>'
    )

    class _VeryLongExternalDocumentClient:
        def __init__(self):
            self.in_tab = True
            self.scrolls = 0
            self.actions = []

        def page(self):
            if self.in_tab:
                return "org.chromium.chrome.browser.customtabs.CustomTabActivity", body
            return ".MainActivity", root

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return False

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def scroll_down(self):
            self.scrolls += 1
            return self.scrolls <= 21

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "back":
                self.in_tab = False

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "结束"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "结束"}

    client = _VeryLongExternalDocumentClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "external_document_wait_retries": 0,
            "max_external_document_scrolls": 20,
            "sdk_observation_dwell_seconds": 0,
            "mode_limits": {"deep": {"max_pages": 30}},
        }},
        data_dir=tmp_path,
        runtime={"last_appium_action": {
            "action": "click", "target": "sdk-entry", "declined_privacy": False,
        }},
    )

    result = engine.run(ctx)
    event_meta = [item.get("meta", {}) for item in result.evidence_files]
    completed = [item for item in event_meta if item.get("event_type") == "external_document_read_complete"]

    assert client.scrolls == 22
    assert completed and completed[-1].get("target") == "服务协议"
    assert completed[-1].get("entry_target") == "sdk-entry"
    assert completed[-1].get("observed_body_title") == "服务协议"
    assert completed[-1].get("document_kind") == "service_terms"
    assert "service_terms" in _read_document_kinds(ctx)
    assert "disclosure_list" not in _read_document_kinds(ctx)
    assert not any(item.get("event_type") == "external_document_scroll_capped" for item in event_meta)
    assert not any(action == "click" and target == "sdk-entry" for action, target in client.actions)
    assert any(item.get("event_type") == "blocked_document_reopen_prevented" for item in event_meta)


class _CrashClient:
    def __init__(self):
        self.closed = False
        self.activations = 0
        self.performed = []

    def page(self):
        return (
            ".SystemErrorDialog",
            '<hierarchy><node text="Demo App keeps stopping" resource-id="android:id/aerr_close" '
            'clickable="true" class="android.widget.Button"/></hierarchy>',
        )

    def activate(self, _package):
        self.activations += 1

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"crash")
        return True

    def perform(self, decision):
        self.performed.append(decision)

    def close(self):
        self.closed = True


def test_explorer_recovers_android_crash_dialog_instead_of_failing_the_task(tmp_path):
    client = _CrashClient()
    engine = AppiumExplorerEngine(client=client, llm=_LLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {
            "max_document_scrolls": 5, "app_crash_relaunch_limit": 2,
            "mode_limits": {"fast": {"max_pages": 12}},
        }},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.closed
    assert client.activations == 3
    assert ctx.runtime["traversal_termination"]["kind"] == "app_crash_relaunch_exhausted"
    timeline = [path.read_text(encoding="utf-8") for path in (tmp_path / "timeline").glob("*.json")]
    assert any("app_crash_recovering" in text for text in timeline)
    assert any("应用发生崩溃后已尝试恢复" in gap for gap in result.stats["coverage_gaps"])


def test_consent_document_crash_retries_the_same_clause_after_reactivation(tmp_path):
    consent = '''<hierarchy>
      <node text="请阅读《隐私政策》和《用户协议》" clickable="false"/>
      <node text="《隐私政策》" resource-id="privacy" clickable="true"/>
      <node text="《用户协议》" resource-id="terms" clickable="true"/>
      <node text="同意" resource-id="agree" clickable="true"/>
      <node text="不同意" resource-id="decline" clickable="true"/>
    </hierarchy>'''
    privacy_body = '<hierarchy><node text="隐私政策 我们如何收集和使用个人信息" class="android.webkit.WebView" scrollable="true"/></hierarchy>'

    class _ConsentCrashClient:
        def __init__(self):
            self.phase = "consent"
            self.actions = []
            self.privacy_clicks = 0
            self.last_package = "com.example.demo"

        def page(self):
            if self.phase == "launcher":
                return ".NexusLauncherActivity", '<hierarchy><node text="电话" clickable="true"/></hierarchy>'
            if self.phase == "privacy":
                return ".WebActivity", privacy_body
            return ".StartupActivity", consent

        def activate(self, _package):
            if self.phase == "launcher":
                self.phase = "consent"

        def recent_app_crash(self, _package):
            return "WebView InflateException" if self.phase == "launcher" else None

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision.get("action") == "click" and (
                "privacy" in str(decision.get("target") or "").lower()
                or "隐私" in str(decision.get("target") or "")
            ):
                self.privacy_clicks += 1
                self.phase = "launcher" if self.privacy_clicks == 1 else "privacy"

        def scroll_down(self):
            return False

        def screenshot(self, _path):
            return False

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _ConsentCrashClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "screen_ocr_enabled": False,
            "sdk_observation_dwell_seconds": 0,
            "page_settle_retries": 0,
            "initial_document_route_retry_limit": 1,
            "mode_limits": {"fast": {"max_pages": 6}},
        }},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.privacy_clicks == 2, client.actions
    events = {item.get("meta", {}).get("event_type") for item in result.evidence_files}
    assert "consent_document_crash_retry_scheduled" in events


def test_explorer_backs_out_of_custom_crash_surface_before_relaunching(tmp_path):
    parent = '''<hierarchy>
      <node text="头像" resource-id="avatar" clickable="true" class="android.widget.ImageView"/>
      <node text="其它设置" resource-id="settings" clickable="true" class="android.widget.TextView"/>
    </hierarchy>'''
    crash = '''<hierarchy>
      <node text="An unexpected error occurred." clickable="false"/>
      <node text="RESTART APP" resource-id="com.demo:id/customactivityoncrash_error_activity_restart_button"
            clickable="true" class="android.widget.Button"/>
      <node text="ERROR DETAILS" resource-id="com.demo:id/customactivityoncrash_error_activity_more_info_button"
            clickable="true" class="android.widget.Button"/>
    </hierarchy>'''

    class _CustomCrashClient:
        def __init__(self):
            self.phase = "parent"
            self.activations = 0
            self.actions = []

        def activate(self, _package):
            self.activations += 1

        def page(self):
            if self.phase == "crash":
                return ".CustomErrorActivity", crash
            return ".ProfileActivity", parent

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append(dict(decision))
            if decision.get("action") == "click" and decision.get("target") == "avatar":
                self.phase = "crash"
            elif decision.get("action") == "back" and self.phase == "crash":
                self.phase = "parent"

        def close(self):
            pass

    class _CrashPathLLM:
        def __init__(self):
            self.seen_activities = []

        def choose_action(self, page, *_args):
            self.seen_activities.append(page["activity"])
            if page["activity"] == ".ProfileActivity" and "avatar" not in page.get("visited_targets", []):
                return {"action": "click", "target": "avatar", "reason": "触发头像业务"}
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _CustomCrashClient()
    llm = _CrashPathLLM()
    engine = AppiumExplorerEngine(client=client, llm=llm)
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "mode_limits": {"fast": {"max_pages": 5}},
        }},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.activations == 1
    assert any(item.get("action") == "back" for item in client.actions)
    assert not any("restart_button" in str(item.get("target") or "") for item in client.actions)
    assert ".CustomErrorActivity" not in llm.seen_activities
    assert "avatar" in (ctx.runtime.get("crash_skip_targets") or set())
    event_types = {
        item.get("meta", {}).get("event_type") for item in result.evidence_files
    }
    assert "app_crash_back_recovered" in event_types


def test_explorer_relaunches_after_webview_inflate_crash_and_skips_that_route(tmp_path):
    root = '''<hierarchy>
      <node text="客服" resource-id="web-entry" clickable="true" class="android.widget.Button"/>
      <node text="设置" resource-id="settings" clickable="true" class="android.widget.Button"/>
    </hierarchy>'''
    recovered = '<hierarchy><node text="设置" resource-id="settings" clickable="true"/><node text="关于" clickable="true"/></hierarchy>'

    class _WebViewCrashClient:
        def __init__(self):
            self.phase = "root"
            self.activations = 0

        def page(self):
            if self.phase == "crash":
                return (
                    "com.android.launcher.NexusLauncherActivity",
                    '<hierarchy><node text="Home" clickable="false"/></hierarchy>',
                )
            return (".SettingsActivity", recovered) if self.phase == "recovered" else (".MainActivity", root)

        def activate(self, _package):
            self.activations += 1
            if self.phase == "crash":
                self.phase = "recovered"

        def recent_app_crash(self, _package):
            return (
                "应用崩溃日志：E/AndroidRuntime: FATAL EXCEPTION: main | "
                "java.lang.RuntimeException: Unable to start activity ComponentInfo{"
                "com.example.travel/com.example.travel.kt.WebViewKT}: "
                "android.view.InflateException: Binary XML file line #32"
            )

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            if decision["action"] == "click" and decision.get("target") == "web-entry":
                self.phase = "crash"

        def close(self):
            pass

    class _LLM:
        def choose_action(self, page, _visited):
            if page["activity"] == ".MainActivity":
                return {"action": "click", "target": "web-entry", "reason": "open webview"}
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _WebViewCrashClient()
    engine = AppiumExplorerEngine(client=client, llm=_LLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.travel", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {"mode_limits": {"fast": {"max_pages": 6}}}},
        data_dir=tmp_path,
    )

    engine.run(ctx)

    assert client.activations == 2
    assert ctx.runtime.get("skip_in_app_webview") is True
    assert "web-entry" in (ctx.runtime.get("crash_skip_targets") or set())
    timeline = [path.read_text(encoding="utf-8") for path in (tmp_path / "timeline").glob("*.json")]
    assert any("app_crash_recovered" in text for text in timeline)
    assert ctx.runtime.get("traversal_termination", {}).get("kind") != "app_crash_relaunch_exhausted"


def test_explorer_recovers_one_non_crash_launcher_exit_and_continues(tmp_path):
    """A benign app background/exit must not discard the rest of an audit."""
    root = '<hierarchy><node text="继续" resource-id="continue" clickable="true" class="android.widget.Button"/></hierarchy>'
    recovered = '<hierarchy><node text="首页" resource-id="home" clickable="false" class="android.widget.TextView"/></hierarchy>'

    class _LauncherRecoveryClient:
        def __init__(self):
            self.phase = "root"
            self.activations = 0

        def page(self):
            if self.phase == "launcher":
                return "com.android.launcher.NexusLauncherActivity", '<hierarchy><node text="Home" resource-id="home" clickable="false" class="android.widget.TextView"/></hierarchy>'
            return (".RecoveredActivity", recovered) if self.phase == "recovered" else (".MainActivity", root)

        def activate(self, _package):
            self.activations += 1
            if self.phase == "launcher":
                self.phase = "recovered"

        def recent_app_crash(self, _package):
            return None

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            if decision["action"] == "click":
                self.phase = "launcher"

        def close(self):
            pass

    class _LLM:
        def choose_action(self, page, _visited):
            return {"action": "click", "target": "continue", "reason": "exercise path"} if page["activity"] == ".MainActivity" else {"action": "stop", "target": "", "reason": "no further route"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _LauncherRecoveryClient()
    engine = AppiumExplorerEngine(client=client, llm=_LLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {"mode_limits": {"fast": {"max_pages": 5}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.activations == 2
    assert result.stats["pages_covered"] == 2
    timeline = list((tmp_path / "timeline").glob("*.json"))
    assert any('"event_type": "app_foreground_recovered"' in path.read_text(encoding="utf-8") for path in timeline)


def test_explorer_relaunches_after_repeated_non_crash_launcher_exits(tmp_path):
    """Going home more than once must relaunch, not fail the audit."""
    root = (
        '<hierarchy>'
        '<node text="继续A" resource-id="continue-a" clickable="true" class="android.widget.Button"/>'
        '<node text="继续B" resource-id="continue-b" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>'
    )
    launcher = '<hierarchy><node text="Home" resource-id="home" clickable="false" class="android.widget.TextView"/></hierarchy>'

    class _RepeatedLauncherClient:
        def __init__(self):
            self.phase = "root"
            self.activations = 0

        def page(self):
            if self.phase == "launcher":
                return "com.android.launcher.NexusLauncherActivity", launcher
            return ".MainActivity", root

        def activate(self, _package):
            self.activations += 1
            if self.phase == "launcher":
                self.phase = "root"

        def recent_app_crash(self, _package):
            return None

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            if decision["action"] == "click":
                self.phase = "launcher"

        def close(self):
            pass

    class _LLM:
        def choose_action(self, page, visited):
            if page["activity"] != ".MainActivity" or client.activations >= 3:
                return {"action": "stop", "target": "", "reason": "no further route"}
            for target in ("continue-a", "continue-b"):
                if target not in visited:
                    return {"action": "click", "target": target, "reason": "exercise path"}
            return {"action": "stop", "target": "", "reason": "no further route"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _RepeatedLauncherClient()
    engine = AppiumExplorerEngine(client=client, llm=_LLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {"mode_limits": {"fast": {"max_pages": 8}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.activations == 3
    assert result.stats["pages_covered"] >= 1
    timeline = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "timeline").glob("*.json"))
    assert '"event_type": "app_left_foreground"' not in timeline
    assert timeline.count('"event_type": "app_foreground_recovered"') == 2


def test_explorer_ends_cleanly_when_launcher_relaunches_are_exhausted(tmp_path):
    root = (
        '<hierarchy>'
        '<node text="继续A" resource-id="continue-a" clickable="true" class="android.widget.Button"/>'
        '<node text="继续B" resource-id="continue-b" clickable="true" class="android.widget.Button"/>'
        '<node text="继续C" resource-id="continue-c" clickable="true" class="android.widget.Button"/>'
        '</hierarchy>'
    )
    launcher = '<hierarchy><node text="Home" resource-id="home" clickable="false" class="android.widget.TextView"/></hierarchy>'

    class _AlwaysHomeClient:
        def __init__(self):
            self.phase = "root"
            self.activations = 0

        def page(self):
            if self.phase == "launcher":
                return "com.android.launcher.NexusLauncherActivity", launcher
            return ".MainActivity", root

        def activate(self, _package):
            self.activations += 1
            if self.phase == "launcher":
                self.phase = "root"

        def recent_app_crash(self, _package):
            return None

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            if decision["action"] == "click":
                self.phase = "launcher"

        def close(self):
            pass

    class _AlwaysClickLLM:
        def choose_action(self, page, visited):
            if page["activity"] != ".MainActivity":
                return {"action": "stop", "target": "", "reason": "done"}
            for target in ("continue-a", "continue-b", "continue-c"):
                if target not in visited:
                    return {"action": "click", "target": target, "reason": "keep going"}
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    engine = AppiumExplorerEngine(client=_AlwaysHomeClient(), llm=_AlwaysClickLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={
            "appium": {"page_wait_seconds": 0},
            "detection": {"launcher_relaunch_limit": 1, "mode_limits": {"fast": {"max_pages": 8}}},
        },
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert ctx.runtime["traversal_termination"]["kind"] == "safe_frontier_exhausted"
    timeline = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "timeline").glob("*.json"))
    assert "app_left_foreground_relaunch_exhausted" in timeline
    assert '"event_type": "app_left_foreground"' not in timeline
    assert result.findings is not None


def test_empty_negative_button_is_not_treated_as_consent():
    elements = [
        {"text": "请阅读《服务协议》", "content_desc": "", "resource_id": "hint", "clickable": False, "class_name": "android.widget.TextView"},
        {"text": "", "content_desc": "", "resource_id": "com.demo:id/btn_negative", "clickable": True, "class_name": "android.widget.Button"},
        {"text": "同意", "content_desc": "", "resource_id": "com.demo:id/btn_positive", "clickable": True, "class_name": "android.widget.Button"},
    ]
    assert _explicit_consent_target(elements) == "com.demo:id/btn_positive"
    assert _target_has_decline_semantics("com.demo:id/btn_negative", elements)


def test_solo_unlabeled_negative_button_is_never_consent():
    """Decline-id without Agree text must not be treated as first-run consent."""
    elements = [
        {"text": "请阅读《隐私政策》", "content_desc": "", "resource_id": "hint", "clickable": False, "class_name": "android.widget.TextView"},
        {"text": "", "content_desc": "", "resource_id": "com.demo:id/btn_negative", "clickable": True, "class_name": "android.widget.Button"},
    ]
    assert _explicit_consent_target(elements) is None
    assert _target_has_decline_semantics("com.demo:id/btn_negative", elements)


def test_positive_id_beats_inverted_negative_when_both_say_agree():
    elements = [
        {"text": "同意", "content_desc": "", "resource_id": "com.demo:id/btn_positive", "clickable": True, "class_name": "android.widget.Button"},
        {"text": "同意", "content_desc": "", "resource_id": "com.demo:id/btn_negative", "clickable": True, "class_name": "android.widget.Button"},
    ]
    assert _explicit_consent_target(elements) == "com.demo:id/btn_positive"


def test_policy_paragraph_mentioning_refuse_is_not_a_decline_button():
    page = parse_page(
        ".WelcomeActivity",
        '''<hierarchy>
          <node text="请阅读并同意《服务协议》和《隐私政策》。若您拒绝，将无法使用本服务。"
                resource-id="com.demo:id/tv_zhengce_content" clickable="true"
                class="android.widget.TextView"/>
          <node text="同意" resource-id="com.demo:id/btn_agree" clickable="true" class="android.widget.Button"/>
          <node text="退出" resource-id="com.demo:id/btn_exit" clickable="true" class="android.widget.Button"/>
        </hierarchy>''',
    )
    assert not _target_has_decline_semantics("com.demo:id/tv_zhengce_content", page.elements)
    assert _target_has_decline_semantics("退出", page.elements)
    assert not _is_privacy_dialog_decline("com.demo:id/tv_zhengce_content", " ".join(
        str(item.get("text") or "") for item in page.elements
    ), page.elements)
    assert _is_privacy_dialog_decline("退出", " ".join(
        str(item.get("text") or "") for item in page.elements
    ), page.elements)
    policy_node = next(item for item in page.elements if "tv_zhengce_content" in str(item.get("resource_id") or ""))
    assert not _is_consent_or_decline_control(policy_node)
    assert _is_consent_dialog(page.elements)
    assert _document_key(page.activity, page.elements, PageState()) is None


def test_welcome_activity_is_not_scrolled_as_a_terms_document():
    page = parse_page(
        ".WelcomeActivity",
        '''<hierarchy>
          <node text="欢迎使用。服务协议与隐私政策要点如下……" clickable="false"/>
          <node text="同意" clickable="true" class="android.widget.Button"/>
        </hierarchy>''',
    )
    assert _document_key(page.activity, page.elements, PageState()) is None
    assert _is_consent_dialog(page.elements)


def test_welcome_webview_policy_body_is_still_a_document():
    page = parse_page(
        ".WelcomeActivity",
        '''<hierarchy>
          <node text="隐私政策正文……" clickable="false" class="android.webkit.WebView" scrollable="true"/>
        </hierarchy>''',
    )
    assert _document_key(page.activity, page.elements, PageState()) is not None


def test_settings_confirm_is_not_treated_as_first_run_consent_dialog():
    page = parse_page(
        ".SettingsActivity",
        '''<hierarchy>
          <node text="隐私政策" clickable="true" class="android.widget.TextView"/>
          <node text="确认" clickable="true" class="android.widget.TextView"/>
        </hierarchy>''',
    )
    assert not _is_consent_dialog(page.elements)


def test_privacy_agreement_row_is_not_a_first_run_consent_button():
    assert _resource_id_matches_hint("com.demo:id/btn_agree", "btn_agree")
    assert _resource_id_matches_hint("com.demo:id/privacy_agree", "privacy_agree")
    assert not _resource_id_matches_hint("com.app:id/cl_setting_privacy_agreement", "privacy_agree")
    page = parse_page(
        ".SettingActivity",
        '''<hierarchy>
          <node text="" resource-id="com.app:id/cl_setting_privacy_agreement" clickable="true"
                class="android.widget.LinearLayout"/>
          <node text="隐私协议" clickable="false"/>
          <node text="个人信息收集清单" clickable="true"/>
          <node text="注销账号" clickable="true"/>
          <node text="关于我们" clickable="true"/>
        </hierarchy>''',
    )
    assert _explicit_consent_target(page.elements) is None
    assert not _is_consent_dialog(page.elements)
    assert not _is_consent_click("com.app:id/cl_setting_privacy_agreement", page.elements)
    assert _target_is_hub_reentry("更多设置", [
        {"text": "更多设置", "resource_id": "ll_item_more_settings", "clickable": True, "content_desc": "", "target": "ll_item_more_settings"},
    ])


def test_webview_policy_body_is_not_a_settings_hub_or_consent_dialog():
    page = parse_page(
        ".WebviewDetailActivity",
        '''<hierarchy>
          <node text="隐私政策 我们会收集个人信息 关于我们 头像昵称仅作示例"
                clickable="false" class="android.webkit.WebView" scrollable="true"/>
          <node text="返回" resource-id="ll_back_layer" clickable="true"/>
        </hierarchy>''',
    )
    assert not _looks_like_settings_or_profile(page.activity, page.elements)
    assert not _is_consent_dialog(page.elements)
    assert _document_key(page.activity, page.elements, PageState()) is not None


def test_settings_hub_lets_llm_open_delete_entry_after_consent(tmp_path):
    settings = (
        '<hierarchy>'
        '<node text="隐私政策" clickable="true"/>'
        '<node text="个人信息收集清单" clickable="true"/>'
        '<node text="注销账号" resource-id="com.demo:id/tv_cancel_account" clickable="true"/>'
        '</hierarchy>'
    )

    class _Client:
        def __init__(self):
            self.actions = []

        def page(self):
            return (".SettingActivity", settings)

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return False

        def scroll_down(self):
            return False

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))

        def close(self):
            pass

    class _DeleteLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "com.demo:id/tv_cancel_account", "reason": "6.1 注销入口"}

        def fallback_action(self, *_args):
            return {"action": "click", "target": "个人信息收集清单", "reason": "本地启发式兜底"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_DeleteLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
            "mode_limits": {"deep": {"max_pages": 3}},
        }},
        data_dir=tmp_path,
    )
    ctx.runtime["consent_dialog_seen"] = True
    ctx.runtime["consent_accepted"] = True
    ctx.runtime["privacy_hub_visited"] = True
    # Hub doc reading wins over LLM delete until privacy/list rows are marked read.
    ctx.runtime["read_document_kinds"] = {"privacy_policy", "disclosure_list"}
    ctx.runtime["read_document_titles"] = {"隐私政策", "个人信息收集清单"}
    engine.run(ctx)
    clicks = [target for action, target in client.actions if action == "click"]
    assert clicks
    assert clicks[0] == "com.demo:id/tv_cancel_account"


def test_splash_photos_is_not_a_deterministic_permission_probe(tmp_path):
    splash = (
        '<hierarchy>'
        '<node text="Photos" clickable="true" class="android.widget.TextView"/>'
        '<node text="正在启动" clickable="false"/>'
        '</hierarchy>'
    )

    class _Client:
        def __init__(self):
            self.actions = []

        def page(self):
            return (".SplashActivity", splash)

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return False

        def scroll_down(self):
            return False

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))

        def close(self):
            pass

    class _WaitLLM:
        def choose_action(self, *_args):
            return {"action": "wait", "target": "", "reason": "闪屏加载"}

        def fallback_action(self, *_args):
            return {"action": "wait", "target": "", "reason": "闪屏加载"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_WaitLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
            "mode_limits": {"deep": {"max_pages": 2}},
        }},
        data_dir=tmp_path,
    )
    engine.run(ctx)
    assert ("click", "Photos") not in client.actions


def test_logout_and_follow_are_not_first_run_decline_buttons():
    assert not _is_short_decline_label("退出登录")
    assert not _is_short_decline_label("取消关注")
    assert _is_short_decline_label("退出")
    assert _is_short_decline_label("拒绝并退出")
    settings = parse_page(
        ".SettingsActivity",
        '''<hierarchy>
          <node text="隐私政策" clickable="true" class="android.widget.TextView"/>
          <node text="退出登录" resource-id="account_logout" clickable="true" class="android.widget.TextView"/>
        </hierarchy>''',
    )
    page_text = " ".join(str(item.get("text") or "") for item in settings.elements)
    assert not _is_privacy_dialog_decline("退出登录", page_text, settings.elements)
    assert _is_authenticated_logout_target("退出登录", settings.elements)


def test_policy_caption_with_agree_word_is_not_a_consent_click():
    page = parse_page(
        ".WelcomeActivity",
        '''<hierarchy>
          <node text="请阅读并同意《服务协议》和《隐私政策》。若您拒绝，将无法使用本服务。"
                resource-id="com.demo:id/tv_zhengce_content" clickable="true"
                class="android.widget.TextView"/>
          <node text="同意" resource-id="com.demo:id/btn_agree" clickable="true" class="android.widget.Button"/>
          <node text="退出" resource-id="com.demo:id/btn_exit" clickable="true" class="android.widget.Button"/>
        </hierarchy>''',
    )
    caption = "请阅读并同意《服务协议》和《隐私政策》。若您拒绝，将无法使用本服务。"
    assert not _is_consent_click(caption, page.elements)
    assert _is_consent_click("同意", page.elements)
    assert _is_consent_click("com.demo:id/btn_agree", page.elements)


def test_launcher_after_policy_tap_is_not_a_read_document():
    assert not _inline_document_open_succeeded(
        ".kt.SplashKT", ".NexusLauncherActivity",
        [{"text": "Phone", "clickable": True, "class_name": "android.widget.TextView"}],
    )
    assert _inline_document_open_succeeded(
        ".kt.SplashKT", "com.google.android.apps.chrome.Main",
        [{"text": "服务协议正文……" * 2, "clickable": False, "class_name": "android.webkit.WebView", "scrollable": True}],
    )


def test_exit_app_ok_button_is_not_a_deep_probe_target():
    elements = [
        {"text": "是否退出应用", "content_desc": "", "resource_id": "msg", "clickable": False},
        {"text": "取消", "content_desc": "", "resource_id": "com.demo:id/btnCancel", "clickable": True, "class_name": "android.widget.Button"},
        {"text": "确定", "content_desc": "", "resource_id": "com.demo:id/btnOK", "clickable": True, "class_name": "android.widget.Button"},
    ]
    assert _is_app_exit_confirmation("com.demo:id/btnOK", elements)
    assert not _is_safe_deep_probe_target("com.demo:id/btnOK", elements)


def test_explorer_treats_launcher_after_intentional_back_as_normal_completion(tmp_path):
    """Returning from the last app screen must not be reported as a crash."""
    root = '<hierarchy><node text="打开设置" resource-id="open-settings" clickable="true" class="android.widget.Button"/></hierarchy>'
    child = '<hierarchy><node text="设置" resource-id="settings" clickable="false" class="android.widget.TextView"/></hierarchy>'
    launcher = '<hierarchy><node text="Home" resource-id="home" clickable="false" class="android.widget.TextView"/></hierarchy>'

    class _ExpectedExitClient:
        def __init__(self):
            self.phase = "root"

        def page(self):
            if self.phase == "root":
                return (".MainActivity", root)
            return (".DetailActivity", child) if self.phase == "child" else (".NexusLauncherActivity", launcher)

        def activate(self, _package):
            pass

        def recent_app_crash(self, _package):
            return None

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            if decision["action"] == "click" and decision.get("target") == "open-settings":
                self.phase = "child"
            elif decision["action"] == "back":
                self.phase = "launcher"

        def close(self):
            pass

    class _BackLLM:
        def choose_action(self, page, _visited):
            if page["activity"] == ".MainActivity":
                return {"action": "click", "target": "open-settings", "reason": "进入设置页检查"}
            return {"action": "back", "target": "", "reason": "已完成当前设置页检查"}

        def fallback_action(self, *_args):
            return {"action": "back", "target": "", "reason": "返回应用根路径"}

    engine = AppiumExplorerEngine(client=_ExpectedExitClient(), llm=_BackLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {"mode_limits": {"fast": {"max_pages": 5}}}},
        data_dir=tmp_path,
    )

    engine.run(ctx)

    assert ctx.runtime["traversal_termination"]["kind"] == "safe_frontier_exhausted"
    timeline = list((tmp_path / "timeline").glob("*.json"))
    assert any('"event_type": "app_exit_after_back_expected"' in path.read_text(encoding="utf-8") for path in timeline)
    assert not any('"event_type": "app_left_foreground"' in path.read_text(encoding="utf-8") for path in timeline)


def test_visible_consent_text_overrides_misleading_positive_negative_resource_ids():
    elements = [
        {"text": "不同意", "content_desc": "", "resource_id": "com.demo:id/btn_positive", "clickable": True, "class_name": "android.widget.Button"},
        {"text": "同意", "content_desc": "", "resource_id": "com.demo:id/btn_negative", "clickable": True, "class_name": "android.widget.Button"},
    ]

    assert _target_has_decline_semantics("com.demo:id/btn_positive", elements)
    assert _explicit_consent_target(elements) == "com.demo:id/btn_negative"


def test_explorer_discovers_privacy_service_paths_but_blocks_final_deletion():
    elements = [
        {"text": "注销账号", "content_desc": "", "resource_id": "delete-entry", "clickable": True},
        {"text": "投诉与举报", "content_desc": "", "resource_id": "complaint-entry", "clickable": True},
        {"text": "确认注销", "content_desc": "", "resource_id": "delete-confirm", "clickable": True},
    ]
    observed = _privacy_path_observations(elements, "注销账号需线下人工审核")

    assert observed["delete_targets"] == ["delete-entry"]
    assert observed["complaint_targets"] == ["complaint-entry"]
    assert observed["withdraw_targets"] == []
    assert observed["personalization_targets"] == []
    assert observed["delete_obstacle"] is True
    assert _is_destructive_confirmation("delete-confirm", elements)


def test_privacy_path_observations_find_withdraw_consent_entry():
    elements = [
        {"text": "授权管理", "content_desc": "", "resource_id": "auth-manage", "clickable": True},
        {"text": "撤回同意", "content_desc": "", "resource_id": "withdraw-entry", "clickable": True},
    ]
    observed = _privacy_path_observations(elements, "账号与隐私")
    assert observed["withdraw_targets"] == ["auth-manage", "withdraw-entry"]


def test_visible_label_beats_resource_id_when_inferring_document_kind():
    assert _infer_document_kind("com.example.reader:id/oi_private", "服务协议") == "service_terms"
    assert _infer_document_kind("com.example.reader:id/oi_private", "隐私政策") == "privacy_policy"
    assert _document_body_kind_from_text("《用户协议》\n欢迎使用本应用") == "user_agreement"
    assert _document_body_kind_from_text("第三方SDK目录\n极光推送收集") == "disclosure_list"


def test_customer_service_entry_and_voice_probe_are_generic():
    main = parse_page(
        ".MainTabActivity",
        '''<hierarchy>
          <node text="首页" clickable="true"/>
          <node text="客服" resource-id="tab_cs" clickable="true"/>
          <node text="我的" clickable="true"/>
        </hierarchy>''',
    )
    assert _complaint_or_cs_entry_target(main.elements) == "tab_cs"
    chat = parse_page(
        ".WebViewKT",
        '''<hierarchy>
          <node text="客服服务" clickable="false"/>
          <node text="您好！欢迎咨询高速出行管家" clickable="false"/>
          <node text="您好，请输入您要咨询的内容~" clickable="false"/>
          <node text="自助工单" clickable="true"/>
          <node resource-id="mic" bounds="[400,1800][680,2080]" clickable="true"/>
        </hierarchy>''',
    )
    page_text = "客服服务 欢迎咨询 请输入 自助工单"
    assert _is_customer_service_surface(chat.activity, page_text)
    assert _customer_service_sensitive_control(chat.activity, chat.elements, page_text)


def test_customer_service_prefers_album_camera_and_attach_not_only_microphone():
    page = parse_page(
        ".activity.WebActivity",
        '''<hierarchy>
          <node text="客服服务" clickable="false" bounds="[0,80][1080,200]"/>
          <node text="请输入您要咨询的内容" clickable="false" bounds="[120,2000][700,2200]"/>
          <node text="相册" resource-id="btn_album" clickable="true" bounds="[200,2100][360,2280]"/>
          <node text="+" resource-id="btn_plus" clickable="true" bounds="[900,2100][1040,2280]"/>
          <node text="" resource-id="mic" clickable="true" bounds="[470,2100][620,2320]"/>
        </hierarchy>''',
    )
    text = "客服服务 请输入您要咨询的内容"
    # Album / camera family outranks an unlabeled mic.
    assert _customer_service_sensitive_control(
        ".activity.WebActivity", page.elements, text,
    ) == "btn_album"
    # After album is excluded, attach (+) still beats mic for storage/camera chooser.
    assert _customer_service_sensitive_control(
        ".activity.WebActivity", page.elements, text, exclude={"btn_album"},
    ) == "btn_plus"
    assert _customer_service_sensitive_control(
        ".activity.WebActivity", page.elements, text, exclude={"btn_album", "btn_plus"},
    ) in {"mic", "bounds:[470,2100][620,2320]"}


def test_customer_service_webview_is_not_misclassified_as_a_long_document():
    chat = parse_page(
        ".activity.WebActivity",
        '''<hierarchy>
          <node text="客服服务" clickable="false" class="android.widget.TextView"/>
          <node text="请输入您要咨询的内容" clickable="false" class="android.widget.TextView"/>
          <node text="相册" resource-id="btn_album" clickable="true" class="android.widget.Button"/>
          <node text="+" resource-id="btn_plus" clickable="true" class="android.widget.Button"/>
        </hierarchy>''',
    )

    assert _document_key(
        chat.activity,
        chat.elements,
        PageState(),
        screen_text="客服服务 请输入您要咨询的内容",
    ) is None


def test_deep_customer_service_exhausts_safe_media_buttons_before_backtracking(tmp_path):
    chat = '''<hierarchy>
      <node text="客服服务" clickable="false" class="android.widget.TextView"/>
      <node text="请输入您要咨询的内容" clickable="false" class="android.widget.TextView"/>
      <node text="相册" resource-id="btn_album" clickable="true" class="android.widget.Button"/>
      <node text="+" resource-id="btn_plus" clickable="true" class="android.widget.Button"/>
      <node text="语音" resource-id="btn_voice" clickable="true" class="android.widget.Button"/>
    </hierarchy>'''

    class _NoEffectCustomerClient:
        def __init__(self):
            self.actions = []

        def page(self):
            return ".activity.WebActivity", chat

        def activate(self, _package):
            pass

        def screenshot(self, _path):
            return False

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))

        def close(self):
            pass

    class _BackImmediatelyLLM:
        def choose_action(self, *_args):
            return {"action": "back", "target": "", "reason": "立即离开客服"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "没有其它入口"}

    client = _NoEffectCustomerClient()
    engine = AppiumExplorerEngine(client=client, llm=_BackImmediatelyLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"detection": {
            "screen_ocr_enabled": False,
            "sdk_observation_dwell_seconds": 0,
            "page_settle_retries": 0,
            "mode_limits": {"deep": {"max_pages": 8}},
        }},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    clicked = [target for action, target in client.actions if action == "click"]
    assert clicked[:3] == ["btn_album", "btn_plus", "btn_voice"]
    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]
    assert "deep_probe_no_effect" in event_types
    assert "customer_service_surface_exhausted" in event_types


def test_customer_service_tries_right_attach_recipe_after_centre_mic_recipe():
    text = "Customer service Please enter your question"
    first = _customer_service_sensitive_control(".activity.WebActivity", [], text)
    assert first == "relative:0.50,0.88"
    second = _customer_service_sensitive_control(
        ".activity.WebActivity", [], text, exclude={first},
    )
    assert second == "relative:0.88,0.88"
    third = _customer_service_sensitive_control(
        ".activity.WebActivity", [], text, exclude={first, second},
    )
    assert third == "relative:0.12,0.88"


def test_customer_service_without_composer_does_not_spray_relative_recipes():
    """CS title alone is not enough for blind bottom taps."""
    assert _customer_service_sensitive_control(
        ".activity.WebActivity", [], "客服服务 您好",
    ) is None


def test_mark_required_document_follows_body_when_click_label_mismatches(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=tmp_path,
    )
    kind = _mark_required_document_read(
        ctx, "《第三方sdk目录》", page_text="《用户协议》\n本协议是用户与平台之间的约定",
    )
    assert kind == "user_agreement"
    assert "user_agreement" in _read_document_kinds(ctx)
    assert "disclosure_list" not in _read_document_kinds(ctx)
    assert ctx.runtime.get("document_kind_mismatches")


def test_external_document_completion_keeps_kind_seen_on_first_viewport(tmp_path):
    """A footer-only last viewport must not erase the heading seen at the top."""
    app_page = (
        '<hierarchy><node text="服务协议" resource-id="terms-entry" '
        'clickable="true" class="android.widget.TextView"/></hierarchy>'
    )
    document_top = (
        '<hierarchy><node text="《用户协议》 本协议是用户与平台之间的约定，'
        '并说明账号服务、使用条件和双方权利义务。" clickable="false" '
        'class="android.widget.TextView"/></hierarchy>'
    )
    document_bottom = (
        '<hierarchy><node text="最后更新日期以及联系方式等正文尾部内容。" '
        'clickable="false" class="android.widget.TextView"/></hierarchy>'
    )

    class _MislabeledDocumentClient:
        def __init__(self):
            self.phase = "app"
            self.scrolls = 0

        def page(self):
            if self.phase == "top":
                return "org.chromium.chrome.browser.ChromeTabbedActivity", document_top
            if self.phase == "bottom":
                return "org.chromium.chrome.browser.ChromeTabbedActivity", document_bottom
            return ".SettingsActivity", app_page

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def scroll_down(self):
            if self.phase not in {"top", "bottom"}:
                return False
            self.scrolls += 1
            if self.phase == "top":
                self.phase = "bottom"
                return True
            return False

        def perform(self, decision):
            if decision["action"] == "click":
                self.phase = "top"
            elif decision["action"] == "back":
                self.phase = "app"

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _MislabeledDocumentClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "external_document_wait_retries": 0,
            "sdk_observation_dwell_seconds": 0,
            "page_settle_retries": 0,
            "mode_limits": {"fast": {"max_pages": 3}},
        }},
        data_dir=tmp_path,
        runtime={"consent_accepted": True, "sdk_observation_dwell_done": True},
    )

    engine.run(ctx)

    assert "user_agreement" in _read_document_kinds(ctx)
    assert "用户协议" in _read_document_titles(ctx)
    assert "service_terms" not in _read_document_kinds(ctx)


def test_stale_mismatched_document_body_is_not_scrolled_twice(tmp_path):
    document_top = (
        '<hierarchy><node text="《用户协议》 本协议是用户与平台之间的约定，'
        '并说明账号服务、使用条件和双方权利义务。" clickable="false" '
        'class="android.widget.TextView"/></hierarchy>'
    )
    document_bottom = (
        '<hierarchy><node text="最后更新日期以及联系方式等正文尾部内容。" '
        'clickable="false" class="android.widget.TextView"/></hierarchy>'
    )

    class _AliasDocumentClient:
        def __init__(self):
            self.phase = "app"
            self.route = 0
            self.scrolls = 0

        def page(self):
            if self.phase == "top":
                return "org.chromium.chrome.browser.ChromeTabbedActivity", document_top
            if self.phase == "bottom":
                return "org.chromium.chrome.browser.ChromeTabbedActivity", document_bottom
            target = "terms-entry-one" if self.route == 0 else "terms-entry-two"
            return ".SettingsActivity", (
                f'<hierarchy><node text="服务协议" resource-id="{target}" '
                'clickable="true" class="android.widget.TextView"/></hierarchy>'
            )

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def scroll_down(self):
            if self.phase not in {"top", "bottom"}:
                return False
            self.scrolls += 1
            if self.phase == "top":
                self.phase = "bottom"
                return True
            return False

        def perform(self, decision):
            if decision["action"] == "click":
                self.phase = "top"
            elif decision["action"] == "back":
                self.phase = "app"
                self.route += 1

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _AliasDocumentClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "external_document_wait_retries": 0,
            "external_document_identity_wait_retries": 0,
            "sdk_observation_dwell_seconds": 0,
            "page_settle_retries": 0,
            "mode_limits": {"fast": {"max_pages": 6}},
        }},
        data_dir=tmp_path,
        runtime={"consent_accepted": True, "sdk_observation_dwell_done": True},
    )

    result = engine.run(ctx)

    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]
    assert client.scrolls == 2
    assert "stale_external_document_body_rejected" in event_types


def test_pause_checkpoint_restores_document_ledger_findings_and_evidence(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=tmp_path,
        runtime={
            "read_document_kinds": {"privacy_policy", "user_agreement"},
            "read_document_titles": {"隐私政策", "用户协议"},
            "completed_document_fingerprints": {"body-hash"},
            "policy_text_fragments_by_kind": {"privacy_policy": ["隐私政策正文"]},
        },
    )
    state = PageState(
        covered_pages={"page-a"}, completed_documents={".WebView:document:隐私政策"},
    )
    root = parse_page(
        ".HomeActivity",
        '<hierarchy><node text="我的" resource-id="profile" clickable="true"/></hierarchy>',
    )
    profile = parse_page(
        ".ProfileActivity",
        '<hierarchy><node text="个人信息" resource-id="personal" clickable="true"/></hierarchy>',
    )
    state.is_new(root)
    state.commit_target(root, "profile")
    state.is_new(profile)
    prior_findings = [
        explorer_module.Finding(kind="consent_checkbox_prechecked", category=3, payload={"page": "splash"}),
    ]
    prior_evidence = [{"type": "timeline", "path": "old.json", "meta": {"event_type": "old"}}]
    explorer_module._save_traversal_checkpoint(ctx, state, prior_findings, prior_evidence)

    resumed = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=tmp_path,
        runtime={"resume_requested": True},
    )
    resumed_state = PageState()
    findings, evidence = explorer_module._restore_traversal_checkpoint(resumed, resumed_state)

    assert _read_document_kinds(resumed) == {"privacy_policy", "user_agreement"}
    assert _read_document_titles(resumed) == {"隐私政策", "用户协议"}
    assert resumed.runtime["completed_document_fingerprints"] == {"body-hash"}
    assert resumed_state.covered_pages == state.covered_pages
    assert resumed_state.completed_documents == {".WebView:document:隐私政策"}
    assert [edge.target for edge in resumed_state.navigation_replay.replay_edges()] == ["profile"]
    assert [item.kind for item in findings] == ["consent_checkbox_prechecked"]
    assert evidence == prior_evidence


def test_page_role_distinguishes_splash_hub_login_and_permission():
    splash = parse_page(
        ".SplashActivity",
        '<hierarchy><node text="启动中" clickable="false"/></hierarchy>',
    )
    assert _page_role(splash.activity, splash.elements, PageState()) == "splash_or_gate"

    hub = parse_page(
        ".SettingActivity",
        '''<hierarchy>
          <node text="隐私政策" clickable="true"/>
          <node text="注销账号" clickable="true"/>
          <node text="通知设置" clickable="true"/>
          <node text="关于" clickable="true"/>
          <node text="通用" clickable="true"/>
          <node text="缓存" clickable="true"/>
          <node text="账号与安全" clickable="true"/>
        </hierarchy>''',
    )
    assert _page_role(hub.activity, hub.elements, PageState()) == "document_hub"
    # Hub list rows are discovery only — not yet a verification surface.
    assert _privacy_path_verification_surface(hub.activity, hub.elements) is None
    assert _click_matches_privacy_path("注销账号", hub.elements, "delete")
    assert _click_matches_privacy_path("授权管理", [
        {"text": "授权管理", "resource_id": "auth", "clickable": True, "content_desc": ""},
    ], "withdraw")

    delete_page = parse_page(
        ".CancelAccountActivity",
        '''<hierarchy>
          <node text="账号注销" clickable="false"/>
          <node text="确认注销" resource-id="confirm" clickable="true"/>
        </hierarchy>''',
    )
    assert _privacy_path_verification_surface(delete_page.activity, delete_page.elements) == "delete"

    permission = parse_page(
        "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity",
        '<hierarchy><node text="允许" clickable="true"/><node text="拒绝" clickable="true"/></hierarchy>',
    )
    assert _page_role(permission.activity, permission.elements, PageState()) == "system_permission"


class _PermissionClient:
    def __init__(self):
        self.index = 0
        self.responses = []

    def page(self):
        pages = [
            (".ProfileActivity", _APP_FUNCTION),
            ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _CAMERA_PROMPT),
            (".ProfileActivity", _DENIED_FUNCTION),
        ]
        return pages[self.index]

    def activate(self, _package):
        pass

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return True

    def respond_to_permission(self, action):
        self.responses.append(action)
        self.index = 2

    def perform(self, _decision):
        self.index = 1

    def close(self):
        pass


class _StopLLM:
    def choose_action(self, page, *_args):
        page_text = " ".join(element.get("text", "") for element in page["elements"])
        if page["activity"] == ".ProfileActivity" and "暂无" not in page_text:
            return {"action": "click", "target": "upload-avatar", "reason": "test permission path"}
        return {"action": "stop", "target": "", "reason": "done"}

    def fallback_action(self, *_args):
        return {"action": "stop", "target": "", "reason": "done"}


def test_explorer_records_permission_denial_and_subsequent_function_block(tmp_path):
    client = _PermissionClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "permission_probe_action": "deny",
                            "permission_probe_post_steps": 3, "mode_limits": {"fast": {"max_pages": 6}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.responses == ["deny"]
    assert {finding.kind for finding in result.findings} == {
        "permission_purpose_not_informed", "permission_denial_blocks_function",
    }
    linked = [item for item in result.evidence_files if item["type"] == "screenshot"]
    linked_kinds = {
        kind for item in linked
        for kind in ([item["meta"].get("finding_kind")] if item["meta"].get("finding_kind") else item["meta"].get("finding_kinds", []))
    }
    assert linked_kinds == {
        "permission_purpose_not_informed", "permission_denial_blocks_function",
    }


def test_explorer_retries_original_business_action_after_permission_denial(tmp_path):
    class _RetryRequiredClient(_PermissionClient):
        def page(self):
            pages = [
                (".ProfileActivity", _APP_FUNCTION),
                ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _CAMERA_PROMPT),
                (".ProfileActivity", _APP_FUNCTION),
                (".ProfileActivity", _DENIED_FUNCTION),
            ]
            return pages[self.index]

        def respond_to_permission(self, action):
            self.responses.append(action)
            self.index = 2

        def perform(self, _decision):
            self.index = 1 if self.index == 0 else 3

    client = _RetryRequiredClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"permission_probe_action": "deny", "permission_probe_post_steps": 4,
                            "mode_limits": {"fast": {"max_pages": 7}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert any(item.kind == "permission_denial_blocks_function" for item in result.findings)
    assert any(
        item["meta"].get("event_type") == "permission_denial_business_action_retried"
        for item in result.evidence_files if item["type"] == "timeline"
    )


def test_deny_profile_completes_42_before_logout_or_delete_boundary(tmp_path):
    profile = '''<hierarchy>
      <node text="个人信息" clickable="false"/>
      <node text="头像" clickable="false"/>
      <node text="" resource-id="head_image" clickable="true"/>
      <node text="注销账号" resource-id="delete_account" clickable="true"/>
      <node text="退出登录" resource-id="logout" clickable="true"/>
    </hierarchy>'''
    chooser = '''<hierarchy>
      <node text="请选择图片来源" clickable="false"/>
      <node text="照相机" resource-id="camera" clickable="true"/>
      <node text="相册" resource-id="album" clickable="true"/>
    </hierarchy>'''
    denied = '''<hierarchy>
      <node text="需要相机权限，未授权时暂无可用的拍照功能" clickable="false"/>
      <node text="返回" resource-id="back" clickable="true"/>
    </hierarchy>'''

    class _CompetingBoundaryClient:
        def __init__(self):
            self.phase = "profile"
            self.responses = []
            self.actions = []

        def activate(self, _package):
            pass

        def page(self):
            if self.phase == "permission":
                return "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _CAMERA_PROMPT
            if self.phase == "chooser":
                return ".AvatarEditActivity", chooser
            if self.phase == "denied":
                return ".AvatarEditActivity", denied
            return ".ProfileActivity", profile

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append(dict(decision))
            target = str(decision.get("target") or "")
            if decision.get("action") == "click" and target == "head_image":
                self.phase = "chooser"
            elif decision.get("action") == "click" and target == "camera":
                self.phase = "permission"

        def respond_to_permission(self, action):
            self.responses.append(action)
            self.phase = "denied"

        def close(self):
            pass

    class _BoundarySeekingLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "delete_account", "reason": "try account boundary"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _CompetingBoundaryClient()
    engine = AppiumExplorerEngine(client=client, llm=_BoundarySeekingLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "permission_probe_action": "deny",
            "permission_probe_post_steps": 4,
            "sdk_observation_dwell_seconds": 0,
            "mode_limits": {"deep": {"max_pages": 8}},
        }},
        data_dir=tmp_path,
        runtime={
            "consent_accepted": True,
            "consent_timestamp_ms": 1,
            "sdk_observation_dwell_done": True,
        },
    )

    result = engine.run(ctx)

    clicked = [str(item.get("target") or "") for item in client.actions if item.get("action") == "click"]
    assert clicked[:2] == ["head_image", "camera"]
    assert "delete_account" not in clicked
    assert "logout" not in clicked
    assert client.responses == ["deny"]
    assert not any(item.kind == "permission_denial_blocks_function" for item in result.findings)
    assert ctx.runtime.get("permission_denial_probe_terminal") is True
    assert any(
        item.get("meta", {}).get("event_type") == "permission_denial_subfeature_only"
        for item in result.evidence_files
    )


def test_pending_42_probe_survives_runtime_session_recovery(tmp_path):
    class _RecoverDuringDenialClient(_PermissionClient):
        def __init__(self):
            super().__init__()
            self.phase = "business"
            self.session_failed = False
            self.recovered = False

        def page(self):
            if self.phase == "permission":
                return "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _CAMERA_PROMPT
            if self.phase == "after_deny" and not self.session_failed:
                self.session_failed = True
                raise ExplorationError("UiAutomator2 instrumentation process is not running")
            if self.phase == "blocked":
                return ".ProfileActivity", _DENIED_FUNCTION
            return ".ProfileActivity", _APP_FUNCTION

        def recover_runtime_session(self, _package, _error):
            self.recovered = True
            return True

        def perform(self, decision):
            if decision.get("action") != "click":
                return
            if self.phase == "business":
                self.phase = "permission"
            elif self.phase == "after_deny":
                self.phase = "blocked"

        def respond_to_permission(self, action):
            self.responses.append(action)
            self.phase = "after_deny"

    client = _RecoverDuringDenialClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "permission_probe_action": "deny",
            "permission_probe_post_steps": 3,
            "mode_limits": {"fast": {"max_pages": 7}},
        }},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.recovered is True
    assert client.responses == ["deny"]
    assert any(item.kind == "permission_denial_blocks_function" for item in result.findings)
    event_types = {
        item.get("meta", {}).get("event_type") for item in result.evidence_files
    }
    assert "permission_denial_probe_session_recovered" in event_types
    assert "permission_denial_business_action_retried" in event_types


def test_explorer_retries_business_trigger_by_bounds_after_a_noop_click(tmp_path):
    profile = (
        '<hierarchy>'
        '<node text="上传头像" resource-id="upload-avatar" clickable="true" '
        'class="android.widget.Button" bounds="[100,200][500,300]"/>'
        '</hierarchy>'
    )
    chooser = '<hierarchy><node text="请选择图片来源" clickable="false" class="android.widget.TextView"/></hierarchy>'

    class _StickyBusinessClient:
        def __init__(self):
            self.phase = "profile"
            self.actions = []

        def page(self):
            return ".ProfileActivity", chooser if self.phase == "chooser" else profile

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            target = str(decision.get("target") or "")
            self.actions.append((decision["action"], target))
            if decision["action"] == "click" and target.startswith("bounds:"):
                self.phase = "chooser"

        def close(self):
            pass

    class _RepeatBusinessLLM:
        def choose_action(self, page, *_args):
            if page["activity"] == ".ProfileActivity" and any(
                element.get("resource_id") == "upload-avatar" for element in page["elements"]
            ):
                return {"action": "click", "target": "upload-avatar", "reason": "触发头像上传业务核验权限"}
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _StickyBusinessClient()
    engine = AppiumExplorerEngine(client=client, llm=_RepeatBusinessLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"mode_limits": {"fast": {"max_pages": 5}}}},
        data_dir=tmp_path,
        runtime={"sdk_observation_dwell_done": True, "manual_login_verified": True},
    )

    result = engine.run(ctx)

    assert client.actions[:2] == [
        ("click", "upload-avatar"),
        ("click", "bounds:[100,200][500,300]"),
    ]
    event_types = {item.get("meta", {}).get("event_type") for item in result.evidence_files}
    assert "business_trigger_retry_without_transition" in event_types


def test_explorer_does_not_call_permission_immediate_after_a_business_action(tmp_path):
    client = _PermissionClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "permission_probe_action": "observe",
                            "permission_after_consent_window_seconds": 30,
                            "mode_limits": {"fast": {"max_pages": 3}}}},
        data_dir=tmp_path,
        runtime={"consent_timestamp_ms": int(time.time() * 1000)},
    )

    result = engine.run(ctx)

    assert not any(item.kind == "permission_requested_immediately_after_consent" for item in result.findings)


_PRIVACY_DECISION = '''<hierarchy><node text="我已阅读隐私政策" resource-id="com.demo:id/privacy_hint" clickable="false" class="android.widget.TextView"/><node text="同意" resource-id="com.demo:id/btn_negative" clickable="true" class="android.widget.Button"/></hierarchy>'''
_ENGLISH_LOCATION_PROMPT = '''<hierarchy><node text="Allow Demo to access this device's location?" resource-id="com.android.permissioncontroller:id/permission_message" clickable="false" class="android.widget.TextView"/></hierarchy>'''


class _PrivacyDecisionClient:
    def __init__(self):
        self.index = 0

    def page(self):
        pages = [
            (".SplashActivity", _PRIVACY_DECISION),
            ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _ENGLISH_LOCATION_PROMPT),
        ]
        return pages[self.index]

    def activate(self, _package):
        pass

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return True

    def scroll_down(self):
        return False

    def perform(self, _decision):
        self.index = 1

    def close(self):
        pass


class _PrivacyDecisionLLM:
    def choose_action(self, page, *_args):
        if page["activity"] == ".SplashActivity":
            # The production trace uses this resource ID, not a button label.
            return {"action": "click", "target": "com.demo:id/btn_negative", "reason": "处理隐私弹窗"}
        return {"action": "stop", "target": "", "reason": "permission observed"}

    def fallback_action(self, *_args):
        return {"action": "stop", "target": "", "reason": "done"}


def test_explorer_recognises_privacy_dialog_resource_id_before_immediate_permission(tmp_path):
    engine = AppiumExplorerEngine(client=_PrivacyDecisionClient(), llm=_PrivacyDecisionLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "permission_probe_action": "observe",
                            "permission_after_consent_window_seconds": 30,
                            "mode_limits": {"fast": {"max_pages": 3}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    finding = next(item for item in result.findings if item.kind == "permission_requested_immediately_after_consent")
    assert finding.payload["permission"] == "定位"
    assert "RULE_4_1_CONSENT" in {match.rule.rule_id for match in match_rules(load_rules(), result.findings)}
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert "privacy_consent_clicked" in event_types


def test_onboarding_transition_does_not_hide_immediate_permission_after_consent(tmp_path):
    onboarding = '''<hierarchy><node text="立即体验" resource-id="com.demo:id/ivGoTo" clickable="true" class="android.widget.Button"/></hierarchy>'''

    class _OnboardingClient(_PrivacyDecisionClient):
        def page(self):
            pages = [
                (".SplashActivity", _PRIVACY_DECISION),
                (".SplashActivity", onboarding),
                ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _ENGLISH_LOCATION_PROMPT),
            ]
            return pages[self.index]

        def perform(self, _decision):
            self.index = min(2, self.index + 1)

    class _OnboardingLLM(_PrivacyDecisionLLM):
        def choose_action(self, page, *_args):
            if page["activity"] == ".SplashActivity":
                target = "com.demo:id/btn_negative" if any(
                    "btn_negative" in item.get("resource_id", "") for item in page["elements"]
                ) else "com.demo:id/ivGoTo"
                return {"action": "click", "target": target, "reason": "同意后点击立即体验进入应用"}
            return {"action": "stop", "target": "", "reason": "permission observed"}

    engine = AppiumExplorerEngine(client=_OnboardingClient(), llm=_OnboardingLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"permission_probe_action": "observe",
                            "permission_after_consent_window_seconds": 30,
                            "mode_limits": {"fast": {"max_pages": 4}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    finding = next(item for item in result.findings if item.kind == "permission_requested_immediately_after_consent")
    assert finding.payload["no_business_action_after_consent"] is True
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert "post_consent_onboarding_transition" in event_types


def test_permission_prompt_maps_english_android_permission_copy_to_a_real_permission_type():
    prompt = _permission_prompt(
        "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity",
        [{"text": "Allow Demo to make and manage phone calls?", "content_desc": "",
          "resource_id": "com.android.permissioncontroller:id/permission_message"}],
    )

    assert prompt is not None
    assert prompt["permission_label"] == "电话"


def test_customer_service_control_requires_the_actual_customer_service_surface():
    page = parse_page(".WebActivity", '''<hierarchy>
      <node text="客服服务" resource-id="title" clickable="false" class="android.widget.TextView" bounds="[0,100][1080,220]"/>
      <node text="您好，请输入您要咨询的内容" resource-id="hint" clickable="false" class="android.widget.TextView" bounds="[120,2050][820,2220]"/>
      <node text="" resource-id="" content-desc="" clickable="true" class="android.view.View" bounds="[470,2100][620,2320]"/>
      <node text="" resource-id="" content-desc="" clickable="true" class="android.view.View" bounds="[930,2180][1050,2310]"/>
    </hierarchy>''')

    target = _customer_service_sensitive_control(
        ".activity.WebActivity", page.elements, "客服服务 您好，请输入您要咨询的内容",
    )

    assert target == "bounds:[470,2100][620,2320]"
    assert target in {item["target"] for item in page.elements}

    # Bottom navigation merely contains a “客服” label; it is not the actual
    # customer-service conversation and must not consume the 4.2 probe.
    assert _customer_service_sensitive_control(
        ".activity.MainTabActivity", page.elements, "首页 资讯 客服 我的",
    ) is None


def test_customer_service_uses_known_voice_recipe_when_webview_hides_the_microphone():
    page = parse_page(".activity.WebActivity", '''<hierarchy>
      <node text="Customer service" resource-id="title" clickable="false" class="android.widget.TextView" bounds="[0,100][1080,220]"/>
      <node text="Please enter your question" resource-id="hint" clickable="false" class="android.widget.TextView" bounds="[120,2050][820,2220]"/>
    </hierarchy>''')

    assert _customer_service_sensitive_control(
        ".activity.WebActivity", page.elements, "Customer service Please enter your question",
    ) == "relative:0.50,0.88"


def test_customer_service_voice_recipe_is_not_bound_to_one_package():
    assert _customer_service_sensitive_control(
        ".activity.WebActivity", [], "Customer service Please enter your question",
    ) == "relative:0.50,0.88"


def test_generic_sensitive_business_probe_uses_visible_upload_control_without_app_specific_rules():
    page = parse_page(".ProfileActivity", '''<hierarchy>
      <node text="Upload avatar" resource-id="com.example:id/upload_avatar" clickable="true" class="android.widget.Button"/>
    </hierarchy>''')

    assert _sensitive_business_control(
        ".ProfileActivity", page.elements, "Profile settings",
    ) == "com.example:id/upload_avatar"


def test_avatar_label_is_treated_as_a_sensitive_permission_probe():
    page = parse_page(".MainActivity", '''<hierarchy>
      <node text="点击修改头像" resource-id="edit-avatar" clickable="true" class="android.widget.Button"/>
    </hierarchy>''')

    assert _sensitive_business_control(
        ".MainActivity", page.elements, "个人中心",
    ) in {"edit-avatar", "点击修改头像"}


def test_deep_customer_service_recipe_binds_denial_to_the_retried_voice_action(tmp_path):
    customer_service = '''<hierarchy>
      <node text="Customer service" resource-id="title" clickable="false" class="android.widget.TextView"/>
      <node text="Please enter your question" resource-id="hint" clickable="false" class="android.widget.TextView"/>
    </hierarchy>'''
    storage_prompt = '''<hierarchy>
      <node text="Allow Demo to access photos and videos?" resource-id="com.android.permissioncontroller:id/permission_message" clickable="false" class="android.widget.TextView"/>
      <node text="Don't allow" resource-id="com.android.permissioncontroller:id/permission_deny_button" clickable="true" class="android.widget.Button"/>
    </hierarchy>'''
    denied_voice = '''<hierarchy>
      <node text="No storage permission" resource-id="permission-result" clickable="false" class="android.widget.TextView"/>
    </hierarchy>'''

    class _CustomerServiceClient:
        def __init__(self):
            self.index = 0
            self.performed = []
            self.responses = []
            self.voice_attempts = 0

        def page(self):
            pages = [
                (".activity.WebActivity", customer_service),
                ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", storage_prompt),
                (".activity.WebActivity", denied_voice),
            ]
            return pages[self.index]

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.performed.append(decision)
            if decision["action"] == "click" and decision["target"].startswith("relative:"):
                self.voice_attempts += 1
                self.index = 1 if self.voice_attempts == 1 else 2

        def respond_to_permission(self, action):
            self.responses.append(action)
            self.index = 0

        def close(self):
            pass

    class _StopAfterProbeLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "recipe completed"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "recipe completed"}

    client = _CustomerServiceClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopAfterProbeLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.example.travel"),
        cfg={"detection": {"permission_probe_action": "deny", "permission_probe_post_steps": 3,
                             "mode_limits": {"deep": {"max_pages": 6}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.responses == ["deny"]
    assert [item["target"] for item in client.performed] == [
        "relative:0.50,0.88", "relative:0.50,0.88", "",
    ]
    assert not any(item.kind == "permission_denial_blocks_function" for item in result.findings)
    assert any(
        item.get("meta", {}).get("event_type") == "permission_denial_probe_complete"
        for item in result.evidence_files
    )


def test_early_stop_on_consent_dialog_clicks_agree_instead_of_terminating(tmp_path):
    consent_xml = '''<hierarchy>
      <node text="请阅读并同意《隐私政策》" clickable="false"/>
      <node text="同意" resource-id="agree" clickable="true" class="android.widget.Button"/>
    </hierarchy>'''
    home_xml = '''<hierarchy>
      <node text="首页" resource-id="home" clickable="true" class="android.widget.Button"/>
    </hierarchy>'''

    class _ConsentClient:
        def __init__(self):
            self.agreed = False
            self.actions = []

        def page(self):
            if self.agreed:
                return (".MainActivity", home_xml)
            return (".SplashActivity", consent_xml)

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append(decision)
            if decision.get("action") == "click" and decision.get("target") == "agree":
                self.agreed = True

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "premature"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "wait", "target": "", "reason": "consent wait"}

    client = _ConsentClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"mode_limits": {"fast": {"max_pages": 4}}}},
        data_dir=tmp_path,
    )
    engine.run(ctx)
    assert any(item.get("target") == "agree" for item in client.actions)
    assert client.agreed is True


def test_sensitive_media_assist_exhausts_customer_toolbar_before_llm_back(tmp_path):
    customer_service = '''<hierarchy>
      <node text="Customer service" resource-id="title" clickable="false" class="android.widget.TextView"/>
      <node text="Please enter your question" resource-id="hint" clickable="false" class="android.widget.TextView"/>
      <node text="返回" resource-id="back" clickable="true" class="android.widget.Button"/>
    </hierarchy>'''

    class _Client:
        def __init__(self):
            self.performed = []

        def page(self):
            return (".activity.WebActivity", customer_service)

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.performed.append(decision)

        def close(self):
            pass

    class _BackLLM:
        def choose_action(self, *_args):
            return {"action": "back", "target": "", "reason": "leave chat"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "back", "target": "", "reason": "leave chat"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_BackLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.example.travel"),
        cfg={"detection": {"mode_limits": {"deep": {"max_pages": 3}}}},
        data_dir=tmp_path,
    )
    result = engine.run(ctx)
    media_clicks = [
        item for item in client.performed
        if item.get("action") == "click" and str(item.get("target") or "").startswith("relative:")
    ]
    assert [item["target"] for item in media_clicks] == [
        "relative:0.50,0.88", "relative:0.88,0.88", "relative:0.12,0.88",
    ]
    assisted_decisions = [
        item.get("meta", {}) for item in result.evidence_files
        if item.get("meta", {}).get("event_type") == "decision"
        and str(item.get("meta", {}).get("target") or "").startswith("relative:")
    ]
    assert assisted_decisions
    assert assisted_decisions[0]["proposed_by"] == "llm"
    assert assisted_decisions[0]["final_by"] == "deterministic_scenario"
    assert not any(
        "媒体" in str(item.get("reason") or "") for item in client.performed
    )


def test_overlay_settings_page_is_not_misclassified_as_a_runtime_permission_dialog():
    elements = [{"text": "Display over other apps", "content_desc": "", "resource_id": "", "clickable": False}]
    # Android can retain GrantPermissionsActivity while showing this Settings
    # surface, so activity alone is not a reliable discriminator.
    activity = "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity"

    assert _permission_prompt(activity, elements) is None
    assert _special_permission_page(activity, elements) == "overlay"


def test_special_permission_page_records_denied_state_without_toggling_the_setting():
    elements = [
        {"text": "Display over other apps", "content_desc": "", "resource_id": "", "clickable": False},
        {"text": "案例C", "content_desc": "Not allowed", "resource_id": "", "clickable": True},
    ]

    assert _special_permission_state(elements) == "denied"


def test_explorer_records_special_permission_state_and_returns_without_failing_task(tmp_path):
    settings_xml = '''<hierarchy><node text="Display over other apps" resource-id="" clickable="false" class="android.widget.TextView"/></hierarchy>'''

    class _SettingsClient:
        def __init__(self):
            self.actions = []

        def page(self):
            return "com.android.settings.spa.SpaActivity", settings_xml

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append(decision["action"])

        def close(self):
            pass

    class _NoLLM:
        def choose_action(self, *_args):
            raise AssertionError("special settings must bypass LLM actions")

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "unused"}

    client = _SettingsClient()
    engine = AppiumExplorerEngine(client=client, llm=_NoLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"detection": {"mode_limits": {"fast": {"max_pages": 1}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.actions == ["back"]
    assert any("特殊权限“overlay”" in gap for gap in result.stats["coverage_gaps"])
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert {"special_permission_page_observed", "special_permission_returned_to_app"} <= event_types


_CHECKED_CONSENT = '''<hierarchy><node text="隐私政策" resource-id="com.demo:id/privacy_hint" clickable="false" class="android.widget.TextView"/><node text="同意隐私政策" resource-id="com.demo:id/consent_checkbox" checked="true" clickable="true" class="android.widget.CheckBox"/></hierarchy>'''


class _CheckedConsentClient:
    def page(self):
        return ".SplashActivity", _CHECKED_CONSENT

    def activate(self, _package):
        pass

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return True

    def perform(self, _decision):
        pass

    def scroll_down(self):
        return False

    def close(self):
        pass


def test_explorer_flags_default_checked_consent_control_with_screenshot_evidence(tmp_path):
    engine = AppiumExplorerEngine(client=_CheckedConsentClient(), llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "mode_limits": {"fast": {"max_pages": 2}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert any(item.kind == "consent_checkbox_prechecked" for item in result.findings)
    evidence = [item for item in result.evidence_files if item["type"] == "screenshot"]
    assert "consent_checkbox_prechecked" in evidence[0]["meta"]["finding_kinds"]


_PHONE_PROMPT = '''<hierarchy><node text="允许 Demo 拨打和管理电话吗？" resource-id="com.android.permissioncontroller:id/permission_message" clickable="false" class="android.widget.TextView"/></hierarchy>'''


class _BatchPermissionClient:
    def __init__(self):
        self.index = 0

    def page(self):
        pages = [
            (".SplashActivity", _PRIVACY_DECISION),
            ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _CAMERA_PROMPT),
            ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _PHONE_PROMPT),
        ]
        current = pages[min(self.index, len(pages) - 1)]
        if self.index >= 1:
            self.index += 1
        return current

    def activate(self, _package):
        pass

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return True

    def perform(self, _decision):
        if _decision["action"] == "click":
            self.index = 1

    def close(self):
        pass


class _PrivacyThenStopLLM:
    def choose_action(self, page, *_args):
        if page["activity"] == ".SplashActivity":
            return {"action": "click", "target": "com.demo:id/btn_negative", "reason": "处理隐私弹窗"}
        return {"action": "wait", "target": "", "reason": "继续观察系统权限序列"}

    def fallback_action(self, *_args):
        return {"action": "stop", "target": "", "reason": "done"}


def test_explorer_flags_multiple_permission_prompts_after_privacy_consent(tmp_path):
    engine = AppiumExplorerEngine(client=_BatchPermissionClient(), llm=_PrivacyThenStopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "permission_probe_action": "observe",
                            "permission_after_consent_window_seconds": 30,
                            "mode_limits": {"fast": {"max_pages": 4}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert any(item.kind == "multiple_permissions_requested_after_consent" for item in result.findings)
    assert "4.6" in ctx.runtime["scenario_completed_items"]


def test_denial_probe_does_not_bind_a_different_permission_message(tmp_path):
    class _MismatchedPermissionClient(_PermissionClient):
        def page(self):
            pages = [
                (".ProfileActivity", _APP_FUNCTION),
                ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _PHONE_PROMPT),
                (".ProfileActivity", '<hierarchy><node text="暂无定位权限，无法继续" resource-id="permission-result" clickable="false" class="android.widget.TextView"/></hierarchy>'),
            ]
            return pages[self.index]

    client = _MismatchedPermissionClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"permission_probe_action": "deny", "permission_probe_post_steps": 2,
                            "mode_limits": {"fast": {"max_pages": 4}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert not any(item.kind == "permission_denial_blocks_function" for item in result.findings)


_LOGIN_PAGE = '''<hierarchy><node text="手机号" resource-id="com.demo:id/et_phone" clickable="true" class="android.widget.EditText"/><node text="密码" resource-id="com.demo:id/et_password" clickable="true" class="android.widget.EditText"/><node text="登录" resource-id="com.demo:id/btn_login" clickable="true" class="android.widget.Button"/></hierarchy>'''
_LOGGED_IN_PROFILE = '''<hierarchy><node text="我的" resource-id="com.demo:id/title" clickable="false" class="android.widget.TextView"/><node text="App用户3367" resource-id="com.demo:id/nickname" clickable="false" class="android.widget.TextView"/><node text="13800138000" resource-id="com.demo:id/phone" clickable="false" class="android.widget.TextView"/><node text="消息中心" resource-id="com.demo:id/messages" clickable="true" class="android.widget.TextView"/><node text="设置" resource-id="com.demo:id/settings" clickable="true" class="android.widget.TextView"/></hierarchy>'''
_ABOUT_WITH_PRIVACY_ENTRY = '''<hierarchy><node text="关于我们" resource-id="com.demo:id/title" clickable="false" class="android.widget.TextView"/><node text="隐私政策" resource-id="com.demo:id/privacy_label" clickable="false" class="android.widget.TextView"/><node text="隐私政策" resource-id="com.demo:id/ll_privacy" clickable="true" class="android.widget.LinearLayout"/></hierarchy>'''
_ABOUT_WITH_NESTED_PRIVACY_ENTRY = '''<hierarchy><node text="关于我们" resource-id="com.demo:id/title" clickable="false" class="android.widget.TextView"/><node text="" resource-id="com.demo:id/ll_privacy" clickable="true" class="android.widget.LinearLayout"><node text="隐私政策" resource-id="com.demo:id/privacy_label" clickable="false" class="android.widget.TextView"/></node></hierarchy>'''
_POLICY_WITH_LOGIN_WORDS = '''<hierarchy><node text="隐私政策：注册或登录账号时会发送验证码，并可能使用手机号。" resource-id="com.demo:id/policy_body" clickable="false" class="android.widget.TextView"/></hierarchy>'''
_ACCOUNT_ENTRY_PAGE = '''<hierarchy><node text="登录" resource-id="com.demo:id/login_entry" clickable="true" class="android.widget.TextView"/><node text="注册" resource-id="com.demo:id/register_entry" clickable="true" class="android.widget.TextView"/></hierarchy>'''
_LOGIN_INVITATION = '''<hierarchy><node text="温馨提示" resource-id="title" clickable="false" class="android.widget.TextView"/><node text="该功能需要您登录后才能使用哦" resource-id="message" clickable="false" class="android.widget.TextView"/><node text="取消" resource-id="cancel" clickable="true" class="android.widget.Button"/><node text="前往登录" resource-id="go_login" clickable="true" class="android.widget.Button"/></hierarchy>'''
_LOGIN_METHOD_CHOOSER = '''<hierarchy><node text="登录方式" resource-id="title" clickable="false" class="android.widget.TextView"/><node text="QQ" resource-id="qq" clickable="true" class="android.widget.ImageView"/><node text="微信" resource-id="wechat" clickable="true" class="android.widget.ImageView"/><node text="手机号" resource-id="phone" clickable="true" class="android.widget.ImageView"/></hierarchy>'''


def test_login_gate_requires_an_actual_login_form_not_login_words_or_an_entry():
    assert _is_login_gate(".LoginActivity", parse_page(".LoginActivity", _LOGIN_PAGE).elements)
    assert not _is_login_gate(".kt.WebViewKT", parse_page(".kt.WebViewKT", _POLICY_WITH_LOGIN_WORDS).elements)
    assert not _is_login_gate(".activity.MainTabActivity", parse_page(".activity.MainTabActivity", _ACCOUNT_ENTRY_PAGE).elements)


def test_login_method_chooser_starts_manual_login_checkpoint():
    page = parse_page(".MainActivity", _LOGIN_METHOD_CHOOSER)
    assert _is_login_gate(page.activity, page.elements)


def test_external_browser_body_requires_real_content_not_toolbar_only():
    toolbar = parse_page("CustomTabActivity", '<hierarchy><node text="返回" clickable="true" class="android.widget.ImageButton"/><node text="https://example.test" clickable="false" class="android.widget.TextView"/></hierarchy>')
    body = parse_page("CustomTabActivity", '<hierarchy><node text="隐私政策 我们如何收集和使用个人信息 这是可阅读正文。" clickable="false" class="android.widget.TextView"/></hierarchy>')
    assert not _external_document_body_visible(toolbar.elements)
    assert _external_document_body_visible(body.elements)


def test_settings_privacy_resource_id_is_a_document_route():
    assert _target_is_document_route("com.example.reader:id/oi_private")
    assert _target_is_document_route("《隐私政策》")
    assert not _target_is_document_route("com.demo:id/home")


def test_chrome_main_loaded_policy_is_read_then_returned_without_llm_wait(tmp_path):
    chrome = (
        '<hierarchy>'
        '<node text="example.com/privacy.html" resource-id="com.android.chrome:id/url_bar" '
        'clickable="true" class="android.widget.EditText"/>'
        '<node text="《隐私政策》 为向你提供案例K产品与服务，我们会收集你的设备信息、操作日志等个人信息。" '
        'clickable="false" class="android.widget.TextView"/>'
        '</hierarchy>'
    )
    home = (
        '<hierarchy>'
        '<node text="首页" clickable="false" class="android.widget.TextView"/>'
        '<node text="设置" resource-id="settings" clickable="true" class="android.widget.TextView"/>'
        '</hierarchy>'
    )

    class _ChromePolicyClient:
        def __init__(self):
            self.in_chrome = True
            self.actions = []
            self.llm_calls = 0

        def page(self):
            if self.in_chrome:
                return "com.google.android.apps.chrome.Main", chrome
            return ".MainActivity", home

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return False

        def scroll_down(self):
            return False

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append(decision["action"])
            if decision["action"] == "back":
                self.in_chrome = False

        def close(self):
            pass

    class _WaitForeverLLM:
        def __init__(self, client):
            self.client = client

        def choose_action(self, *_args):
            self.client.llm_calls += 1
            return {"action": "stop", "target": "", "reason": "home reached"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _ChromePolicyClient()
    engine = AppiumExplorerEngine(client=client, llm=_WaitForeverLLM(client))
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={
            "appium": {"page_wait_seconds": 0},
            "detection": {
                "external_document_wait_retries": 3,
                "external_document_wait_seconds": 0,
                "page_settle_retries": 0,
                "mode_limits": {"fast": {"max_pages": 6}},
            },
        },
        data_dir=tmp_path,
    )
    result = engine.run(ctx)
    event_types = [item.get("meta", {}).get("event_type") for item in result.evidence_files]
    assert "external_document_read_complete" in event_types
    assert "external_surface_returned_to_app" in event_types
    assert client.actions[0] == "back"
    assert "wait" not in client.actions
    assert "privacy_policy" in (ctx.runtime.get("read_document_kinds") or set())


def test_login_invitation_selects_only_the_explicit_transition_to_the_form():
    page = parse_page(".activity.MainTabActivity", _LOGIN_INVITATION)
    page_text = " ".join(item["text"] for item in page.elements)

    assert _login_invitation_target(page.elements, page_text) == "go_login"
    assert _login_invitation_target(
        parse_page(".MainActivity", _ACCOUNT_ENTRY_PAGE).elements, "登录 注册"
    ) is None


class _LoginInvitationClient:
    def __init__(self):
        self.index = 0
        self.performed = []

    def page(self):
        pages = [
            (".activity.MainTabActivity", _LOGIN_INVITATION),
            (".kt.LoginKT", _LOGIN_PAGE),
            (".activity.MainTabActivity", _PUBLIC_PAGE),
        ]
        return pages[self.index]

    def activate(self, _package):
        pass

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return True

    def perform(self, decision):
        self.performed.append((decision["action"], decision.get("target", "")))
        if decision["action"] == "click":
            self.index = 1
        elif decision["action"] == "back":
            self.index = 2

    def close(self):
        pass


class _InvitationFlowLLM:
    def __init__(self):
        self.pages = []

    def choose_action(self, page, *_args):
        self.pages.append(page["activity"])
        return {"action": "stop", "target": "", "reason": "公开路径已检查"}

    def fallback_action(self, *_args):
        return {"action": "stop", "target": "", "reason": "done"}

    def assess_login_state(self, _page):
        return False


def test_login_invitation_enters_form_before_starting_manual_login_gate(tmp_path):
    client = _LoginInvitationClient()
    llm = _InvitationFlowLLM()
    engine = AppiumExplorerEngine(client=client, llm=llm)
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"manual_login_wait_seconds": 0,
                            "mode_limits": {"fast": {"max_pages": 5}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.performed[:2] == [("click", "go_login"), ("back", "")]
    assert llm.pages and set(llm.pages) == {".activity.MainTabActivity"}
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert {"login_invitation_followed", "awaiting_manual_login", "manual_login_timeout"} <= event_types


def test_public_feedback_frontier_is_explored_before_optional_login_invitation(tmp_path):
    """A login invitation cannot hide a still-public 4.2 business frontier."""
    public_page = '''<hierarchy>
      <node text="意见反馈" resource-id="feedback" clickable="true" class="android.widget.Button"/>
      <node text="该功能需要登录" clickable="false" class="android.widget.TextView"/>
      <node text="前往登录" resource-id="go_login" clickable="true" class="android.widget.Button"/>
    </hierarchy>'''
    feedback_page = '<hierarchy><node text="请输入问题" resource-id="message" clickable="true" class="android.widget.EditText"/></hierarchy>'

    class _PublicFrontierClient:
        def __init__(self):
            self.phase = "public"
            self.actions = []

        def page(self):
            return (".FeedbackActivity", feedback_page) if self.phase == "feedback" else (".MainActivity", public_page)

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and decision.get("target") == "feedback":
                self.phase = "feedback"

        def close(self):
            pass

    class _FeedbackFirstLLM:
        def choose_action(self, page, *_args):
            if page["activity"] == ".MainActivity":
                return {"action": "click", "target": "feedback", "reason": "公开反馈入口仍可用于权限业务场景"}
            return {"action": "stop", "target": "", "reason": "feedback reviewed"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _PublicFrontierClient()
    engine = AppiumExplorerEngine(client=client, llm=_FeedbackFirstLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"manual_login_wait_seconds": 0, "mode_limits": {"fast": {"max_pages": 4}}}},
        data_dir=tmp_path,
    )

    engine.run(ctx)

    assert client.actions[0] == ("click", "feedback")
    assert ("click", "go_login") not in client.actions


def test_logged_in_profile_is_not_mistaken_for_login_when_activity_name_is_reused():
    elements = parse_page(".kt.LoginKT", _LOGGED_IN_PROFILE).elements

    assert _authenticated_session_visible(elements)
    assert not _is_login_gate(".kt.LoginKT", elements)


def test_logged_in_flutter_profile_with_only_phone_and_selected_my_tab_is_verified():
    elements = parse_page(
        ".MainActivity",
        '<hierarchy><node text="我的" clickable="false"/><node text="13800138001" clickable="false"/></hierarchy>',
    ).elements

    assert _authenticated_session_visible(elements)
    assert not _is_login_gate(".MainActivity", elements)


def test_about_page_privacy_link_is_not_mistaken_for_a_readable_policy_document():
    page = parse_page(".kt.AboutKT", _ABOUT_WITH_PRIVACY_ENTRY)

    assert _document_key(page.activity, page.elements, PageState()) is None


def test_about_page_nested_privacy_label_is_still_an_entry_not_a_document():
    """Real apps often put the label inside a clickable parent container."""
    page = parse_page(".kt.AboutKT", _ABOUT_WITH_NESTED_PRIVACY_ENTRY)

    assert _document_key(page.activity, page.elements, PageState()) is None


def test_privacy_policy_and_terms_in_the_same_webview_keep_separate_read_progress():
    state = PageState()
    privacy = parse_page(".kt.WebViewKT", '<hierarchy><node text="隐私声明：我们如何处理个人信息" resource-id="body" clickable="false" class="android.widget.TextView"/></hierarchy>')
    terms = parse_page(".kt.WebViewKT", '<hierarchy><node text="使用条款：服务使用规则" resource-id="body" clickable="false" class="android.widget.TextView"/></hierarchy>')

    privacy_key = _document_key(privacy.activity, privacy.elements, state)
    terms_key = _document_key(terms.activity, terms.elements, state)

    assert privacy_key
    assert terms_key
    assert privacy_key != terms_key


class _LoginClient:
    def __init__(self):
        self.performed = []

    def page(self):
        return ".LoginActivity", _LOGIN_PAGE

    def activate(self, _package):
        pass

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return True

    def perform(self, decision):
        self.performed.append(decision["action"])

    def close(self):
        pass


class _NeverAskLLM:
    def choose_action(self, *_args):
        raise AssertionError("登录检查点不应让模型操作账号控件")

    def fallback_action(self, *_args):
        raise AssertionError("登录检查点不应走本地点击兜底")


class _HumanLoggedInClient(_LoginClient):
    """The activity stays LoginKT even after a human finishes authentication."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def page(self):
        self.calls += 1
        return (".kt.LoginKT", _LOGIN_PAGE if self.calls == 1 else _LOGGED_IN_PROFILE)


class _ProfileStopLLM:
    def choose_action(self, *_args):
        return {"action": "stop", "target": "", "reason": "已读取登录后的账户页"}

    def fallback_action(self, *_args):
        return {"action": "stop", "target": "", "reason": "done"}


class _TransientLoginSurfaceClient(_LoginClient):
    """The app briefly exposes an empty/old LoginKT UI during navigation."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def page(self):
        self.calls += 1
        pages = [
            (".kt.LoginKT", _LOGIN_PAGE),
            (".kt.LoginKT", "<hierarchy/>"),
            (".kt.LoginKT", _LOGIN_PAGE),
            (".activity.MainTabActivity", _LOGGED_IN_PROFILE),
            (".activity.MainTabActivity", _LOGGED_IN_PROFILE),
        ]
        return pages[min(self.calls - 1, len(pages) - 1)]


def test_login_verification_waits_out_transient_login_surface_before_marking_unverified(tmp_path, monkeypatch):
    # Keep the test deterministic: simulate four one-second poll slots without
    # making the test sleep for real.
    ticks = iter([0, 0, 0, 0, 0, 10])
    monkeypatch.setattr(explorer_module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(explorer_module.time, "sleep", lambda _seconds: None)
    client = _TransientLoginSurfaceClient()
    engine = AppiumExplorerEngine(client=client, llm=_ProfileStopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "manual_login_wait_seconds": 3,
                            "mode_limits": {"fast": {"max_pages": 3}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert ctx.runtime["manual_login_verified"] is True
    assert not any("登录后功能未覆盖" in gap for gap in result.stats["coverage_gaps"])


def test_human_login_is_verified_from_profile_identity_even_if_activity_is_loginkt(tmp_path):
    client = _HumanLoggedInClient()
    engine = AppiumExplorerEngine(client=client, llm=_ProfileStopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "manual_login_wait_seconds": 1,
                            "mode_limits": {"fast": {"max_pages": 3}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert ctx.runtime["manual_login_verified"] is True
    assert not any("登录后功能未覆盖" in gap for gap in result.stats["coverage_gaps"])
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert "manual_login_state_verified" in event_types


def test_explorer_waits_for_human_login_instead_of_treating_login_page_as_complete(tmp_path):
    engine = AppiumExplorerEngine(client=_LoginClient(), llm=_NeverAskLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "manual_login_wait_seconds": 0,
                            "mode_limits": {"fast": {"max_pages": 3}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert result.stats["llm_calls"] == 0
    assert engine.client.performed == ["back"]
    assert any("登录后功能未覆盖" in gap for gap in result.stats["coverage_gaps"])
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert {"awaiting_manual_login", "manual_login_timeout", "login_path_skipped", "coverage_incomplete"} <= event_types


def test_allow_phase_first_login_gate_keeps_full_manual_wait(tmp_path, monkeypatch):
    """Allow phase alone must not reduce a never-seen login form to five seconds."""
    waits = []
    monkeypatch.setattr(
        explorer_module,
        "_wait_for_manual_login",
        lambda _client, _ctx, seconds: waits.append(seconds) or False,
    )
    engine = AppiumExplorerEngine(client=_LoginClient(), llm=_ProfileStopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {
            "manual_login_wait_seconds": 120,
            "subsequent_phase_login_wait_seconds": 5,
            "mode_limits": {"fast": {"max_pages": 2}},
        }},
        data_dir=tmp_path,
        runtime={"permission_only_phase": True},
    )

    engine.run(ctx)

    assert waits == [120]


def test_login_footer_agreements_do_not_preempt_manual_login_checkpoint(tmp_path):
    login_with_footer = (
        '<hierarchy>'
        '<node text="手机号" resource-id="com.demo:id/et_phone" clickable="true" class="android.widget.EditText"/>'
        '<node text="密码" resource-id="com.demo:id/et_password" clickable="true" class="android.widget.EditText"/>'
        '<node text="登录" resource-id="com.demo:id/btn_login" clickable="true" class="android.widget.Button"/>'
        '<node text="《用户协议》" resource-id="com.demo:id/right" clickable="true" class="android.widget.TextView"/>'
        '<node text="《隐私政策》" resource-id="com.demo:id/privacy" clickable="true" class="android.widget.TextView"/>'
        '</hierarchy>'
    )

    class _LoginWithFooterClient(_LoginClient):
        def page(self):
            return ".LoginActivity", login_with_footer

    client = _LoginWithFooterClient()
    engine = AppiumExplorerEngine(client=client, llm=_NeverAskLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {
            "manual_login_wait_seconds": 0,
            "mode_limits": {"fast": {"max_pages": 3}},
        }},
        data_dir=tmp_path,
        runtime={
            "consent_accepted": True,
            "manual_login_waited": True,
            "manual_login_verified": True,
            "manual_login_ocr_blob": "登录成功 我的 个人中心",
            "read_document_kinds": {"privacy_policy"},
            "read_document_titles": {"隐私政策"},
        },
    )

    result = engine.run(ctx)

    assert client.performed == ["back"]
    event_types = {
        item["meta"].get("event_type")
        for item in result.evidence_files if item["type"] == "timeline"
    }
    assert "required_document_prioritized" not in event_types


_PUBLIC_PAGE = '''<hierarchy><node text="隐私设置" resource-id="com.demo:id/privacy_settings" clickable="true" class="android.widget.TextView"/></hierarchy>'''


class _LoginTimeoutThenPublicClient(_LoginClient):
    def __init__(self):
        super().__init__()
        self.index = 0

    def page(self):
        return ((".LoginActivity", _LOGIN_PAGE), (".PublicSettingsActivity", _PUBLIC_PAGE))[self.index]

    def perform(self, decision):
        super().perform(decision)
        if decision["action"] == "back":
            self.index = 1


class _PublicOnlyLLM:
    def __init__(self):
        self.calls = []

    def choose_action(self, page, *_args):
        self.calls.append(page["activity"])
        return {"action": "stop", "target": "", "reason": "公开路径已检查"}

    def fallback_action(self, *_args):
        return {"action": "stop", "target": "", "reason": "done"}

    def assess_login_state(self, _page):
        return False


def test_login_timeout_returns_to_and_continues_public_paths(tmp_path):
    client = _LoginTimeoutThenPublicClient()
    llm = _PublicOnlyLLM()
    engine = AppiumExplorerEngine(client=client, llm=llm)
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "manual_login_wait_seconds": 0,
                            "mode_limits": {"fast": {"max_pages": 4}}}}, data_dir=tmp_path,
    )

    result = engine.run(ctx)

    # A model stop is advisory while the public page still exposes an
    # unvisited privacy-settings route required by the deterministic plan.
    assert client.performed == ["back", "click"]
    assert llm.calls and all(activity == ".PublicSettingsActivity" for activity in llm.calls)
    assert result.stats["pages_covered"] == 2


def test_login_timeout_back_to_launcher_relaunches_and_continues_public_home(tmp_path):
    login = _LOGIN_PAGE
    launcher = '<hierarchy><node text="Home" resource-id="home" clickable="false" class="android.widget.TextView"/></hierarchy>'
    home = (
        '<hierarchy>'
        '<node text="书城" resource-id="tab_library" clickable="true" class="android.widget.TextView"/>'
        '<node text="我的" resource-id="tab_mine" clickable="true" class="android.widget.TextView"/>'
        '<node text="热门小说列表占位避免过短" clickable="false" class="android.widget.TextView"/>'
        '</hierarchy>'
    )

    class _LoginThenLauncherThenHome:
        def __init__(self):
            self.phase = "login"
            self.performed = []
            self.activations = 0

        def page(self):
            if self.phase == "launcher":
                return "com.android.launcher.NexusLauncherActivity", launcher
            if self.phase == "home":
                return ".module.home.HomeActivity", home
            return ".LoginActivity", login

        def activate(self, _package):
            self.activations += 1
            if self.phase == "launcher":
                self.phase = "home"

        def recent_app_crash(self, _package):
            return None

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.performed.append(decision["action"])
            if decision["action"] == "back" and self.phase == "login":
                self.phase = "launcher"

        def close(self):
            pass

    class _HomeStopLLM:
        def choose_action(self, page, *_args):
            if "Home" in str(page.get("activity") or ""):
                return {"action": "stop", "target": "", "reason": "已进入公开首页"}
            raise AssertionError("登录门禁不应让模型操作账号控件")

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def assess_login_state(self, _page):
            return False

    client = _LoginThenLauncherThenHome()
    engine = AppiumExplorerEngine(client=client, llm=_HomeStopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "manual_login_wait_seconds": 0, "sdk_observation_dwell_seconds": 0,
            "page_settle_retries": 0, "mode_limits": {"fast": {"max_pages": 8}},
        }},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)
    event_types = {item.get("meta", {}).get("event_type") for item in result.evidence_files}
    assert "back" in client.performed
    assert client.activations >= 1
    assert "app_exit_after_back_expected" not in event_types
    assert "app_foreground_recovered" in event_types
    assert result.stats["pages_covered"] >= 2


def test_login_timeout_asks_llm_to_verify_current_state_before_skipping(tmp_path):
    client = _LoginClient()
    llm = _NeverAskLLM()
    llm.assessed = 0
    llm.assess_login_state = lambda _page: setattr(llm, "assessed", llm.assessed + 1) or False
    engine = AppiumExplorerEngine(client=client, llm=llm)
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"manual_login_wait_seconds": 0, "mode_limits": {"fast": {"max_pages": 2}}}}, data_dir=tmp_path,
    )

    engine.run(ctx)

    assert llm.assessed == 1


_STOP_BEFORE_POLICY_HOME = '''<hierarchy><node text="隐私政策" resource-id="com.demo:id/privacy_entry" clickable="true" class="android.widget.TextView"/></hierarchy>'''
_STOP_BEFORE_POLICY_DOCUMENT = '''<hierarchy><node text="Privacy Policy collection and use rules" resource-id="com.demo:id/policy_body" clickable="false" class="android.widget.TextView"/></hierarchy>'''


class _StopBeforePolicyClient:
    def __init__(self):
        self.index = 0
        self.actions = []

    def page(self):
        return ((".HomeActivity", _STOP_BEFORE_POLICY_HOME), (".PolicyActivity", _STOP_BEFORE_POLICY_DOCUMENT))[self.index]

    def activate(self, _package):
        pass

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return True

    def scroll_down(self):
        return False

    def perform(self, decision):
        self.actions.append(decision)
        if decision["action"] == "click" and decision["target"] == "com.demo:id/privacy_entry":
            self.index = 1

    def close(self):
        pass


class _AlwaysStopLLM:
    def choose_action(self, *_args):
        return {"action": "stop", "target": "", "reason": "no more work"}

    def fallback_action(self, elements, visited_targets, *_args):
        from agent.ai_explorer.llm_controller import LLMController

        return LLMController.fallback_action(elements, visited_targets)


def test_explorer_overrides_early_model_stop_to_read_reachable_privacy_policy(tmp_path):
    client = _StopBeforePolicyClient()
    engine = AppiumExplorerEngine(client=client, llm=_AlwaysStopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "max_document_scrolls": 5, "document_stuck_wait_seconds": 0,
            "mode_limits": {"deep": {"max_pages": 6}},
        }},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.actions[0]["action"] == "click"
    assert client.actions[0]["target"] == "com.demo:id/privacy_entry"
    assert ctx.runtime.get("policy_document_read_complete") is not True
    assert ctx.runtime["incomplete_documents"][0]["reason"] == "document_scroll_stuck"
    assert result.stats["pages_covered"] == 2


def test_user_agreement_text_is_excluded_from_privacy_policy_corpus():
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={}, data_dir=SimpleNamespace(),
    )
    ctx.runtime = {}
    _append_policy_fragment(ctx, "隐私政策正文：我们收集个人信息用于提供写作服务，范围包括账号。", "《隐私政策》")
    _append_policy_fragment(ctx, "用户服务协议：服务中断将在三个工作日内恢复，投诉可通过客服联系。", "《用户服务协议》")

    assert "写作服务" in ctx.runtime["privacy_policy_text"]
    assert "三个工作日" not in ctx.runtime["privacy_policy_text"]
    assert "三个工作日" not in ctx.runtime["policy_text"]


def test_photo_picker_camera_control_triggers_permission_purpose_check(tmp_path):
    avatar_page = '''<hierarchy><node text="点击修改头像" resource-id="edit-avatar" clickable="true" class="android.widget.Button"/></hierarchy>'''
    picker_page = '''<hierarchy><node text="拍照" resource-id="picker-camera" clickable="true" class="android.widget.Button"/><node text="Recent" resource-id="com.google.android.photopicker:id/toolbar" clickable="false" class="android.widget.TextView"/></hierarchy>'''

    class _PhotoPickerClient:
        def __init__(self):
            self.phase = "app"
            self.actions = []
            self.responses = []

        def page(self):
            if self.phase == "picker":
                return ("com.google.android.photopicker.external.ExternalPickerActivity", picker_page)
            if self.phase == "permission":
                return ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _CAMERA_PROMPT)
            return (".MainActivity", avatar_page)

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and self.phase == "app":
                self.phase = "picker"
            elif decision["action"] == "click" and self.phase == "picker":
                self.phase = "permission"
            elif decision["action"] == "back":
                self.phase = "app"

        def respond_to_permission(self, action):
            self.responses.append(action)
            self.phase = "app"

        def close(self):
            pass

    class _StopAfterPermissionLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _PhotoPickerClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopAfterPermissionLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"permission_probe_action": "deny", "max_sensitive_permission_probes": 3,
                            "mode_limits": {"deep": {"max_pages": 8}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert ("click", "拍照") in client.actions or ("click", "picker-camera") in client.actions
    assert "permission_purpose_not_informed" in {finding.kind for finding in result.findings}
    assert client.responses == ["deny"]
    assert any(
        item.get("meta", {}).get("event_type") == "file_picker_camera_probe_started"
        for item in result.evidence_files
    )


def test_login_success_toast_is_treated_as_authenticated_session():
    elements = parse_page(
        ".LoginActivity",
        '<hierarchy><node text="手机号" clickable="false"/><node text="登录成功！" clickable="false"/></hierarchy>',
    ).elements
    assert _authenticated_session_visible(elements)
    assert _authenticated_session_visible([], extra_text="成功登陆")
    assert not _authenticated_session_visible(
        parse_page(".LoginActivity", '<hierarchy><node text="请登录" clickable="false"/></hierarchy>').elements
    )


def test_login_wait_success_is_not_overridden_by_stale_login_form(tmp_path, monkeypatch):
    ticks = iter([0, 0, 10])
    monkeypatch.setattr(explorer_module.time, "monotonic", lambda: next(ticks, 10))
    monkeypatch.setattr(explorer_module.time, "sleep", lambda _seconds: None)

    class _ToastThenFormClient(_LoginClient):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def page(self):
            self.calls += 1
            if self.calls == 1:
                return ".kt.LoginKT", (
                    '<hierarchy><node text="手机号" clickable="true" class="android.widget.EditText"/>'
                    '<node text="登录" clickable="true" class="android.widget.Button"/>'
                    '<node text="登录成功！" clickable="false"/></hierarchy>'
                )
            return ".kt.LoginKT", _LOGIN_PAGE

    class _DenyLoginLLM(_ProfileStopLLM):
        def assess_login_state(self, _page):
            return False

        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "已离开登录页"}

    client = _ToastThenFormClient()
    engine = AppiumExplorerEngine(client=client, llm=_DenyLoginLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"max_document_scrolls": 5, "manual_login_wait_seconds": 3,
                            "mode_limits": {"fast": {"max_pages": 3}}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert ctx.runtime["manual_login_verified"] is True
    event_types = {item["meta"].get("event_type") for item in result.evidence_files if item["type"] == "timeline"}
    assert "manual_login_state_verified" in event_types
    assert not any("登录后功能未覆盖" in gap for gap in result.stats["coverage_gaps"])


def test_reading_record_is_not_a_sensitive_permission_probe():
    page = parse_page(".HomeActivity", '''<hierarchy>
      <node text="阅读记录" resource-id="com.example.reader:id/oi_reading_record" clickable="true"/>
      <node text="修改头像" resource-id="com.example.reader:id/avatar" clickable="true"/>
    </hierarchy>''')
    assert _sensitive_business_control(".HomeActivity", page.elements, "首页") in {
        "com.example.reader:id/avatar", "修改头像",
    }


def test_home_activity_counts_as_main_content_for_sdk_dwell():
    page = parse_page(
        "com.example.reader.ui.HomeActivity",
        '<hierarchy><node text="书城" clickable="true"/><node text="我的" clickable="true"/></hierarchy>',
    )
    assert _looks_like_main_content_surface(page.activity, page.elements)


def test_privacy_hub_tab_prefers_settings_over_customer_service():
    page = parse_page(".HomeActivity", '''<hierarchy>
      <node text="QQ客服" resource-id="com.example.reader:id/oi_qq" clickable="true"/>
      <node text="我的" resource-id="com.example.reader:id/tab_mine" clickable="true"/>
      <node text="设置" resource-id="com.example.reader:id/tab_settings" clickable="true"/>
    </hierarchy>''')
    assert _privacy_hub_tab_target(page.elements) == "com.example.reader:id/tab_settings"


def test_qq_unavailable_dialog_is_dismissed_by_ok_button():
    page = parse_page(".HomeActivity", '''<hierarchy>
      <node text="没有检测到QQ或版本过低" clickable="false"/>
      <node text="确定" resource-id="android:id/button1" clickable="true"/>
    </hierarchy>''')
    page_text = "没有检测到qq或版本过低 确定"
    assert _channel_unavailable_dialog_dismiss_target(page.elements, page_text) in {
        "android:id/button1", "确定",
    }


def test_own_splash_activity_is_not_associated_start_when_java_package_differs():
    splash = "com.example.smarthome.main.ui.SplashActivity"
    package = "com.example.smarthome"
    assert _activity_belongs_to_package(splash, package)
    assert not _associated_start_activity(splash, package)
    assert not _activity_belongs_to_package("com.tencent.mobileqq.activity.Splash", "com.tencent.mm")
    assert _associated_start_activity("com.tencent.mobileqq.activity.Splash", "com.tencent.mm")
    assert _associated_start_activity("com.other.app.FooActivity", package)
    setting = "com.example.smarthome.mine.activity.SettingActivity"
    assert _activity_belongs_to_package(setting, package)
    assert not _associated_start_activity(setting, package)
    assert not _associated_start_activity(
        setting, package, foreground_package="com.example.smarthome",
    )
    assert _associated_start_activity(
        "com.tencent.mm.ui.LauncherUI", "com.example.smarthome",
        foreground_package="com.tencent.mm",
    )


def test_checkbox_caption_keeps_privacy_policy_unread_after_user_agreement():
    # The unread policy remains eligible for one bounded splash probe.
    consent = parse_page(
        ".SplashActivity",
        '''<hierarchy>
          <node text="请勾选阅读并同意《用户协议》和《隐私政策》" clickable="false"/>
          <node text="《用户协议》" clickable="true"/>
          <node text="同意" clickable="true"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )
    _remember_consent_document_titles(ctx, consent.elements)
    _mark_required_document_read(ctx, "《用户协议》", page_text="用户协议正文")
    assert _unread_for_page(ctx, consent.elements, {"《用户协议》"}) == "《隐私政策》"

    hub = parse_page(
        ".SettingActivity",
        '''<hierarchy>
          <node text="用户协议" resource-id="oi_user" clickable="true"/>
          <node text="隐私政策" resource-id="oi_private" clickable="true"/>
        </hierarchy>''',
    )
    unread = _unread_for_page(ctx, hub.elements, {"《用户协议》", "oi_user", "用户协议"})
    assert unread is not None
    assert "隐私" in unread or "private" in unread.lower()


def test_privacy_agreement_caption_stays_unread_after_user_agreement():
    consent = parse_page(
        ".SplashActivity",
        '''<hierarchy>
          <node text="请勾选阅读并同意《用户协议》和《隐私协议》" clickable="false"/>
          <node text="《用户协议》" clickable="true"/>
          <node text="同意" clickable="true"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )
    _remember_consent_document_titles(ctx, consent.elements)
    _mark_required_document_read(ctx, "《用户协议》", page_text="用户协议正文")
    assert _unread_for_page(ctx, consent.elements, {"《用户协议》"}) == "《隐私协议》"
    assert _required_document_kind("隐私协议") == "privacy_policy"
    assert _page_names_privacy_policy(consent.elements)

    hub = parse_page(
        ".AboutActivity",
        '''<hierarchy>
          <node text="用户协议" clickable="true"/>
          <node text="隐私协议" clickable="true"/>
        </hierarchy>''',
    )
    unread = _unread_for_page(ctx, hub.elements, {"《用户协议》", "用户协议"})
    assert unread is not None
    assert "隐私" in unread


def test_login_code_page_is_not_a_policy_document_body():
    page = parse_page(
        "com.example.smarthome.mine.activity.LoginCodeActivity",
        '''<hierarchy>
          <node class="android.widget.EditText" text="" resource-id="et_code" clickable="true"/>
          <node text="获取验证码" clickable="true"/>
          <node text="登录即同意《用户协议》" clickable="false"/>
        </hierarchy>''',
    )
    state = PageState()
    state.active_document = "com.example.smarthome.main.ui.WebActivity:document:用户协议"
    state.last_action = "scroll"
    assert _document_key(page.activity, page.elements, state) is None


def test_document_child_provenance_wins_over_login_shaped_webview():
    """A policy link may open a WebView whose accessibility tree mimics a login form."""
    page = parse_page(
        ".CActivity",
        '''<hierarchy>
          <node class="android.webkit.WebView" scrollable="true" clickable="false"/>
          <node class="android.widget.EditText" resource-id="web_phone" text="手机号" clickable="true"/>
          <node text="登录" resource-id="web_login" clickable="true" class="android.widget.Button"/>
        </hierarchy>''',
    )

    assert _is_login_gate(page.activity, page.elements)
    assert _document_key(page.activity, page.elements, PageState()) is None
    assert _document_key(
        page.activity, page.elements, PageState(), document_origin="《隐私政策》",
    ) == ".CActivity:document:隐私政策"


def test_settings_privacy_agreement_id_is_privacy_policy_not_service_terms():
    assert _infer_document_kind("com.app:id/cl_setting_privacy_agreement", "隐私协议") == "privacy_policy"
    page = parse_page(
        ".SettingActivity",
        '''<hierarchy>
          <node text="个人信息收集清单" resource-id="cl_setting_third_party_information" clickable="true"/>
          <node text="注销账号" clickable="true"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=None,
    )
    _mark_required_document_read(ctx, "个人信息收集清单", page_text="清单正文")
    assert _already_read_document_target(ctx, "cl_setting_third_party_information", page.elements)
    row = _hub_privacy_action_target(ctx, page.elements, {"cl_setting_third_party_information"})
    assert row == "注销账号"


def test_webview_collection_list_is_a_document_but_settings_row_is_not():
    settings = parse_page(
        ".SettingActivity",
        '''<hierarchy>
          <node text="隐私协议" clickable="true"/>
          <node text="个人信息收集清单" clickable="true"/>
          <node text="注销账号" clickable="true"/>
        </hierarchy>''',
    )
    assert _document_key(settings.activity, settings.elements, PageState()) is None

    body = parse_page(
        ".WebviewDetailActivity",
        '''<hierarchy>
          <node class="android.webkit.WebView" clickable="false">
            <node text="个人信息收集清单" clickable="true"/>
            <node text="《与第三方共享个人信息清单_示例》" clickable="true"/>
          </node>
          <node text="返回" resource-id="ll_back" clickable="true"/>
        </hierarchy>''',
    )
    assert _document_key(body.activity, body.elements, PageState()) is not None
    assert _is_document_body_hyperlink(
        "《与第三方共享个人信息清单_示例》", body.activity, body.elements,
    )
    assert not _is_document_body_hyperlink("ll_back", body.activity, body.elements)


def test_self_app_name_is_ignored_once_already_inside_the_audited_app():
    splash = "com.example.smarthome.main.ui.SplashActivity"
    assert _is_self_app_launch_click("案例B", splash, "com.example.smarthome", "案例B")
    assert not _is_self_app_launch_click("同意", splash, "com.example.smarthome", "案例B")
    assert not _is_self_app_launch_click(
        "案例B", "com.android.launcher3.Launcher", "com.example.smarthome", "案例B",
    )


def test_foreign_app_icon_click_is_blocked_while_inside_audited_app():
    splash = "com.example.smarthome.main.ui.SplashActivity"
    page = parse_page(
        splash,
        '''<hierarchy>
          <node text="同意" resource-id="com.example.smarthome:id/btn_agree" clickable="true"/>
          <node text="案例K" resource-id="com.android.launcher3:id/bubble_text"
                class="com.android.launcher3.BubbleTextView" clickable="true"/>
          <node text="隐私政策" resource-id="com.example.smarthome:id/privacy" clickable="true"/>
        </hierarchy>''',
    )
    assert _is_foreign_app_launch_click(
        "案例K", splash, "com.example.smarthome", "案例B", page.elements,
        foreground_package="com.example.smarthome",
    )
    assert not _is_foreign_app_launch_click(
        "同意", splash, "com.example.smarthome", "案例B", page.elements,
        foreground_package="com.example.smarthome",
    )
    assert not _is_foreign_app_launch_click(
        "隐私政策", splash, "com.example.smarthome", "案例B", page.elements,
        foreground_package="com.example.smarthome",
    )
    assert not _is_foreign_app_launch_click(
        "案例K", "com.android.launcher3.Launcher", "com.example.smarthome", "案例B",
        page.elements, foreground_package="com.android.launcher3",
    )


def test_leaving_audited_package_forces_recovery_except_system_surfaces():
    assert _has_left_audited_package(
        "com.example.reader.module.home.HomeActivity",
        "com.example.smarthome",
        foreground_package="com.example.reader",
    )
    assert not _has_left_audited_package(
        "com.android.launcher3.Launcher",
        "com.example.smarthome",
        foreground_package="com.android.launcher3",
    )
    assert not _has_left_audited_package(
        "com.example.smarthome.main.ui.SplashActivity",
        "com.example.smarthome",
        foreground_package="com.example.smarthome",
    )
    assert not _has_left_audited_package(
        "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity",
        "com.example.smarthome",
        foreground_package="com.android.permissioncontroller",
    )
    assert _is_allowed_non_audited_surface(
        "org.chromium.chrome.browser.customtabs.CustomTabActivity",
        "com.example.smarthome",
        foreground_package="com.android.chrome",
    )
    assert _is_allowed_non_audited_surface(
        "com.android.launcher3.Launcher",
        "com.example.smarthome",
        foreground_package="com.android.launcher3",
    )


def test_perception_ocr_covers_gates_and_hubs_but_not_policy_bodies():
    splash = parse_page(
        ".SplashActivity",
        '<hierarchy><node text="同意" clickable="true"/><node text="《隐私政策》" clickable="true"/></hierarchy>',
    )
    hub = parse_page(
        ".SettingActivity",
        '<hierarchy><node text="隐私政策" clickable="true"/><node text="注销账号" clickable="true"/></hierarchy>',
    )
    body = parse_page(
        ".WebviewDetailActivity",
        '<hierarchy><node text="隐私政策正文" clickable="false" class="android.webkit.WebView"/></hierarchy>',
    )
    assert _needs_perception_ocr(splash.activity, splash.elements)
    assert not _needs_perception_ocr(hub.activity, hub.elements)
    assert not _needs_perception_ocr(body.activity, body.elements)


def test_in_body_share_list_is_a_follow_target_after_parent_is_read():
    body = parse_page(
        ".WebviewDetailActivity",
        '''<hierarchy>
          <node class="android.webkit.WebView" clickable="false">
            <node text="个人信息收集清单" clickable="true"/>
            <node text="《与第三方共享个人信息清单_示例》" clickable="true"/>
          </node>
        </hierarchy>''',
    )
    assert _document_follow_target(
        body.elements, set(), ".WebviewDetailActivity:document:个人信息收集清单",
    ) == "《与第三方共享个人信息清单_示例》"
    assert _document_follow_target(
        body.elements, {"《与第三方共享个人信息清单_示例》"},
        ".WebviewDetailActivity:document:个人信息收集清单",
    ) is None


def test_finished_collection_list_opens_nested_share_disclosure(tmp_path):
    listing = (
        '<hierarchy>'
        '<node class="android.webkit.WebView" clickable="false">'
        '<node text="个人信息收集清单" clickable="true"/>'
        '<node text="《与第三方共享个人信息清单_示例》" clickable="true"/>'
        '</node>'
        '<node text="返回" resource-id="ll_back" clickable="true"/>'
        '</hierarchy>'
    )
    nested = (
        '<hierarchy>'
        '<node text="第三方共享个人信息清单正文" clickable="false" class="android.webkit.WebView"/>'
        '<node text="返回" resource-id="ll_back" clickable="true"/>'
        '</hierarchy>'
    )

    class _Client:
        def __init__(self):
            self.phase = "list"
            self.scrolls = 0
            self.actions = []

        def page(self):
            return (".WebviewDetailActivity", listing if self.phase == "list" else nested)

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return False

        def scroll_down(self):
            self.scrolls += 1
            return self.scrolls == 1

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision.get("action") == "click" and "第三方共享" in str(decision.get("target") or ""):
                self.phase = "nested"

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "观察"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "观察"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
            "mode_limits": {"fast": {"max_pages": 6}},
        }},
        data_dir=tmp_path,
        runtime={"consent_accepted": True, "sdk_observation_dwell_done": True, "privacy_hub_visited": True},
    )
    engine.run(ctx)
    assert any(
        action == "click" and "第三方共享" in str(target)
        for action, target in client.actions
    )


def test_settings_hub_sends_screen_text_to_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(
        explorer_module,
        "extract_words_from_image",
        lambda _path: [
            {"text": "关于我们", "left": 10, "top": 80, "width": 80, "height": 20},
            {"text": "版本信息", "left": 10, "top": 120, "width": 80, "height": 20},
        ],
    )
    seen = []

    class _Client:
        def page(self):
            return (
                ".SettingActivity",
                '<hierarchy>'
                '<node text="" resource-id="row_auth" clickable="true" bounds="[0,80][200,110]"/>'
                '<node text="" resource-id="row_cancel" clickable="true" bounds="[0,120][200,150]"/>'
                '</hierarchy>',
            )

        def activate(self, _package):
            pass

        def document_body_is_blank(self):
            return False

        def scroll_down(self):
            return False

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
                b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT"
                b"x\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND"
                b"\xaeB`\x82"
            )
            return True

        def perform(self, decision):
            pass

        def close(self):
            pass

    class _CaptureLLM:
        def choose_action(self, page, _visited):
            seen.append(page)
            return {"action": "stop", "target": "", "reason": "已观察设置页"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "已观察设置页"}

    engine = AppiumExplorerEngine(client=_Client(), llm=_CaptureLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"appium": {"page_wait_seconds": 0}, "detection": {
            "sdk_observation_dwell_seconds": 0, "page_settle_retries": 0,
            "mode_limits": {"fast": {"max_pages": 3}},
        }},
        data_dir=tmp_path,
        runtime={"consent_accepted": True, "sdk_observation_dwell_done": True, "privacy_hub_visited": True},
    )
    engine.run(ctx)
    assert seen
    assert "关于我们" in str(seen[0].get("screen_text") or "")


def test_logged_out_banner_is_recognized_as_login_entry():
    page = parse_page(
        ".MainActivity",
        '''<hierarchy>
          <node text="未登录" resource-id="tv_login_state" clickable="true"
                class="android.widget.TextView" bounds="[400,220][680,300]"/>
          <node text="更多设置" resource-id="ll_item_more_settings" clickable="true"
                class="android.widget.LinearLayout"/>
          <node text="我的" resource-id="navi_mine" clickable="true"/>
        </hierarchy>''',
    )
    assert _logged_out_profile_visible(page.elements)
    assert _profile_login_entry(page.elements) == "tv_login_state"


def test_logged_out_label_uses_enclosing_clickable_header():
    page = parse_page(
        ".MainActivity",
        '''<hierarchy>
          <node resource-id="cl_user_header" clickable="true" class="android.view.ViewGroup"
                bounds="[40,120][1040,360]">
            <node text="未登录" clickable="false" class="android.widget.TextView"
                  bounds="[400,220][680,300]"/>
          </node>
          <node text="更多设置" resource-id="ll_item_more_settings" clickable="true"/>
        </hierarchy>''',
    )
    assert _logged_out_profile_visible(page.elements)
    assert _profile_login_entry(page.elements) == "cl_user_header"


def test_hub_scroll_runs_even_without_scrollable_flag(tmp_path):
    settings = '''<hierarchy>
      <node text="通知设置" resource-id="cl_setting_notification_settings" clickable="true"/>
      <node text="隐私协议" resource-id="cl_setting_privacy_agreement" clickable="true"/>
    </hierarchy>'''
    scrolled = '''<hierarchy>
      <node text="注销账号" resource-id="cl_setting_logout" clickable="true"/>
      <node text="通知设置" resource-id="cl_setting_notification_settings" clickable="true"/>
    </hierarchy>'''

    class _Client:
        def __init__(self):
            self.phase = "top"
            self.actions = []
            self.scrolls = 0

        def page(self):
            return ".SettingActivity", scrolled if self.phase == "bottom" else settings

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def scroll_down(self):
            self.scrolls += 1
            self.phase = "bottom"
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))
            if decision["action"] == "click" and decision.get("target") == "cl_setting_logout":
                self.phase = "done"

        def close(self):
            pass

    class _LLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "cl_setting_notification_settings", "reason": "点通知"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def assess_login_state(self, _page):
            return False

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_LLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"detection": {
            "manual_login_wait_seconds": 0, "sdk_observation_dwell_seconds": 0,
            "mode_limits": {"fast": {"max_pages": 8}},
        }},
        data_dir=tmp_path,
        runtime={
            "consent_accepted": True, "sdk_observation_dwell_done": True,
            "privacy_hub_visited": True, "manual_login_verified": True,
        },
    )
    result = engine.run(ctx)
    assert client.scrolls >= 1
    assert any(action == "click" and "logout" in str(target) for action, target in client.actions)
    event_types = {item.get("meta", {}).get("event_type") for item in result.evidence_files}
    assert "privacy_hub_scrolled" in event_types or "privacy_path_row_prioritized" in event_types


def test_next_hub_exploration_skips_notification_settings():
    page = parse_page(
        ".SettingActivity",
        '''<hierarchy>
          <node text="通知设置" resource-id="cl_setting_notification_settings" clickable="true"/>
          <node text="隐私协议" resource-id="cl_setting_privacy_agreement" clickable="true"/>
          <node text="固件升级" resource-id="cl_firmware" clickable="true"/>
        </hierarchy>''',
    )
    assert _next_hub_exploration_target(page.elements, set()) == "cl_setting_privacy_agreement"
    assert _next_hub_exploration_target(
        page.elements, {"cl_setting_privacy_agreement"},
    ) != "cl_setting_notification_settings"


def test_logged_out_profile_is_clicked_before_more_settings(tmp_path):
    profile = '''<hierarchy>
      <node text="未登录" resource-id="tv_login_state" clickable="true"/>
      <node text="更多设置" resource-id="ll_item_more_settings" clickable="true"/>
      <node text="我的" resource-id="navi_mine" clickable="true"/>
    </hierarchy>'''

    class _Client:
        def __init__(self):
            self.actions = []

        def page(self):
            return ".MainActivity", profile

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append((decision["action"], decision.get("target", "")))

        def close(self):
            pass

    class _LLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "ll_item_more_settings", "reason": "不该先点设置"}

        def fallback_action(self, *_args):
            return {"action": "stop", "target": "", "reason": "done"}

        def assess_login_state(self, _page):
            return False

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_LLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"detection": {
            "manual_login_wait_seconds": 0, "sdk_observation_dwell_seconds": 0,
            "mode_limits": {"fast": {"max_pages": 4}},
        }},
        data_dir=tmp_path,
        runtime={"consent_accepted": True, "sdk_observation_dwell_done": True, "privacy_hub_visited": True},
    )
    engine.run(ctx)
    assert client.actions
    assert client.actions[0][0] == "click"
    assert client.actions[0][1] == "tv_login_state"


def test_explorer_enforces_configured_duration_deadline(tmp_path, monkeypatch):
    clock = iter((100.0, 101.0))
    monkeypatch.setattr(explorer_module.time, "monotonic", lambda: next(clock))
    class _DeadlineClient:
        def __init__(self):
            self.page_reads = 0

        def activate(self, _package):
            pass

        def page(self):
            self.page_reads += 1
            return ".MainActivity", '<hierarchy><node text="首页" clickable="false"/></hierarchy>'

        def close(self):
            pass

    client = _DeadlineClient()
    engine = AppiumExplorerEngine(client=client, llm=SimpleNamespace())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"detection": {"mode_limits": {"fast": {
            "max_pages": 10, "max_duration_minutes": 0.001,
        }}}},
        data_dir=tmp_path,
    )

    result = engine.run(ctx)

    assert client.page_reads == 0
    assert ctx.runtime["traversal_termination"]["kind"] == "duration_limit_reached"
    assert result.stats["coverage_complete"] is False


def test_hub_progress_prefers_delete_logout_then_avatar_when_docs_already_read():
    from agent.ai_explorer.explorer_engine import _hub_progress_target

    page = parse_page(
        ".AvatarSettingActivity",
        '''<hierarchy>
          <node text="个人信息" clickable="false"/>
          <node text="头像" resource-id="oi_headimage" clickable="true"/>
          <node text="隐私政策" resource-id="privacy_policy" clickable="true"/>
          <node text="退出账号" resource-id="logout" clickable="true"/>
          <node text="手机号" resource-id="phone_row" clickable="true"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={}, data_dir=SimpleNamespace(),
    )
    ctx.runtime = {
        "read_document_kinds": {"privacy_policy"},
        "read_document_titles": {"隐私政策"},
    }
    ctx.cfg = {"detection": {"explore_logout_confirmation": True}}
    # Opt-in allow/observe audits may inspect a reversible logout confirmation.
    target = _hub_progress_target(ctx, page.elements, set())
    assert target == "logout"
    ctx.runtime["logout_entry_explored"] = True
    target2 = _hub_progress_target(ctx, page.elements, {"logout"})
    assert target2 == "oi_headimage"
    target3 = _hub_progress_target(ctx, page.elements, {"logout", "oi_headimage"})
    assert target3 == "phone_row"


def test_profile_form_does_not_misclassify_birthday_or_location_as_settings_drill():
    from agent.ai_explorer.explorer_engine import(
        _hub_drill_target,
        _hub_progress_target,
        _permission_related_hub_drill_target,
    )

    page = parse_page(
        ".PersonalDataActivity",
        '''<hierarchy>
          <node text="个人信息" clickable="false" bounds="[0,0][1080,180]"/>
          <node text="头像" clickable="false" bounds="[20,200][180,300]"/>
          <node text="" resource-id="com.demo:id/head_image" clickable="true" bounds="[780,180][980,340]"/>
          <node text="生日" resource-id="com.demo:id/ll_personal_birthday" clickable="true" bounds="[0,360][1080,520]"/>
          <node text="地区" resource-id="com.demo:id/ll_personal_location" clickable="true" bounds="[0,520][1080,680]"/>
          <node text="退出登录" resource-id="com.demo:id/btn_exit_login" clickable="true" bounds="[0,900][1080,1060]"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo"),
        cfg={"detection": {"permission_probe_action": "deny"}},
        data_dir=SimpleNamespace(), runtime={},
    )
    assert _hub_drill_target(page.elements, set()) is None
    assert _hub_progress_target(ctx, page.elements, set()) == "com.demo:id/head_image"
    assert _permission_related_hub_drill_target(page.elements, {"com.demo:id/head_image"}) is None


def test_personalized_recommendation_setting_is_not_a_privacy_hub_fallback():
    from agent.ai_explorer.explorer_engine import _hub_drill_target

    page = parse_page(
        ".GuideActivity",
        '''<hierarchy>
          <node text="《个性精准推荐设置》" resource-id="com.demo:id/tv_auto_greet" clickable="true"/>
        </hierarchy>''',
    )

    assert _hub_drill_target(page.elements, set()) is None
    assert _next_hub_exploration_target(page.elements, set()) is None


def test_allow_phase_hub_drill_ignores_documents_and_prefers_personal_info():
    page = parse_page(
        ".SettingActivity",
        '''<hierarchy>
          <node text="隐私政策" resource-id="privacy" clickable="true"/>
          <node text="服务协议" resource-id="terms" clickable="true"/>
          <node text="个人信息" resource-id="personal_info" clickable="true"/>
          <node text="清除缓存" resource-id="clear_cache" clickable="true"/>
        </hierarchy>''',
    )
    assert explorer_module._permission_related_hub_drill_target(
        page.elements, set(),
    ) == "personal_info"


def test_service_terms_body_resolves_user_agreement_family_coverage_gap(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={}, data_dir=tmp_path,
        runtime={
            "policy_document_read_complete": True,
            "seen_document_kinds": {"user_agreement"},
            "read_document_kinds": {"service_terms"},
        },
    )
    gaps = _coverage_gaps(ctx, 0, False, 4, {"remaining_items": []})
    assert "可见的用户服务协议/服务条款未完成阅读" not in gaps


def test_profile_stats_and_attribute_editors_are_low_audit_value():
    stats = parse_page(
        ".WritingStatsActivity",
        '''<hierarchy><node text="作品数 12" clickable="false"/><node text="章节数 81" clickable="true"/>
        <node text="总字数 120000" clickable="true"/><node text="近7天 3000字" clickable="true"/></hierarchy>''',
    )
    location = parse_page(
        ".LocationSetActivity",
        '''<hierarchy><node text="选择地区" clickable="false"/><node text="北 京" clickable="true"/>
        <node text="天 津" clickable="true"/><node text="河 北 省" clickable="true"/></hierarchy>''',
    )
    assert _low_audit_value_surface_kind(stats.activity, stats.elements) == "usage_statistics"
    assert _low_audit_value_surface_kind(location.activity, location.elements) == "profile_attribute_editor"


def test_deny_hub_defers_logout_and_delete_until_sensitive_probe_runs():
    from agent.ai_explorer.explorer_engine import(
        _hub_privacy_action_target,
        _hub_progress_target,
        _logout_entry_exploration_target,
    )

    page = parse_page(
        ".ProfileActivity",
        '''<hierarchy>
          <node text="头像" clickable="false"/>
          <node text="" resource-id="head_image" clickable="true"/>
          <node text="注销账号" resource-id="delete_account" clickable="true"/>
          <node text="退出登录" resource-id="logout" clickable="true"/>
          <node text="手机号" resource-id="phone_row" clickable="true"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {
            "permission_probe_action": "deny",
            "explore_logout_confirmation": True,
        }},
        data_dir=SimpleNamespace(),
        runtime={},
    )

    assert _hub_progress_target(ctx, page.elements, set()) == "head_image"
    assert _hub_privacy_action_target(ctx, page.elements, set()) is None
    assert _logout_entry_exploration_target(ctx, page.elements, set()) is None


def test_profile_avatar_sibling_label_makes_head_image_a_sensitive_probe():
    from agent.ai_explorer.explorer_engine import _hub_avatar_probe_target

    page = parse_page(
        ".ProfileActivity",
        '''<hierarchy>
          <node text="个人信息" clickable="false"/>
          <node text="头像" clickable="false" bounds="[20,100][180,180]"/>
          <node text="" resource-id="head_image" clickable="true" bounds="[800,80][980,260]"/>
        </hierarchy>''',
    )
    assert _hub_avatar_probe_target(page.elements, set()) == "head_image"


def test_semantic_sensitive_ignores_home_chrome_image_ids():
    from agent.ai_explorer.explorer_engine import _semantic_sensitive_business_control

    home = parse_page(
        ".HomeActivity",
        '''<hierarchy>
          <node text="" resource-id="com.demo:id/head_image" clickable="true"/>
          <node text="" resource-id="com.demo:id/history_image" clickable="true"/>
          <node text="我" resource-id="tab_mine" clickable="true"/>
        </hierarchy>''',
    )
    assert _semantic_sensitive_business_control(home.elements) is None
    assert _semantic_sensitive_business_control(home.elements, allow_nav_chrome=False) is None

    profile = parse_page(
        ".ProfileActivity",
        '''<hierarchy>
          <node text="头像" resource-id="oi_headimage" clickable="true"/>
        </hierarchy>''',
    )
    assert _semantic_sensitive_business_control(
        profile.elements, allow_nav_chrome=False, require_avatar_or_upload=True,
    ) == "oi_headimage"


def test_privacy_hub_tab_preferred_on_home_even_if_hub_visited_flag_set(tmp_path):
    home = '''<hierarchy>
      <node text="推荐" resource-id="tab_recommend" clickable="true"/>
      <node text="" resource-id="com.demo:id/head_image" clickable="true"/>
      <node text="我" resource-id="tab_mine" clickable="true"/>
    </hierarchy>'''
    profile = '''<hierarchy>
      <node text="个人信息" clickable="false"/>
      <node text="头像" resource-id="oi_headimage" clickable="true"/>
      <node text="隐私政策" resource-id="privacy_row" clickable="true"/>
    </hierarchy>'''

    class _Client:
        def __init__(self):
            self.index = 0
            self.actions = []

        def page(self):
            return ((".HomeActivity", home), (".AvatarSettingActivity", profile))[min(self.index, 1)]

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append(decision)
            if decision.get("action") == "click" and decision.get("target") == "tab_mine":
                self.index = 1

        def close(self):
            pass

    class _StopLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "com.demo:id/head_image", "reason": "wrong chrome"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "stop", "target": "", "reason": "done"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"detection": {
            "sdk_observation_dwell_seconds": 0,
            "mode_limits": {"deep": {"max_pages": 4}},
        }},
        data_dir=tmp_path,
        runtime={
            "consent_accepted": True,
            "sdk_observation_dwell_done": True,
            "privacy_hub_visited": True,
            "sdk_observation_permissions_granted": False,
        },
    )
    engine.run(ctx)
    assert client.actions
    assert client.actions[0]["target"] == "tab_mine"


def test_profile_hub_duplicate_avatar_advances_to_other_row(tmp_path):
    profile = '''<hierarchy>
      <node text="个人信息" clickable="false"/>
      <node text="头像" resource-id="oi_headimage" clickable="true"/>
      <node text="手机号" resource-id="phone_row" clickable="true"/>
      <node text="退出账号" resource-id="logout" clickable="true"/>
    </hierarchy>'''

    class _Client:
        def __init__(self):
            self.actions = []

        def page(self):
            return ".AvatarSettingActivity", profile

        def activate(self, _package):
            pass

        def screenshot(self, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"image")
            return True

        def perform(self, decision):
            self.actions.append(decision)

        def close(self):
            pass

    class _AlwaysAvatarLLM:
        def choose_action(self, *_args):
            return {"action": "click", "target": "oi_headimage", "reason": "avatar again"}

        def fallback_action(self, *_args, **_kwargs):
            return {"action": "click", "target": "oi_headimage", "reason": "avatar again"}

    client = _Client()
    engine = AppiumExplorerEngine(client=client, llm=_AlwaysAvatarLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo", permissions=[]),
        cfg={"detection": {
            "sdk_observation_dwell_seconds": 0,
            "mode_limits": {"deep": {"max_pages": 5}},
        }},
        data_dir=tmp_path,
        runtime={
            "consent_accepted": True,
            "sdk_observation_dwell_done": True,
            "privacy_hub_visited": True,
        },
    )
    engine.run(ctx)
    targets = [item.get("target") for item in client.actions if item.get("action") == "click"]
    assert "oi_headimage" in targets
    assert "phone_row" in targets
    # Logout is observation-only by default: do not assume every App presents
    # a reversible confirmation dialog. Other sibling rows must still advance.
    assert targets.count("logout") == 0


def test_media_chooser_matches_camera_and_album_family():
    from agent.ai_explorer.explorer_engine import(
        _hub_list_may_need_swipe,
        _hub_progress_target,
        _media_album_chooser_target,
        _media_capture_chooser_target,
    )

    page = parse_page(
        ".AvatarSettingEditActivity",
        '''<hierarchy>
          <node text="请选择图片来源" clickable="false"/>
          <node text="照相机" resource-id="com.example.reader:id/tv_camera" clickable="true"/>
          <node text="相册" resource-id="com.example.reader:id/tv_file" clickable="true"/>
          <node text="取消" resource-id="cancel" clickable="true"/>
        </hierarchy>''',
    )
    assert _media_capture_chooser_target(page.elements) == "com.example.reader:id/tv_camera"
    assert _media_album_chooser_target(page.elements) == "com.example.reader:id/tv_file"
    assert _hub_list_may_need_swipe(page) is False

    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.example.reader"),
        cfg={}, data_dir=SimpleNamespace(),
        runtime={},
    )
    assert _hub_progress_target(ctx, page.elements, set()) == "com.example.reader:id/tv_camera"
    assert _hub_progress_target(ctx, page.elements, {"com.example.reader:id/tv_camera"}) == "com.example.reader:id/tv_file"


def test_avatar_edit_form_does_not_swipe_for_withdraw_hunt():
    from agent.ai_explorer.explorer_engine import _hub_list_may_need_swipe

    page = parse_page(
        ".AvatarSettingEditActivity",
        '''<hierarchy>
          <node text="头像" resource-id="oi_headimage" clickable="true"/>
          <node text="昵称" resource-id="nickname" clickable="true"/>
          <node text="编辑资料" clickable="false"/>
        </hierarchy>''',
    )
    assert _hub_list_may_need_swipe(page) is False


def test_consent_dialog_unread_for_page_prioritizes_bounded_policy_probe():
    page = parse_page(
        ".SplashActivity",
        '''<hierarchy>
          <node text="请阅读《隐私政策》《用户协议》《第三方SDK目录》" clickable="false"/>
          <node text="《隐私政策》" clickable="true"/>
          <node text="同意" resource-id="ok" clickable="true"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=SimpleNamespace(),
        runtime={},
    )
    assert _is_consent_dialog(page.elements)
    assert _unread_for_page(ctx, page.elements, set()) == "《隐私政策》"


def test_hub_personal_info_still_prioritizes_privacy_policy_rows():
    page = parse_page(
        ".AvatarSettingActivity",
        '''<hierarchy>
          <node text="个人信息" clickable="false"/>
          <node text="头像" resource-id="oi_headimage" clickable="true"/>
          <node text="服务协议" resource-id="service" clickable="true"/>
          <node text="隐私政策" resource-id="privacy" clickable="true"/>
          <node text="第三方SDK目录" resource-id="sdk" clickable="true"/>
          <node text="退出账号" resource-id="logout" clickable="true"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.example.reader"),
        cfg={}, data_dir=SimpleNamespace(),
        runtime={"consent_accepted": True},
    )
    assert _unread_for_page(ctx, page.elements, set()) in {"privacy", "隐私政策"}


def test_in_app_permission_rationale_prefers_ok_button():
    from agent.ai_explorer.explorer_engine import _in_app_permission_rationale_continue_target

    page = parse_page(
        ".AvatarSettingEditActivity",
        '''<hierarchy>
          <node text="请选择图片来源" clickable="false"/>
          <node text="照相机" resource-id="tv_camera" clickable="true"/>
          <node text="相册" resource-id="tv_file" clickable="true"/>
          <node text="权限申请" clickable="false"/>
          <node text="为了你能正常使用，需要以下权限" clickable="false"/>
          <node text="使用摄像头" clickable="false"/>
          <node text="允许应用进行拍照，App修改用户头像使用" clickable="false"/>
          <node text="取消" resource-id="cancel" clickable="true"/>
          <node text="好的" resource-id="btn_ok" clickable="true"/>
        </hierarchy>''',
    )
    assert _in_app_permission_rationale_continue_target(page.elements) in {"好的", "btn_ok"}


def test_third_app_privacy_activity_is_document_body():
    from agent.ai_explorer.explorer_engine import _has_document_body_surface

    page = parse_page(
        "com.example.module.ThirdAppPrivacyActivity",
        '''<hierarchy>
          <node text="第三方SDK目录" clickable="false"/>
          <node text="极光推送 SDK" clickable="false"/>
          <node text="收集的信息：设备标识、网络信息" clickable="false"/>
          <node text="使用目的：消息推送" clickable="false"/>
          <node text="申请的权限：网络" clickable="false"/>
        </hierarchy>''',
    )
    assert _has_document_body_surface(page.activity, page.elements)
    assert _page_role(page.activity, page.elements, PageState()) == "document_body"
    assert _document_key(page.activity, page.elements, PageState())


def test_block_document_route_suppresses_alternate_sdk_target():
    from agent.ai_explorer.explorer_engine import _block_document_route

    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={}, data_dir=SimpleNamespace(),
    )
    _block_document_route(ctx, "oi_third_app_sdk", kind="disclosure_list")
    page = parse_page(
        ".SettingActivity",
        '''<hierarchy>
          <node text="第三方SDK目录" resource-id="oi_third_app_sdk" clickable="true"/>
          <node text="隐私政策" resource-id="oi_private" clickable="true"/>
        </hierarchy>''',
    )
    unread = _unread_for_page(ctx, page.elements, set())
    assert unread in {"oi_private", "隐私政策"}
    assert unread not in {"oi_third_app_sdk", "第三方SDK目录"}


def test_privacy_hub_tab_falls_back_to_head_image():
    page = parse_page(
        ".HomeActivity",
        '''<hierarchy>
          <node text="" resource-id="com.example.reader:id/head_image" clickable="true"/>
          <node text="书城" resource-id="tab_bookstore" clickable="true"/>
        </hierarchy>''',
    )
    assert "head_image" in str(_privacy_hub_tab_target(page.elements) or "")


def test_explorer_keeps_business_trigger_across_in_app_rationale(tmp_path):
    rationale = (
        '<hierarchy>'
        '<node text="权限申请" clickable="false"/>'
        '<node text="使用摄像头" clickable="false"/>'
        '<node text="好的" resource-id="btn_ok" clickable="true"/>'
        '<node text="取消" resource-id="cancel" clickable="true"/>'
        '</hierarchy>'
    )

    class _RationaleClient(_PermissionClient):
        def page(self):
            pages = [
                (".ProfileActivity", _APP_FUNCTION),
                (".AvatarEditActivity", rationale),
                ("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity", _CAMERA_PROMPT),
                (".ProfileActivity", _DENIED_FUNCTION),
            ]
            return pages[self.index]

        def perform(self, decision):
            target = str(decision.get("target") or "")
            if self.index == 0 and decision.get("action") == "click":
                self.index = 1
            elif self.index == 1 and decision.get("action") == "click" and (
                "好的" in target or "btn_ok" in target
            ):
                self.index = 2

        def respond_to_permission(self, action):
            self.responses.append(action)
            self.index = 3

    client = _RationaleClient()
    engine = AppiumExplorerEngine(client=client, llm=_StopLLM())
    engine._prepared = True
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {
            "permission_probe_action": "deny", "permission_probe_post_steps": 4,
            "mode_limits": {"fast": {"max_pages": 10}},
        }},
        data_dir=tmp_path,
        runtime={"consent_accepted": True, "consent_timestamp_ms": 1},
    )

    result = engine.run(ctx)

    assert client.responses == ["deny"]
    assert any(item.kind == "permission_denial_blocks_function" for item in result.findings)
    assert not any(
        item["meta"].get("event_type") == "permission_denial_not_bound_to_business_action"
        for item in result.evidence_files if item["type"] == "timeline"
    )


def test_redirect_after_ignored_app_icon_prefers_hub_then_stops():
    from agent.ai_explorer.explorer_engine import _redirect_after_ignored_app_icon

    page = parse_page(
        ".HomeActivity",
        '''<hierarchy>
          <node text="我的" resource-id="tab_mine" clickable="true"/>
          <node text="书城" resource-id="tab_bookstore" clickable="true"/>
        </hierarchy>''',
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"detection": {"home_idle_cycle_limit": 2}},
        data_dir=SimpleNamespace(),
        runtime={"consent_accepted": True},
    )
    state = PageState()
    first = _redirect_after_ignored_app_icon(
        ctx, state, page, consent_accepted=True, settings_hub=False, hub_pending=True,
    )
    assert first["action"] == "click"
    assert "tab_mine" in str(first.get("target") or "") or first.get("target") == "我的"
    state.mark_target(page, first["target"])
    second = _redirect_after_ignored_app_icon(
        ctx, state, page, consent_accepted=True, settings_hub=False, hub_pending=True,
    )
    third = _redirect_after_ignored_app_icon(
        ctx, state, page, consent_accepted=True, settings_hub=False, hub_pending=True,
    )
    assert second["action"] == "wait" or second["source"] == "home_idle_exhausted"
    assert third["action"] == "stop"
    assert third["source"] == "home_idle_exhausted"


def test_media_chooser_exclude_polls_alternate_camera_control():
    from agent.ai_explorer.explorer_engine import(
        _iter_media_capture_chooser_targets,
        _media_capture_chooser_target,
        _media_family_of,
        _next_media_family_candidate,
    )

    page = parse_page(
        ".ChooserActivity",
        '''<hierarchy>
          <node text="拍照" resource-id="btn_take" clickable="true"/>
          <node text="照相机" resource-id="tv_camera" clickable="true"/>
          <node text="相册" resource-id="tv_album" clickable="true"/>
        </hierarchy>''',
    )
    first = _media_capture_chooser_target(page.elements)
    assert first in {"btn_take", "tv_camera", "拍照", "照相机"}
    rest = _iter_media_capture_chooser_targets(page.elements, exclude={first})
    assert rest
    assert first not in rest
    assert _media_family_of("拍照 tv_camera") == "camera"
    assert _media_family_of("相册 gallery") == "album"
    assert _media_family_of("按住说话 mic") == "voice"
    next_one = _next_media_family_candidate(
        ["mic_btn", "tv_camera", "tv_album"],
        elements=[
            {"target": "mic_btn", "text": "语音", "content_desc": "", "resource_id": "mic_btn", "clickable": True},
            {"target": "tv_camera", "text": "拍照", "content_desc": "", "resource_id": "tv_camera", "clickable": True},
            {"target": "tv_album", "text": "相册", "content_desc": "", "resource_id": "tv_album", "clickable": True},
        ],
        attempted={"mic_btn"},
    )
    assert next_one == "tv_camera"


def test_disclosure_list_intent_covers_shared_and_sdk_synonyms():
    assert _required_document_kind("第三方SDK清单") == "disclosure_list"
    assert _required_document_kind("个人信息共享清单") == "disclosure_list"
    assert _required_document_kind("应用权限说明") == "disclosure_list"
    assert _required_document_kind("隐私条款") == "privacy_policy"


def test_hidden_custom_crash_nodes_do_not_turn_returned_parent_into_crash():
    """Hidden crash-library nodes must not trigger a second Back after camera."""
    page = parse_page(
        ".module.setting.AvatarSettingEditActivity",
        '''<hierarchy>
          <node text="个人信息" resource-id="com.demo:id/title" displayed="true"/>
          <node text="头像" resource-id="com.demo:id/avatar" clickable="true" displayed="true"/>
          <node text="An unexpected error occurred."
                resource-id="com.demo:id/customactivityoncrash_message" displayed="false"/>
          <node text="RESTART APP"
                resource-id="com.demo:id/customactivityoncrash_error_activity_restart_button"
                clickable="true" displayed="false"/>
          <node text="ERROR DETAILS"
                resource-id="com.demo:id/customactivityoncrash_error_activity_more_info_button"
                clickable="true" displayed="false"/>
        </hierarchy>''',
    )
    visible_text = explorer_module._page_visible_text(page.elements)
    assert explorer_module._crash_reason(page.activity, page.elements, visible_text) is None
    assert not explorer_module._is_custom_crash_surface(page.elements, visible_text)


def test_profile_tab_wins_over_leaked_launcher_node_with_the_same_label():
    page = parse_page(
        ".module.home.HomeActivity",
        '''<hierarchy>
          <node text="我" resource-id="com.example.reader:id/tab_mine" clickable="true"
                bounds="[300,700][400,800]" displayed="true"/>
          <node text="我" resource-id="com.android.launcher3:id/bubble_text"
                clickable="true" bounds="[0,0][100,100]" displayed="false"/>
        </hierarchy>''',
    )
    assert not _is_foreign_app_launch_click(
        "我", page.activity, "com.example.reader", "案例K", page.elements,
        foreground_package="com.example.reader",
    )
    assert not _is_foreign_app_launch_click(
        "& 我", page.activity, "com.example.reader", "案例K", page.elements,
        foreground_package="com.example.reader",
    )


def test_account_maintenance_verification_pages_are_not_manual_login_gates():
    delete_page = parse_page(
        ".kt.WebViewKT",
        '''<hierarchy>
          <node text="是否确认注销易行账号" clickable="false"/>
          <node text="手机号" resource-id="phone" class="android.widget.EditText" clickable="true"/>
          <node text="验证码" resource-id="verify_code" class="android.widget.EditText" clickable="true"/>
          <node text="获取验证码" resource-id="get_code" clickable="true"/>
          <node text="确认" resource-id="confirm_delete" clickable="true"/>
          <node text="暂不注销" resource-id="cancel_delete" clickable="true"/>
        </hierarchy>''',
    )
    change_phone = parse_page(
        ".AccountSecurityActivity",
        '''<hierarchy>
          <node text="更换手机号" clickable="false"/>
          <node text="新手机号" resource-id="new_phone" class="android.widget.EditText" clickable="true"/>
          <node text="短信验证码" resource-id="sms_code" class="android.widget.EditText" clickable="true"/>
          <node text="获取验证码" resource-id="get_code" clickable="true"/>
          <node text="确认更换" resource-id="confirm_change" clickable="true"/>
        </hierarchy>''',
    )

    assert not _is_login_gate(delete_page.activity, delete_page.elements)
    assert not _is_login_gate(change_phone.activity, change_phone.elements)


def test_long_policy_mentions_redress_words_without_becoming_a_customer_service_surface():
    text = (
        "隐私政策 我们如何收集和使用个人信息。您可联系客服进行投诉，"
        "也可发送文件说明问题。我们会保护您的设备信息、位置信息和账号信息。"
    ) * 8

    assert not _is_redress_interaction_surface(".WebViewActivity", text)


def test_real_redress_composer_with_unlabeled_bottom_icons_remains_explorable():
    page = parse_page(
        ".WebViewActivity",
        '''<hierarchy>
          <node text="意见反馈" clickable="false" bounds="[0,0][1080,120]"/>
          <node text="请输入问题描述" class="android.widget.EditText" clickable="true"
                bounds="[120,1780][760,1940]"/>
          <node text="" resource-id="toolbar_attach" class="android.widget.ImageButton"
                clickable="true" bounds="[870,1780][1030,1940]"/>
        </hierarchy>''',
    )
    text = explorer_module._page_visible_text(page.elements)

    assert explorer_module._is_redress_interaction_surface(page.activity, text, page.elements)
    assert _customer_service_sensitive_control(page.activity, page.elements, text) == "toolbar_attach"


def test_redress_title_plus_icon_toolbar_is_explorable_when_webview_hides_composer_text():
    page = parse_page(
        ".WebViewActivity",
        '''<hierarchy>
          <node text="在线客服" clickable="false" bounds="[0,0][1080,120]"/>
          <node text="" resource-id="bottom_more" class="android.widget.ImageButton"
                clickable="true" bounds="[880,1780][1040,1940]"/>
        </hierarchy>''',
    )
    text = explorer_module._page_visible_text(page.elements)

    assert explorer_module._is_redress_interaction_surface(page.activity, text, page.elements)
    assert _customer_service_sensitive_control(page.activity, page.elements, text) == "bottom_more"


def test_logout_confirmation_prefers_explicit_safe_dismiss_control():
    page = parse_page(
        ".SettingsActivity",
        '''<hierarchy>
          <node text="确定退出登录吗？" clickable="false"/>
          <node text="确认退出" resource-id="confirm" clickable="true"/>
          <node text="再想想" resource-id="think_again" clickable="true"/>
        </hierarchy>''',
    )

    assert explorer_module._logout_confirmation_cancel_target(page.elements) == "think_again"


def test_in_app_account_text_is_not_guessed_to_be_a_foreign_launcher_icon():
    page = parse_page(
        ".module.home.HomeActivity",
        '''<hierarchy>
          <node text="我的" resource-id="tab_mine" clickable="true"/>
          <node text="13800138001" clickable="true"/>
        </hierarchy>''',
    )

    assert not _is_foreign_app_launch_click(
        "13800138001", page.activity, "com.example.reader", "案例K", page.elements,
        foreground_package="com.example.reader",
    )


def test_settings_maintenance_actions_are_pruned_from_deep_hub_search():
    page = parse_page(
        ".SettingsActivity",
        '''<hierarchy>
          <node text="清除缓存" resource-id="settings_clear_cache" clickable="true"/>
          <node text="检查更新" resource-id="settings_check_update" clickable="true"/>
        </hierarchy>''',
    )

    assert _next_hub_exploration_target(page.elements, set()) is None
    assert explorer_module._is_low_audit_value_route("settings_clear_cache", page.elements)


def test_generic_display_metadata_and_website_routes_are_pruned():
    page = parse_page(
        ".SettingsActivity",
        '''<hierarchy>
          <node text="版本说明" resource-id="version_notes" clickable="true"/>
          <node text="主题色" resource-id="theme_color" clickable="true"/>
          <node text="屏幕方向" resource-id="screen_orientation" clickable="true"/>
          <node text="好评鼓励" resource-id="rate_app" clickable="true"/>
          <node text="口袋官网" resource-id="official_website" clickable="true"/>
          <node text="APP备案号" resource-id="icp_record" clickable="true"/>
          <node text="字数统计" resource-id="word_count" clickable="true"/>
        </hierarchy>''',
    )

    for target in (
        "version_notes", "theme_color", "screen_orientation", "rate_app",
        "official_website", "icp_record", "word_count",
    ):
        assert explorer_module._is_low_audit_value_route(target, page.elements)


def test_top_level_deep_search_prefers_unvisited_redress_then_other_tabs():
    page = parse_page(
        ".MainActivity",
        '''<hierarchy>
          <node text="首页" resource-id="tab_home" clickable="true" selected="false"
                bounds="[0,1800][270,2000]"/>
          <node text="投诉反馈" resource-id="tab_feedback" clickable="true" selected="false"
                bounds="[270,1800][540,2000]"/>
          <node text="我的" resource-id="tab_mine" clickable="true" selected="true"
                bounds="[810,1800][1080,2000]"/>
        </hierarchy>''',
    )

    first = explorer_module._next_top_level_audit_target(page.elements, set())
    first_key = _global_target_key("", first, page.elements)
    second = explorer_module._next_top_level_audit_target(page.elements, {first_key})

    assert first == "tab_feedback"
    assert second == "tab_home"


def test_completed_document_route_is_not_reopened_in_second_probe_phase(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(), cfg={},
        data_dir=tmp_path,
        runtime={
            "completed_document_routes": {"com.example.reader:id/oi_third_app_sdk"},
        },
    )
    page = parse_page(
        ".module.setting.AvatarSettingActivity",
        '''<hierarchy><node text="第三方SDK目录"
          resource-id="com.example.reader:id/oi_third_app_sdk" clickable="true"/></hierarchy>''',
    )
    assert explorer_module._already_read_document_target(
        ctx, "com.example.reader:id/oi_third_app_sdk", page.elements,
    )


def test_home_idle_stop_is_terminal_and_not_revived_by_deep_search():
    assert not explorer_module._stop_override_allowed("home_idle_exhausted")
    assert not explorer_module._stop_override_allowed("safety_boundary")
    assert explorer_module._stop_override_allowed("llm")


def test_completed_denial_probe_closes_repeated_permission_rationale(tmp_path):
    page = parse_page(
        ".ProfileActivity",
        '''<hierarchy><node text="权限申请"/><node text="好的"
          resource-id="okButton" clickable="true"/></hierarchy>''',
    )
    state = PageState()
    state.mark_target(page, "okButton")
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(), cfg={},
        data_dir=tmp_path, runtime={"permission_denial_probe_terminal": True},
    )
    decision = explorer_module._permission_rationale_decision(
        ctx, state, page, "okButton",
    )
    assert decision["action"] == "back"


def test_deep_search_override_blocked_when_consent_dialog_seen_this_phase():
    """任务 281 回归：同意弹窗页上 LLM 的 wait 被改成点击「Appium Settings」。

    元素级 _is_consent_dialog 可能在探测返回后失判；深搜覆盖必须同时尊重
    本页周期的 consent 事实与阶段内 consent_dialog_seen 台账。
    """
    assert explorer_module._deep_search_consent_blocked(True, False)
    assert explorer_module._deep_search_consent_blocked(False, True)
    assert not explorer_module._deep_search_consent_blocked(False, False)


def test_document_session_skip_helper_flags_only_already_read_kinds(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="deep"), apk=SimpleNamespace(package_name="com.demo"),
        cfg={}, data_dir=tmp_path, runtime={"read_document_kinds": {"privacy_policy"}},
    )

    assert explorer_module._document_session_already_read(
        ctx, document_origin="《隐私政策》", page_text="",
    ) == "privacy_policy"
    assert explorer_module._document_session_already_read(
        ctx, document_origin="《服务协议》", page_text="",
    ) is None
    assert explorer_module._document_session_already_read(
        ctx, document_origin="", page_text="完全无关的页面文字",
    ) is None


def test_skip_already_read_document_closes_session_every_viewport_but_flags_once():
    """后续视口必须持续跳过（不能因 completed_keys 反选而重新开卷），
    但可见的 document_already_read_skip 事件每个文档键只发一次。"""
    state = PageState()

    assert explorer_module._skip_already_read_document(state, "doc-key") is True
    assert explorer_module._skip_already_read_document(state, "doc-key") is False
    assert explorer_module._skip_already_read_document(state, "doc-key") is False
    assert "doc-key" in state.documents.completed_keys()
