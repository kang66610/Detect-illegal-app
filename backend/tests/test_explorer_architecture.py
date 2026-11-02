from types import SimpleNamespace

import pytest

from agent.ai_explorer.action_arbitration import ActionArbiter, ActionProposal, DecisionAudit
from agent.ai_explorer.action_effect import ActionEffectLedger
from agent.ai_explorer.action_executor import ActionExecutionResult
from agent.ai_explorer.document_session import DocumentReadingLedger, DocumentScrollDirective
from agent.ai_explorer.permission_probe import PermissionProbeLedger, PermissionProbeStatus
from agent.ai_explorer.exploration_completion import ExplorationCompletionGate
from agent.ai_explorer.login_session import TestAccountLoginAdapter
from agent.ai_explorer.page_state import NavigationGraph, PageState, parse_page
from agent.ai_explorer.runtime_state import DetectionRunState, LoginStatus
from agent.ai_explorer.surface_budget import SurfaceBudgetPolicy
from agent.ai_explorer.consent_decision import ConsentDecisionInput, ConsentDecisionModule
from agent.ai_explorer.permission_decision import PermissionDecisionInput, PermissionDecisionModule
from agent.ai_explorer.hub_decision import HubDecisionInput, HubDecisionModule
from agent.ai_explorer.login_session import LoginDecisionModule
from agent.ai_explorer.sdk_observation import SdkObservationDecisionModule, SdkObservationInput
from agent.ai_explorer.explorer_engine import _document_key, _page_role
from agent.detection_engines.page_semantics import (
    PageFacts,
    PageRole,
    classify_page,
    is_foreign_package,
)
from agent.rule_engine.scenario_execution import ScenarioExecutionLedger


def test_confirmed_document_outranks_empty_state_pruning():
    page = parse_page(
        ".kt.WebViewKT",
        '''<hierarchy>
        <node text="暂无相关记录" class="android.webkit.WebView" scrollable="true"/>
        </hierarchy>''',
    )
    state = PageState()
    state.start_document(".kt.WebViewKT:document:隐私政策")
    state.last_action = "scroll"

    assert _document_key(page.activity, page.elements, state, screen_text="暂无相关记录") == state.active_document
    assert _page_role(page.activity, page.elements, state, screen_text="暂无相关记录") == "document_body"


def test_unconfirmed_empty_webview_remains_prunable():
    semantics = classify_page(PageFacts(low_value_kind="empty_state"))

    assert semantics.role is PageRole.LOW_VALUE
    assert semantics.allow_deep_search is False
    assert semantics.preferred_exit == "back"


@pytest.mark.parametrize("role", [PageRole.SYSTEM_CAMERA, PageRole.SYSTEM_SETTINGS, PageRole.FOREIGN_APP])
def test_action_arbitration_never_deep_clicks_external_or_system_surfaces(role):
    semantics = classify_page(PageFacts(
        system_camera=role is PageRole.SYSTEM_CAMERA,
        system_settings=role is PageRole.SYSTEM_SETTINGS,
        foreign_app=role is PageRole.FOREIGN_APP,
    ))
    result = ActionArbiter().arbitrate(
        [ActionProposal("click", "shutter", "LLM suggested click", "llm", priority=100)],
        semantics=semantics,
        is_root=False,
    )

    assert result.overridden is True
    assert result.proposal.action == "back"
    assert result.proposal.source == "safety_scope_exit"


def test_system_overlay_wait_is_rewritten_to_back():
    """Notification shade is an interruption, not a valid page to wait on."""
    semantics = classify_page(PageFacts(system_overlay=True))

    result = ActionArbiter().arbitrate(
        [ActionProposal("wait", reason="等待页面稳定", source="llm", priority=100)],
        semantics=semantics,
        is_root=False,
    )

    assert result.proposal.action == "back"
    assert result.proposal.source == "safety_scope_exit"


def test_permission_verification_event_name_matches_actual_state():
    storage = {}
    state = DetectionRunState(storage)

    failed = state.record_permission_allow_result(
        permission="相机",
        selected_permissions=["android.permission.CAMERA"],
        states={"android.permission.CAMERA": None},
    )
    assert failed.verified is False
    assert failed.event_type == "permission_allow_unverified"

    passed = state.record_permission_allow_result(
        permission="相机",
        selected_permissions=["android.permission.CAMERA"],
        states={"android.permission.CAMERA": True},
    )
    assert passed.verified is True
    assert passed.event_type == "permission_allow_verified"


