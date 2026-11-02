from agent.ai_explorer.decision_directive import DecisionDirective, DecisionDirectiveApplier


def test_rejected_directive_does_not_write_runtime_before_commit():
    runtime = {}
    completed = []
    applier = DecisionDirectiveApplier(
        runtime=runtime, emit=lambda *_args, **_kwargs: None,
        mark_completed=lambda items, **_kwargs: completed.extend(items),
    )
    directive = DecisionDirective(
        "click", "会员", "test", "deterministic", runtime_updates={"seen": True},
        completed_scenarios=("1.1",), completion_source="test",
    )

    proposal = applier.to_proposal(directive)

    assert proposal.target == "会员"
    assert runtime == {}
    assert completed == []

    applier.commit_selected(proposal.token, activity=".MainActivity")

    assert runtime["seen"] is True
    assert completed == ["1.1"]


def test_preview_state_preserves_old_branch_gate_without_writing_runtime():
    from agent.ai_explorer.directive_preview import DirectivePreviewState

    runtime = {"sdk_observation_dwell_armed": False}
    preview = DirectivePreviewState(runtime)
    preview.preview(DecisionDirective(
        "click", "首页", "", "sdk",
        runtime_updates={"sdk_observation_dwell_armed": True},
    ))

    assert preview.runtime_view["sdk_observation_dwell_armed"] is True
    assert runtime["sdk_observation_dwell_armed"] is False


def test_selection_session_commits_only_pipeline_selected_token():
    from agent.ai_explorer.action_pipeline import FinalAction
    from agent.ai_explorer.directive_selection import DirectiveSelectionSession

    runtime = {}
    applier = DecisionDirectiveApplier(
        runtime=runtime, emit=lambda *_args, **_kwargs: None,
        mark_completed=lambda *_args, **_kwargs: None,
    )
    session = DirectiveSelectionSession(runtime, applier)
    selected_effects = []
    rejected_effects = []
    first = session.add(
        DecisionDirective("click", "设置", "", "a", runtime_updates={"a": 1}, effects=("revoke",)),
        on_selected=selected_effects.append,
    )
    session.add(
        DecisionDirective("click", "会员", "", "b", runtime_updates={"b": 1}, effects=("revoke",)),
        on_selected=rejected_effects.append,
    )

    session.commit(FinalAction("click", "设置", "", "a", token=first.token), activity=".Main")

    assert runtime == {"a": 1}
    assert selected_effects == [("revoke",)]
    assert rejected_effects == []


def test_replaced_final_action_never_commits_original_directive_effect():
    """A late revisit/safety replacement must not book a route it did not execute."""
    from agent.ai_explorer.action_pipeline import FinalAction
    from agent.ai_explorer.directive_selection import DirectiveSelectionSession

    runtime = {}
    applier = DecisionDirectiveApplier(
        runtime=runtime, emit=lambda *_args, **_kwargs: None,
        mark_completed=lambda *_args, **_kwargs: None,
    )
    session = DirectiveSelectionSession(runtime, applier)
    effects_seen = []
    proposal = session.add(
        DecisionDirective(
            "click", "原媒体入口", "", "deterministic_scenario",
            runtime_updates={"media_probe_booked": True}, effects=("record_media_probe",),
        ),
        on_selected=effects_seen.append,
    )

    decision, source, effects = session.commit(
        FinalAction(
            "click", "替代入口", "跨页重访后改走替代路径", "frontier_recovery",
            token=proposal.token,
        ),
        activity=".MainActivity",
    )

    assert decision["target"] == "替代入口"
    assert source == "frontier_recovery"
    assert effects == ()
    assert runtime == {}
    assert effects_seen == []


def test_selection_session_discards_unselected_side_effects_and_preview():
    from agent.ai_explorer.directive_selection import DirectiveSelectionSession

    runtime = {"gate": False}
    applier = DecisionDirectiveApplier(
        runtime=runtime, emit=lambda *_args, **_kwargs: None,
        mark_completed=lambda *_args, **_kwargs: None,
    )
    session = DirectiveSelectionSession(runtime, applier)
    session.add(DecisionDirective(
        "click", "首页", "", "sdk",
        runtime_updates={"gate": True},
    ))

    assert session.preview.runtime_view["gate"] is True
    assert runtime.get("gate") is False

    session.discard()

    assert session.preview.runtime_view["gate"] is False
    assert session.proposals == []
    # Replaced candidates are dropped from the applier too: no unbounded
    # pending growth and no stale token can be committed later.
    import pytest

    with pytest.raises(KeyError):
        session.commit_token("directive-1", activity=".Main")


def test_selection_session_commit_token_commits_immediately():
    from agent.ai_explorer.directive_selection import DirectiveSelectionSession

    runtime = {}
    applier = DecisionDirectiveApplier(
        runtime=runtime, emit=lambda *_args, **_kwargs: None,
        mark_completed=lambda *_args, **_kwargs: None,
    )
    session = DirectiveSelectionSession(runtime, applier)
    effects_seen = []
    proposal = session.add(
        DecisionDirective(
            "observe", "", "", "sdk", runtime_updates={"done": True}, effects=("no_action",),
        ),
        on_selected=effects_seen.append,
    )

    committed = session.commit_token(proposal.token, activity=".Main")

    assert runtime == {"done": True}
    assert committed[2] == ("no_action",)
    assert effects_seen == [("no_action",)]


def test_directive_priority_does_not_reinterpret_legacy_event_positionals():
    events = []
    directive = DecisionDirective(
        "observe", "", "", "sdk", "legacy_event", {"seconds": 0.0},
    )
    applier = DecisionDirectiveApplier(
        runtime={},
        emit=lambda event_type, **meta: events.append((event_type, meta)),
        mark_completed=lambda *_args, **_kwargs: None,
    )

    proposal = applier.to_proposal(directive)
    applier.commit_selected(proposal.token, activity=".Main")

    assert proposal.priority == 0
    assert events == [("legacy_event", {"activity": ".Main", "seconds": 0.0, "reason": ""})]
