from types import SimpleNamespace

from agent.ai_explorer.page_state import PageState
from agent.ai_explorer.explorer_engine import (
    _denial_blocks_base_service,
    _global_target_key,
    _mark_required_document_read,
    _permission_request_context_key,
    _phase_artifact_path,
    _purpose_explained,
    _should_report_permission_rerequest,
    _system_settings_surface,
    _page_semantics,
    _document_probe_allowed_for_role,
    _rendered_document_body_kind,
    _scenario_items_for_action,
    _unchecked_consent_checkbox,
)
from agent.detection_engines.page_semantics import PageRole
from agent.detection_engines.policy_analyzer import _policy_source
from agent.detection_engines.base import Finding
from agent.agent_core.workflow import _reconcile_frida_phase_coverage
from agent.agent_core.workflow import _emit_deferred_finding_evidence
from agent.rule_engine.report_generator import report_confidence


class _Frontier:
    def __init__(self):
        self.completed = []

    def mark_completed(self, items, **_kwargs):
        self.completed.extend(items)


def _ctx(*, bundled="", runtime=None, profile="deny", tmp_path=None):
    return SimpleNamespace(
        apk=SimpleNamespace(policy_raw=bundled, package_name="com.example.app"),
        runtime={"probe_profile": profile, **(runtime or {})},
        data_dir=tmp_path,
    )


def test_policy_source_rejects_compiled_android_xml_and_prefers_runtime_document():
    compiled_layout = (
        "\x03\x00\x08\x00\x10\x00\x00\x00LinearLayout\x00TextView\x00"
        "textSize\x00textColor\x00layout_width\x00layout_height"
    )
    runtime_policy = (
        "隐私政策\n我们为提供账号服务收集手机号码，并说明收集目的、方式和范围。"
        "用户可以在设置-隐私管理中撤回同意，也可以通过客服邮箱投诉举报。"
    )
    ctx = _ctx(
        bundled=compiled_layout,
        runtime={
            "privacy_policy_text": runtime_policy,
            "privacy_policy_read_complete": True,
            "policy_document_read_complete": True,
        },
    )

    raw, source, complete = _policy_source(ctx)

    assert raw == runtime_policy
    assert source == "appium_document"
    assert complete is True


def test_permission_purpose_understands_spaced_ocr_rationale():
    text = (
        "权 限 使 用 说 明 相 机 权 限 使 用 场 景 包 括 直 播、录 制 视 频、"
        "发 布 商 品、意 见 反 馈 和 资 料 编 辑；拒 绝 不 影 响 其 他 功 能"
    )
    assert _purpose_explained(text, permission_label="相机") is True


def test_permission_rerequest_requires_same_context_and_no_new_user_action():
    first = _permission_request_context_key("相机", ".ProfileActivity", "修改头像")
    other = _permission_request_context_key("相机", ".AdviceActivity", "意见反馈上传图片")
    record = {"context_key": first, "business_action_sequence": 2, "denied_at_ms": 10}

    assert _should_report_permission_rerequest(
        record, context_key=other, business_action_sequence=2, denial_business_retry=False,
    ) is False
    assert _should_report_permission_rerequest(
        record, context_key=first, business_action_sequence=3, denial_business_retry=False,
    ) is False
    assert _should_report_permission_rerequest(
        record, context_key=first, business_action_sequence=2, denial_business_retry=False,
    ) is True


def test_camera_subfeature_denial_does_not_become_base_service_block():
    elements = [
        {"text": "请输入反馈内容", "content_desc": "", "resource_id": "et_content", "clickable": True},
        {"text": "相册", "content_desc": "", "resource_id": "btn_album", "clickable": True},
        {"text": "以后再说", "content_desc": "", "resource_id": "btn_cancel", "clickable": True},
    ]
    result = _denial_blocks_base_service(
        "相机", "去开启相机访问权限，才能拍摄照片或录制视频", elements, "拍照",
    )
    assert result["blocked"] is False
    assert result["permission_intrinsic_to_action"] is True
    assert result["alternative_service_available"] is True


def test_android_app_details_is_a_system_settings_surface():
    elements = [
        {"text": "卸载", "content_desc": "", "resource_id": "", "clickable": True},
        {"text": "强行停止", "content_desc": "", "resource_id": "", "clickable": True},
        {"text": "权限", "content_desc": "", "resource_id": "android:id/title", "clickable": True},
    ]
    assert _system_settings_surface("com.android.settings.spa.SpaActivity", elements) == "app_details"