def test_login_timeout_cannot_claim_authenticated_coverage():
    storage = {}
    state = DetectionRunState(storage)
    state.mark_login_waiting()
    state.mark_login_timed_out()

    assert state.login_status is LoginStatus.TIMED_OUT
    assert state.authenticated_paths_covered is False
    assert storage["manual_login_verified"] is False


def test_semantic_navigation_graph_distinguishes_phase_and_role():
    page = parse_page(
        ".MainActivity",
        '<hierarchy><node text="我的" resource-id="mine" clickable="true"/></hierarchy>',
    )
    graph = NavigationGraph()
    graph.set_semantic_context(role="main_content", phase="deny")
    deny_node = graph.node_for(page)
    graph.set_semantic_context(role="document_hub", phase="allow")
    allow_node = graph.node_for(page)

    assert deny_node != allow_node
    assert deny_node.startswith(page.surface_fingerprint)


def test_scenario_execution_requires_evidence_to_complete():
    ledger = ScenarioExecutionLedger([
        {"item": "4.2", "goal": "拒权后业务可用性", "executor": "device"},
    ])
    execution = ledger.begin("4.2", target="图片")
    assert execution.step == "target_selected"
    assert execution.terminal is False

    with pytest.raises(ValueError):
        ledger.observe_evidence("4.2", source="")

    completed = ledger.observe_evidence("4.2", source="permission_denial_function_blocked")
    assert completed.terminal is True
    assert completed.evidence_sources == ["permission_denial_function_blocked"]


def test_document_reading_session_round_trips_interrupted_progress():
    ledger = DocumentReadingLedger()
    ledger.start(
        "privacy:https://example.test/policy",
        kind="privacy_policy",
        title="隐私政策",
        source_activity="ChromeTabbedActivity",
        source_target="《隐私政策》",
    )
    ledger.mark_scrolled("privacy:https://example.test/policy", "viewport-1")
    ledger.mark_scrolled("privacy:https://example.test/policy", "viewport-1")
    ledger.interrupt()

    restored = DocumentReadingLedger()
    restored.restore(ledger.as_dict())
    session = restored.sessions["privacy:https://example.test/policy"]

    assert session.scrolls == 1
    assert session.interrupted is True
    assert session.kind == "privacy_policy"


def test_document_ledger_owns_blank_stuck_and_bottom_progress():
    ledger = DocumentReadingLedger()
    key = "policy:privacy"

    assert ledger.observe_blank(key) == 1
    assert ledger.record_stuck(key) == 1
    assert ledger.record_bottom_candidate(key) == 1
    session = ledger.sessions[key]
    assert session.stuck_retries == 0
    assert session.bottom_confirmations == 1
    assert session.blank_observations == 1


def test_overlay_no_effect_retains_its_execution_layer_for_dfs_isolation():
    runtime = {}
    ledger = ActionEffectLedger(runtime)
    ledger.schedule(
        surface="splash", activity=".MainActivity", target="bounds:[1,1][2,2]",
        semantic_target="bounds:[1,1][2,2]", global_key="consent:agree",
        execution_layer="overlay", page_role="consent_dialog",
    )

    effect = ledger.observe(current_surface="splash", permission_prompt=False)

    assert effect.status == "no_effect"
    assert effect.execution_layer == "overlay"
    assert effect.page_role == "consent_dialog"


def test_no_effect_consent_target_is_globally_blocked():
    """A first-run button that did nothing must not be proposed again."""
    runtime = {}
    ledger = ActionEffectLedger(runtime)
    ledger.schedule(
        surface="splash", activity=".StartupActivity", target="agree",
        semantic_target="agree", global_key="consent:agree",
        execution_layer="overlay", page_role="consent_dialog",
    )

    ledger.observe(current_surface="splash", permission_prompt=False)

    assert ledger.is_blocked("consent:agree") is True


def test_consent_module_stops_when_the_only_agree_action_is_no_effect_blocked():
    """Removing the blocked branch would recreate repeated '同意' clicks."""
    directive = ConsentDecisionModule().propose(ConsentDecisionInput(
        consent_dialog=True,
        consent_target="agree",
        consent_target_visited=True,
        consent_target_blocked=True,
    ))

    assert directive is not None
    assert directive.action == "stop"
    assert directive.event_type == "consent_target_no_effect"


