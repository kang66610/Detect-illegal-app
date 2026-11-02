from agent.ai_explorer.dfs_navigation import (
    DfsNavigationInput,
    DfsNavigationPolicy,
    DfsNavigationStep,
)


def _facts(**overrides):
    values = {
        "deep_mode": True,
        "current_action": "back",
        "role": "app_page",
        "decision_source": "llm",
        "sibling_target": "settings",
        "can_scroll": True,
        "scroll_attempts": 0,
        "max_scrolls": 2,
        "consent_blocked": False,
        "pre_app_entry": False,
        "settings_hub": False,
    }
    values.update(overrides)
    return DfsNavigationInput(**values)


def test_dfs_explores_unvisited_sibling_before_backtracking():
    directive = DfsNavigationPolicy().decide(_facts())

    assert directive.step is DfsNavigationStep.EXPLORE_SIBLING
    assert directive.target == "settings"


def test_dfs_scrolls_only_after_visible_siblings_are_exhausted():
    directive = DfsNavigationPolicy().decide(_facts(sibling_target=""))

    assert directive.step is DfsNavigationStep.SCROLL


def test_dfs_does_not_override_backtrack_on_blocked_roles():
    policy = DfsNavigationPolicy()

    for role in ("consent_dialog", "document_body", "login_gate", "low_value_commercial"):
        directive = policy.decide(_facts(role=role))
        assert directive.step is DfsNavigationStep.NONE


def test_dfs_does_not_scroll_after_the_route_budget_is_exhausted():
    directive = DfsNavigationPolicy().decide(
        _facts(sibling_target="", scroll_attempts=2)
    )

    assert directive.step is DfsNavigationStep.NONE
