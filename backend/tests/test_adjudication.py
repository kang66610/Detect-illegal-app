from types import SimpleNamespace

from agent.rule_engine.adjudication import build_adjudication_matrix


def test_all_31_items_receive_exactly_one_tri_state_result():
    matched = [SimpleNamespace(rule=SimpleNamespace(rule_id="RULE_3_1"))]
    runtime = {"scenario_coverage": {"attempted_items": ["1.1", "3.1"]}, "scenario_completed_items": ["1.1", "3.1"]}

    rows = build_adjudication_matrix(matched, runtime)

    assert len(rows) == 31
    assert {row["state"] for row in rows} <= {"violation", "no_violation_evidence", "not_covered"}
    assert next(row for row in rows if row["legal_key"] == "3.1")["state"] == "violation"
    assert next(row for row in rows if row["legal_key"] == "1.1")["state"] == "no_violation_evidence"
    assert next(row for row in rows if row["legal_key"] == "6.4")["state"] == "not_covered"


def test_no_evidence_is_never_used_when_scenario_was_not_attempted():
    rows = build_adjudication_matrix([], {"scenario_coverage": {"attempted_items": []}})
    assert all(row["state"] == "not_covered" for row in rows if row["evidence_scope"] == "device")


def test_clicking_an_entry_without_completing_the_scenario_remains_not_covered():
    rows = build_adjudication_matrix([], {"scenario_coverage": {"attempted_items": ["1.1"]}})
    assert next(row for row in rows if row["legal_key"] == "1.1")["state"] == "not_covered"


def test_attempted_scenario_counts_as_covered_in_lenient_mode():
    runtime = {"scenario_coverage": {"items": [{"item": "1.1", "state": "attempted"}]}}
    rows = build_adjudication_matrix([], runtime, attempted_as_covered=True)
    row = next(row for row in rows if row["legal_key"] == "1.1")
    assert row["state"] == "no_violation_evidence"
    assert "已尝试执行" in row["reason"]


def test_attempted_scenario_stays_not_covered_without_the_lenient_flag():
    runtime = {"scenario_coverage": {"items": [{"item": "1.1", "state": "attempted"}]}}
    rows = build_adjudication_matrix([], runtime, attempted_as_covered=False)
    assert next(row for row in rows if row["legal_key"] == "1.1")["state"] == "not_covered"


def test_blocked_scenario_is_never_marked_as_covered_in_lenient_mode():
    runtime = {"scenario_coverage": {"items": [{"item": "1.1", "state": "blocked_external", "reason": "外部文档不可用"}]}}
    rows = build_adjudication_matrix([], runtime, attempted_as_covered=True)
    assert next(row for row in rows if row["legal_key"] == "1.1")["state"] == "not_covered"


def test_permission_denial_service_rule_is_a_device_scenario_not_a_permanent_manual_only_check():
    rows = build_adjudication_matrix([], {"scenario_completed_items": ["4.2"]})
    row = next(item for item in rows if item["legal_key"] == "4.2")

    assert row["evidence_scope"] == "device"
    assert row["state"] == "no_violation_evidence"
