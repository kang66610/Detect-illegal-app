# Runtime Recovery and Phase Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement each task test-first.

**Goal:** Make every safe Appium action recover from a lost UiAutomator2 session without losing the semantic DFS checkpoint, and keep permission/login/document evidence truthful across deny and allow phases.

**Architecture:** `RuntimeRecoveryCoordinator` becomes the single recovery boundary for page reads and safe actions. It emits a visible waiting/recovered timeline, restores the audited package and replays only the persisted semantic route. Explorer branches classify action purpose (normal, external-return, system-return) but never implement their own recovery loop.

**Tech Stack:** Python, pytest, Appium/UiAutomator2, ADB-backed `AndroidDevice`.

**Spec:** `docs/superpowers/specs/2026-08-27-appium-explorer-deep-modularization-design.md`

## Global Constraints

- Do not add App names, package names or fixed page-title rules.
- Never reinstall an installed APK during recovery; retain app data and the run checkpoint.
- Never repeat a transaction, destructive action, permission response or consent action after recovery.
- A session failure, unavailable document, unavailable Frida monitor, or pending login must remain a coverage gap, not a compliant result.
- Every production change starts with a behavioral regression test that is observed to fail.

### Task 1: Unify Safe Action Recovery

**Files:**
- Modify: `agent/ai_explorer/runtime_recovery.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_appium_explorer.py`

**Interface:** add `RuntimeRecoveryCoordinator.perform_safe_action(step, decision, recovery_kind="normal") -> bool`. It saves a checkpoint before an action; on a runtime disconnect it emits `runtime_session_lost`, `runtime_session_waiting_for_recovery`, and `runtime_session_recovered`, then replays the route. It retries only idempotent `back`/navigation actions once.

- [ ] Write a client fixture whose Custom Tab `back` raises `ExplorationError("... socket hang up")`, whose `recover_runtime_session` succeeds, and whose app page is available after replay.
- [ ] Assert that the explorer continues, records the three recovery timeline events, records external return recovery, and does not abort the audit.
- [ ] Run this one test and observe its failure because direct `client.perform` bypasses recovery.
- [ ] Implement the coordinator action method and replace external/system/document safe return calls with it.
- [ ] Run the focused recovery and external-document tests.

### Task 2: Preserve Recovery Semantics and Observability

**Files:**
- Modify: `agent/ai_explorer/appium_client.py`
- Modify: `agent/ai_explorer/runtime_recovery.py`
- Test: `backend/tests/test_appium_client.py`
- Test: `backend/tests/test_appium_explorer.py`

**Interface:** recovery events distinguish `emulator_boot_wait` from `uiautomator2_restart`; existing `recover_runtime_session(...) -> bool` remains compatible.

- [ ] Write tests proving emulator loss calls `wait_until_ready`, while a physical/instrumentation loss skips boot waiting.
- [ ] Write an explorer test asserting the waiting event is emitted before the recovery call.
- [ ] Run the tests and observe the event assertion fail.
- [ ] Add recovery metadata/event emission without changing Appium client compatibility.
- [ ] Run all Appium client and runtime-recovery tests.

### Task 3: Poll Permission Grants and Preserve Login-Wait Fairness

**Files:**
- Modify: `agent/detection_engines/appium_explorer.py`
- Modify: `agent/ai_explorer/runtime_state.py`
- Test: `backend/tests/test_appium_explorer.py`
- Test: `backend/tests/test_explorer_architecture.py`

**Interface:** permission verification polls Android state until all selected permissions are granted or the bounded configured retry window expires; login wait shortening requires a previously-waited equivalent login gate, not merely `permission_only_phase`.

- [ ] Write a permission fixture returning `None`, `False`, then `True` and assert the final event is verified with all reads recorded.
- [ ] Write a phase-two first-login fixture and assert it uses `manual_login_wait_seconds`, not the short subsequent wait.
- [ ] Run both tests and observe failures against immediate verification/phase-only shortening.
- [ ] Implement the condition poll and semantic login-gate fingerprint state.
- [ ] Run permission, phase and login focused tests.

### Task 4: Keep Public DFS Ahead of Optional Login and Stabilize Document Identity

**Files:**
- Modify: `agent/detection_engines/appium_explorer.py`
- Modify: `agent/ai_explorer/runtime_state.py`
- Test: `backend/tests/test_appium_explorer.py`

**Interface:** a visible public semantic target with outstanding public scenarios is selected before a login invitation; document progress stores `origin_target`, observed body kind and canonical identity separately.

- [ ] Write a fixture containing a feedback/avatar target and a login invitation, with outstanding 4.2, and assert public target wins.
- [ ] Write a mismatched document fixture and assert report/evidence retains the clicked entry name while separately recording the observed body type, with no duplicate reopen.
- [ ] Run the tests and observe the login-first/document-label failure.
- [ ] Implement deterministic public-frontier deferral and canonical document identity fields.
- [ ] Run document, navigation and scenario focused tests.

### Task 5: Frida Degradation and Full Regression

**Files:**
- Modify: `agent/agent_core/workflow.py`
- Test: `backend/tests/test_frida_monitor.py`
- Test: `backend/tests/test_appium_explorer.py`

**Interface:** a Frida attach failure after the bounded fallback records a phase-scoped dynamic-evidence gap and leaves Appium traversal running; it never upgrades or removes UI evidence.

- [ ] Write a fixture that fails both spawn and fallback attach and asserts an unavailable phase status plus an explicit coverage gap.
- [ ] Run it and observe the current status/event mismatch, if any.
- [ ] Make the fallback result and failure stage deterministic; do not add extra process starts.
- [ ] Run all focused modules, then `python -m pytest backend/tests -q` and `python -m compileall -q agent backend/app`.
