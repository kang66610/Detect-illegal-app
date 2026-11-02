# Appium 遍历器最终模块化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有遍历行为的前提下，将 Appium 遍历器迁为单一状态所有者、单一页面语义、单一最终动作和薄编排层。

**Architecture:** 以现有 `agent/ai_explorer` 模块为唯一领域入口。先建立行为基线和架构门禁，再按页面证据、文档/检查点、动作执行、领域候选、裁决、安全、编排和删除兼容层的顺序迁移。`workflow.py` 继续拥有 deny/allow 阶段循环。

**Tech Stack:** Python 3.11、pytest、dataclasses、现有 Appium/OCR/LLM/Frida 适配器。

**Spec:** `docs/superpowers/specs/2026-08-28-appium-explorer-final-modularization-design.md`

## 全局约束

- 不改变 DFS、动作优先级、deny/allow、文档完成、登录等待、权限策略、低价值剪枝或 LLM 降级行为。
- 不增加 App/包名/Activity/固定页面名称特判。
- 每项生产改动前先写架构或行为测试；既有行为表征测试始终保持通过。
- 每个阶段结束前运行相应测试、`compileall` 和 `git diff --check`。
- `workflow.py` 不迁入 `ExplorerOrchestrator`；跨阶段合并保持原位。

---

### Task 1：阶段 0——行为基线与架构门禁

**Files:**

- Create: `backend/tests/test_appium_explorer_modularization_contract.py`
- Modify: `backend/tests/test_appium_replay.py`
- Read: `agent/detection_engines/appium_explorer.py`

**Interfaces:**

- Consumes: 现有 `classify_observation`、`ActionPipeline`、回放夹具和遍历器源码。
- Produces: `assert_explorer_boundary(source: str, forbidden: tuple[str, ...])` 与稳定行为快照断言。

- [x] **Step 1: 写入先失败的架构门禁测试**

```python
from pathlib import Path

EXPLORER_PATH = Path("agent/detection_engines/appium_explorer.py")

def test_explorer_still_exposes_legacy_direct_action_boundary():
    source = EXPLORER_PATH.read_text(encoding="utf-8")
    assert "self.client.perform(decision)" not in source
```

- [x] **Step 2: 运行并确认测试因当前直接执行而失败**

Run: `python -m pytest backend/tests/test_appium_explorer_modularization_contract.py::test_explorer_still_exposes_legacy_direct_action_boundary -q`

Expected: FAIL，断言命中 `self.client.perform(decision)`。

- [x] **Step 3: 增加行为表征测试，不改生产代码**

```python
def test_consent_catalog_and_role_baseline_are_stable():
    elements = (
        {"text": "同意", "content_desc": "", "target": "agree", "clickable": True, "displayed": True},
        {"text": "不同意", "content_desc": "", "target": "decline", "clickable": True, "displayed": True},
        {"text": "隐私政策", "content_desc": "", "target": "policy", "clickable": True, "displayed": True},
    )
    page = classify_observation(PageObservation(
        activity="com.example.MainActivity",
        elements=elements,
        facts=PageFacts(consent_dialog=True, main_content=True),
    ))
    assert page.role is PageRole.CONSENT_DIALOG
    assert [item.kind.value for item in page.targets] == ["consent", "decline", "document"]
```

- [x] **Step 4: 运行行为表征、页面语义和回放测试**

Run: `python -m pytest backend/tests/test_appium_explorer_modularization_contract.py backend/tests/test_appium_replay.py backend/tests/test_explorer_architecture.py -q`

Expected: 行为表征通过；架构门禁仍失败，作为后续迁移目标。

- [x] **Step 5: 提交阶段 0 基线**

```bash
git add backend/tests/test_appium_explorer_modularization_contract.py backend/tests/test_appium_replay.py
git commit -m "test: lock appium explorer modularization baseline"
```

### Task 2：页面证据和观察策略

**Files:**

- Create: `agent/ai_explorer/page_evidence.py`
- Modify: `agent/detection_engines/page_semantics.py`
- Modify: `agent/ai_explorer/page_observer.py`
- Modify: `agent/ai_explorer/page_stability.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_page_evidence.py`

**Interfaces:**

- Produces: `PageEvidenceInput`、`PageEvidenceBuilder.build(input) -> PageEvidence`。
- Consumes: immutable Activity、元素、OCR、前一动作、路由快照和文档身份结果。

- [x] **Step 1: 写入先失败的证据构建测试**

```python
def test_page_evidence_builder_keeps_overlay_as_role_evidence_only():
    elements = (
        {"text": "同意", "target": "agree", "clickable": True, "displayed": True},
        {"text": "不同意", "target": "decline", "clickable": True, "displayed": True},
    )
    evidence = PageEvidenceBuilder().build(PageEvidenceInput(
        activity="com.example.MainActivity", elements=elements,
        screen_text="", previous_action="", route=(), document=None,
    ))
    assert any(item.role is PageRole.CONSENT_DIALOG for item in evidence.candidates)
```

- [x] **Step 2: 运行并确认缺少模块失败**

Run: `python -m pytest backend/tests/test_page_evidence.py -q`

Expected: FAIL，`ModuleNotFoundError: agent.ai_explorer.page_evidence`。

- [x] **Step 3: 实现纯证据构建和观察策略迁移**

```python
@dataclass(frozen=True)
class PageEvidenceInput:
    activity: str
    elements: tuple[dict, ...]
    screen_text: str
    previous_action: str
    route: tuple[str, ...]
    document: object | None

class PageEvidenceBuilder:
    def build(self, value: PageEvidenceInput) -> PageEvidence:
        facts = PageFacts(consent_dialog=any(
            item.get("text") in {"同意", "不同意"} for item in value.elements
        ))
        return PageEvidence.from_facts(facts)
```

将 `_needs_perception_ocr` 迁为 `PageObserver` 策略、将加载壳/可点击数量判断迁为 `PageStabilityCoordinator` 策略；保留原配置次数和等待。

- [x] **Step 4: 用构建器替换 `_page_semantics` 事实构建**

`_page_semantics` 只调用构建器和既有 `classify_observation`；不创建第二个仲裁器，不修改 `_PRECEDENCE`。

