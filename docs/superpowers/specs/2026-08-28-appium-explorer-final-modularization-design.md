# Appium 遍历器最终模块化设计与迁移计划

## 1. 目的与当前事实

`agent/detection_engines/appium_explorer.py` 当前约 1.2 万行。第一轮模块化已经建立页面语义、目标目录、页面/导航状态、文档会话、DFS 策略、权限与登录决策、设置枢纽、投诉/反馈媒体探测、恢复、动作裁决、LLM 适配、规则证据和完成门禁等模块。

未完成的问题不是“缺少文件”，而是主遍历器仍拥有约数百处领域状态写入、动作执行和决策覆盖。现有模块多数只提供建议，主循环仍会再次扫描原始元素、修改决策、直接标记场景、维护文档集合和执行恢复，形成新旧两条事实链。

本计划只做行为保持式模块化：复用已有模块、确定唯一状态所有者、迁移调用点、删除重复实现，最终把 `appium_explorer.py` 收敛为薄入口。

## 2. 目标与非目标

### 目标

1. 每次稳定页面观察只生成一个权威 `ResolvedPage` 和一个权威目标目录。
2. 每个领域状态有且只有一个所有者；兼容字段只能由所有者投影。
3. 每轮只有一个不可变 `FinalAction`，裁决后不得再次改写。
4. 页面观察、领域候选、动作裁决、执行、效果归因、检查点和结果汇总形成单向链路。
5. 现有事件、报告字段和检查点继续可读；不删除已落盘证据。
6. `appium_explorer.py` 最终只保留引擎外观、准备流程、依赖装配和编排委托，目标不超过 700 行。

### 非目标

- 不改变 DFS 方法、现有候选顺序、动作优先级、deny→allow 阶段语义、文档完成条件、登录等待、权限策略、低价值剪枝阈值或 LLM 降级规则。
- 不把 deny/allow 多阶段循环从 `agent_core/workflow.py` 移入遍历器；工作流继续拥有阶段顺序、阶段重置、完整性门禁和跨阶段结果合并。
- 不新增 App 名称、包名、Activity、固定页面标题或单一控件文字特判。
- 不把人工报告结论注入遍历决策或自动证据。
- 不替换 Appium、OCR、Frida、LLM 或报告引擎。

## 3. 行为冻结与验证原则

模块化前先固定当前生效行为。每个迁移批次包含两类测试：

1. **行为表征测试**：迁移前必须通过，记录页面角色、目标目录、决策覆盖顺序、最终动作、状态变化和关键事件；迁移后结果必须一致。
2. **架构边界测试**：迁移前因旧依赖仍存在而失败，迁移后通过，用于证明主遍历器已停止直接解释页面或写入对应领域状态。

纯重构不能故意让既有行为测试先失败。只有新架构边界测试需要经历红→绿。若迁移中发现旧行为确有缺陷，先记录为独立“行为优化项”，不在本计划中顺手修改。

当前 `ActionPipeline._SOURCE_RANK`、`ActionArbiter`、`FinalActionSafetyPolicy.CHECK_ORDER` 以及主循环在进入 `ActionPipeline` 前的顺序覆盖，共同构成现有动作优先级。迁移基线必须记录最终结果，不能只把 `_SOURCE_RANK` 当作完整旧行为。

## 4. 当前模块与唯一状态所有权

