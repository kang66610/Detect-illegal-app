# Traversal Contract Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore pre-modularization traversal semantics: only the action that finally executes may commit candidate effects; first-run clause failures must retry the same clause; device-session failure must not fabricate an allow phase.

**Architecture:** Keep the existing DFS, deny/allow workflow, document ledger, final safety gate and action pipeline. Repair the handoff between `FinalAction` and `DirectiveSelectionSession`, then lock the real observable contracts with regression tests. Historical timelines remain immutable; new runs expose a blocked phase instead of creating a zero-coverage phase.

**Tech Stack:** Python 3.11, pytest, dataclasses, Appium explorer modules, Vue task progress view.

**Spec:** `docs/superpowers/plans/2026-08-28-appium-explorer-final-modularization.md`

## Global Constraints

- Do not change DFS ordering, permission deny/allow ordering, login waiting, document completion, permission policy, low-value pruning or LLM fallback.
- A directive effect, runtime update, event and completion may commit only when its own action, target and source remain final.
- Preserve immutable historical evidence; repair future-run behavior and its tests.
- Use test-first red/green cycles and run the full `backend/tests` suite before integration.

---

### Task 1: Lock post-arbitration effect ownership

**Files:**
- Modify: `backend/tests/test_decision_directive_commit.py`
- Modify: `agent/ai_explorer/directive_selection.py`

**Interfaces:**
- Consumes: `DirectiveSelectionSession.commit(final_action, activity)` and `FinalAction.token`.
- Produces: no callback/effect/runtime mutation when a post-arbitration replacement no longer equals the directive proposal.

- [ ] **Step 1: Write the failing regression test**

```python
def test_replaced_final_action_never_commits_original_directive_effect():
    effects = []
    proposal = session.add(
        DecisionDirective("click", "original", "", "deterministic", effects=("probe",)),
        on_selected=effects.extend,
    )
    session.commit(FinalAction("click", "replacement", "", "frontier_recovery", token=proposal.token), activity=".Main")
    assert effects == []
```

- [ ] **Step 2: Run the test and confirm it fails because the old token commits `probe`.**

Run: `python -m pytest backend/tests/test_decision_directive_commit.py -q`

- [ ] **Step 3: Implement the minimal token/action/source equality guard.**

`DirectiveSelectionSession.commit` must commit a token only when the matching proposal has the same `action`, `target` and `source` as `final_action`; otherwise drop the pending directive and return the replacement action unchanged.

- [ ] **Step 4: Re-run the directive tests.**

Run: `python -m pytest backend/tests/test_decision_directive_commit.py backend/tests/test_action_pipeline.py -q`

### Task 2: Preserve observed traversal recovery contracts

**Files:**
- Modify: `backend/tests/test_appium_explorer.py`
- Modify only if a test exposes a defect: `agent/ai_explorer/document_state.py`, `agent/ai_explorer/explorer_engine.py`, `agent/ai_explorer/appium_client.py`

**Interfaces:**
- Consumes: first-run document route, crash recovery, completion mismatch and runtime session recovery.
- Produces: same document route is retried once; mismatched body cannot consume the clicked route; emulator accessibility disconnect enters recovery instead of immediately starting a new profile.

- [ ] **Step 1: Run the existing concrete behavior tests.**

Run: `python -m pytest backend/tests/test_appium_explorer.py -k "consent_document_crash_retries or mismatched_document_route_remains_retryable or runtime_activity_disconnect" -q`

- [ ] **Step 2: Add a new failing test only if a real uncovered route differs from the contract.**

The assertion must observe target/action/event order, never source text or a mock call count.

- [ ] **Step 3: Apply the smallest production change required by that failing test.**

- [ ] **Step 4: Re-run the focused traversal tests.**

### Task 3: Protect phase truth and user-visible history

**Files:**
- Verify: `backend/tests/test_probe_phase_integrity.py`
- Verify: `backend/tests/test_workflow_coverage.py`
- Verify: `frontend/src/views/TaskProgress.vue`

**Interfaces:**
- Consumes: a deny result with `failure.category == "device_unavailable"`.
- Produces: no allow profile, persisted `phase_transition_blocked`, zero counters only when zero pages were actually observed.

- [ ] **Step 1: Run phase-boundary regressions.**

Run: `python -m pytest backend/tests/test_probe_phase_integrity.py backend/tests/test_workflow_coverage.py -q`

- [ ] **Step 2: Verify historical screenshot semantics against task 296 evidence.**

Task 296 has only three timeline entries because UiAutomator2 never created a session; do not synthesize missing first-phase actions.

- [ ] **Step 3: Update front-end copy only if it misstates that historical condition.**

### Task 4: Reconcile the modularization handoff and verify

**Files:**
- Modify: `docs/superpowers/plans/2026-08-28-appium-explorer-final-modularization.md`
- Modify: `docs/superpowers/plans/2026-08-31-traversal-contract-recovery.md`

- [ ] **Step 1: Record actual engine budget (9864/9866) and mark uncompleted page-cycle extraction as deferred, not complete.**

- [ ] **Step 2: Run full verification.**

Run: `python -m pytest backend/tests -q`

Run: `python -m compileall -q agent backend`

Run: `npm --prefix frontend run build`

- [ ] **Step 3: Run target-App real-device deny/allow smoke only after Appium and emulator readiness checks pass.**