def test_phase_artifacts_are_isolated(tmp_path):
    deny = _phase_artifact_path(_ctx(profile="deny", tmp_path=tmp_path), "screenshot", "page-001.png")
    allow = _phase_artifact_path(_ctx(profile="allow", tmp_path=tmp_path), "screenshot", "page-001.png")
    assert deny != allow
    assert "deny" in deny.parts
    assert "allow" in allow.parts


def test_privacy_document_does_not_complete_terms_scenario():
    ctx = _ctx(runtime={})
    frontier = _Frontier()
    kind = _mark_required_document_read(
        ctx, "隐私政策", frontier,
        page_text="隐私政策 我们收集个人信息用于提供服务",
        body_kind_hint="privacy_policy",
    )
    assert kind == "privacy_policy"
    assert "1.4" not in frontier.completed


def test_frida_phase_reconciliation_keeps_scoped_failure_not_stale_global_gap():
    runtime = {
        "coverage_gaps": ["Frida 动态监测未附加（spawn failed），本次仅形成 Appium/静态证据"],
        "frida_phase_status": {
            "deny": {"available": False, "error": "spawn failed"},
            "allow": {"available": True, "event_count": 30},
        },
    }
    _reconcile_frida_phase_coverage(runtime)
    assert runtime["frida_available_any"] is True
    assert runtime["frida_available_all"] is False
    assert all("本次仅形成" not in gap for gap in runtime["coverage_gaps"])
    assert any("拒绝权限阶段" in gap for gap in runtime["coverage_gaps"])


def test_incomplete_coverage_makes_score_provisional():
    confidence = report_confidence({
        "coverage_complete": False,
        "scenario_coverage": {"planned": 31, "completed": 14, "remaining": 17},
        "evidence_chain_adjudication": [
            {"status": "admissible"}, {"status": "downgraded"},
        ],
    })
    assert confidence["status"] == "provisional"
    assert confidence["final_score_available"] is False
    assert "覆盖" in confidence["reason"]


def test_global_semantic_route_key_is_stable_across_equivalent_profile_activities():
    elements = [{
        "text": "修改头像", "content_desc": "", "resource_id": "com.demo:id/avatar",
        "class_name": "android.widget.ImageView", "bounds": "[0,0][100,100]", "clickable": True,
    }]
    left = _global_target_key("com.demo.profile.PersonalDataActivity", "com.demo:id/avatar", elements)
    right = _global_target_key("com.demo.user.ProfileActivity", "com.demo:id/avatar", elements)
    assert left == right


def test_rendered_policy_body_wins_over_login_shape_on_reused_activity():
    """A policy WebView may expose template credential controls in its tree."""
    elements = [
        {"text": "手机号", "resource_id": "phone", "class_name": "android.widget.EditText",
         "editable": True, "clickable": True, "displayed": True},
        {"text": "验证码", "resource_id": "code", "class_name": "android.widget.EditText",
         "editable": True, "clickable": True, "displayed": True},
        {"text": "登录", "resource_id": "submit", "class_name": "android.widget.Button",
         "clickable": True, "displayed": True},
    ]
    rendered_text = (
        "隐私政策 案例L隐私政策 本公司深知个人信息的重要性。"
        "我们说明收集个人信息的目的、方式和范围，并说明账号注册、设备信息、"
        "投诉举报、撤回同意和个人信息保护负责人的联系方式。"
    ) * 4

    resolved = _page_semantics(
        ".CActivity", elements, PageState(), screen_text=rendered_text,
        package_name="com.example.app", foreground_package="com.example.app",
    )

    assert resolved.role is PageRole.DOCUMENT_BODY
    assert resolved.requires_login_wait is False