| 领域 | 现有/目标所有者 | 允许的兼容投影 | 禁止的第二事实源 |
| --- | --- | --- | --- |
| 页面事实与角色 | 现有 `page_semantics.py` 的 `PageRoleAdjudicator`、`ResolvedPage` | `_page_role` 可临时只转发 `legacy_role` | 主循环再次调用登录、文档、低价值等 `_is_*` 决定角色 |
| 可执行目标 | 现有 `target_catalog.py` | 旧元素白名单可由目录生成 | LLM、DFS、领域模块各自重新扫描原始元素生成另一份目标列表 |
| 页面读取与 OCR | 现有 `PageStabilityCoordinator`、`PageObserver` | 旧 `screen_text` 事件字段 | 领域模块各自重新读取页面或自行触发无界 OCR；主循环保留加载壳或客服聊天 OCR 特判 |
| 页面与实时导航 | 现有 `PageState`、`NavigationGraph`、`NavigationReplayLedger` | 旧 `visited_targets` 等集合在迁移期由 `PageState` 方法维护 | 新导航执行器建立第二份图、栈或回放账本 |
| 文档身份与阅读 | 扩展 `document_session.py` 的纯 `DocumentIdentityResolver` + 现有 `DocumentReadingLedger`，通过 `PageState.documents` 持有进度 | `active_document`、`completed_documents`、`document_scrolls` 暂时由账本单向投影 | 页面证据层拥有文档进度，或主循环/`ctx.runtime` 独立维护标题、完成、阻断、滚动真值 |
| 阶段/登录/权限结果 | 现有 `DetectionRunState` | 旧字符串键由该对象投影 | 领域分支直接写相反状态或用事件名代替验证结果 |
| deny/allow 工作流 | 现有 `agent_core/workflow.py` + `probe_phase_integrity.py` | 单阶段 profile/plan 注入 `DetectionContext` | `ExplorerOrchestrator` 自行循环、重排或合并两个阶段 |
| 权限拒绝探测 | 现有 `PermissionProbeLedger` | 其 `navigation_replay` 是探测开始时的恢复快照 | 把该快照当成第二份实时导航图 |
| 有序动态规则 | 现有 `ScenarioController`，当前只覆盖 3.8、4.2 | 终态同步给 `ScenarioFrontier` | 同一有序场景同时由主循环和控制器完成 |
| 静态规则证据 | 现有 `RuleEvidenceExecutor` + `ScenarioFrontier` | 1.1、1.2、2.3、3.4、4.5、6.1 等静态观察可直接带证据完成 | 强行迁入 `ScenarioController` 或无证据 `mark_completed` |
| 同意与登录 | 现有 `ConsentDecisionModule`、`LoginSurfaceClassifier`、`LoginDecisionModule`、`ManualLoginWaiter` | 场景控制器只接收需要的观察事件 | 将同意状态、登录状态或人工等待交给规则场景控制器 |
| 权限候选 | 现有 `PermissionScenarioPolicy`、`PermissionDecisionModule` | `PermissionProbeLedger` 保存执行期状态 | 主循环另建权限优先级或凭文字直接完成 4.2 |
| 枢纽与反馈媒体 | 现有 `HubDecisionModule`、`SettingsHubNavigator`、`RedressSurfaceDetector`、`RedressMediaProbeExecutor` | 旧帮助函数只可转发领域模块结果 | 按“客服”等固定名称建立旁路策略 |
| LLM 候选与效果 | 现有 `LLMProposalAdapter`、`LLMEffectivenessLedger` | 旧日志字段由适配器输出 | LLM 直接执行、写状态或点击目录外目标 |
| 页面/时间预算 | 现有 `SurfaceBudgetPolicy`、`PerformanceBudget` | 旧计数键由预算对象投影 | 主循环另写重复点击、页面停留或重试阈值 |
| 动作裁决与安全 | 现有 `ActionPipeline`、`ActionArbiter`、`FinalActionSafetyPolicy` | `DecisionDirectiveApplier` 在迁移期负责把旧指令转成候选 | 裁决后继续覆盖 `decision` 或在多处重复安全判定 |
| 指令副作用 | 扩展后的 `DecisionDirectiveApplier` 两阶段接口 | 仅最终获选指令按旧时机提交更新/增量/事件 | 候选生成时提前写状态，或被拒绝候选留下副作用 |
| 本轮候选预览 | 新 `DirectivePreviewState` | 只在当前页面周期向后续候选提供旧分支所需的假设状态 | 写入真实 `ctx.runtime`、检查点或报告事件 |
| 动作执行与效果 | 新 `ActionExecutor` + 现有 `ActionEffectLedger` | `ActionExecutionResult` 将结果交给领域模块 | 执行器通过页面文字判断规则、登录、文档或权限结论 |
| 会话与加载恢复 | 现有 `RuntimeRecoveryCoordinator`、`PageStabilityCoordinator` | 通过回调调用导航回放和检查点仓库 | 导航执行器复制会话恢复或冷启动策略 |
| 完成判定 | 现有 `ExplorationCompletionGate` | 报告汇总读取其结果 | 页面耗尽直接等价为完整覆盖 |
| 时间线与决策审计 | 现有 `ReplayWriter`、`DecisionAudit`、事件日志 | 保留旧事件字段并追加来源/效果 | 汇总阶段重建或篡改实际候选、裁决、执行顺序 |

