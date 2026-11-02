from agent.ai_explorer.llm_effectiveness import LLMEffectivenessLedger


def test_ledger_counts_accepted_and_rejected_proposals():
    ledger = LLMEffectivenessLedger()
    ledger.record_proposal(status="accepted")
    ledger.record_proposal(status="rejected", fallback_reason="model_error")
    ledger.record_proposal(status="rejected", fallback_reason="model_error")

    summary = ledger.summarize()

    assert summary["proposals_total"] == 3
    assert summary["proposals_accepted"] == 1
    assert summary["proposals_rejected"] == 2
    assert summary["rejection_reasons"]["model_error"] == 2


def test_ledger_totals_final_decisions_by_source_and_derives_fallback_ratio():
    ledger = LLMEffectivenessLedger()
    for _ in range(3):
        ledger.record_final_decision(source="llm")
    for _ in range(2):
        ledger.record_final_decision(source="deterministic_privacy_hub")
    ledger.record_final_decision(source="fallback")
    ledger.record_final_decision(source="fallback")

    summary = ledger.summarize()

    assert summary["decisions_total"] == 7
    assert summary["fallback_decisions"] == 2
    assert summary["decision_sources"]["llm"] == 3
    assert summary["fallback_ratio"] == round(2 / 7, 4)


def test_empty_ledger_reports_zeros_with_null_ratio_instead_of_dividing():
    summary = LLMEffectivenessLedger().summarize()

    assert summary["proposals_total"] == 0
    assert summary["decisions_total"] == 0
    assert summary["fallback_ratio"] is None


def test_summary_is_json_serializable_without_set_or_object_values():
    import json

    ledger = LLMEffectivenessLedger()
    ledger.record_proposal(status="rejected", fallback_reason="invalid_action")
    ledger.record_final_decision(source="safety_boundary")

    serialized = json.dumps(ledger.summarize(), ensure_ascii=False)

    assert "invalid_action" in serialized
