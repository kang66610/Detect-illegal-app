# Appium Explorer Deep Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Appium explorer's shared-string state and post-hoc decision rewrites with typed state, one arbitration path, semantic observations, evidence-driven scenarios, replayable LLM proposals, complete manual baselines, timeline replay, and measurable budgets.

**Architecture:** Keep the existing Appium worker operational while moving one invariant at a time behind deep modules in `agent/ai_explorer`. The main loop becomes an orchestrator for observation, proposals, arbitration, execution and evidence; compatibility mappings remain readable until all call sites migrate.

**Tech Stack:** Python 3.11+, pytest, dataclasses/enums, JSON/JSONL fixtures, existing Appium/OCR/LLM adapters.

**Spec:** `docs/superpowers/specs/2026-08-27-appium-explorer-deep-modularization-design.md`

## Global Constraints

- Do not add App names, package names, or page-title special cases to traversal logic.
- Manual reports are regression oracles only and never create findings or traversal priorities.
- The deny phase runs first; allow replays only consent/permission-dependent safe routes.
- Every scenario terminal state is backed by evidence or an explicit blocked/not-applicable reason.
- Preserve existing report fields and checkpoint evidence; append versioned fields only.
- Write and run a failing behavioral test before each production change.

---

### Task 1: Typed Run State and Versioned Checkpoints

**Files:**
- Modify: `agent/ai_explorer/runtime_state.py`
- Create: `agent/ai_explorer/run_checkpoint.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_explorer_runtime_state.py`

**Interfaces:**
- Consumes: the existing `ctx.runtime` mutable mapping and JSON-compatible checkpoint payloads.
- Produces: `DetectionRunState`, typed domain snapshots, `RunCheckpointCodec.dump(state)` and `RunCheckpointCodec.restore(payload, state)`.

- [ ] **Step 1: Write failing state-invariant tests**

```python
def test_allow_phase_reuses_navigation_but_not_deny_permission_state():
    state = DetectionRunState({})
    state.navigation.record_verified_route(["我的", "头像"])
    state.permission.begin_denial_probe("相机", "头像")
    state.begin_phase(ProbePhase.ALLOW)
    assert state.navigation.verified_routes == [("我的", "头像")]
    assert state.permission.active_probe is None

def test_checkpoint_rejects_future_schema_without_claiming_restore():
    state = DetectionRunState({})
    result = RunCheckpointCodec.restore({"schema_version": 999}, state)
    assert result.restored is False
    assert result.reason == "unsupported_future_schema"
```

- [ ] **Step 2: Run the new tests and confirm they fail because domain state/checkpoint interfaces do not exist**

Run: `python -m pytest backend/tests/test_explorer_runtime_state.py -q`

- [ ] **Step 3: Implement typed sub-state objects and checkpoint codec**

Implement phase, navigation, document, permission, login, scenario and budget ownership. Keep one compatibility mapping inside `DetectionRunState`; no other new module receives the raw mapping.

- [ ] **Step 4: Migrate checkpoint save/restore and phase transitions to the typed interface**

Replace `_RESUME_RUNTIME_KEYS` copying with the codec. Invalid or future checkpoints emit a recovery gap and start the current phase cleanly without deleting persisted evidence.

- [ ] **Step 5: Run state, recovery and phase tests**

Run: `python -m pytest backend/tests/test_explorer_runtime_state.py backend/tests/test_runtime_permission_reset.py backend/tests/test_state_machine.py backend/tests/test_appium_explorer.py -q`

### Task 2: One Final Action Arbitration Path

**Files:**
- Modify: `agent/ai_explorer/action_arbitration.py`
- Create: `agent/ai_explorer/action_pipeline.py`
- Modify: `agent/ai_explorer/decision_directive.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_action_pipeline.py`

**Interfaces:**
- Consumes: typed `ActionProposal` values plus a page semantic snapshot and run-state snapshot.
- Produces: one immutable `FinalAction` carrying chosen source, rejected proposals, safety reason and scenario association.

- [ ] **Step 1: Write failing arbitration tests**

```python
def test_final_action_cannot_be_rewritten_after_arbitration():
    final = ActionPipeline().choose(proposals, semantics=system_camera, state=state)
    assert final.action == "back"
    with pytest.raises(dataclasses.FrozenInstanceError):
        final.action = "restart"

def test_active_scenario_beats_llm_but_safety_beats_active_scenario():
    final = ActionPipeline().choose([llm_click, scenario_click], semantics=external_page, state=state)
    assert final.action == "back"
    assert final.source == "safety_scope_exit"
    assert [row.source for row in final.rejected] == ["scenario", "llm"]
```