## 5. 需要新增或扩展的模块

只新增当前确实没有的边界，不再建立平行决策器。

### 5.1 `page_evidence.py`（新增）

纯证据提取层。接收 Activity、包范围、元素、OCR、前一动作、不可变路由快照和 `DocumentIdentityResolver` 的结果，输出 `PageFacts`、`RoleEvidence` 及证据摘要。它不持有可变 `PageState`，不拥有文档进度，不决定角色、不选动作、不写状态。现有 `PageRoleAdjudicator` 继续是唯一角色仲裁器。

这样避免 `page_semantics.py` 反向依赖庞大的 `appium_explorer.py`，也不新建第二个 `page_role_arbitration.py`。

### 5.2 `action_executor.py`（新增）

只负责执行已经裁决的点击、滚动、返回，记录操作耗时，并返回不可变 `ActionExecutionResult`。它按 `FinalAction` 已携带的元数据调用 `PageState` 和 `ActionEffectLedger` 的提交接口，但不重新扫描页面文字、不推断业务/同意/权限/文档语义、不选择候选、不拥有导航图、不保存检查点、不决定是否重启应用。

`ActionProposal`/`FinalAction` 在行为保持前提下补充现有执行期需要的元数据：目标语义类型、执行层、关联规则、是否业务动作、是否同意动作及是否需要专用后验验证。元数据只搬运当前已经计算出的事实，不能引入新的判断。

### 5.3 `document_executor.py`（新增）

执行文档领域特有的等待、滚动、底部确认、同意弹窗内短标题打开验证、外部文档加载、嵌套披露链接和完成后返回。它消费 `DocumentFlowPolicy` 指令并只写 `DocumentReadingLedger`，再发出文档观察事件；普通 `ActionExecutor` 不包含这些文档分支。

同时在 `document_session.py` 增加纯 `DocumentIdentityResolver`，迁入 `_document_key` 的身份判定和规范化；它只返回 key/kind/title/source/conflict，不改变阅读进度。页面角色只消费“是否为已验证正文”的证据，文档账本消费完整身份。

### 5.4 `run_checkpoint.py`（扩展，不新增平行仓库）

在现有 `RunCheckpointCodec` 基础上增加 `TraversalCheckpointRepository`，统一当前散落在主遍历器中的：

- traversal checkpoint 路径、版本、保存与恢复；
- navigation replay checkpoint 路径、保存与恢复；
- `DetectionRunState`、`PageState`、文档账本、导航回放、findings/evidence 的兼容序列化。

`RuntimeRecoveryCoordinator` 继续决定何时恢复，只通过仓库接口保存/读取；它不拥有持久化格式。

### 5.5 `action_safety_checks.py`（新增纯谓词模块）

迁出 `_is_foreign_app_launch_click`、低价值、交易、无标签容器、破坏性确认、目标可见性等安全谓词。`FinalActionSafetyPolicy` 保持现有检查顺序，只消费这些纯谓词；本阶段不改变安全规则。

### 5.6 `explorer_orchestrator.py`（新增）

只负责编排一次 probe profile 内的页面周期、取消/暂停/终止、依赖调用和本阶段异常边界。它不循环 deny/allow，不合并跨阶段结果，也不包含页面关键词、规则编号特判或领域状态结构。

### 5.7 `run_finalizer.py`（新增）

为单个 probe profile 组装 `EngineResult`，汇总本阶段覆盖缺口、性能统计、LLM 效果、场景快照和终止原因。它调用现有 `ExplorationCompletionGate` 判断完成真实性，不改造该门禁为报告生成器；跨 deny/allow 的合并仍由 `workflow.py` 完成。规则事实来自各自所有者，汇总阶段不重新推断。

### 5.8 既有领域模块的执行接口（扩展）

- `sdk_observation.py` 接管允许阶段授权、主内容停留和结束时后台观察；`RunFinalizer` 只触发，不直接操作设备。
- `redress_media_probe.py` 接管媒体探测前权限撤销及探测结果观察。
- `document_executor.py` 接管当前引擎私有的嵌套披露点击。
- `page_observer.py` 接管现有 `_needs_perception_ocr` 和有界的聊天/反馈页面强制 OCR 策略；`page_stability.py` 接管 `_page_is_loading_shell` 与可点击数量判断，不增加重试次数。
- 同意、登录、权限和规则模块分别增加 `observe_action_result` 或等价接口，消费 `ActionExecutionResult`；不由通用执行器写领域状态。

