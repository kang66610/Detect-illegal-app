from agent.detection_engines.ui_roles import (
    forced_service_consent,
    misleading_consent_copy,
    personalization_mentioned,
    roles_for_element,
)
from agent.rule_engine.scenario_plan import ScenarioFrontier, device_scenario_plan


def test_feed_recommendation_is_not_a_personalization_opt_out_control():
    roles = roles_for_element({
        "text": "个性化推荐", "content_desc": "", "resource_id": "feed", "clickable": True, "class_name": "",
    })
    assert "personalization_control" not in roles


def test_opt_out_control_is_classified_even_without_the_old_keyword_shape():
    roles = roles_for_element({
        "text": "关闭个性化", "content_desc": "", "resource_id": "ads_off", "clickable": True, "class_name": "",
    })
    assert "personalization_control" in roles


def test_forced_and_misleading_consent_need_both_the_gate_and_the_copy():
    assert forced_service_consent("为改善服务必须同意后才能使用") is True
    assert forced_service_consent("请阅读并同意隐私政策") is False
    assert misleading_consent_copy(
        "请阅读隐私政策",
        [{"text": "开启全部权限", "clickable": True, "resource_id": "", "content_desc": "", "class_name": ""}],
    ) is True
    assert misleading_consent_copy(
        "请阅读隐私政策",
        [{"text": "同意", "clickable": True, "resource_id": "ok", "content_desc": "", "class_name": ""}],
    ) is False


def test_personalized_ads_language_is_detected_in_policy_or_ui_text():
    assert personalization_mentioned("我们提供个性化推荐") is True
    assert personalization_mentioned("仅展示关注内容") is False


def test_frontier_still_ignores_feed_cards_after_3_6_gained_a_detector():
    frontier = ScenarioFrontier(device_scenario_plan())
    assert frontier.recommend(
        [{"text": "个性化推荐", "content_desc": "", "resource_id": "feed", "clickable": True}],
        set(),
    ) is None
    rec = frontier.recommend(
        [{"text": "关闭个性化", "content_desc": "", "resource_id": "ads_off", "clickable": True}],
        set(),
    )
    assert rec is not None
    assert "3.6" in rec["scenario_items"]


def test_notification_settings_is_not_a_privacy_hub_or_3_8_route():
    notify = roles_for_element({
        "text": "通知设置", "content_desc": "", "resource_id": "notify", "clickable": True, "class_name": "",
    })
    assert "privacy_hub_entry" not in notify
    assert "settings_entry" not in notify
    more = roles_for_element({
        "text": "更多设置", "content_desc": "", "resource_id": "more", "clickable": True, "class_name": "",
    })
    assert "privacy_hub_entry" in more
    frontier = ScenarioFrontier(device_scenario_plan())
    rec = frontier.recommend(
        [{"text": "通知设置", "content_desc": "", "resource_id": "notify", "clickable": True}],
        set(),
    )
    assert rec is None or rec.get("target") != "notify"


def test_customer_service_entry_is_not_used_to_satisfy_complaint_deadline():
    frontier = ScenarioFrontier(device_scenario_plan())
    rec = frontier.recommend(
        [{"text": "联系客服", "content_desc": "", "resource_id": "cs", "clickable": True}],
        set(),
    )
    assert rec is None or "6.5" not in rec["scenario_items"]


def test_redress_and_account_hub_roles_are_not_tied_to_one_app_wording():
    for label in ("意见反馈", "投诉举报", "帮助与支持", "创建工单", "问题申诉"):
        roles = roles_for_element({
            "text": label, "content_desc": "", "resource_id": "row", "clickable": True, "class_name": "",
        })
        assert "complaint_control" in roles
    for label in ("个人中心", "用户中心", "账户中心", "账号中心", "个人信息"):
        roles = roles_for_element({
            "text": label, "content_desc": "", "resource_id": "row", "clickable": True, "class_name": "",
        })
        assert {"settings_entry", "privacy_hub_entry"} <= roles