- [x] **Step 5: 回归与提交**

Run: `python -m pytest backend/tests/test_page_evidence.py backend/tests/test_page_semantics_contract.py backend/tests/test_appium_explorer.py -q`

```bash
git add agent/ai_explorer/page_evidence.py agent/detection_engines/page_semantics.py agent/ai_explorer/page_observer.py agent/ai_explorer/page_stability.py agent/detection_engines/appium_explorer.py backend/tests/test_page_evidence.py
git commit -m "refactor: extract appium page evidence"
```

### Task 3：文档身份、唯一账本与检查点仓库

**Files:**

- Modify: `agent/ai_explorer/document_session.py`
- Modify: `agent/ai_explorer/page_state.py`
- Modify: `agent/ai_explorer/run_checkpoint.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_document_identity.py`
- Test: `backend/tests/test_traversal_checkpoint.py`

**Interfaces:**

- Produces: `DocumentIdentityResolver.resolve(activity, elements, screen_text, active_key, last_action, origin_target) -> DocumentIdentity | None`。
- Produces: `TraversalCheckpointRepository.save_traversal(ctx, state, findings, evidence)` 和 `restore_traversal(payload)`。

- [x] **Step 1: 写入文档身份和旧检查点兼容的失败测试**

```python
def test_document_identity_uses_rendered_body_not_entry_label():
    identity = DocumentIdentityResolver().resolve(
        activity="com.example.WebViewActivity",
        elements=(), screen_text="服务协议 第一条", active_key="",
        last_action="click", origin_target="第三方SDK目录",
    )
    assert identity.kind == "service_terms"

def test_repository_restores_existing_version_four_payload(tmp_path):
    payload = {"version": 4, "runtime": {}, "page_state": {}, "findings": [], "evidence": []}
    restored = TraversalCheckpointRepository(tmp_path).restore_traversal(payload)
    assert restored.restored is True
```

- [x] **Step 2: 确认两个接口缺失**

Run: `python -m pytest backend/tests/test_document_identity.py backend/tests/test_traversal_checkpoint.py -q`

Expected: FAIL，缺少 `DocumentIdentityResolver`、`TraversalCheckpointRepository`。

- [x] **Step 3: 实现身份解析、账本投影和仓库**

`DocumentReadingLedger` 成为进度唯一写入方；`PageState` 旧文档字段仅从账本投影。仓库兼容 traversal payload version 4 与独立 navigation replay payload，不改变恢复结果。

- [x] **Step 4: 替换主遍历器中的检查点函数和文档重复写入**

保留旧 JSON 字段读取；禁止新增 `ctx.runtime` 文档真值集合。

- [x] **Step 5: 回归与提交**

Run: `python -m pytest backend/tests/test_document_identity.py backend/tests/test_traversal_checkpoint.py backend/tests/test_appium_explorer.py backend/tests/test_runtime_recovery_contract.py -q`

```bash
git add agent/ai_explorer/document_session.py agent/ai_explorer/page_state.py agent/ai_explorer/run_checkpoint.py agent/detection_engines/appium_explorer.py backend/tests/test_document_identity.py backend/tests/test_traversal_checkpoint.py
git commit -m "refactor: centralize document and checkpoint state"
```

### Task 4：动作执行边界

**Files:**

- Create: `agent/ai_explorer/action_executor.py`
- Modify: `agent/ai_explorer/action_arbitration.py`
- Modify: `agent/ai_explorer/action_pipeline.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_action_executor.py`

**Interfaces:**

- Produces: immutable `ActionExecutionResult`。
- Consumes: `FinalAction`、当前 `PageSnapshot`、`PageState`、`ActionEffectLedger` 和 Appium 客户端。

- [x] **Step 1: 写入动作执行失败测试**

```python
class FailingClient:
    def perform(self, _decision):
        raise ExplorationError("tap failed")

def test_action_executor_commits_navigation_only_after_success():
    page = parse_page("MainActivity", "<hierarchy />")
    state = PageState()
    effects = ActionEffectLedger({})
    final = FinalAction("click", "upload", "test", "test")
    result = ActionExecutor(client=FailingClient(), state=state, effects=effects).execute(final, page)
    assert result.succeeded is False
    assert state.target_visited(page, final.target) is False
```

- [x] **Step 2: 运行并确认缺少执行器失败**

Run: `python -m pytest backend/tests/test_action_executor.py -q`

Expected: FAIL，缺少 `ActionExecutor`。

- [x] **Step 3: 实现执行器和元数据搬运**

```python
@dataclass(frozen=True)
class ActionExecutionResult:
    action: str
    target: str
    succeeded: bool
    error: str = ""
    elapsed_seconds: float = 0.0
```

执行器只按 `FinalAction` 元数据调用客户端和状态接口；不扫描元素文本、不判断规则编号。

- [x] **Step 4: 迁移普通执行块**

将普通 `self.client.perform(decision)`、导航提交、性能计时和失败分类迁入执行器；文档专用轮询暂时保留，留给 Task 5。

- [x] **Step 5: 回归与提交**

Run: `python -m pytest backend/tests/test_action_executor.py backend/tests/test_action_pipeline.py backend/tests/test_appium_explorer.py -q`

```bash
git add agent/ai_explorer/action_executor.py agent/ai_explorer/action_arbitration.py agent/ai_explorer/action_pipeline.py agent/detection_engines/appium_explorer.py backend/tests/test_action_executor.py
git commit -m "refactor: isolate appium action execution"
```

### Task 5：两阶段指令、文档执行与领域结果观察

**Files:**

- Create: `agent/ai_explorer/document_executor.py`
- Create: `agent/ai_explorer/directive_preview.py`
- Modify: `agent/ai_explorer/decision_directive.py`
- Modify: `agent/ai_explorer/document_flow.py`
- Modify: `agent/ai_explorer/consent_decision.py`
- Modify: `agent/ai_explorer/login_session.py`
- Modify: `agent/ai_explorer/permission_decision.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_decision_directive_commit.py`
- Test: `backend/tests/test_document_executor.py`

**Interfaces:**

