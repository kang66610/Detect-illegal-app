from agent.ai_explorer.permission_scenario import (
    PermissionScenarioInput,
    PermissionScenarioPolicy,
    PermissionScenarioStep,
)


def test_permission_scenario_starts_a_probe_only_for_business_bound_denial():
    directive = PermissionScenarioPolicy().decide(PermissionScenarioInput(
        prompt_visible=True, response_action="deny", business_target="upload_photo",
    ))

    assert directive.step is PermissionScenarioStep.START_DENIAL_PROBE
    assert directive.target == "upload_photo"


def test_permission_scenario_retries_original_business_action_once_after_denial():
    directive = PermissionScenarioPolicy().decide(PermissionScenarioInput(
        active_probe=True, business_target="upload_photo", target_visible=True,
    ))

    assert directive.step is PermissionScenarioStep.RETRY_BUSINESS_ACTION


def test_permission_scenario_marks_base_service_blocked_before_retry():
    directive = PermissionScenarioPolicy().decide(PermissionScenarioInput(
        active_probe=True, business_target="upload_photo", denial_blocked=True,
    ))

    assert directive.step is PermissionScenarioStep.MARK_BLOCKED


def test_permission_scenario_leaves_unconfirmed_probe_open_until_budget_expires():
    policy = PermissionScenarioPolicy()
    active = PermissionScenarioInput(
        active_probe=True, business_target="upload_photo", remaining_steps=1,
    )

    assert policy.decide(active).step is PermissionScenarioStep.NONE
    assert policy.decide(PermissionScenarioInput(
        active_probe=True, business_target="upload_photo", remaining_steps=0,
    )).step is PermissionScenarioStep.MARK_UNCONFIRMED