### 5.9 `decision_directive.py`（扩展）

把当前“一调用 `apply()` 就立刻写 runtime”的接口拆为两步：

1. `to_proposal(directive)`：纯转换，不写状态、不发事件、不完成规则；返回携带指令令牌的 `ActionProposal`。
2. `commit_selected(token, timing)`：只对最终获选指令提交旧有 `runtime_updates`、`runtime_increments`、事件和合法静态规则完成。

提交时机必须由阶段 0 行为基线确定。当前在 `perform` 前发生的计数仍在获选后、执行前提交；依赖动作成功或下一页面效果的状态改为由领域 `observe_action_result` 提交。被安全策略替换或被仲裁拒绝的候选不得留下任何副作用。

### 5.10 `directive_preview.py`（新增）

当前部分领域分支需要读取前一指令刚产生的状态，才能按既有顺序继续生成同一页面的下一候选。`DirectivePreviewState` 提供每轮短生命周期的只读覆盖层：

1. `preview(directive)` 把该指令的 `runtime_updates`、`runtime_increments` 和 effects 投影到预览层；后续候选只能读预览层，不写真实 runtime。
2. 预览层按照迁移前的分支顺序生成候选和 gate 结果，因此维持 SDK 停留、同意复选框、权限撤销、登录入口、枢纽推进的原顺序。
3. `ActionPipeline` 选择唯一最终动作后，只有其 token 对应的指令由 `commit_selected()` 写入真实 runtime、事件和规则完成记录。
4. 被拒绝或被安全动作替换的预览状态随本轮结束丢弃；不进入检查点、报告、回放或下一页面。

## 6. 单页周期数据流

每轮严格执行以下顺序，顺序本身先按旧行为基线实现：

1. `PageStabilityCoordinator` 读取稳定页；`RuntimeRecoveryCoordinator` 处理会话丢失。
2. `PageObserver` 合并 XML、OCR 和截图可见事实。
3. `page_evidence.py` 构建证据；`PageRoleAdjudicator` 输出唯一 `ResolvedPage`；`target_catalog.py` 输出唯一目录。
4. `DetectionRunState`、`PageState`、动作效果和场景控制器接收本轮观察。
5. 文档、权限、同意、登录、枢纽、反馈媒体、SDK 观察、DFS、恢复与 LLM 模块各自产生 `ActionProposal`，不得执行普通动作；文档等需要专用后验验证的流程通过提案元数据声明对应执行器。
6. `DirectivePreviewState` 按迁移前分支顺序投影候选前置状态；`DecisionDirectiveApplier.to_proposal()` 和其它适配器据此构造无副作用候选及优先级，`ActionPipeline` 输出一个 `FinalAction`。
7. `FinalActionSafetyPolicy` 按当前调用位置和检查顺序执行；最终动作冻结；仅获选指令由 `commit_selected()` 按旧时机提交执行前副作用。
8. `ActionExecutor` 或声明的领域执行器执行动作并产生 `ActionExecutionResult`；领域所有者消费结果并提交动作后状态，导航状态只通过 `PageState` 接口提交。
9. `TraversalCheckpointRepository` 保存状态；事件时间线记录候选、裁决、获选指令提交、执行、效果与证据来源。

主循环不得在第 7 步以后重写动作，也不得绕过第 8 步直接调用 `client.perform()`/`back()`；执行器不得包含页面关键词或规则编号判断。

## 7. 关键行为不变量

### 页面角色

角色优先级保持 `page_semantics.py` 当前 `_PRECEDENCE` 和现有证据强度。迁移目标是把 `_page_semantics` 的事实构建迁出，而不是改变角色顺序。遮罩背景目标不能写入 DFS 访问、失败或无效果记忆。

### 文档

文档身份继续由来源、正文语义、路由和页面指纹联合确定。只有滚动到底并满足当前重复确认规则才完成。迁移期 `DocumentReadingLedger` 写入后同步旧字段；所有读取迁完且检查点版本兼容后，旧 `PageState.completed_documents/document_scrolls/active_document` 和 `ctx.runtime` 文档真值才可删除。

### 导航与恢复

