from agent.rule_engine.recognition_contract import (
    CONTRACT,
    RULE_LEGAL_KEYS,
    completion_allowed,
    finding_kind_to_legal_keys,
)
from agent.rule_engine.recognition_coverage import ITEM_BY_KEY
from agent.rule_engine.rule_loader import load_rules
from agent.rule_engine.scenario_plan import ScenarioFrontier


def test_contract_covers_every_recognition_item_and_every_yaml_rule():
    assert set(CONTRACT) == set(ITEM_BY_KEY)
    yaml_ids = {rule.rule_id for rule in load_rules() if not rule.rule_id.startswith("RULE_EXT_")}
    mapped_ids = {rule_id for item in CONTRACT.values() for rule_id in item.rule_ids}
    assert yaml_ids <= mapped_ids


def test_every_rule_legal_key_matches_the_contract():
    for rule in load_rules():
        if rule.rule_id.startswith("RULE_EXT_"):
            assert rule.rule_id not in RULE_LEGAL_KEYS
            continue
        assert rule.rule_id in RULE_LEGAL_KEYS
        assert RULE_LEGAL_KEYS[rule.rule_id]


def test_finding_kinds_used_by_live_rules_are_registered():
    assert finding_kind_to_legal_keys("policy_missing") == {"1.1"}
    assert finding_kind_to_legal_keys("policy_entry_exceeds_four_clicks") == {"1.3"}
    assert finding_kind_to_legal_keys("collected_beyond_authorization") == {"3.3"}
    assert finding_kind_to_legal_keys("api_called_after_permission_denial") == {"3.2"}
    assert finding_kind_to_legal_keys("no_delete_entry") == {"6.1"}
    assert finding_kind_to_legal_keys("withdraw_consent_unavailable") == {"3.8"}
    assert finding_kind_to_legal_keys("first_run_notice_missing") == {"1.2"}
    assert finding_kind_to_legal_keys("targeted_push_no_opt_out") == {"3.6"}
    assert finding_kind_to_legal_keys("no_complaint_channel") == {"6.3"}
    assert finding_kind_to_legal_keys("complaint_processing_time_missing") == {"6.5"}


def test_frontier_ignores_completion_without_a_registered_evidence_source():
    frontier = ScenarioFrontier()
    frontier.mark_completed(["1.3", "3.8"])
    snapshot = {row["item"]: row["state"] for row in frontier.snapshot()["items"]}
    assert snapshot["1.3"] == "pending"
    assert snapshot["3.8"] == "pending"


def test_frontier_completes_only_with_an_allowed_source_or_finding():
    frontier = ScenarioFrontier()
    frontier.mark_completed(["1.1"], evidence_source="policy_document_read")
    frontier.mark_completed(["1.3"], finding_kind="policy_entry_exceeds_four_clicks")
    snapshot = {row["item"]: row["state"] for row in frontier.snapshot()["items"]}
    assert snapshot["1.1"] == "evidence_observed"
    assert snapshot["1.3"] == "evidence_observed"


def test_reading_a_policy_does_not_count_as_verifying_four_click_depth():
    assert not completion_allowed("1.3", evidence_source="policy_document_read")
    assert completion_allowed("1.1", evidence_source="policy_document_read")
    assert completion_allowed("1.4", evidence_source="terms_document_read")
    assert completion_allowed("1.4", evidence_source="all_consent_documents_read")
    assert completion_allowed("3.8", evidence_source="withdraw_entry_found")
    assert completion_allowed("3.8", finding_kind="withdraw_consent_unavailable")
    assert not completion_allowed("3.8", evidence_source="logout_confirmation_observed")
    assert completion_allowed("1.2", evidence_source="first_run_notice_observed")
    assert completion_allowed("3.6", evidence_source="personalization_opt_out_found")
    assert completion_allowed("4.5", evidence_source="consent_not_forced_for_service")
