"""Safety predicate module and check-order behavior for the explorer."""
from agent.ai_explorer.final_action_policy import FinalActionContext, FinalActionSafetyPolicy


def test_safety_checks_preserve_existing_check_order():
    checks = {"low_audit_value_route": lambda target: target == "购买"}
    ctx = FinalActionContext(is_root=False)
    decision, reason = FinalActionSafetyPolicy(checks=checks).enforce(
        {"action": "click", "target": "购买"}, ctx,
    )
    assert decision["action"] == "back"
    assert reason == "low_audit_value_route"


def test_safety_checks_factory_keeps_check_order_keys():
    from agent.ai_explorer.action_safety_checks import SafetyCheckFacts, SafetyChecks

    checks = SafetyChecks.for_page(SafetyCheckFacts(
        elements=({"text": "购买", "clickable": True, "displayed": True},),
        label_blob_for=lambda target: target,
        protected_route_terms=(),
        maintenance_terms=(),
        low_value_route_terms=("购买",),
    ))

    assert tuple(checks) == FinalActionSafetyPolicy.CHECK_ORDER
    assert checks["transaction_boundary"]("购买") is True
    assert checks["low_audit_value_route"]("购买") is True
    assert checks["low_audit_value_route"]("隐私政策") is False


def test_pure_predicates_do_not_depend_on_the_explorer_module():
    from agent.ai_explorer.action_safety_checks import (
        bounds_tuple, is_destructive_confirmation, is_stale_or_invisible_target,
        is_transaction_target, is_unlabelled_structural_bounds_target,
    )

    assert is_transaction_target("立即购买", ()) is True
    assert is_transaction_target("隐私政策", ()) is False
    assert is_destructive_confirmation("确认注销", ()) is True
    assert is_stale_or_invisible_target("missing", ()) is False
    assert is_stale_or_invisible_target(
        "购买", ({"text": "购买", "displayed": True},),
    ) is True
    assert is_unlabelled_structural_bounds_target(
        "bounds:[0,0][1080,2400]", (),) is True
    assert bounds_tuple("[0,0][10,20]") == (0, 0, 10, 20)


def test_explorer_no_longer_defines_moved_safety_predicates():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "agent" / "ai_explorer" / "explorer_engine.py"
    ).read_text(encoding="utf-8")

    assert "def _is_transaction_target(" not in source
    assert "def _is_destructive_confirmation(" not in source
    assert "def _target_is_visible(" not in source
    assert "def _is_unlabelled_structural_bounds_target(" not in source
    # The low-value route adapter survives only as label resolution +
    # delegation; the vocabulary and the decision live in the pure module.
    assert source.count("def _is_low_audit_value_route(") == 1
    assert "Delegate to the pure predicate" in source