`PageState` 是实时导航唯一所有者；`PermissionProbeLedger.navigation_replay` 仅是场景快照。`ActionExecutor` 只提交动作结果。`RuntimeRecoveryCoordinator` 决定重新激活、会话恢复、冷启动升级和重放时机；普通业务返回仍是已裁决动作。检查点仓库负责持久化；各方不得互相复制状态。

### 规则完成

3.8、4.2 等有序动作链由 `ScenarioController` 验证里程碑后同步给 `ScenarioFrontier`。静态规则仍通过 `RuleEvidenceExecutor` 带 `evidence_source` 或 `finding_kind` 完成。导航耗尽只产生覆盖缺口，不能完成任何待执行场景。

### 动作与 LLM

迁移前先保存最终动作基线，因为当前大量顺序覆盖发生在进入 `ActionPipeline` 之前。迁移过程把这些覆盖逐个转换为候选，但必须保持同一输入下的最终动作、来源和关键理由。LLM 只能对权威目标目录提出候选，不能写状态、坐标盲点或结束未完成场景。

## 8. 迁移阶段

### 阶段 0：建立行为基线和架构门禁

1. 从现有测试和脱敏回放中固定同意遮罩、文档、登录、权限拒绝、设置枢纽、反馈媒体、相机返回、加载恢复、低价值剪枝和 deny/allow 差异。
2. 记录每个夹具的 `ResolvedPage`、目标目录、决策覆盖顺序、最终动作、场景终态和关键事件。
3. 新增架构测试，统计主遍历器中直接 `ctx.runtime` 领域写入、`mark_completed`、`client.perform/back` 以及领域 `_is_*` 调用；按阶段逐步降低。最终这些写入/调用全部归零；只允许编排器通过封装接口读取取消、暂停、终止回调，不设置模糊的通用白名单。

验收：行为基线在任何生产迁移前全部通过；架构测试能准确发现现有越界依赖。

### 阶段 A：页面证据与目标目录收口

1. 新建 `page_evidence.py`，迁出 `_page_semantics` 使用的非文档事实提取逻辑；文档正文事实消费 `DocumentIdentityResolver` 结果，不在证据层复制 `_document_key`。
2. 复用现有 `page_semantics.py` 和 `target_catalog.py`；把现有宿主控件解析、相对/坐标定位、语义别名和风险标签作为 `TargetCandidate` 的兼容字段迁入，不新建仲裁器或第二目录。
3. 将 `_needs_perception_ocr`、客服/反馈强制 OCR 条件迁到 `PageObserver`，将 `_page_is_loading_shell`、可点击数量条件迁到 `PageStabilityCoordinator`；保持当前次数和等待配置。
4. 逐步让同意、文档、登录、低价值、外部页、系统页及 LLM 只消费 `ResolvedPage`/目标目录。
5. `_page_role` 仅保留兼容转发；无生产调用后删除。

验收：角色、目录、最终动作和事件与阶段 0 基线一致；`page_semantics.py` 不依赖主遍历器。

### 阶段 B：文档唯一账本与检查点收口

1. 扩展 `document_session.py` 的 `DocumentIdentityResolver`，让 `DocumentReadingLedger` 成为文档完成、滚动、活动会话、空白、卡住和底部确认的唯一写入方；本阶段先统一身份与状态，不提前迁移动作执行。
2. `PageState` 旧文档字段和 `ctx.runtime` 文档集合改为账本单向投影；禁止反向独立写入。
3. 扩展 `run_checkpoint.py`，迁出 traversal/navigation checkpoint 函数并版本化兼容旧 payload。
4. 全部读取迁移后，在明确 schema 迁移测试通过时删除旧投影字段。

验收：旧检查点可以恢复；新检查点只保存一个文档真值；隐私政策/用户协议不串台、不重复、完成条件不变。

### 阶段 C：动作执行与恢复边界收口

1. 新建 `action_executor.py` 和 `ActionExecutionResult`，迁移普通点击、滚动、返回、操作耗时、失败分类以及导航/效果账本提交。
2. 给 `ActionProposal`/`FinalAction` 增加从现有分支搬运的执行元数据；执行器不重新计算语义。
3. `DfsNavigationPolicy` 继续只选择候选；`PageState` 继续拥有实时图和回放账本。
4. `RuntimeRecoveryCoordinator` 继续决定恢复时机，通过 `TraversalCheckpointRepository` 与导航回放回调协作。
5. 主循环停止直接调用 Appium 动作和直接提交导航边；领域模块消费 `ActionExecutionResult` 更新各自状态。

