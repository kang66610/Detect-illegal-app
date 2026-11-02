from agent.ai_explorer.scenario_controller import ScenarioController
from agent.rule_engine.scenario_execution import ExecutionState
from agent.rule_engine.scenario_execution import ScenarioExecutionLedger


def test_rule_4_2_requires_denial_retry_and_function_outcome():
    controller = ScenarioController.for_items(["4.2"])

    controller.observe("permission_prompt", item="4.2", target="头像", source="prompt")
    controller.observe("permission_denied", item="4.2", target="头像", source="deny")
    assert controller.execution("4.2").terminal is False
    controller.observe("business_action_retried", item="4.2", target="头像", source="retry")
    assert controller.execution("4.2").terminal is False
    controller.observe("function_blocked", item="4.2", target="头像", source="blocked")

    execution = controller.execution("4.2")
    assert execution.state is ExecutionState.EVIDENCE_OBSERVED
    assert execution.evidence_sources == ["prompt", "deny", "retry", "blocked"]


def test_rule_4_2_rejects_out_of_order_outcome_evidence():
    controller = ScenarioController.for_items(["4.2"])

    transition = controller.observe(
        "function_blocked", item="4.2", target="头像", source="blocked",
    )

    assert transition.accepted is False
    assert transition.reason == "expected:permission_prompt"
    assert controller.execution("4.2").state is ExecutionState.PENDING


def test_rule_4_2_accepts_explicit_blocking_result_immediately_after_denial():
    controller = ScenarioController.for_items(["4.2"])
    controller.observe("permission_prompt", item="4.2", target="头像", source="prompt")
    controller.observe("permission_denied", item="4.2", target="头像", source="deny")

    transition = controller.observe(
        "function_blocked", item="4.2", target="头像", source="blocked",
        direct_outcome=True,
    )

    assert transition.accepted is True
    assert controller.execution("4.2").state is ExecutionState.EVIDENCE_OBSERVED
    assert controller.execution("4.2").step == "evidence_observed"


def test_rule_4_2_requires_same_semantic_business_target_after_denial():
    controller = ScenarioController.for_items(["4.2"])
    controller.observe("permission_prompt", item="4.2", target="头像", source="prompt")
    controller.observe("permission_denied", item="4.2", target="头像", source="deny")

    transition = controller.observe(
        "business_action_retried", item="4.2", target="上传附件", source="retry",
    )

    assert transition.accepted is False
    assert transition.reason == "semantic_target_changed"


def test_navigation_exhaustion_does_not_complete_withdraw_scenario():
    controller = ScenarioController.for_items(["3.8"])

    transition = controller.observe(
        "navigation_exhausted", item="3.8", target="", source="frontier",
    )

    assert transition.accepted is False
    assert controller.execution("3.8").state is ExecutionState.PENDING


def test_withdraw_entry_requires_observed_entry_evidence():
    controller = ScenarioController.for_items(["3.8"])

    controller.observe(
        "withdraw_entry_observed", item="3.8", target="撤回授权", source="screenshot+timeline",
    )

    execution = controller.execution("3.8")
    assert execution.state is ExecutionState.EVIDENCE_OBSERVED
    assert execution.evidence_sources == ["screenshot+timeline"]


def test_ledger_ignores_completion_for_item_outside_phase_plan():
    """A shared callback must not crash when the active phase omits an item."""
    ledger = ScenarioExecutionLedger([
        {"item": "4.2", "goal": "permission probe", "executor": "device"},
    ])

    result = ledger.observe_evidence("1.2", source="navigation_callback")

    assert result is None
    assert ledger.outstanding() == ["4.2"]


def test_ledger_ignores_unknown_items_for_all_state_mutations():
    ledger = ScenarioExecutionLedger([
        {"item": "4.2", "goal": "permission probe", "executor": "device"},
    ])

    assert ledger.begin("1.2") is None
    assert ledger.advance("1.2", step="ignored") is None
    assert ledger.observe_step("1.2", step="ignored", source="callback") is None
    assert ledger.block("1.2", state="blocked_external", reason="ignored") is None
    assert ledger.row("1.2") is None
    assert ledger.row("4.2")["state"] == "pending"


def test_phase_local_controller_ignores_observation_from_another_scenario():
    controller = ScenarioController.for_items(["4.2"])

    transition = controller.observe(
        "first_run_notice_observed",
        item="1.2",
        source="common_navigation_callback",
    )

    assert transition.accepted is False
    assert transition.reason == "scenario_not_planned"
    assert controller.execution("4.2").attempts == 0
    assert controller.execution("1.2") is None