- [ ] **Step 2: Run the tests and confirm missing `ActionPipeline`/`FinalAction` failures**

Run: `python -m pytest backend/tests/test_action_pipeline.py -q`

- [ ] **Step 3: Implement proposal collection, deterministic ranking and immutable final action**

Ranking is safety, active recovery, active scenario, document integrity, deterministic DFS and LLM. Deduplicate equivalent actions before ranking and preserve every rejection reason.

- [ ] **Step 4: Convert main-loop deterministic branches to proposals and remove post-arbitration rewrites**

The execution call accepts only `FinalAction`. `DecisionAudit` serializes the final action rather than inferring whether a mutable dictionary changed.

- [ ] **Step 5: Run action and Appium regression tests**

Run: `python -m pytest backend/tests/test_action_pipeline.py backend/tests/test_explorer_architecture.py backend/tests/test_appium_explorer.py -q`

### Task 3: Central Page Semantics and Target Catalog

**Files:**
- Modify: `agent/detection_engines/page_semantics.py`
- Create: `agent/ai_explorer/target_catalog.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_page_semantics_contract.py`

**Interfaces:**
- Consumes: `PageFacts` derived from Activity, package, elements, OCR, prior action and route.
- Produces: immutable `PageSemantics` and semantic `TargetCandidate` records used by every decision module.

- [ ] **Step 1: Write table-driven failing semantic tests**

```python
@pytest.mark.parametrize("fixture,role,login_wait,deep", [
    ("confirmed_policy_with_purchase_text", "document_body", False, True),
    ("change_phone", "business_interaction", False, True),
    ("logout", "privacy_hub", False, True),
    ("member_purchase", "low_value", False, False),
    ("feedback_icons", "business_interaction", False, True),
])
def test_semantics_are_structural_not_app_named(load_page_fixture, fixture, role, login_wait, deep):
    result = classify_observation(load_page_fixture(fixture))
    assert result.role.value == role
    assert result.requires_login_wait is login_wait
    assert result.allow_deep_search is deep
```

- [ ] **Step 2: Run the test and confirm classification/target-catalog gaps**

Run: `python -m pytest backend/tests/test_page_semantics_contract.py -q`

- [ ] **Step 3: Implement structural role precedence and semantic target clusters**

Target clusters cover account/profile, settings, privacy governance, complaint/feedback/help/contact, avatar/media, deletion/logout, permission-triggering business actions, documents and low-value commercial actions.

- [ ] **Step 4: Replace local `_is_*` and target-selection call sites with semantic snapshot queries**

Keep temporary compatibility functions as pure forwarding adapters only; delete each adapter once no call site remains.

- [ ] **Step 5: Run semantics, UI-role and navigation tests**

Run: `python -m pytest backend/tests/test_page_semantics_contract.py backend/tests/test_ui_roles.py backend/tests/test_navigation_state.py backend/tests/test_explorer_architecture.py -q`

### Task 4: Evidence-Driven Rule Scenario Execution

**Files:**
- Modify: `agent/rule_engine/scenario_execution.py`
- Modify: `agent/rule_engine/scenario_plan.py`
- Create: `agent/ai_explorer/scenario_controller.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_scenario_execution_paths.py`

**Interfaces:**
- Consumes: semantic page observations, final actions, action effects and evidence events.
- Produces: scenario proposals and evidence-backed terminal `ScenarioExecution` records.

- [ ] **Step 1: Write failing 4.2, 3.8 and blocked-path tests**

```python
def test_rule_4_2_requires_denial_retry_and_outcome():
    run = scenario("4.2")
    run.observe("permission_prompt", target="头像")
    run.observe("permission_denied", target="头像")
    assert run.terminal is False
    run.observe("business_action_retried", target="头像")
    run.observe("function_blocked", target="头像")
    assert run.state.value == "evidence_observed"

def test_navigation_exhaustion_does_not_complete_unexecuted_scenario():
    run = scenario("3.8")
    run.observe("navigation_exhausted")
    assert run.state.value == "pending"
```

- [ ] **Step 2: Run the tests and confirm current ledger lacks ordered event validation**

Run: `python -m pytest backend/tests/test_scenario_execution_paths.py -q`