验收：DFS 顺序、无效果处理、相机/崩溃返回、冷启动升级和安全路径回放与基线一致。

### 阶段 D：领域候选和规则证据收口

1. 扩展 `DecisionDirectiveApplier` 为无副作用提案与获选提交两阶段，并新建 `DirectivePreviewState`；候选生成可读取本轮预览状态，但不得提前修改真实 runtime、发事件或完成规则。
2. 新建 `document_executor.py`，基于阶段 C 的 `ActionExecutor` 迁移内联标题打开轮询、外部正文、嵌套披露、滚动和完成后返回。
3. 权限、同意、登录、枢纽、反馈媒体、SDK 观察、文档和 DFS 模块统一输出 `ActionProposal`，并通过明确接口消费动作结果。
4. 同意/登录保持各自状态所有权；`ScenarioController` 只处理已声明的有序动态规则。
5. 静态规则继续经 `RuleEvidenceExecutor` 完成；删除无证据或与控制器重复的完成调用。
6. `PermissionProbeLedger` 保留探测期导航快照语义，不与实时导航合并。
7. 将媒体探测前权限撤销迁到 `redress_media_probe.py`，将 SDK 授权/停留/后台观察迁到 `sdk_observation.py`。
8. 将全局目标、根路由、枢纽滚动、重复/无效果和恢复次数收口到 `SurfaceBudgetPolicy`/`PerformanceBudget`，旧计数键仅作单向投影。

验收：deny/allow、登录等待、3.8、4.2、静态规则覆盖和报告缺口与基线一致。

### 阶段 E：动作裁决和安全谓词收口

1. 把当前顺序覆盖逐个改造成带来源、优先级和拒绝理由的候选；每迁一个覆盖点都对照阶段 0 最终动作。
2. 迁出安全谓词到 `action_safety_checks.py`，保持 `FinalActionSafetyPolicy` 检查顺序和调用位置。
3. 所有候选统一进入 `ActionPipeline`；删除裁决后的决策改写。
4. LLM 输入只来自 `ResolvedPage`、目标目录、场景摘要和 DFS 状态；保持现有降级与效果统计。
5. 安全替换完成后才提交获选指令副作用；原候选被替换时不得写入访问、重试、场景完成或事件状态。

验收：同一回放输入的最终动作、来源、安全原因和 LLM 采用/拒绝结果一致；裁决后动作不可变。

### 阶段 F：薄编排层和结果汇总

1. 新建 `ExplorerOrchestrator.run_phase()`，装配单个 probe profile 内的稳定观察、恢复、语义、领域候选、裁决、执行和检查点；deny/allow 循环继续由 `workflow.py` 调用。
2. 新建 `RunFinalizer`，调用现有 `ExplorationCompletionGate` 并迁出覆盖缺口、终止原因、场景/性能/LLM 汇总；完成门禁本身保持单一职责。
3. `AppiumExplorerEngine.run()` 改为委托；`prepare()` 只保留 APK 校验、连接、安装/清理和初始权限重置。
4. 引擎私有 `_revoke_media_probe_permissions`、`_maybe_enter_sdk_observation_phase`、`_click_nested_disclosure_if_present` 分别迁到反馈媒体、SDK 观察和文档执行器。

验收：`appium_explorer.py` 不超过 700 行，只包含引擎外观、准备、装配和兼容导出。

### 阶段 G：删除兼容层和无用分支

1. 更新测试，使其从真实领域模块导入；不再依赖遍历器私有函数。
2. 用 `rg` 和架构测试确认旧帮助函数、字符串状态键、直接动作、直接动态场景完成和裁决后覆盖已无生产调用；静态规则通过 `RuleEvidenceExecutor` 的合法调用不计为违规。
3. 删除兼容转发和死代码；不删除仍被旧检查点恢复所需的 schema 迁移器。

验收：不存在平行状态或循环依赖；所有行为基线、架构门禁、完整测试和真实设备冒烟通过。

## 9. 兼容与回滚