def test_document_scroll_transition_centralizes_retry_and_completion():
    ledger = DocumentReadingLedger()
    key = "policy:terms"

    first = ledger.apply_scroll_status(key, "stuck", stuck_retry_limit=2)
    second = ledger.apply_scroll_status(key, "stuck", stuck_retry_limit=2)
    moved = ledger.apply_scroll_status(key, "moved", viewport_fingerprint="v1")
    candidate = ledger.apply_scroll_status(key, "bottom", bottom_confirmations=2)
    complete = ledger.apply_scroll_status(key, "bottom", bottom_confirmations=2)

    assert first.directive is DocumentScrollDirective.RETRY_STUCK
    assert second.directive is DocumentScrollDirective.ABORT_STUCK
    assert moved.directive is DocumentScrollDirective.CONTINUE
    assert moved.scrolls == 1
    assert candidate.directive is DocumentScrollDirective.RETRY_BOTTOM
    assert complete.directive is DocumentScrollDirective.COMPLETE


def test_permission_probe_survives_recovery_and_clears_atomically():
    storage = {}
    ledger = PermissionProbeLedger(storage)
    ledger.start(permission="相机", remaining_steps=2, trigger_target="拍照")
    ledger.tick()
    ledger.refresh_after_recovery(minimum_steps=6, route_replayed=True)

    assert ledger.active.remaining_steps == 6
    assert storage["pending_permission_denial_probe"]["route_replayed"] is True

    ledger.complete(PermissionProbeStatus.BLOCKED, terminal=True)
    assert ledger.active is None
    assert "pending_permission_denial_probe" not in storage
    assert storage["permission_denial_probe_status"] == "blocked"
    assert storage["permission_denial_probe_terminal"] is True


def test_decision_audit_repairs_stale_llm_attribution():
    audit = DecisionAudit.finalize(
        activity="MainActivity",
        decision={"action": "back", "target": "", "reason": "安全退出"},
        decision_source="llm",
        proposed={"action": "click", "target": "购买", "reason": "探索"},
        proposal_source="llm",
    )

    assert audit.proposal_changed is True
    assert audit.source == "deterministic_override"
    assert audit.record["final_by"] == "deterministic_override"


def test_package_scope_does_not_misclassify_allowed_system_surface():
    assert is_foreign_package("com.example.app", "com.other.vendor") is True
    assert is_foreign_package(
        "com.example.app", "com.android.camera", allowed_system_surface=True,
    ) is False


def test_completion_gate_separates_navigation_exhaustion_from_pending_scenario():
    result = ExplorationCompletionGate().assess(
        proposed_termination={"kind": "safe_frontier_exhausted"},
        scenario_snapshot={"items": [{"item": "4.2", "state": "attempted"}]},
        coverage_gaps=[],
        navigation_frontier_exhausted=True,
    )

    assert result.termination["kind"] == "safe_frontier_exhausted"
    assert result.unfinished_items == ["4.2"]
    assert result.coverage_complete is False


def test_completion_gate_requires_pending_action_effect_to_be_verified():
    result = ExplorationCompletionGate().assess(
        proposed_termination={"kind": "safe_frontier_exhausted"},
        scenario_snapshot={"items": []},
        coverage_gaps=[],
        pending_action_validation=True,
        navigation_frontier_exhausted=True,
    )

    assert result.termination["kind"] == "frontier_incomplete"
    assert any("动作效果" in gap for gap in result.gaps)


def test_low_value_surface_budget_is_semantic_and_bounded():
    runtime = {}
    policy = SurfaceBudgetPolicy(runtime)

    first = policy.leave_low_value(
        surface_key="commercial:stable-fingerprint", surface_kind="commercial", is_root=False,
    )
    second = policy.leave_low_value(
        surface_key="commercial:stable-fingerprint", surface_kind="commercial", is_root=False,
    )

    assert first.action == "back"
    assert first.first_observation is True
    assert second.first_observation is False
    assert runtime["low_value_surface_observations"]["commercial:stable-fingerprint"] == 2


def test_consent_module_keeps_document_checkbox_agree_ordering():
    module = ConsentDecisionModule()
    document = module.propose(ConsentDecisionInput(
        unread_document="隐私政策", document_kind="privacy_policy", consent_dialog=True,
    ))
    checkbox = module.propose(ConsentDecisionInput(
        consent_dialog=True, checkbox_target="agree-check", consent_target="agree",
    ))
    agree = module.propose(ConsentDecisionInput(
        consent_dialog=True, consent_target="agree",
    ))

    assert (document.source, document.target) == ("deterministic_document", "隐私政策")
    assert (checkbox.source, checkbox.target) == ("deterministic_consent_checkbox", "agree-check")
    assert (agree.source, agree.target) == ("deterministic_consent", "agree")


