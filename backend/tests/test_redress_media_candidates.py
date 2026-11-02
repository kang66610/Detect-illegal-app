from agent.ai_explorer.action_arbitration import ActionProposal
from agent.ai_explorer.action_pipeline import ActionPipeline
from agent.ai_explorer.decision_directive import DecisionDirectiveApplier
from agent.ai_explorer.directive_selection import DirectiveSelectionSession
from agent.detection_engines.page_semantics import PageFacts, classify_page


def test_customer_service_early_exit_candidate_commits_probe_effects_only_when_selected():
    """A rejected media probe must not consume its target or emit probe evidence."""
    from agent.ai_explorer.redress_media_probe import RedressMediaProbePolicy

    policy = RedressMediaProbePolicy()
    directive = policy.early_exit_directive(
        action="back",
        candidates=("upload", "voice"),
        attempted_targets=set(),
    )

    assert directive is not None
    assert (directive.action, directive.target, directive.source) == (
        "click", "upload", "deterministic_scenario",
    )

    runtime = {}
    effects = []
    applier = DecisionDirectiveApplier(
        runtime=runtime,
        emit=lambda *_args, **_kwargs: None,
        mark_completed=lambda *_args, **_kwargs: None,
    )
    selection = DirectiveSelectionSession(runtime, applier)
    candidate = selection.add(directive, on_selected=effects.append)
    assert candidate.priority == 150
    final = ActionPipeline().choose(
        [
            ActionProposal("back", reason="LLM early exit", source="llm", priority=100),
            candidate,
        ],
        semantics=classify_page(PageFacts()),
        is_root=False,
    )

    assert (final.action, final.target, final.source) == (
        "click", "upload", "deterministic_scenario",
    )
    assert effects == []

    selection.commit(final, activity=".CustomerService")

    assert effects == [("record_media_probe",)]


def test_customer_service_exhaustion_returns_a_delayed_back_candidate():
    from agent.ai_explorer.redress_media_probe import RedressMediaProbePolicy

    directive = RedressMediaProbePolicy().exhausted_directive(action="wait")

    assert directive is not None
    assert (directive.action, directive.target, directive.source, directive.priority) == (
        "back", "", "deterministic_deep_search", 150,
    )
    assert directive.effects == ("record_customer_service_exhausted",)
