# Unified Page Role Adjudication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every stable Appium observation produce one evidence-backed page role and one role-scoped target catalog before consent, document, login, DFS, or LLM logic chooses an action.

**Architecture:** Add immutable evidence and resolved-page models around the existing `PageSemantics` compatibility API. A single adjudicator applies the documented precedence, marks background candidates blocked by overlays, and requests a role-aware target catalog. The Appium loop will consume the resolved result once per observation, then attach its role/surface to final actions and LLM input.

**Tech Stack:** Python 3, dataclasses, pytest, existing Appium XML parser and semantic-navigation state.

**Spec:** `docs/superpowers/specs/2026-08-27-unified-page-role-adjudication-design.md`

## Global Constraints

- Do not add package-, Activity-, or App-name-specific branches.
- Do not treat OCR or LLM output alone as violation evidence or as an executable action.
- Keep deny-before-allow permission probing, manual login, scenario execution, and recovery boundaries unchanged.
- Preserve legacy `PageSemantics` consumers while migration proceeds; new fields must have safe defaults.
- Do not commit because the workspace already contains unrelated user changes.

---

### Task 1: Evidence model and authoritative role adjudicator

**Files:**
- Modify: `agent/detection_engines/page_semantics.py`
- Test: `backend/tests/test_page_semantics_contract.py`

**Interfaces:**
- Consumes: `PageFacts`, visible elements, optional route/runtime/LLM evidence.
- Produces: `PageEvidence`, `RoleEvidence`, `ResolvedPage`, and `PageRoleAdjudicator.resolve(evidence, elements)`.

- [ ] **Step 1: Write failing precedence and overlay tests**

```python
def test_consent_overlay_blocks_background_document_login_and_navigation():
    resolved = PageRoleAdjudicator().resolve(PageEvidence.from_facts(PageFacts(
        consent_dialog=True, document_body=True, login_gate=True, main_content=True,
    )), elements=())
    assert resolved.role is PageRole.CONSENT_DIALOG
    assert {item.role for item in resolved.blocked} == {
        PageRole.DOCUMENT_BODY, PageRole.LOGIN_GATE, PageRole.MAIN_CONTENT,
    }

def test_system_permission_outranks_consent_overlay():
    resolved = PageRoleAdjudicator().resolve(PageEvidence.from_facts(PageFacts(
        permission_prompt=True, consent_dialog=True,
    )), elements=())
    assert resolved.role is PageRole.SYSTEM_PERMISSION
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest backend/tests/test_page_semantics_contract.py -k "overlay or outranks" -q`

Expected: FAIL because the evidence and adjudicator APIs do not exist.

- [ ] **Step 3: Implement immutable evidence, resolved result, and precedence**

```python
class EvidenceSource(str, Enum):
    UI_TREE = "ui_tree"
    OCR = "ocr"
    ROUTE = "route"
    PREVIOUS_ACTION = "previous_action"
    RUNTIME_CHECKPOINT = "runtime_checkpoint"
    LLM_HINT = "llm_hint"

@dataclass(frozen=True)
class RoleEvidence:
    role: PageRole
    source: EvidenceSource
    strength: int
    hits: tuple[str, ...] = ()

class PageRoleAdjudicator:
    def resolve(self, evidence: PageEvidence, *, elements: tuple[dict, ...]) -> ResolvedPage: ...
```

Use the precedence in the spec. When an overlay wins, retain all lower-role candidates in `blocked`; the selected result owns the only executable role.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `pytest backend/tests/test_page_semantics_contract.py -k "overlay or outranks" -q`

Expected: PASS.

### Task 2: Role-scoped semantic target catalog

**Files:**
- Modify: `agent/ai_explorer/target_catalog.py`
- Modify: `agent/detection_engines/page_semantics.py`
- Test: `backend/tests/test_page_semantics_contract.py`

**Interfaces:**
- Consumes: `ResolvedPage.role`, overlay bounds, visible elements.
- Produces: `TargetCandidate` with `surface_id`, `execution_layer`, `bounds`, and `coordinate_only` fields.

- [ ] **Step 1: Write failing target-isolation tests**

```python
def test_consent_catalog_keeps_only_overlay_targets_and_allows_bounded_text_taps():
    resolved = resolve_consent_page_with_non_clickable_agree_decline_and_bottom_nav()
    labels = {target.label for target in resolved.targets}
    assert {"同意", "不同意", "隐私政策"} <= labels
    assert "我的" not in labels
    assert all(target.execution_layer == "overlay" for target in resolved.targets)

def test_plain_non_clickable_page_copy_never_becomes_coordinate_target():
    catalog = build_target_catalog([_element("欢迎使用", clickable=False)])
    assert catalog == ()
```

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `pytest backend/tests/test_page_semantics_contract.py -k "catalog and (consent or coordinate)" -q`

Expected: FAIL because catalogs have no role/surface restriction.

- [ ] **Step 3: Implement bounded overlay catalog generation**