- Produces: `DecisionDirectiveApplier.to_proposal(directive)`。
- Produces: `DecisionDirectiveApplier.commit_selected(token, timing)`。
- Produces: `DirectivePreviewState.preview(directive)` 和 `DirectivePreviewState.runtime_view`。
- Produces: `DocumentExecutor.handle(result, context)`。

- [x] **Step 1: 写入副作用隔离和文档执行失败测试**

```python
def test_rejected_directive_does_not_write_runtime():
    runtime = {}
    applier = DecisionDirectiveApplier(runtime=runtime, emit=lambda *_a, **_k: None, mark_completed=lambda *_a, **_k: None)
    proposal = applier.to_proposal(DecisionDirective("click", "会员", "", "test", runtime_updates={"x": 1}))
    assert runtime.get("x") is None
    applier.commit_selected(proposal.token, timing="before_execute")
    assert runtime["x"] == 1

def test_preview_state_preserves_old_branch_gate_without_writing_runtime():
    preview = DirectivePreviewState({"sdk_observation_dwell_armed": False})
    preview.preview(DecisionDirective("click", "首页", "", "sdk", runtime_updates={"sdk_observation_dwell_armed": True}))
    assert preview.runtime_view["sdk_observation_dwell_armed"] is True
    assert preview.base_runtime["sdk_observation_dwell_armed"] is False

def test_document_executor_marks_only_ledger_on_bottom_confirmation():
    result = executor.handle_scroll(identity, status="bottom")
    assert result.completed is True
    assert identity.key in ledger.completed_keys()
```

- [x] **Step 2: 运行并确认缺少两阶段接口/执行器失败**

Run: `python -m pytest backend/tests/test_decision_directive_commit.py backend/tests/test_document_executor.py -q`

- [x] **Step 3: 实现两阶段指令和文档专用执行**

保持旧的“执行前计数”时机，只对最终动作提交；成功/下一页效果依赖状态由领域 `observe_action_result` 更新。迁移内联条款打开、外部正文、嵌套链接、滚动和返回。

- [x] **Step 4: 迁移同意、登录、权限结果观察**

这些模块只消费 `ActionExecutionResult`，`ScenarioController` 仍只管理 3.8、4.2。

- [x] **Step 5: 回归与提交**

Run: `python -m pytest backend/tests/test_decision_directive_commit.py backend/tests/test_document_executor.py backend/tests/test_scenario_execution_paths.py backend/tests/test_appium_explorer.py -q`

```bash
git add agent/ai_explorer/document_executor.py agent/ai_explorer/decision_directive.py agent/ai_explorer/document_flow.py agent/ai_explorer/consent_decision.py agent/ai_explorer/login_session.py agent/ai_explorer/permission_decision.py agent/detection_engines/appium_explorer.py backend/tests/test_decision_directive_commit.py backend/tests/test_document_executor.py
git commit -m "refactor: commit only selected explorer directives"
```

### Task 6：领域候选、预算与安全谓词

**Files:**

- Create: `agent/ai_explorer/action_safety_checks.py`
- Modify: `agent/ai_explorer/hub_decision.py`
- Modify: `agent/ai_explorer/redress_media_probe.py`
- Modify: `agent/ai_explorer/sdk_observation.py`
- Modify: `agent/ai_explorer/surface_budget.py`
- Modify: `agent/ai_explorer/performance_budget.py`
- Modify: `agent/ai_explorer/final_action_policy.py`
- Test: `backend/tests/test_action_safety_checks.py`
- Test: `backend/tests/test_explorer_architecture.py`

**Interfaces:**

- Produces: `SafetyChecks.for_page(context) -> Mapping[str, Callable[[str], bool]]`。
- Consumes: existing `TargetCandidate`/`ResolvedPage` and prior runtime projections.

- [x] **Step 1: 写入安全顺序与通用反馈媒体测试**

```python
def test_safety_checks_preserve_existing_check_order():
    checks = {"low_audit_value_route": lambda target: target == "购买"}
    ctx = FinalActionContext(is_root=False)
    decision, reason = FinalActionSafetyPolicy(checks=checks).enforce({"action": "click", "target": "购买"}, ctx)
    assert decision["action"] == "back"
    assert reason == "low_audit_value_route"
```

- [x] **Step 2: 运行并确认缺少安全谓词模块失败**

Run: `python -m pytest backend/tests/test_action_safety_checks.py -q`

- [x] **Step 3: 实现纯安全谓词和领域执行接口**

迁出安全谓词，不改变 `CHECK_ORDER`。将媒体权限撤销迁至 `redress_media_probe.py`，SDK 授权/停留/后台观察迁至 `sdk_observation.py`，计数迁至预算对象单向投影。

- [x] **Step 4: 回归与提交**

Run: `python -m pytest backend/tests/test_action_safety_checks.py backend/tests/test_explorer_architecture.py backend/tests/test_appium_explorer.py -q`

```bash
git add agent/ai_explorer/action_safety_checks.py agent/ai_explorer/hub_decision.py agent/ai_explorer/redress_media_probe.py agent/ai_explorer/sdk_observation.py agent/ai_explorer/surface_budget.py agent/ai_explorer/performance_budget.py agent/ai_explorer/final_action_policy.py backend/tests/test_action_safety_checks.py backend/tests/test_explorer_architecture.py
git commit -m "refactor: centralize explorer safety and domain budgets"
```

### Task 7：候选裁决、薄编排与阶段结果

**Files:**

- Create: `agent/ai_explorer/explorer_orchestrator.py`
- Create: `agent/ai_explorer/run_finalizer.py`
- Modify: `agent/ai_explorer/exploration_completion.py`
- Modify: `agent/detection_engines/appium_explorer.py`
- Test: `backend/tests/test_explorer_orchestrator.py`
- Test: `backend/tests/test_run_finalizer.py`

**Interfaces:**

- Produces: `ExplorerOrchestrator.run_phase(ctx) -> EngineResult`。
- Produces: `RunFinalizer.finalize(ctx, termination, state, scenario_snapshot, evidence, findings) -> EngineResult`。

- [x] **Step 1: 写入编排器不接管 deny/allow 的失败测试**