def test_unchecked_consent_checkbox_ignores_unrelated_radio_options():
    """Sync-mode radio buttons on a consent sheet are not agreement checkboxes."""
    elements = [
        {"text": "《服务协议》和《隐私政策》", "resource_id": "docs", "clickable": True,
         "displayed": True, "class_name": "android.widget.TextView"},
        {"text": "同步前30个通话记录", "resource_id": "c1", "clickable": True,
         "checkable": True, "checked": False, "displayed": True,
         "class_name": "android.widget.RadioButton"},
        {"text": "不同步已有通话记录", "resource_id": "c3", "clickable": True,
         "checkable": True, "checked": True, "displayed": True,
         "class_name": "android.widget.RadioButton"},
        {"text": "同意条款", "resource_id": "agree", "clickable": True,
         "displayed": True, "class_name": "android.widget.Button"},
        {"text": "不同意", "resource_id": "decline", "clickable": True,
         "displayed": True, "class_name": "android.widget.Button"},
    ]

    assert _unchecked_consent_checkbox(elements) is None


def test_every_final_click_is_mapped_to_scenarios_without_frontier_recommendation():
    elements = [{
        "text": "我的", "content_desc": "", "resource_id": "profile_tab",
        "target": "profile_tab", "clickable": True, "displayed": True,
        "class_name": "android.widget.TextView",
    }]

    assert _scenario_items_for_action("profile_tab", elements) == {"1.3", "3.8", "6.1"}


def test_ocr_policy_body_without_heading_is_still_canonicalized_as_privacy_policy():
    text = ("\u672c\u516c\u53f8\u6536\u96c6\u548c\u4f7f\u7528\u4e2a\u4eba\u4fe1\u606f\u3001\u8bbe\u5907\u4fe1\u606f\u548c\u4f4d\u7f6e\u6743\u9650\uff0c\u7528\u4e8e\u63d0\u4f9b\u548c\u6539\u8fdb\u670d\u52a1\uff1b"
            "\u7528\u6237\u53ef\u4ee5\u5728\u8bbe\u7f6e\u4e2d\u7ba1\u7406\u6388\u6743\u3001\u64a4\u56de\u540c\u610f\u5e76\u8054\u7cfb\u6295\u8bc9\u6e20\u9053\u3002") * 4
    assert _rendered_document_body_kind(text) == "privacy_policy"


def test_deferred_permission_mismatch_emits_rule_scoped_artifact(tmp_path):
    finding = Finding(kind="permission_industry_mismatch", category=4, payload={
        "industry": "工具", "permissions": ["android.permission.READ_PHONE_STATE"],
        "permission_industry_mismatch": True,
    })
    ctx = SimpleNamespace(data_dir=tmp_path, runtime={})

    evidence = _emit_deferred_finding_evidence(ctx, [finding])

    assert evidence[0]["type"] == "permission_list"
    assert evidence[0]["meta"]["finding_kind"] == "permission_industry_mismatch"
    assert (tmp_path / "behavior" / "permission-list.json").is_file()


def test_deferred_privacy_hub_finding_binds_to_captured_hub_screenshot(tmp_path):
    screenshot = tmp_path / "screenshot" / "hub.png"
    screenshot.parent.mkdir()
    screenshot.write_bytes(b"image")
    finding = Finding(kind="no_delete_entry", category=6, payload={"pages_covered": 4})
    ctx = SimpleNamespace(data_dir=tmp_path, runtime={"privacy_hub_screenshot": str(screenshot)})

    evidence = _emit_deferred_finding_evidence(ctx, [finding])

    assert evidence == [{
        "type": "screenshot", "path": str(screenshot),
        "meta": {"finding_kind": "no_delete_entry", "source": "privacy_hub_observation"},
    }]


def test_login_guest_entry_surface_cannot_be_reclassified_as_privacy_hub():
    elements = [
        {"text": "登录/注册", "resource_id": "login", "clickable": True, "displayed": True},
        {"text": "先逛逛", "resource_id": "btn_tourist", "clickable": True, "displayed": True},
        {"text": "隐私政策", "resource_id": "privacy", "clickable": True, "displayed": True},
        {"text": "用户协议", "resource_id": "terms", "clickable": True, "displayed": True},
        {"text": "关于我们", "resource_id": "about", "clickable": True, "displayed": True},
    ]

    resolved = _page_semantics(
        "com.example.login.StartupActivity", elements, PageState(),
        package_name="com.example.app", foreground_package="com.example.app",
    )

    assert resolved.role is PageRole.SPLASH_OR_GATE
    assert resolved.privacy_hub is False


def test_consent_entry_surface_does_not_reopen_policy_links_after_acceptance():
    assert _document_probe_allowed_for_role(PageRole.SPLASH_OR_GATE) is False
    assert _document_probe_allowed_for_role(PageRole.DOCUMENT_HUB) is True
