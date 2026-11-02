from types import SimpleNamespace

from agent.detection_engines.policy_analyzer import (
    policy_discloses_withdraw_path,
    run_policy_audit,
    sensitive_information_emphasis_status,
)
from agent.detection_engines.base import DetectionContext


def test_complete_policy_can_automate_purpose_and_complaint_time_checks(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw="隐私政策：我们通过收集信息提供服务，收集范围包括个人信息。投诉、举报可通过客服或邮箱联系我们。"),
        cfg={}, data_dir=tmp_path,
    )

    findings, evidence, gaps = run_policy_audit(ctx)

    assert "complaint_processing_time_missing" in {item.kind for item in findings}
    assert not gaps
    assert evidence[0]["type"] == "policy"
    assert evidence[0]["meta"]["complete"] is True


def test_incomplete_external_policy_never_becomes_a_violation(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw=None),
        cfg={}, data_dir=tmp_path,
        runtime={"policy_text": "隐私政策正在加载"},
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert findings == []
    assert gaps


def test_generic_reply_language_does_not_satisfy_complaint_deadline(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw="我们收集个人信息用于提供服务，范围包括账号。投诉、举报可通过客服或邮箱联系我们，我们会及时回复并受理。"),
        cfg={}, data_dir=tmp_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert {item.kind for item in findings} == {"complaint_processing_time_missing", "invalid_contact_format"}
    assert not gaps


def test_explicit_complaint_deadline_satisfies_rule_6_5(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw="我们收集个人信息用于提供服务，范围包括账号。投诉可通过客服联系我们，我们将在7个工作日内处理并反馈。"),
        cfg={}, data_dir=tmp_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert findings == []
    assert not gaps


def test_retention_or_service_sla_does_not_satisfy_complaint_deadline(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw=(
            "我们收集个人信息用于提供服务，范围包括账号。"
            "个人信息保存不超过15个工作日。"
            "用户协议约定服务中断将在3个工作日内恢复。"
            "投诉、举报可通过客服或邮箱联系我们。"
        )),
        cfg={}, data_dir=tmp_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert "complaint_processing_time_missing" in {item.kind for item in findings}
    assert not gaps


def test_unpunctuated_policy_dump_does_not_treat_distant_retention_as_complaint_deadline(tmp_path):
    blob = (
        "投诉举报可通过客服或邮箱联系我们"
        + ("收集个人信息用于提供写作服务范围包括账号" * 40)
        + "个人信息保存不超过15个工作日"
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw=blob),
        cfg={}, data_dir=tmp_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert "complaint_processing_time_missing" in {item.kind for item in findings}
    assert not gaps


def test_privacy_policy_text_is_preferred_over_user_agreement_corpus(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw=None),
        cfg={}, data_dir=tmp_path,
        runtime={
            "policy_document_read_complete": True,
            "policy_text": "用户服务协议：服务中断将在3个工作日内恢复。投诉可通过客服联系我们。",
            "privacy_policy_text": (
                "我们收集个人信息用于提供服务，范围包括账号。"
                "投诉、举报可通过客服或邮箱联系我们。"
            ),
        },
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert "complaint_processing_time_missing" in {item.kind for item in findings}
    assert not gaps


def _write_flutter_apk(path):
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("lib/arm64-v8a/libflutter.so", b"flutter")
        archive.writestr("assets/flutter_assets/AssetManifest.json", b"{}")


def test_flutter_apk_without_plugin_itemization_is_purpose_not_disclosed(tmp_path):
    apk_path = tmp_path / "flutter.apk"
    _write_flutter_apk(apk_path)
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw=(
            "我们收集个人信息用于提供服务，范围包括账号。"
            "本应用采用Flutter开发，并接入若干第三方SDK。"
            "投诉可通过客服联系我们，我们将在7个工作日内处理并反馈。"
        )),
        cfg={}, data_dir=tmp_path, apk_path=apk_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert {item.kind for item in findings} == {"purpose_not_disclosed"}
    assert "第三方插件收集项" in findings[0].payload["missing_dimensions"]
    assert not gaps