- `TraversalCheckpointRepository` 接受现有 traversal payload version 4 和现有 navigation replay payload，输出新版本；未知未来版本拒绝恢复并记录覆盖缺口。
- 文档账本迁移采用“新账本写入 → 旧字段单向投影 → 所有读取迁移 → 删除投影”，禁止双向同步。
- 事件和报告字段只追加；旧事件名继续产生直到消费方迁移完成。
- 每阶段独立提交。行为基线任何差异都停止该阶段，不继续叠加后续迁移。
- 恢复失败时保留已落盘证据并安全重启当前阶段，不能把失败状态恢复为完成。

## 10. 测试矩阵

| 层级 | 内容 |
| --- | --- |
| 行为表征 | 页面角色、目标目录、旧覆盖顺序、最终动作、事件序列、场景终态 |
| 单元 | 页面证据、文档账本/执行器、检查点兼容、动作执行结果、导航提交、规则状态机、安全谓词、完成门禁和结果汇总 |
| 架构 | 禁止主遍历器直接写领域状态、直接执行动作、重复仲裁或完成有序场景 |
| 回放 | 同意遮罩、文档串台/重复、登录误判、权限拒绝重试、反馈媒体、相机返回、加载恢复、低价值剪枝 |
| 集成 | Appium 遍历器、规则证据、报告绑定、deny/allow 工作流和终止/暂停恢复 |
| 真实设备 | 创建会话、进入主界面、执行一个安全权限场景、恢复一次可逆路径、关闭会话 |

真实设备不可用时必须报告“未执行”，不能用单元测试替代端到端结论。

## 11. 最终验收标准

1. `appium_explorer.py` 不超过 700 行，且不含页面关键词规则、规则编号状态机、文档集合或导航图实现。
2. 主遍历器没有直接 `ctx.runtime[...]` 领域写入，没有直接 `client.perform/back`，没有裁决后动作改写；普通执行器没有页面关键词或规则编号判断。
3. 页面角色、目标目录、文档、导航、阶段/登录/权限、动态场景、静态规则和完成判定分别只有一个事实所有者。
4. 迁移前后基线回放的角色、目标、最终动作、场景终态和关键事件一致。
5. 旧检查点可恢复，新检查点没有重复文档真值；恢复失败不会伪装成功。
6. 没有新增 App 名称、包名或固定页面名称特判。
7. 全量自动测试通过；Appium 真实设备冒烟结果单独记录。

## 12. 后续独立行为优化

以下事项不属于模块化迁移：改变角色或场景优先级、默认点击同意/拒绝、改变文档完成条件、改变低价值页停留/回退阈值、改变 allow 阶段回放范围、调整 LLM 权重或安全检查顺序。

这些变化必须在模块化完成后单独设计，明确旧新差异、配置开关、人工报告基准和回归测试，经确认后实施。

## 13. 本计划的源码核对依据

本版本已逐项核对以下当前实现，后续如接口变化需先更新本计划：

- `appium_explorer.py`：约 12,048 行、242 个函数/方法；动作在进入 `ActionPipeline` 前仍有大量顺序覆盖，动作执行后仍直接写导航、文档、权限、隐私路径和场景状态。
- `page_semantics.py`：已存在 `PageRoleAdjudicator`、`ResolvedPage` 和固定 `_PRECEDENCE`；无需新建仲裁器。
- `target_catalog.py`：已存在 `TargetCandidate`/`TargetKind` 和同意遮罩目录；需要补兼容定位信息，不需第二目录。
- `page_state.py`：同时持有导航图、导航回放和 `DocumentReadingLedger`，并保留旧文档字段；因此必须做单向投影迁移。
- `run_checkpoint.py`：当前只序列化 `DetectionRunState`；traversal version 4 和 navigation replay 文件仍由主遍历器保存/恢复。
- `decision_directive.py`：当前 `apply()` 在候选阶段立即写 runtime、发事件和完成规则；必须先拆为无副作用提案与获选提交。
- `scenario_controller.py`：当前模板仅含 3.8、4.2；其它静态规则由 `RuleEvidenceExecutor`/`ScenarioFrontier` 处理。
- `workflow.py`：当前拥有 deny→allow 循环、阶段重置、完整性检查和跨阶段结果合并；遍历器不得接管。
- `runtime_recovery.py`：拥有会话恢复和重放时机，但通过回调依赖主遍历器的检查点/回放实现；持久化格式应迁到 `run_checkpoint.py`。
- `test_explorer_architecture.py` 与 `test_appium_explorer.py`：仍直接导入大量遍历器私有函数；兼容转发只能在最后阶段、测试改为领域模块入口后删除。