- [ ] **Step 3: Implement scenario templates and ordered transitions**

Encode preconditions, semantic targets, action/evidence milestones, recoverable interruptions and explicit blocked states. Reject evidence that does not match the active step and semantic target.

- [ ] **Step 4: Replace direct `mark_completed` calls with scenario observations**

Compatibility completion events may update report counters only after `ScenarioController` returns an evidence-backed terminal state.

- [ ] **Step 5: Run scenario, evidence and latest-audit regressions**

Run: `python -m pytest backend/tests/test_scenario_execution_paths.py backend/tests/test_scenario_plan.py backend/tests/test_evidence_chain.py backend/tests/test_latest_audit_regressions.py -q`

### Task 5: Versioned LLM Proposal Adapter and Offline Evaluation

**Files:**
- Modify: `agent/ai_explorer/llm_controller.py`
- Create: `agent/ai_explorer/llm_proposal.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_llm_proposal.py`

**Interfaces:**
- Consumes: semantic snapshot, target whitelist, outstanding scenario summary and DFS status.
- Produces: validated `ActionProposal`, prompt trace metadata and deterministic fallback reason.

- [ ] **Step 1: Write failing whitelist, prompt-version and fallback tests**

```python
def test_llm_cannot_click_target_outside_current_catalog():
    result = adapter.validate({"action": "click", "target": "购买"}, allowed=["设置"])
    assert result.proposal is None
    assert result.fallback_reason == "target_not_visible_or_allowed"

def test_prompt_trace_contains_version_but_not_raw_credentials():
    trace = adapter.build_trace(snapshot_with_password_text)
    assert trace.prompt_version
    assert "secret" not in json.dumps(trace.as_dict())
```

- [ ] **Step 2: Run the test and confirm missing adapter contract**

Run: `python -m pytest backend/tests/test_llm_proposal.py -q`

- [ ] **Step 3: Implement payload construction, validation, redaction and deterministic fallback**

Only semantic target IDs are accepted. The adapter records latency, parse status, proposal and later adoption without storing credentials or full sensitive screen text.

- [ ] **Step 4: Move main-loop LLM payload construction into the adapter**

Feed the returned proposal into `ActionPipeline`; remove direct model-decision execution.

- [ ] **Step 5: Run LLM and action-pipeline tests**

Run: `python -m pytest backend/tests/test_llm_proposal.py backend/tests/test_ai_explorer.py backend/tests/test_action_pipeline.py backend/tests/test_appium_explorer.py -q`

### Task 6: Import Every Manual Report as a Regression Baseline

**Files:**
- Create: `agent/rule_engine/manual_baseline_import.py`
- Create: `agent/config/manual_baselines.yaml`
- Modify: `agent/rule_engine/manual_baseline.py`
- Modify: `agent/rule_engine/report_generator.py`
- Test: `backend/tests/test_manual_baseline_import.py`

**Interfaces:**
- Consumes: `.docx` report paths, explicit package mapping and known rule catalog.
- Produces: versioned baseline rows with source report, expected rule IDs, unresolved statements and optional ordered milestones.

- [ ] **Step 1: Write failing import and non-injection tests**

```python
def test_all_report_files_are_accounted_for(report_dir, baseline_catalog):
    names = {p.name for p in report_dir.glob("*.docx")}
    assert baseline_catalog.accounted_report_names() == names

def test_baseline_comparison_never_adds_a_finding():
    result = compare_manual_baseline("pkg", set(), catalog=fixture_catalog)
    assert result["false_negative"] == ["RULE_4_2"]
    assert result["detected"] == []
```

- [ ] **Step 2: Run the tests and confirm only five hard-coded baselines exist**

Run: `python -m pytest backend/tests/test_manual_baseline_import.py -q`

- [ ] **Step 3: Implement deterministic DOCX extraction and checked YAML catalog**

Import rule-number paragraphs, preserve unresolved text, require explicit package mapping, and reject unknown rule IDs. Populate the catalog for all reports currently in `app人工检测报告`.

- [ ] **Step 4: Load the catalog in report metrics without affecting findings or traversal**

Expose missing mappings and unresolved report statements as baseline-quality gaps, not detection findings.

- [ ] **Step 5: Run baseline, report and rules tests**

Run: `python -m pytest backend/tests/test_manual_baseline_import.py backend/tests/test_detection_accuracy.py backend/tests/test_rules.py backend/tests/test_report_template.py -q`