def test_permission_module_prefers_camera_then_album():
    module = PermissionDecisionModule()
    camera = module.propose(PermissionDecisionInput(
        capture_target="camera", album_target="album", permission_scenarios_pending=True,
    ))
    album = module.propose(PermissionDecisionInput(
        album_target="album", permission_scenarios_pending=True,
    ))

    assert camera.target == "camera"
    assert album.target == "album"
    assert "revoke_media_permissions" in camera.effects


def test_hub_module_keeps_deny_probe_ahead_of_documents_and_logout():
    directive = HubDecisionModule().propose(HubDecisionInput(
        deny_probe_outstanding=True, media_probe="avatar", unread_document="隐私政策",
        logout_entry="退出登录",
    ))

    assert directive.target == "avatar"
    assert directive.event_type == "hub_media_probe_prioritized"


def test_login_timeout_module_never_repeats_back_forever():
    module = LoginDecisionModule()
    first = module.propose_timeout_exit(
        bypass_target="", bypass_visited=False, back_already_done=False,
    )
    exhausted = module.propose_timeout_exit(
        bypass_target="", bypass_visited=False, back_already_done=True,
    )

    assert first.action == "back"
    assert "terminate_login_gate_unresolved" in exhausted.effects


def test_sdk_observation_module_bounds_wait_gate():
    directive = SdkObservationDecisionModule().propose(SdkObservationInput(
        pending=True, eligible=True, wait_attempts=1, dwell_seconds=8,
    ))

    assert "no_action" in directive.effects
    assert directive.runtime_updates["sdk_observation_dwell_done"] is True


def test_test_account_adapter_uses_environment_without_persisting_secret(monkeypatch):
    class Client:
        def __init__(self):
            self.filled = []
            self.clicked = None

        def enter_text(self, target, value):
            self.filled.append((target, value))

        def perform(self, decision):
            self.clicked = decision["target"]

    monkeypatch.setenv("AUDIT_USER", "tester")
    monkeypatch.setenv("AUDIT_PASS", "secret")
    runtime = {}
    client = Client()
    adapter = TestAccountLoginAdapter({
        "test_account_enabled": True,
        "test_account_username_env": "AUDIT_USER",
        "test_account_password_env": "AUDIT_PASS",
    }, runtime, client)
    result = adapter.attempt([
        {"editable": True, "target": "username", "resource_id": "username"},
        {"editable": True, "password": True, "target": "password", "resource_id": "password"},
        {"clickable": True, "target": "login", "text": "登录"},
    ])

    assert result.status == "submitted"
    assert client.filled == [("username", "tester"), ("password", "secret")]
    assert "secret" not in repr(runtime)


def test_consent_module_classifies_executed_click_for_effect_confirmation():
    module = ConsentDecisionModule()
    landed = ActionExecutionResult("click", "agree", succeeded=True)
    failed = ActionExecutionResult("click", "agree", succeeded=False, error="tap lost")

    accepted = module.observe_action_result(landed, consent_action=True)
    declined = module.observe_action_result(landed, consent_action=False, declined_privacy=True)
    not_landed = module.observe_action_result(failed, consent_action=True)

    assert accepted.accept_attempted is True
    assert accepted.awaiting_effect_confirmation is True
    assert declined.declined_privacy is True
    assert declined.accept_attempted is False
    assert not_landed.accept_attempted is False


def test_permission_module_builds_business_trigger_record_from_execution():
    module = PermissionDecisionModule()
    result = ActionExecutionResult("click", "拍照", succeeded=True)

    observation = module.observe_action_result(
        result, media_source=True, business_action=True,
        business_target="拍照", activity=".CameraActivity", sequence=3,
    )

    assert observation.media_probe_executed is True
    assert observation.business_trigger_record == {
        "action": "click", "target": "拍照", "is_business_action": True,
        "activity": ".CameraActivity", "sequence": 3,
    }
    assert module.observe_action_result(
        ActionExecutionResult("click", "拍照", succeeded=False),
        business_action=True, business_target="拍照",
    ).business_trigger_record == {}


def test_login_module_confirms_only_its_own_entry_tap():
    module = LoginDecisionModule()

    confirmed = module.observe_action_result(
        ActionExecutionResult("click", "登录", succeeded=True), entry_target="登录",
    )
    other_target = module.observe_action_result(
        ActionExecutionResult("click", "首页", succeeded=True), entry_target="登录",
    )

    assert confirmed.entry_confirmed is True
    assert other_target.entry_confirmed is False
