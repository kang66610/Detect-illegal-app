import pytest

from agent.ai_explorer.target_catalog import TargetKind, build_target_catalog
from agent.detection_engines.page_semantics import (
    EvidenceSource,
    PageFacts,
    PageObservation,
    PageRole,
    PageEvidence,
    PageRoleAdjudicator,
    RoleEvidence,
    classify_observation,
)


def _element(text, *, resource_id="", clickable=True, class_name="android.widget.TextView"):
    return {
        "text": text, "content_desc": "", "resource_id": resource_id,
        "target": resource_id or text, "clickable": clickable,
        "displayed": True, "class_name": class_name,
    }


@pytest.mark.parametrize(
    "elements,expected",
    [
        ([_element("我的")], TargetKind.PROFILE_HUB),
        ([_element("意见反馈")], TargetKind.REDRESS),
        ([_element("头像")], TargetKind.MEDIA_ENTRY),
        ([_element("撤回授权")], TargetKind.WITHDRAW_CONSENT),
        ([_element("注销账号")], TargetKind.ACCOUNT_DELETE),
        ([_element("购买会员")], TargetKind.LOW_VALUE_COMMERCIAL),
    ],
)
def test_target_catalog_uses_generic_semantic_clusters(elements, expected):
    catalog = build_target_catalog(elements)
    assert catalog[0].kind is expected


def test_target_catalog_view_resolves_only_visible_role_scoped_targets():
    from agent.ai_explorer.target_catalog import TargetCatalogView

    catalog = build_target_catalog([
        _element("意见反馈", resource_id="feedback"),
        _element("上传图片", resource_id="upload"),
    ])
    view = TargetCatalogView(catalog, has_overlay=False)

    assert view.target_for_kind(TargetKind.REDRESS) == "feedback"
    assert view.kind_for_target("upload") is TargetKind.MEDIA_ENTRY
    assert view.resolve("上传图片") == "upload"
    assert view.is_overlay_target("upload", TargetKind.MEDIA_ENTRY) is False


def test_target_catalog_returns_bounds_for_visible_clickable_retry_target():
    from agent.ai_explorer.target_catalog import bounds_retry_target

    assert bounds_retry_target("upload", [
        {**_element("上传图片", resource_id="upload"), "bounds": "[1,2][30,40]"},
    ]) == "bounds:[1,2][30,40]"


def test_target_catalog_uses_tightest_clickable_host_and_aggregates_child_labels():
    from agent.ai_explorer.target_catalog import bounds_retry_target, labels_for_target

    host = {**_element("", resource_id="row", clickable=True), "bounds": "[0,0][100,60]"}
    child = {**_element("服务协议", clickable=False), "bounds": "[10,10][80,40]"}
    elements = [host, child]

    assert bounds_retry_target("服务协议", elements) == "bounds:[0,0][100,60]"
    assert "服务协议" in labels_for_target("row", elements, label_for_element=lambda item: item["text"])


def test_target_catalog_identity_for_bounds_includes_contained_child_text():
    from agent.ai_explorer.target_catalog import identity_values_for_target

    values = identity_values_for_target("bounds:[0,0][100,60]", [
        {**_element("", resource_id="row", clickable=True), "bounds": "[0,0][100,60]"},
        {**_element("退出登录", clickable=False), "bounds": "[10,10][80,40]"},
    ])

    assert "退出登录" in values


def test_target_catalog_projects_llm_whitelist_without_raw_elements():
    from agent.ai_explorer.target_catalog import llm_catalog_elements

    catalog = build_target_catalog([_element("意见反馈", resource_id="feedback")])
    payload = llm_catalog_elements(catalog)

    assert payload == [{
        "target": "feedback", "text": "意见反馈", "content_desc": "意见反馈",
        "resource_id": "feedback", "bounds": "", "clickable": True,
        "displayed": True, "semantic_target_id": catalog[0].target_id,
        "execution_layer": "page",
    }]


def test_confirmed_document_outranks_commercial_and_empty_copy():
    observation = PageObservation(
        activity=".WebViewActivity",
        elements=(_element("购买会员 暂无内容", clickable=False),),
        facts=PageFacts(document_body=True, low_value_kind="commercial"),
    )

    result = classify_observation(observation)

    assert result.role is PageRole.DOCUMENT_BODY
    assert result.allow_deep_search is False
    assert result.requires_login_wait is False


@pytest.mark.parametrize("label", ["注销账号", "更换手机号", "安全验证"])
def test_account_maintenance_target_does_not_create_login_wait(label):
    result = classify_observation(PageObservation(
        activity=".AccountActivity",
        elements=(_element(label),),
        facts=PageFacts(document_hub=True, login_gate=False),
    ))

    assert result.role is PageRole.DOCUMENT_HUB
    assert result.requires_login_wait is False


def test_feedback_surface_keeps_icon_and_attachment_targets_for_deep_search():
    result = classify_observation(PageObservation(
        activity=".SupportActivity",
        elements=(
            _element("意见反馈"),
            _element("添加图片", resource_id="attachment"),
            _element("提交", resource_id="submit"),
        ),
        facts=PageFacts(),
    ))

    assert result.allow_deep_search is True
    assert any(item.kind is TargetKind.MEDIA_ENTRY for item in result.targets)
    assert any(item.kind is TargetKind.REDRESS for item in result.targets)