### Task 7: Redacted Timeline Replay Harness

**Files:**
- Create: `agent/ai_explorer/replay_format.py`
- Create: `agent/ai_explorer/replay_runner.py`
- Create: `backend/tests/fixtures/appium_replays/`
- Test: `backend/tests/test_appium_replay.py`

**Interfaces:**
- Consumes: versioned JSONL observations/actions/effects with redacted element values.
- Produces: deterministic final actions, scenario states, evidence events and regression metrics without a device.

- [ ] **Step 1: Write failing redaction, checkpoint and cross-phase replay tests**

```python
def test_replay_writer_redacts_credentials_and_device_identifiers(tmp_path):
    path = write_replay(tmp_path, sensitive_trace)
    body = path.read_text("utf-8")
    assert "secret" not in body
    assert "emulator-5554" not in body

def test_replay_resumes_from_checkpoint_and_reaches_same_scenario_state():
    whole = run_replay(fixture_path)
    resumed = run_replay(fixture_path, checkpoint=4)
    assert resumed.scenarios == whole.scenarios
```

- [ ] **Step 2: Run the tests and confirm replay interfaces are absent**

Run: `python -m pytest backend/tests/test_appium_replay.py -q`

- [ ] **Step 3: Implement schema validation, redaction and deterministic adapters**

Replay the real semantics, scenario and action modules; only Appium/OCR/LLM external calls are replaced by recorded adapters.

- [ ] **Step 4: Add minimal generic fixtures derived from known failure shapes**

Fixtures cover incomplete document scroll, duplicate document identity, false login gate, feedback icon permission trigger, camera back recovery, low-value pruning and deny-to-allow route reuse. Names describe behavior and contain no App-specific decision rule.

- [ ] **Step 5: Run replay and architecture tests**

Run: `python -m pytest backend/tests/test_appium_replay.py backend/tests/test_explorer_architecture.py backend/tests/test_latest_audit_regressions.py -q`

### Task 8: Performance Budgets, Completion Gate and Full Verification

**Files:**
- Create: `agent/ai_explorer/performance_budget.py`
- Modify: `agent/ai_explorer/exploration_completion.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Modify: `agent/config/default.yaml`
- Modify: `benchmarks/privacy_benchmark.yaml`
- Test: `backend/tests/test_performance_budget.py`
- Test: `backend/tests/test_benchmark_suite.py`

**Interfaces:**
- Consumes: timed operation observations and semantic surface/scenario value.
- Produces: budget decisions, per-operation metrics and evidence-honest completion results.

- [ ] **Step 1: Write failing semantic-budget and completion tests**

```python
def test_document_has_no_fixed_scroll_count_but_stuck_time_is_bounded():
    budget = PerformanceBudget(config)
    for _ in range(25):
        assert budget.allow_document_scroll(moved=True)
    assert budget.allow_document_scroll(moved=False) is True
    clock.advance(config.document_stuck_seconds + 1)
    assert budget.allow_document_scroll(moved=False) is False

def test_total_timeout_reports_pending_scenario_as_gap():
    result = completion.assess(total_budget_exhausted=True, scenarios=[pending_42])
    assert result.coverage_complete is False
    assert "4.2" in result.unfinished_items
```

- [ ] **Step 2: Run the tests and confirm fixed counters/current completion behavior fail**

Run: `python -m pytest backend/tests/test_performance_budget.py backend/tests/test_benchmark_suite.py -q`

- [ ] **Step 3: Implement injectable clock, operation metrics and semantic budgets**

Use elapsed time and stable-fingerprint progress for documents, bounded retries for no-effect actions, one-observation budgets for low-value surfaces, and explicit recovery budgets for active scenarios.

- [ ] **Step 4: Integrate metrics and truthful completion into the orchestration loop**

Emit page, stability, OCR, LLM, Appium and recovery durations plus repeat/no-effect ratios. Total timeout ends with coverage gaps rather than completed coverage.

- [ ] **Step 5: Run focused and complete verification**

Run focused: `python -m pytest backend/tests/test_performance_budget.py backend/tests/test_benchmark_suite.py backend/tests/test_appium_explorer.py -q`

Run full: `python -m pytest backend/tests -q`

Run syntax check: `python -m compileall -q agent backend/app`

Run a real-device smoke test only when the configured emulator and Appium service are available. Record it as not executed when unavailable; do not infer end-to-end success from unit tests.