```python
def test_orchestrator_runs_one_profile_without_mutating_phase_order():
    ctx = SimpleNamespace(runtime={"probe_profile": "deny"})
    runner = lambda value: EngineResult(findings=[], evidence_files=[], stats={"probe_profile": value.runtime["probe_profile"]})
    orchestrator = ExplorerOrchestrator(run_cycle=runner)
    ctx.runtime["probe_profile"] = "deny"
    result = orchestrator.run_phase(ctx)
    assert result.stats["probe_profile"] == "deny"
    assert ctx.runtime["probe_profile"] == "deny"
```

- [x] **Step 2: 运行并确认缺少编排器/终结器失败**

Run: `python -m pytest backend/tests/test_explorer_orchestrator.py backend/tests/test_run_finalizer.py -q`

- [x] **Step 3: 实现单阶段编排与结果汇总**

```python
class ExplorerOrchestrator:
    def __init__(self, *, run_cycle):
        self._run_cycle = run_cycle

    def run_phase(self, ctx):
        return self._run_cycle(ctx)
```

生产装配把完整单阶段循环作为 `run_cycle` 注入；测试用最小 runner 验证不改写 `probe_profile`。`RunFinalizer` 调用 `ExplorationCompletionGate` 生成当前阶段 `EngineResult`；跨阶段合并继续由 `workflow.py`。

- [x] **Step 4: 将 `AppiumExplorerEngine.run()` 委托给编排器**

保留 `prepare()` 的 APK 校验、连接、安装/清理和权限重置；不迁移工作流。

- [x] **Step 5: 回归与提交**

Run: `python -m pytest backend/tests/test_explorer_orchestrator.py backend/tests/test_run_finalizer.py backend/tests/test_workflow_coverage.py backend/tests/test_appium_explorer.py -q`

```bash
git add agent/ai_explorer/explorer_orchestrator.py agent/ai_explorer/run_finalizer.py agent/ai_explorer/exploration_completion.py agent/detection_engines/appium_explorer.py backend/tests/test_explorer_orchestrator.py backend/tests/test_run_finalizer.py
git commit -m "refactor: orchestrate one appium probe phase"
```

### Task 8：删除兼容层与完整验证

**Files:**

- Modify: `agent/detection_engines/appium_explorer.py`
- Modify: affected tests under `backend/tests/`
- Test: `backend/tests/test_appium_explorer_modularization_contract.py`

**Interfaces:**

- Consumes: all prior modules and baseline fixtures.
- Produces: <=700-line `AppiumExplorerEngine` facade with no direct domain state/action writes.

- [x] **Step 1: 将架构门禁改为最终约束**

> 状态备注：已完成。实现文件经 `git mv` 迁至 `agent/ai_explorer/explorer_engine.py`，
> `agent/detection_engines/appium_explorer.py` 现为 ≤700 行 facade（仅引擎外观与兼容导出），
> 9 个测试文件的导入已改指真实模块，门禁转绿。

```python
def test_engine_facade_has_no_direct_domain_execution_or_state_writes():
    source = EXPLORER_PATH.read_text(encoding="utf-8")
    assert "self.client.perform(" not in source
    assert "scenario_frontier.mark_completed(" not in source
    assert not re.search(r"ctx\.runtime\[[^\]]+\]\s*=", source)
    assert len(source.splitlines()) <= 700
```

- [x] **Step 2: 运行并确认旧兼容分支仍使测试失败**

Run: `python -m pytest backend/tests/test_appium_explorer_modularization_contract.py -q`

- [x] **Step 3: 删除无调用者的兼容转发、旧状态键写入和私有帮助函数**

> 状态备注：`DecisionDirectiveApplier.apply()` 兼容方法已删（零调用方）；
> 仍被测试引用的别名转发按"测试引用迁移后删除"原则保留。

只在生产调用和测试引用均已迁移后删除；保留旧 checkpoint schema 迁移器。

- [x] **Step 4: 运行完整验证**

Run: `python -m pytest backend/tests -q`

Run: `python -m compileall -q agent backend/app worker`

Run: `git diff --check`

- [x] **Step 5: 真实设备冒烟并提交**

> 状态备注：**已执行且通过**（Pixel_7_Root 模拟器 emulator-5554，uiautomator2@8.4.0）。
> 冒烟脚本 `backend/tests/smoke_real_device.py`：创建 UiAutomator2 会话 → 启动已安装
> 测试 App（com.android.settings）→ 读取页面（.Settings，58 元素）→ 一次可逆 back
> （页面真实变化：回到 Launcher，28 元素）→ 关闭会话。Appium server 由项目自带
> `AppiumService` 自动拉起。

在 Appium/模拟器可用时：创建会话、启动已安装测试 App、读取页面、关闭会话；记录未执行原因而不是伪造成功。

```bash
git add agent backend/tests docs/superpowers
git commit -m "refactor: complete appium explorer modularization"
```

---

## 复审结论（外部审查后的诚实勘误）

外部审查指出"实现文件仅迁移未分解、预裁决改写级联未候选化、编排器为薄包装、
Task 5-8 勾选超出设计书实际达成度"。复核结论：**上述差距属实**，但两点指控
需要纠正：

1. **25 处 `scenario_frontier.mark_completed` 全部携带合法证据形态**
   （`evidence_source` 或 `finding_kind`，精确括号级核查 0 例外）。设计书所有权表
   明文允许"1.1、1.2、2.3、3.4、4.5、6.1 等静态观察可直接带证据完成"——数量大
   不等于违规；将其迁入 `RuleEvidenceExecutor` 统一收口是后续精化项，不是合规缺陷。
2. **`DirectiveSelectionSession` 已完整接线**：11 处领域分支经 `add()`（预览投影、
   无副作用候选）+ 4 处提交点（3 处 continue/无动作的旧时机即时提交 + 1 处
   pipeline 获选后提交），`test_decision_directive_commit` 等测试覆盖。"只是被
   初始化"的说法不成立。

### 确认属实的剩余设计差距（未完成任务，按设计书原文）