Extend `TargetCandidate` with backward-compatible defaults. Permit a `bounds:` target only for a consent role and only if visible text, valid bounds, and consent/decline/document-link semantics jointly support it. Exclude elements outside the inferred overlay bounds and never create coordinate targets on normal pages.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `pytest backend/tests/test_page_semantics_contract.py -k "catalog and (consent or coordinate)" -q`

Expected: PASS.

### Task 3: Make `_page_semantics` the only observation adapter

**Files:**
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_appium_explorer.py`

**Interfaces:**
- Consumes: raw activity, parsed elements, OCR text, package context, `PageState`.
- Produces: `ResolvedPage` through `_page_semantics`; `_page_role` remains only a compatibility string projection.

- [ ] **Step 1: Write failing replay tests for non-clickable consent controls and document exclusion**

```python
def test_webview_consent_controls_are_adjudicated_before_document_or_login():
    semantics = _page_semantics(".MainActivity", webview_consent_elements, PageState())
    assert semantics.role is PageRole.CONSENT_DIALOG
    assert semantics.targets_by_label["同意"].coordinate_only is True
    assert semantics.requires_login_wait is False
    assert semantics.legacy_role != "document_body"
```

- [ ] **Step 2: Run focused test to verify it fails**

Run: `pytest backend/tests/test_appium_explorer.py -k "webview_consent_controls_are_adjudicated" -q`

Expected: FAIL because the raw helper currently requires clickable consent controls and does not expose the resolved catalog.

- [ ] **Step 3: Implement a pure evidence-extraction adapter**

Keep old `_is_*` helpers private evidence extractors only. Build `RoleEvidence` records in `_page_semantics`, including route and checked document-session facts. Do not call `_document_key`, `_is_login_gate`, or `_is_consent_dialog` directly from action selection once `current_page_semantics` is available.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest backend/tests/test_appium_explorer.py -k "webview_consent_controls_are_adjudicated" -q`

Expected: PASS.

### Task 4: Consume resolved role and catalog in deterministic branches, LLM, and DFS attribution

**Files:**
- Modify: `agent/detection_engines/appium_explorer.py`
- Modify: `agent/ai_explorer/llm_proposal.py`
- Modify: `agent/ai_explorer/action_arbitration.py`
- Test: `backend/tests/test_appium_explorer.py`
- Test: `backend/tests/test_llm_proposal.py`
- Test: `backend/tests/test_explorer_architecture.py`

**Interfaces:**
- Consumes: one `ResolvedPage` per stable observation.
- Produces: role-scoped LLM request, action metadata (`role`, `surface_id`, `execution_layer`), and overlay-local no-effect attribution.

- [ ] **Step 1: Write failing integration tests**

```python
def test_overlay_no_effect_does_not_exhaust_background_dfs_target():
    state, resolved = page_state_with_background_tab_and_consent_overlay()
    record_action_effect(state, resolved, target="同意", changed=False)
    assert not state.target_visited(background_page, "我的")

def test_llm_receives_resolved_catalog_not_raw_background_targets():
    result = LLMProposalAdapter(controller).propose_resolved(resolved_consent_page, visited=set())
    assert "我的" not in result.trace.request["page"]["targets"]
```

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `pytest backend/tests/test_appium_explorer.py -k "overlay_no_effect" -q; pytest backend/tests/test_llm_proposal.py -k "resolved_catalog" -q`

Expected: FAIL because action attribution and LLM payload still consult raw page targets.

- [ ] **Step 3: Implement role-scoped consumption**

Have consent, document, login, generic DFS, and LLM proposal branches read `current_page_semantics.role` and `targets`. Add role/surface metadata to decisions and action audit records. When a target is in an overlay catalog, isolate no-effect retries and do not update background `PageState` navigation edges or visited targets.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `pytest backend/tests/test_appium_explorer.py -k "overlay_no_effect" -q; pytest backend/tests/test_llm_proposal.py -k "resolved_catalog" -q; pytest backend/tests/test_explorer_architecture.py -q`

Expected: PASS.

### Task 5: Regression and compatibility verification

**Files:**
- Test: `backend/tests/test_page_semantics_contract.py`
- Test: `backend/tests/test_appium_explorer.py`
- Test: `backend/tests/test_llm_proposal.py`
- Test: `backend/tests/test_explorer_architecture.py`

- [ ] **Step 1: Run semantic, Appium, LLM, and architecture regressions**

Run: `pytest backend/tests/test_page_semantics_contract.py backend/tests/test_appium_explorer.py backend/tests/test_llm_proposal.py backend/tests/test_explorer_architecture.py -q`

Expected: PASS, including document-reading, login, consent, external-surface, DFS, and LLM allowlist regressions.

- [ ] **Step 2: Run the complete backend suite and syntax checks**

Run: `python -m compileall -q agent backend/app; pytest backend/tests -q; git diff --check`

Expected: all tests pass; no whitespace errors. Any device smoke test remains separately reported and is not substituted for unit regression.
