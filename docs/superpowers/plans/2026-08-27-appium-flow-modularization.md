# Appium Traversal Flow Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move DFS/backtracking, document progression, permission scenario progression, and runtime recovery policy out of the Appium loop into independently testable modules.

**Architecture:** The explorer remains the I/O orchestrator: it observes a resolved page, asks policy modules for a directive, executes the directive through Appium, and records evidence. Modules accept immutable facts and return directives or state transitions; they never access a driver, task database, or LLM.

**Tech Stack:** Python 3, dataclasses, pytest, existing `DecisionDirective`, `DocumentReadingLedger`, `PermissionProbeLedger`, and `RuntimeRecoveryCoordinator`.

**Spec:** `docs/superpowers/specs/2026-08-27-unified-page-role-adjudication-design.md`

## Global Constraints

- Preserve deny-before-allow permission probing and existing evidence event names.
- Do not add package, app-name, or Activity-specific logic.
- Policy modules cannot call Appium or mutate evidence directly.
- The explorer owns all driver calls, checkpoint persistence, and event output.
- Do not commit or clean unrelated workspace changes.

---

### Task 1: DFS and safe-backtrack policy

**Files:**
- Create: `agent/ai_explorer/dfs_navigation.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_dfs_navigation.py`

**Interfaces:**
- Consumes: `DfsNavigationInput` including mode, role, visible sibling target, scroll eligibility, and safety blockers.
- Produces: `DfsNavigationDirective` with `explore_sibling`, `scroll`, `backtrack`, or `none`.

- [x] Write red tests showing a deep run clicks an unvisited sibling before backtracking, scrolls only after sibling exhaustion, and never applies either on consent, document, login, or low-value pages.
- [x] Implement the pure policy and replace the generic DFS/sibling-scroll branches in the explorer.
- [x] Run `python -m pytest backend/tests/test_dfs_navigation.py -q`.

### Task 2: Document flow policy

**Files:**
- Create: `agent/ai_explorer/document_flow.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_document_flow.py`

**Interfaces:**
- Consumes: document key, ledger state, blank/body/scroll observations, and configured bounds.
- Produces: a `DocumentFlowDirective` for wait, scroll, retry-stuck, complete-and-back, or incomplete-and-back.

- [x] Write red tests for blank-body retry, two-pass bottom confirmation, stuck-scroll abort, and already-complete document backtracking.
- [x] Implement pure transition policy using `DocumentReadingLedger`; route both in-app and external document branches through it.
- [x] Run focused document regressions, including empty WebView, scroll-session loss, and external return paths.

### Task 3: Permission scenario executor policy

**Files:**
- Create: `agent/ai_explorer/permission_scenario.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_permission_scenario.py`

**Interfaces:**
- Consumes: permission prompt facts, probe ledger state, denial outcome, and whether the original business action remains visible.
- Produces: `PermissionScenarioDirective` for answer, retry-business-action, mark blocked/subfeature/unconfirmed, or none.

- [x] Write red tests for deny starting a business-bound probe, one retry after denial, base-service blocked, and unconfirmed expiry.
- [x] Implement the pure scenario transitions and leave Appium answer/click operations in the explorer.
- [x] Run `python -m pytest backend/tests/test_permission_scenario.py -q`.

### Task 4: Device recovery policy boundary

**Files:**
- Modify: `agent/ai_explorer/runtime_recovery.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_runtime_recovery.py`

**Interfaces:**
- Consumes: operation kind, action safety, checkpoint/replay result, and recovery budget.
- Produces: an explicit recovery disposition: `retry_read`, `recovered_without_retry`, `redecide`, or `failed`.

- [x] Write red tests for read retry, external/system back satisfied by recovery, unsafe click requiring re-decision, and failed replay.
- [x] Return a typed recovery result while retaining compatibility booleans at the orchestration boundary.
- [x] Run `python -m pytest backend/tests/test_runtime_recovery_contract.py -q`.

### Task 5: Regression and architecture guardrails

**Files:**
- Modify: `backend/tests/test_explorer_architecture.py`
- Test: `backend/tests/test_appium_explorer.py`

- [ ] Add an architecture test that policy modules have no driver/evidence imports and are used by the explorer.
- [ ] Run focused module tests, then `python -m pytest backend/tests/test_appium_explorer.py -q`, `python -m compileall -q agent`, and `git diff --check`.