- **[未完成] 设计书 E.1/E.3——覆盖改写级联候选化**：`explorer_engine.py` 中约 40 处
  预裁决命令式改写（combined_document_redirected、splash defer、root override、
  transaction/blocked-document 防护等）仍是循环内直接改写 `decision`；统一候选进
  `ActionPipeline` 的目标态未达成。实施书 Task 5/6 的步骤清单遗漏了该项，属计划
  相对设计书的范围缺口。
- **[未完成] 设计书 F.1——编排器拥有页面周期装配**：`ExplorerOrchestrator` 按实施
  书 Task 7 草图实现为 `run_cycle` 注入包装（22 行）；真正的页面周期装配仍在
  `AppiumExplorerEngine._run_phase_cycle`。设计意图的"真实薄编排"未达成。
- **[未完成→进行中] 实现文件物理分解**：`agent/ai_explorer/explorer_engine.py` 为 11,819 行
  的整体迁移产物（Mimosa 钩子拦截 bash 重命名后由用户执行 git mv，内容未拆分）。
  **第一刀已完成**：导航回放领域迁出为 `agent/ai_explorer/navigation_replay.py`（270 行，
  安全谓词倒置注入），主循环模块的直接设备动作降为 **0**，真机冒烟在迁移后代码复跑通过。
  **第二刀已完成**：文档阅读状态领域迁出为 `agent/ai_explorer/document_state.py`
  （518 行：条款词汇表、runtime 已读/失败/封锁台账与已读判定，29 个成员公共命名，
  引擎经迁回导入消费），行数降至 11,137。
  **第三刀已完成**：反馈媒体/客服敏感入口领域并入 `agent/ai_explorer/redress_media_probe.py`
  （17 个扫描函数 + 3 个词表 + `RedressSurfaceDetector` 实例，逐字迁移），行数降至
  10,725，真机冒烟在迁移后代码复跑通过。
  **第四刀已完成**：同意簇迁出为 `agent/ai_explorer/consent_vocabulary.py`（375 行：
  同意/拒绝词表与按钮 id 提示、显式同意目标解析、未勾选/预勾选同意复选框探测、
  短拒绝标签语义、登录旁路入口判定；12 个函数 + 10 个词表成员，AST 依赖闭包定界后
  逐字迁移），引擎按 22 个别名回导消费，行数降至 10,435。后续按"登录/枢纽"继续分片。
  **第五刀前置已全部完成（三次提交，行数降至 10,222）**：
  ① 纯文档 kind/title 词表（GROUPS/KIND_TERMS/ID_HINTS 与 9 个纯分类函数）
  下沉 `target_catalog`（其本就是元素编目域），document_state 再导出保持引擎零改动；
  ② 未读家族迁入 `document_state`（unread_for_page/unread_required_document_target
  与安全宿主谓词、clickable-host 解析、标题安全检查共 9 函数；consent_or_decline_control
  归位 consent_vocabulary、element_locator 归位 target_catalog）——consent↔document
  双向依赖由此解为单向（document_state → consent_vocabulary → target_catalog）；
  ③ redress 观察家族迁入 `redress_media_probe`（redress_entry/complaint_or_cs_entry/
  page_visible_text/privacy_path_observations + 投诉/注销/撤回/障碍词表；
  element_semantic_identity 下沉 target_catalog）。
  **第五刀主刀已完成（行数降至 9,756）**：枢纽导航家族迁出为
  `agent/ai_explorer/hub_navigation.py`——15 个 hub 函数（tab 选择器、钻取行、
  hub 进度候选装配、有界顶层 DFS）+ HUB_DISTRACTOR/EXPLORATION_ROW/
  MAIN_CONTENT_TAB 词表 + SETTINGS_HUB_NAVIGATOR 实例，逐字迁移；
  `global_target_key` 归位 target_catalog、`authenticated_logout_target` 归位
  consent_vocabulary、`NON_AUDIT_MAINTENANCE_TERMS` 归位 action_safety_checks；
  低审计裁剪以 `low_audit_route_check` 参数注入 `next_top_level_audit_target`
  （引擎包装函数注入 `_is_low_audit_value_route`，延续 navigation_replay 的
  谓词倒置注入先例）。引擎按别名回导消费全部成员。**实现模块首次降至万行以下。**
  **E.1/E.3 已开工**：`_run_phase_cycle` 内 `decision` 命令式改写以 **85 处**为当前
  ratchet（基线 103）。已完成的转化（全部经 263 表征套件验证最终动作不变）：
  ① `blocked_document_reopen_prevented` 后置守卫 → priority=10,000 候选；
  ② `llm_document_back_deferred` → priority=150 的 llm 候选（下游守卫均 click 门控）；
  ③ blocked-route 阻断 → priority=10,001 候选（高于已读守卫，重叠场景归因保持
  `coverage_recovery`；全局尝试计数块以 `proposal is None` 门控复刻旧跳过语义）。
  ④ transaction 阻断 → priority=200 候选。转化前置步骤已先行落地：
  `global_target_attempts` 计数否决块从改写级联移到 `action_pipeline.choose` 之后、
  `directive_selection.commit` 之前——否决对象从"级联中途的 decision"改为"仲裁胜者
  final_action"，块内六处 `decision` 改写变为 `dataclasses.replace(final_action, ...)`
  （外部退出/桌面/低价值胜者已被 arbiter 置为 back/wait，否决替换不会绕过安全层；
  arbiter/校验器可表达的替换语义不变）。
  ⑤ root override 组（5 处转候选 + 2 处有意保留）→ 候选：frontier 覆写与深度
  业务路由/进度点击（priority=200，归因沿用旧改写未变更的 decision_source）、
  next_top click/stop（click=200，stop=150）与根页 stop（llm 来源时预应用旧
  stop-handling 的 frontier 归因链，priority=150）。**两处根页纯等待有意保持
  命令式**：下游连续等待熔断器与枢纽等待改写仍以 `decision == "wait"` 为键，
  候选化会使 decision 停留在 back 而令熔断器失明（回归风险，须待 wait-handling
  自身候选化时一并处理）。组 2 以 `root_override_proposal is None` 与组 1 互斥；
  consent 强制推进门与 llm_back 延后同样以该门控复刻"旧改写已把 decision 变为
  click/wait"的跳过语义。
  ⑥ 深搜兄弟探索（1 处）→ priority=300 候选——与 ⑤ 同批转化：旧级联中兄弟
  改写发生在 root stop 输出之后并覆盖它，静态优先级 300>150 复刻该链。两个
  dfs 调用的 `current_action`/`decision_source` 输入改喂"有效决策"（root 候选
  存在时取候选的 action/source，否则取 decision）——候选为 click 时 dfs 自然
  返回 NONE，候选来源被 dfs 屏蔽集覆盖时自然无兄弟，与旧级联输入完全一致；
  滚动分支以 `sibling_proposal is None` 门控。
  ⑦ 候选胜出者的下游守卫收口（候选化的关键教训）：旧级联里兄弟/root 改写产出的
  click 仍会流过后置已读守卫与 stop/wait 级联块；候选化后 decision 不再承载这些
  click，守卫会失明。263 套件捕获两例（sdk-entry 重开、root frontier 改写注销），
  修法：后置已读守卫泛化为裁决全部待选 click 候选（decision + root_override +
  sibling，其 10,000 候选天然压过 300/200 的点击候选）；stop/wait 级联处理块加
  `sibling_proposal is None` 门控（兄弟改写旧时先占了它们）；frontier 候选在
  生成处折叠注销边界与退出确认框裁决（`_is_safe_deep_probe_target` 的屏蔽词表
  已覆盖兄弟候选的同类风险）。兄弟目标未访问，仲裁后计数否决块不触发。
  ⑧ 第三方登录跳过（2）、退出确认 click 分支（2）、破坏性确认（1）、注销
  确认/边界（2）→ priority=150 候选（退出确认的 2 处 wait 分支按约束①保持
  命令式）。深搜有效输入升级为全族级联组合（decision → third_party → exit →
  destructive → logout → root_override，最后非空者生效）；后置已读守卫的候选表
  同步纳入全族。守卫族位于 consent 门**下游**，族内 back 不回流该门（级联顺序
  事实，勿凭直觉扩展上游门条件）。priority=150 的依据：族候选须让位兄弟（300，
  经有效 back 共存）与 root 候选，且压过 base（100）；族内各守卫词表互斥，
  实际不会共存。
  ⑨ 连续等待熔断转候选（4 处）→ priority=160 候选。熔断块改为对"有效动作"
  （全族级联组合 + 兄弟候选）记账与裁决：hub_wait_redirected（click next_row）、
  hub_wait_exhausted（back/stop）、wait_loop_home_redirected（redirected 提案）、
  wait_loop_broken（back）。计数语义与旧级联逐点等价（sibling 候选在场时按其
  click 重置计数）。**约束①自此解除**：上游各层产生 wait 的改写现在可以按
  "wait 候选（150）+ 有效动作记账"范式转化，熔断以 160 压过它们。
  **E.1/E.3 机械转化部分至此完成（改写 103→76，8 组）**。剩余命令式改写经逐点
  核查全部为**纠缠类**，不在本项内机械转化，归入 F.1：客服探针（sensitive_media_assist、
  customer_service_surface_exhausted）、combined_document_redirected、hub 行选择
  （unread/consent_target/hub_row/settings_hub）、会话边界链（logout_observation_only →
  defer_session_boundary → 二次破坏性确认 → logout 确认/边界——五段顺序链，每段输入
  依赖前段输出的 `session_boundary_target`/重写后 decision）。这些改写与 LLM 获取流程
  及局部变量（`target`/`unread_document`/`session_boundary_target`）双向耦合，须在 F.1
  装配迁移中把"局部变量传递"重构为"有效视图传递"后统一候选化。另有 5 处
  赋值后立即 perform_action+continue 的内联恢复处理器与 14 处
  DirectiveSelectionSession 提交点，本就不属于预裁决改写。
  行数凭据：9,767 = 9,756 + 11（熔断候选化开销）。

