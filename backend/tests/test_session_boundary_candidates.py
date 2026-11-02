def test_logout_observation_only_redirect_is_a_priority_150_candidate():
    from agent.ai_explorer.session_boundary import SessionBoundaryPolicy

    directive = SessionBoundaryPolicy().observation_only_directive(
        action="click", target="退出登录", is_logout_target=True,
        explore_confirmation=False, replacement="上传头像",
    )

    assert directive is not None
    assert (directive.action, directive.target, directive.source, directive.priority) == (
        "click", "上传头像", "safety_boundary", 150,
    )
    assert directive.effects == ("mark_session_boundary_observed",)


def test_deny_probe_defers_a_session_boundary_as_a_candidate():
    from agent.ai_explorer.session_boundary import SessionBoundaryPolicy

    directive = SessionBoundaryPolicy().defer_for_deny_probe(
        action="click", target="注销账号", deny_probe_outstanding=True,
        is_session_boundary=True, replacement="上传头像",
    )

    assert directive is not None
    assert (directive.action, directive.target, directive.source, directive.priority) == (
        "click", "上传头像", "deny_permission_priority", 150,
    )
    assert directive.effects == ("mark_session_boundary_deferred",)


def test_destructive_confirmation_is_replaced_with_a_safe_back_candidate():
    from agent.ai_explorer.session_boundary import SessionBoundaryPolicy

    directive = SessionBoundaryPolicy().destructive_confirmation_directive(
        action="click", target="确认注销", is_destructive_confirmation=True,
    )

    assert directive is not None
    assert (directive.action, directive.target, directive.source, directive.priority) == (
        "back", "", "safety_boundary", 150,
    )
    assert directive.effects == ("record_destructive_confirmation_blocked",)


def test_logout_confirmation_commits_observation_flags_only_when_selected():
    from agent.ai_explorer.session_boundary import SessionBoundaryPolicy

    directive = SessionBoundaryPolicy().logout_confirmation_directive(
        action="click", target="确认退出", is_logout_confirmation=True,
    )

    assert directive is not None
    assert directive.runtime_updates == {
        "logout_confirmation_observed": True,
        "logout_entry_explored": True,
    }


def test_repeated_logout_entry_is_replaced_with_a_safe_back_candidate():
    from agent.ai_explorer.session_boundary import SessionBoundaryPolicy

    directive = SessionBoundaryPolicy().repeated_logout_directive(
        action="click", target="退出登录", is_logout_target=True,
        already_explored=True, source="llm",
    )

    assert directive is not None
    assert (directive.action, directive.target, directive.source, directive.priority) == (
        "back", "", "safety_boundary", 150,
    )