def test_consent_overlay_blocks_background_document_login_and_navigation_roles():
    resolved = PageRoleAdjudicator().resolve(
        PageEvidence.from_facts(PageFacts(
            consent_dialog=True,
            document_body=True,
            login_gate=True,
            main_content=True,
        )),
        elements=(),
    )

    assert resolved.role is PageRole.CONSENT_DIALOG
    assert resolved.evidence[0].source is EvidenceSource.UI_TREE
    assert set(resolved.blocked_roles) == {
        PageRole.DOCUMENT_BODY,
        PageRole.LOGIN_GATE,
        PageRole.MAIN_CONTENT,
    }
    assert resolved.requires_login_wait is False


def test_system_permission_outranks_consent_overlay():
    resolved = PageRoleAdjudicator().resolve(
        PageEvidence.from_facts(PageFacts(permission_prompt=True, consent_dialog=True)),
        elements=(),
    )

    assert resolved.role is PageRole.SYSTEM_PERMISSION
    assert resolved.blocked_roles == ()


def test_route_evidence_is_retained_for_external_browser_role():
    resolved = PageRoleAdjudicator().resolve(
        PageEvidence.from_facts(PageFacts(external_browser=True), additional=(
            RoleEvidence(
                role=PageRole.EXTERNAL_BROWSER,
                source=EvidenceSource.ROUTE,
                strength=130,
                hits=("custom_tab_activity",),
            ),
        )),
        elements=(),
    )

    assert resolved.role is PageRole.EXTERNAL_BROWSER
    assert any(item.source is EvidenceSource.ROUTE for item in resolved.evidence)


def test_consent_catalog_keeps_overlay_targets_and_excludes_background_navigation():
    elements = (
        {**_element("隐私政策", clickable=False), "bounds": "[80,260][220,310]"},
        {**_element("不同意", clickable=False), "bounds": "[60,600][180,680]"},
        {**_element("同意", clickable=False), "bounds": "[220,600][340,680]"},
        {**_element("我的", clickable=True), "bounds": "[320,900][420,980]"},
    )
    resolved = PageRoleAdjudicator().resolve(
        PageEvidence.from_facts(PageFacts(consent_dialog=True)), elements=elements,
    )

    labels = {target.label for target in resolved.targets}
    assert {"隐私政策", "不同意", "同意"} <= labels
    assert "我的" not in labels
    assert all(target.execution_layer == "overlay" for target in resolved.targets)
    assert all(target.coordinate_only for target in resolved.targets)


def test_consent_catalog_keeps_native_clickable_controls_without_bounds():
    resolved = PageRoleAdjudicator().resolve(
        PageEvidence.from_facts(PageFacts(consent_dialog=True)),
        elements=(
            _element("隐私政策", resource_id="privacy", clickable=True),
            _element("同意", resource_id="agree", clickable=True),
            _element("我的", resource_id="mine", clickable=True),
        ),
    )

    assert {target.target for target in resolved.targets} == {"privacy", "agree"}
    assert all(target.execution_layer == "overlay" for target in resolved.targets)
    assert all(target.surface_id == "consent_dialog" for target in resolved.targets)
    assert not any(target.coordinate_only for target in resolved.targets)


def test_consent_catalog_keeps_quoted_inline_document_titles_but_not_plain_copy():
    resolved = PageRoleAdjudicator().resolve(
        PageEvidence.from_facts(PageFacts(consent_dialog=True)),
        elements=(
            _element("请阅读并同意《隐私政策》《服务协议》", clickable=False),
            _element("同意", resource_id="agree", clickable=True),
        ),
    )

    assert {target.target for target in resolved.targets} == {
        "《隐私政策》", "《服务协议》", "agree",
    }
    assert all(target.execution_layer == "overlay" for target in resolved.targets)


def test_plain_non_clickable_copy_never_becomes_coordinate_target():
    assert build_target_catalog([
        {**_element("欢迎使用", clickable=False), "bounds": "[10,10][300,60]"},
    ]) == ()


def test_document_entry_is_not_promoted_to_privacy_hub_without_profile_evidence():
    resolved = classify_observation(PageObservation(
        activity=".MainActivity",
        elements=(_element("隐私政策", resource_id="privacy", clickable=True),),
        facts=PageFacts(document_hub=True, privacy_hub=False),
    ))

    assert resolved.role is PageRole.DOCUMENT_HUB
    assert resolved.privacy_hub is False


def test_systemui_nodes_override_stale_audited_activity_as_system_overlay():
    """The notification shade must never be handed to LLM as an app page."""
    from agent.ai_explorer.page_state import PageState
    from agent.ai_explorer.explorer_engine import _page_semantics

    semantics = _page_semantics(
        ".StartupActivity",
        [
            _element("02:06", resource_id="com.android.systemui:id/clock", clickable=True),
            _element("全部清除", resource_id="com.android.systemui:id/dismiss_text", clickable=True),
            _element("蓝牙，已开启", resource_id="com.android.systemui:id/header_label", clickable=True),
        ],
        PageState(), package_name="com.example.audit", foreground_package="com.example.audit",
    )

    assert semantics.role is PageRole.SYSTEM_OVERLAY
    assert semantics.allow_deep_search is False
    assert semantics.preferred_exit == "back"