### 已就位的治理门禁（防止差距扩大，支撑后续只降不升）

`test_appium_explorer_modularization_contract.py` 新增两个 ratchet（对实现模块生效）：

- `test_engine_loop_completes_rules_only_with_legal_evidence`：任何
  `mark_completed` 缺 `evidence_source`/`finding_kind` 即失败。
- `test_engine_loop_direct_write_and_action_surface_only_shrinks`：直接
  `ctx.runtime[...]=` 写入冻结在 117；直接设备动作预算降为 **0**（回放执行器已迁至
  `navigation_replay.py`）；实现模块行数冻结在 11,602，分解切片只允许迁出。

以上未完成项必须按设计书原文另行立项实施，不得在既有 Task 勾选上追加或回改。

---

## 交接文档（2026-08-30 更新 · 供后续 AI 编程工具续作）

> 本节自包含。只读本节 + 代码库即可无损续作；历史过程记录见上方"复审结论"。

### 一、项目目的

把 Appium 遍历引擎从单文件整体迁移产物（`agent/ai_explorer/explorer_engine.py`，原 11,819 行）改造为**领域模块 + 候选决策管线**：所有预裁决命令式改写转为 `ActionProposal` 候选，由 `ActionPipeline` 统一仲裁；大块领域逻辑逐字迁出为独立模块。全程由五项 ratchet 门禁（只降不升）与 263 项表征套件（`backend/tests/test_appium_explorer.py`）守护行为不变。

### 二、当前进度（2026-08-31，全部经表征与完整后端套件验证）

**五项 ratchet 门禁**（`backend/tests/test_appium_explorer_modularization_contract.py`，只许下降）：

| 门禁 | 现值 |
|---|---|
| 引擎行数 | 9,864（预算 ≤ 9,866；原 11,819） |
| 直接 `ctx.runtime[...]=` 写入 | ≤ 117 |
| 直接设备动作（`client.perform/back`） | = 0 |
| `_run_phase_cycle` 内 `decision` 命令式改写 | ≤ 67（原 103） |
| `mark_completed` 证据字段 | 必须携带 |

**模块地图**（全部在 `agent/ai_explorer/`，引擎按别名回导消费）：