def test_itemized_flutter_plugins_do_not_emit_purpose_finding(tmp_path):
    apk_path = tmp_path / "flutter.apk"
    _write_flutter_apk(apk_path)
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw=(
            "我们收集个人信息用于提供服务，范围包括账号。"
            "Flutter插件image_picker用于访问相册中的个人信息。"
            "Flutter插件device_info用于获取设备标识。"
            "投诉可通过客服联系我们，我们将在7个工作日内处理并反馈。"
        )),
        cfg={}, data_dir=tmp_path, apk_path=apk_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert findings == []
    assert not gaps


def test_withdraw_path_requires_action_and_in_app_route():
    silent = "我们收集个人信息用于提供服务，范围包括账号。"
    named = "用户可在设置中点击撤回同意授权。"
    action_only = "用户可以撤回同意。"

    assert policy_discloses_withdraw_path(silent) is False
    assert policy_discloses_withdraw_path(named) is True
    assert policy_discloses_withdraw_path(action_only) is False


def test_complete_policy_flags_embedded_sdk_missing_from_disclosure(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(
            policy_raw=(
                "我们收集个人信息用于提供服务，范围包括账号与设备信息。"
                "投诉可通过客服联系我们，我们将在7个工作日内处理并反馈。"
            ),
            sdk_list=[{"name": "友盟", "collected": ["设备标识"], "matched_by": ["UMENG_APPKEY"]}],
        ),
        cfg={}, data_dir=tmp_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert {item.kind for item in findings} == {"purpose_not_disclosed"}
    assert "嵌入第三方SDK逐项披露" in findings[0].payload["missing_dimensions"]
    assert findings[0].payload["undisclosed_sdks"] == ["友盟"]
    assert not gaps


def test_policy_that_names_the_sdk_does_not_emit_embedded_sdk_gap(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(
            policy_raw=(
                "我们收集个人信息用于提供服务，范围包括账号与设备信息。"
                "友盟SDK用于统计分析设备标识。"
                "投诉可通过客服联系我们，我们将在7个工作日内处理并反馈。"
            ),
            sdk_list=[{"name": "友盟", "collected": ["设备标识"], "matched_by": ["UMENG_APPKEY"]}],
        ),
        cfg={}, data_dir=tmp_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert findings == []
    assert not gaps


def test_preserved_html_without_sensitive_term_emphasis_emits_extension_finding(tmp_path):
    policy = (
        "<html><body>"
        "<p>为了实名认证，我们收集身份证号。</p>"
        "<p>为了支付服务，我们收集银行卡。</p>"
        "<p>投诉可通过客服电话联系我们，我们将在7个工作日内处理并反馈。</p>"
        "</body></html>"
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw=policy), cfg={}, data_dir=tmp_path,
    )

    findings, evidence, gaps = run_policy_audit(ctx)

    finding = next(item for item in findings if item.kind == "sensitive_information_not_emphasized")
    assert set(finding.payload["unemphasized_terms"]) >= {"身份证号", "银行卡"}
    assert "sensitive_information_not_emphasized" in evidence[0]["meta"]["finding_kinds"]
    assert not gaps


def test_all_sensitive_terms_emphasized_does_not_emit_extension_finding(tmp_path):
    policy = (
        "<html><body>"
        "<p>为了实名认证，我们收集<strong>身份证号</strong>。</p>"
        "<p>为了支付服务，我们收集<u>银行卡</u>。</p>"
        "<p>投诉可通过客服电话联系我们，我们将在7个工作日内处理并反馈。</p>"
        "</body></html>"
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw=policy), cfg={}, data_dir=tmp_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert "sensitive_information_not_emphasized" not in {item.kind for item in findings}
    assert sensitive_information_emphasis_status(policy)["status"] == "emphasized"
    assert not gaps


def test_plain_policy_text_cannot_prove_visual_emphasis(tmp_path):
    policy = (
        "为了实名认证，我们收集身份证号。为了支付服务，我们收集银行卡。"
        "投诉可通过客服电话联系我们，我们将在7个工作日内处理并反馈。"
    )
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(policy_raw=policy), cfg={}, data_dir=tmp_path,
    )

    findings, _evidence, gaps = run_policy_audit(ctx)

    assert "sensitive_information_not_emphasized" not in {item.kind for item in findings}
    assert any("未保留可解析样式" in gap for gap in gaps)
