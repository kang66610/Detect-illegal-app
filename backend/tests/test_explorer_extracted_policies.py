from types import SimpleNamespace


def test_settings_hub_navigator_preserves_audit_priority():
    from agent.ai_explorer.hub_decision import HubProgressCandidates, SettingsHubNavigator

    navigator = SettingsHubNavigator()
    assert navigator.next_target(HubProgressCandidates(
        capture="拍照", album="相册", privacy="注销账号", drill="设置",
        unread="隐私政策", avatar="头像", logout="退出登录", fallback="关于我们",
        deny_probe_outstanding=True,
    )) == "拍照"
    assert navigator.next_target(HubProgressCandidates(
        privacy="撤回同意", drill="设置", unread="隐私政策",
    )) == "撤回同意"


def test_login_surface_classifier_rejects_account_maintenance_and_accepts_real_form():
    from agent.ai_explorer.login_session import LoginSurfaceClassifier

    classifier = LoginSurfaceClassifier()
    maintenance = [
        {"text": "更换手机号", "class_name": "android.widget.TextView", "displayed": True},
        {"text": "验证码", "class_name": "android.widget.EditText", "displayed": True},
        {"text": "下一步", "clickable": True, "displayed": True},
    ]
    login = [
        {"text": "手机号", "class_name": "android.widget.EditText", "displayed": True},
        {"text": "验证码", "class_name": "android.widget.EditText", "displayed": True},
        {"text": "登录", "clickable": True, "displayed": True},
    ]

    assert classifier.is_login_gate(".ChangePhoneActivity", maintenance) is False
    assert classifier.is_login_gate(".LoginActivity", login) is True

    invitation = [
        {"text": "该功能需要登录", "displayed": True},
        {"text": "前往登录", "target": "go-login", "clickable": True, "displayed": True},
    ]
    assert classifier.invitation_target(invitation, "该功能需要登录") == "go-login"

    bypass = [{"text": "随便看看", "target": "guest", "clickable": True, "displayed": True}]
    assert classifier.bypass_target(bypass) == "guest"

    profile = [
        {"text": "未登录", "displayed": True},
        {"resource_id": "profile_header", "target": "profile_header", "clickable": True, "displayed": True},
    ]
    assert classifier.profile_entry(profile, "未登录") == "profile_header"


def test_redress_media_executor_explores_a_new_family_before_repeating():
    from agent.ai_explorer.redress_media_probe import RedressMediaProbeExecutor, RedressSurfaceDetector

    executor = RedressMediaProbeExecutor(identity_resolver=lambda target: target)
    candidates = ["相机", "拍照", "相册", "语音"]

    assert executor.next_target(candidates, attempted={"相机"}) == "相册"
    assert executor.next_target(candidates, attempted={"相机", "相册"}) == "语音"
    detector = RedressSurfaceDetector()
    assert detector.matches(".FeedbackActivity", "意见反馈 请描述您的问题 提交反馈", [
        {"class_name": "android.widget.EditText", "displayed": True},
        {"text": "添加图片", "clickable": True, "displayed": True},
    ]) is True
    assert detector.matches(".PolicyActivity", "您可以联系客服进行投诉", []) is False


def test_settings_hub_scroll_policy_has_one_terminal_owner():
    from agent.ai_explorer.hub_decision import SettingsHubScrollPolicy

    policy = SettingsHubScrollPolicy(max_scrolls=3)
    assert policy.observe(attempts=0, moved=True).exhausted is False
    assert policy.observe(attempts=2, moved=False).exhausted is True


def test_rule_evidence_executor_does_not_complete_without_evidence():
    from agent.ai_explorer.rule_evidence_executor import RuleEvidenceExecutor

    completed = []
    executor = RuleEvidenceExecutor(mark_completed=lambda items, **meta: completed.append((items, meta)))

    assert executor.complete(["4.2"]) is False
    assert completed == []
    assert executor.complete(["4.2"], evidence_source="permission_denial_function_blocked") is True
    assert completed == [(["4.2"], {"evidence_source": "permission_denial_function_blocked"})]


def test_final_action_policy_turns_unsafe_click_into_scope_exit():
    from agent.ai_explorer.final_action_policy import FinalActionContext, FinalActionSafetyPolicy

    policy = FinalActionSafetyPolicy(checks={
        "transaction_boundary": lambda target: target == "立即购买",
        "stale_or_invisible_target": lambda target: target == "消失按钮",
    })
    decision, reason = policy.enforce(
        {"action": "click", "target": "立即购买", "reason": "继续探索"},
        FinalActionContext(is_root=False),
    )

    assert decision == {"action": "back", "target": "", "reason": "transaction_boundary"}
    assert reason == "transaction_boundary"
