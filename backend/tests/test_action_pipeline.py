from dataclasses import FrozenInstanceError

import pytest

from agent.ai_explorer.action_arbitration import ActionProposal, DecisionAudit
from agent.ai_explorer.action_pipeline import ActionPipeline
from agent.detection_engines.page_semantics import PageFacts, classify_page


def _ordinary_page():
    return classify_page(PageFacts())


def _camera_page():
    return classify_page(PageFacts(system_camera=True))


def test_final_action_is_immutable_after_arbitration():
    final = ActionPipeline().choose(
        [ActionProposal("click", "设置", source="dfs", priority=10)],
        semantics=_ordinary_page(), is_root=False,
    )

    assert final.action == "click"
    with pytest.raises(FrozenInstanceError):
        final.action = "restart"


def test_active_scenario_beats_llm_candidate():
    final = ActionPipeline().choose(
        [
            ActionProposal("click", "推荐", source="llm", priority=999),
            ActionProposal("click", "头像", source="scenario", priority=1, scenario_items=("4.2",)),
        ],
        semantics=_ordinary_page(), is_root=False,
    )

    assert (final.action, final.target, final.source) == ("click", "头像", "scenario")
    assert [proposal.source for proposal in final.rejected] == ["llm"]


def test_safety_exit_beats_active_scenario_on_system_camera():
    final = ActionPipeline().choose(
        [
            ActionProposal("click", "拍照", source="scenario", priority=1000, scenario_items=("4.2",)),
            ActionProposal("click", "快门", source="llm", priority=1000),
        ],
        semantics=_camera_page(), is_root=False,
    )

    assert final.action == "back"
    assert final.source == "safety_scope_exit"
    assert {proposal.source for proposal in final.rejected} == {"scenario", "llm"}


def test_equivalent_candidates_are_deduplicated_without_losing_sources():
    final = ActionPipeline().choose(
        [
            ActionProposal("click", "设置", source="dfs", priority=50),
            ActionProposal("click", "设置", source="llm", priority=20),
        ],
        semantics=_ordinary_page(), is_root=False,
    )

    assert final.source == "dfs"
    assert final.duplicate_sources == ("llm",)


def test_final_action_preserves_selected_directive_token_only():
    final = ActionPipeline().choose(
        [
            ActionProposal("click", "设置", source="deterministic", priority=10, token="directive-1"),
            ActionProposal("click", "会员", source="llm", priority=1, token="directive-2"),
        ],
        semantics=_ordinary_page(), is_root=False,
    )

    assert final.token == "directive-1"


def test_decision_audit_keeps_resolved_role_and_execution_layer():
    audit = DecisionAudit.finalize(
        activity=".MainActivity",
        decision={"action": "click", "target": "bounds:[1,1][2,2]", "reason": "同意"},
        decision_source="deterministic_consent",
        context={
            "page_role": "consent_dialog", "execution_layer": "overlay",
            "surface_id": "surface-a",
        },
    )

    assert audit.record["page_role"] == "consent_dialog"
    assert audit.record["execution_layer"] == "overlay"
    assert audit.record["surface_id"] == "surface-a"