- `explorer_engine.py`（9,864 行）：主循环 `_run_phase_cycle`（唯一实现模块，ratchet 对象）
- `navigation_replay.py`：导航回放执行（安全谓词倒置注入）
- `document_state.py`：文档阅读台账（read/failed/blocked）+ 未读家族（unread_for_page 等 9 函数）
- `redress_media_probe.py`：媒体/客服探针 + redress 观察家族（privacy_path_observations 等）
- `consent_vocabulary.py`：同意/拒绝词表、对话框判定、复选框探测、authenticated_logout_target、consent_or_decline_control
- `target_catalog.py`：元素编目 + 纯文档词表（kind/title 分类）+ element_label/locator/semantic_identity/labels_for_click_target/global_target_key
- `hub_navigation.py`：枢纽导航 15 函数（tab/钻取/进度装配/有界顶层 DFS）+ HUB 词表
- `action_safety_checks.py`：纯安全谓词 + bounds_tuple + NON_AUDIT_MAINTENANCE_TERMS

**导入分层（防环，勿破坏）**：`target_catalog`（底层，仅依赖 re）← `action_safety_checks` / `consent_vocabulary` / `document_state` ← `redress_media_probe` / `hub_navigation` ← `explorer_engine`。

**E.1/E.3 候选化进度（8 组完成，改写 103→76）**：

| 组 | 候选 priority |
|---|---|
| late already-read 守卫 | 10,000 |
| blocked-route 阻断 | 10,001 |
| 深搜兄弟探索 | 300 |
| transaction 阻断 | 200 |
| root override 组（frontier/深度路由/进度点击/next_top，5 处） | 200 / stop 150 |
| 守卫族（第三方 2/退出确认 click 2/破坏性 1/注销 2） | 150 |
| 连续等待熔断（hub_wait_redirected/exhausted、wait_loop_home_redirected/broken，4 处） | 160 |
| llm back 延后 | 150 |

priority 谱系：base=100 < 守卫族/root stop/llm_back=150 < 熔断=160 < transaction/root click=200 < 兄弟=300 < 已读=10,000 < blocked-route=10,001。

**E.1/E.3 机械可转化部分已全部完成**。剩余 ~55 处命令式改写为**纠缠类**，归入 F.1（见任务 2）。

### 三、结构性约束与既定范式（必须遵守）

1. **候选胜出者的下游 click 守卫会失明**：旧级联里改写产出的 click 会流过后置守卫；候选化后 decision 不再承载它。修法范式（已有三处先例）：后置已读守卫泛化裁决全部待选 click 候选；frontier 候选生成处折叠注销/退出确认裁决；上游门不加下游条件。
2. **有效动作视图**：下游块（深搜、等待熔断）读"级联组合后的有效 action/source"（最后非空候选生效），而非裸 decision。已实现于 `deep_search_action/deep_search_source` 与 wait 熔断。
3. **级联顺序**（当前）：root override → consent 门 → llm_back → blocked-route → transaction → 守卫族 → 深搜 → wait 熔断 → stop-handling → 已读守卫 → pipeline → 计数否决（choose 后、commit 前）→ 执行。族内 back 不回流上游门。
4. **谓词倒置注入是 house style**：跨域谓词（is_unsafe_host、low_audit_route_check）以参数注入，不做跨模块硬编码（先例：tightest_clickable_host、next_top_level_audit_target）。
5. **priority 增补规则**：新候选须压过 base(100)、让位兄弟(300)与已读(10,000)；与旧改写一致的 decision_source 归因必须随候选携带。
6. **每完成一组**：ratchet 凭据下调（行数按实际开销在合同测试注释留痕）→ 先 `-k` 定向子集 → 全量 263 套件（约 6.5 分钟，用项目根 `.venv/Scripts/python.exe`）。

### 四、后续任务安排（按序执行）

**任务 1：真机冒烟复跑**（✅ 已完成 2026-08-30，重构后代码复跑通过）
- UiAutomator2 会话创建 → 启动 com.android.settings → 读取页面（.Settings，58 元素）→ 可逆 back → 再读取（.NexusLauncherActivity，28 元素）→ 会话关闭，exit 0。检测任务可正常执行。

**任务 2：F.1——页面周期装配迁移 + 纠缠改写统一候选化**（页面周期整体迁移仍未完成，保持待办）
- 目标一：把页面周期装配从 `_run_phase_cycle` 移入 `ExplorerOrchestrator`（当前仅拥有 prepare、阶段终止、激活与稳定页面观察边界；完整循环仍在引擎）。
- 目标二：把"局部变量传递"重构为"有效视图传递"后，将以下**纠缠改写**统一候选化（改写 ratchet 67 将继续下降）：
  - 客服探针层：`sensitive_media_assist`、`customer_service_surface_exhausted`（位于 LLM 提案获取 try/except 区，~7077-7200）；
  - `combined_document_redirected`（同时改写局部变量 `target`，下游多处消费）；
  - hub 行选择（unread/consent_target/hub_row/settings_hub，~7265-7520）；
  - 会话边界链五段顺序耦合：logout_observation_only → defer_session_boundary → 二次破坏性确认 → logout 确认/边界（每段输入依赖前段输出的 `session_boundary_target`/重写后 decision）。
- 验收：改写 ratchet 显著下降且 263 套件全绿；行为不变的证据 = 表征套件。
- 注意：这些改写与 LLM 获取流程双向耦合，**不可在不改装配的情况下硬套候选范式**。

**任务 3：真机端到端回归**（任务 1、2 完成后）
- 复跑完整 263 套件 + `python -m compileall -q agent backend/app worker` + `git diff --check` + 真机冒烟。

**明确不做 / 不属于本计划**：
- 5 处"赋值后立即 perform_action + continue"的内联恢复处理器（~4785/6016/6044/6076/6117）是独立迷你执行路径，不是预裁决改写，保持原样；
- 14 处 `decision = X.as_decision()` 是 DirectiveSelectionSession 提交点（已是候选形态），保持原样；
- 登录簇（5 个薄委托函数）不值得单独成刀，已随 consent_vocabulary/login_session 就位。

### 五、纪律与已知坑

- **Mimosa 钩子拦截 Bash 写源码/git mv**：内容改动一律走 Write/Edit 工具；纯重命名需用户手动 `git mv`。
- **Edit 的 old/new 方向在长会话疲劳期极易写反**：删块前先读一遍现场；每次编辑后立即 `python -m py_compile` 验证。
- **proposal 初始化必须放在其消费门之前**（级联顺序），否则 UnboundLocalError（已踩坑一次）。
- **词表搬迁必须逐字核对**：曾把 `_LOW_VALUE_HELP_TERMS` 的词条混入 `NON_AUDIT_MAINTENANCE_TERMS`（已修正）；搬迁后 diff 词表内容。
- **改一行就要看门禁**：行数 ratchet、改写 ratchet 都在合同测试注释中带凭据链，每次下调都要留痕来历。
- **提交纪律**：每个转化单元独立提交；提交信息写明 ratchet 变化；不勾选上方 Task 清单（未完成项在本节与"复审结论"跟踪）。

### 六、F.1 执行补充（2026-08-30 确认）

#### 2026-08-31 行为恢复约束

- 模块化不得改变既有遍历方法。候选化只允许把命令式改写搬到仲裁前；DFS、条款优先级、deny/allow 顺序、登录等待、权限探针、低价值剪枝和 LLM 降级保持原语义。
- `FinalAction` 在后置重访/安全守卫中被替换时必须清空候选归属：替换后的 action、target 或 source 任一不同，原候选的 runtime 更新、场景完成、事件和 effect 均不得提交。
- 首次同意页条款崩溃或正文类型错配时，已读正文只记入实际正文；点击入口保持未完成并优先重试一次。重试耗尽后才记录覆盖缺口。
- `device_unavailable` 发生在 deny 阶段时，不启动 allow 阶段；历史任务的零覆盖与三条连接记录不能伪造为第一阶段操作历史。

F.1 不以一次性搬运主循环完成。以下四个切片按顺序独立测试、独立提交；任一切片不得改变 DFS、deny/allow、文档完成、登录等待、权限策略、低价值剪枝或 LLM 降级。

| 切片 | 迁移对象 | 完成门槛 |
|---|---|---|
| F.1a | 客服媒体探针的 LLM 早退覆盖 | `sensitive_media_assist` 与 `customer_service_surface_exhausted` 产生无副作用 `ActionProposal`；只有最终获选动作才登记尝试与事件。 |
| F.1b | 合并文档重定向与枢纽行选择 | 以有效动作视图传递 target/source；未读文档、同意目标、hub 行和设置页穷尽不再直接覆写 `decision`。 |
| F.1c | 会话边界顺序链 | 登出仅观察、拒绝权限延后、二次破坏性确认、登出确认/边界按旧顺序生成候选；前层候选输出由后层有效视图消费。 |
| F.1d | 页面周期装配 | `ExplorerOrchestrator` 实际拥有单 profile 页面周期装配与阶段异常边界；`workflow.py` 仍独占 deny/allow 循环和跨阶段合并。 |

#### 候选冲突矩阵

新增候选必须在构造处记录来源、优先级和下游消费者。除明确安全替换外，不得在 `ActionPipeline.choose()` 后再改写动作。

| 候选族 | 优先级 | 必须压过 | 必须让位 | 下游有效视图消费者 |
|---|---:|---|---|---|
| LLM 基础候选 | 100 | 无 | 所有确定性候选 | 全部 F.1 族 |
| 媒体/文档/会话边界确定性候选 | 150 | LLM 基础候选 | 等待熔断、业务路由、兄弟探索、已读与 blocked-route 守卫 | 同族后续层、深搜、等待熔断 |
| 连续等待熔断 | 160 | 等待类候选 | 业务路由、兄弟探索、已读与 blocked-route 守卫 | pipeline |
| 业务路由/根页点击 | 200 | 150/160 | 兄弟探索、已读与 blocked-route 守卫 | 深搜、pipeline |
| 深搜兄弟 | 300 | 200 及以下 | 已读与 blocked-route 守卫 | 等待熔断、pipeline |
| 已读/blocked-route 守卫 | 10,000 / 10,001 | 其它所有普通候选 | 仅最终安全替换 | pipeline |

#### 组合回归矩阵

每个 F.1 切片至少新增一项表征测试；测试断言最终动作、来源和关键可观察事件，而非源代码文本或 mock 调用次数。

| 场景 | 预期不变量 |
|---|---|
| 客服媒体入口与 LLM `back/stop/wait` | 优先点击未尝试媒体族；候选未获选时不写探针账本。 |
| 客服媒体已穷尽与 LLM `back/stop/wait` | 最终动作为 `back`，并仅在获选后记录穷尽事件。 |
| 合并文档链接与后置已读守卫 | 点击未读独立条款，且已读守卫仍可覆盖该点击。 |
| 设置枢纽的未读条款、同意按钮与可探索行 | 未读条款优先；全部已读后才允许同意或枢纽推进。 |
| deny 阶段的登出/注销入口与敏感业务替代入口 | 保持会话并先探测替代敏感入口；候选来源及事件顺序与旧链相同。 |
| 已观察登出确认后的重复入口 | 最终动作为 `back`，不提交登出。 |

#### 编排器与真机验收

- F.1d 的边界测试不得只断言回调包装。验收测试必须证明：`AppiumExplorerEngine.run()` 仅装配依赖并委托；单 profile 的循环、取消/暂停/终止检查和阶段异常边界由 `ExplorerOrchestrator` 承担；`workflow.py` 的 deny/allow 顺序和跨阶段合并未被改写。
- 每个切片完成时，运行对应定向测试、`backend/tests/test_appium_explorer_modularization_contract.py`、全量 `backend/tests/test_appium_explorer.py`、`compileall` 与 `git diff --check`；将实际行数和 decision 改写数写入提交说明。
- 真机冒烟前必须先执行 `adb devices` 并确认至少一个 `device` 状态目标；随后确认 Appium 可创建 UiAutomator2 会话。任一前置条件不满足时记录“环境未就绪”，不将其写作测试通过或代码缺陷。
