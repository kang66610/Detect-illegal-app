# App隐私合规自动化检测平台 技术设计文档

| 项目 | 内容 |
|------|------|
| 文档编号 | DESIGN-PRIVACY-PLATFORM-001 |
| 文档版本 | V1.0 |
| 编制日期 | 2026-08-14 |
| 上游依据 | ①《PRD-App隐私合规自动化检测平台》V1.0（docs/prd/）；②《AI驱动的App隐私合规自动化检测Agent设计方案》V1.0（仓库根目录 DOCX，下称「方案文档」） |
| 目标读者 | 开发、测试、评审 |

## 0. 变更记录

| 版本 | 日期 | 变更说明 | 编制人 |
|------|------|----------|--------|
| V1.0 | 2026-08-14 | 首版发布 | — |
| V1.1 | 2026-08-14 | 规则库按官方正文收敛为六大类，共 14 条规则；违规法条标注精确到「第X条第（X）点」；报告模板对齐用户提供的检测报告格式 | — |

---

## 1. 已确认的关键决策

| 决策点 | 结论 |
|--------|------|
| 技术栈 | 全 Python + Vue 3：检测引擎 Python 3.10+，后端 FastAPI，前端 Vue 3 + Vite + Element Plus |
| 数据存储 | 仅 SQLite（单文件 `data/app.db`）：业务数据 + 任务队列（轮询）一体；**Redis 移除**（用户决策，减少外部依赖，V2.0 按需引入） |
| 大模型接入 | OpenAI 兼容协议适配层（`openai` SDK，`base_url` 可配置，通义/DeepSeek/GLM 均可直接接入）；开发期使用 MockLLM |
| 开发路线 | **路线 B：Web 平台优先 + 模拟管线先行**。平台骨架先跑通全链路（Mock 引擎），真实引擎按里程碑逐个替换，检测环境（模拟器/Appium/Frida）由用户后续安装 |
| 部署形态 | Monorepo 单仓库；API 服务与检测 Worker 双进程；**V1.0 仅本机原生运行**（一键启动脚本），Docker 部署延后至 V1.1 |
| 账号体系 | **V1.0 不做**（用户决策，偏离 PRD 4.1）：无登录注册，打开即进入检测页面，单用户/本机或内网使用 |

## 2. 与上游文档的差异对齐

| 差异点 | 方案文档 | PRD | 本设计处理 |
|--------|---------|-----|-----------|
| 前端 | 无前端设计 | Web 平台为 P0（账号/APK/任务/报告/导出） | 新增 Vue 3 前端，纳入 V1.0 |
| 整改建议 | 列入「后续迭代方向」 | P0（FR-4.6.3） | 按 PRD 纳入 V1.0：LLM 生成、中文、方案级（无代码示例）、单条 ≤200 字 |
| 加固 APK | 未提及 | P0（FR-4.2.1.3） | 尝试解析（Androguard），失败时解析状态置为失败并给出明确原因，不阻塞其他功能 |
| LangChain | 选型含 LangChain 0.2.10 | 未提及 | **省掉**：单轮决策场景直连 OpenAI 兼容 SDK 更简单，少一层依赖；后续确需 Prompt 编排能力时再引入 |
| 账号与登录 | PRD 4.1 为 P0（注册/登录/找回/个人中心） | — | **V1.0 移除**（用户决策，减负）：无登录直接使用；随之移除数据隔离与防暴力破解要求 |
| 站内消息 | 未提及 | P0（FR-4.3.2.4 任务完成通知） | 随账号体系一并移除；任务完成状态由前端轮询任务列表展示 |
| Redis 队列 | 方案文档选型 Redis 做任务队列 | 未提及 | **V1.0 移除**（用户决策）：任务队列改 SQLite 轮询，单机 3 并发足够；V2.0 再引入 |
| Word 导出 | 未提及 | P0（FR-4.6.4 双格式导出） | **V1.0 只导出 PDF**（用户决策）；Word 放 V1.1 |
| 政策结构化字段 | 方案文档 4.5 五类字段提取 | P0（FR-4.2.2.4） | **V1.0 只提取政策原文 + 入口可访问性检测**；结构化五类字段（依赖 LLM）放 V1.1 |
| 规则集规模 | 未明确条数 | P0 KPI：每类 ≥5 条可触发规则 | **V1.0 官方六大类共 14 条核心规则起步（第六类含删除/更正及投诉/举报）**；YAML 配置化，后续补充零代码；KPI 同步放宽 |
| Docker 部署 | 方案文档选型 Docker 部署 | 未提及 | **V1.0 延后**（用户决策）：仅本机一键启动脚本；V1.1 补容器化 |

## 3. 总体架构

### 3.1 进程与运行形态

```
┌──────────────┐      ┌──────────────────┐      ┌───────────────┐
│  Vue 3 前端   │ ───► │ FastAPI API 服务  │ ───► │  检测 Worker   │
│  (frontend/)  │      │    (backend/)     │      │   (worker/)    │
└──────────────┘      └────────┬─────────┘      └───────┬───────┘
                               │  任务入队（SQLite 轮询）  │
                               └────────────────────────┘
                    Worker 内：静态分析 → AI遍历（+Frida/mitmproxy 侧车监控）
                              → 规则判定 → 证据聚合 → 报告生成
```

- **API 服务**：APK 上传与解析触发、任务 CRUD、进度查询、报告查询与导出。无登录体系（见 §1）。生产构建后的前端静态文件由 FastAPI 托管（单容器部署）。
- **检测 Worker**：独立进程，消费 Redis 队列，执行完整检测管线（方案文档六层架构的第 2–6 层）。单节点可启动多个 worker 进程满足「≥3 个深度任务并行」；worker 数由配置控制。
- **任务队列（V1.0）**：SQLite 轮询实现——worker 定时查询 pending 任务并领取（WAL 模式 + 事务保证多 worker 不重复领取）；前端 3–5 秒轮询进度接口（SSE/WebSocket 留待 P1 遍历可视化）。
- **SQLite**：WAL 模式，文件位于 `data/app.db`（gitignore）。

### 3.2 六层架构映射（方案文档 3.1）

| 层 | 落地位置 |
|----|---------|
| 基础设施层 | 模拟器/真机、Frida、mitmproxy、SQLite、Redis（开发期 Mock 替身） |
| 资源调度层 | `agent/agent_core/`：task_manager（队列）、device_manager（设备/Appium 节点） |
| 检测引擎层 | `agent/detection_engines/`：static_analyzer、frida_monitor、traffic_analyzer、sdk_detector、policy_parser |
| 核心决策层 | `agent/ai_explorer/`：appium_client、llm_controller、page_state、explorer |
| 合规判定层 | `agent/rule_engine/`：rule_loader、rule_matcher、evidence_aggregator |
| 输出层 | `agent/rule_engine/report_generator.py` + Web 报告页与导出 |

### 3.3 模块边界约束

- `agent/` 包**不依赖 Web 层**（不 import backend），对外只暴露引擎接口与数据产物。
- 所有检测引擎实现统一接口：`DetectionEngine.run(ctx: DetectionContext) -> EngineResult`，由 `agent_core/workflow.py` 编排——这是 Mock 引擎与真实引擎无缝互换、Web 层零改动的前提。
- 检测数据产物（违规、证据、进度快照）以 JSON 结构在阶段间传递，Worker 负责落库。

## 4. 仓库结构

```
Detect illegal app/
├── docs/
│   ├── prd/PRD-App隐私合规自动化检测平台-V1.0.md
│   └── superpowers/specs/…-design.md        # 本文档
├── backend/                                 # FastAPI API 服务
│   ├── app/
│   │   ├── main.py                          # 入口、路由挂载、静态托管
│   │   ├── config.py                        # config.yaml + 环境变量
│   │   ├── db.py                            # SQLAlchemy 引擎与会话
│   │   ├── models/                          # ORM：apk/task/violation/evidence/report
│   │   ├── schemas/                         # Pydantic 请求/响应模型
│   │   ├── api/                             # apk.py task.py report.py
│   │   └── services/                        # 业务逻辑：apk_service/task_service/report_service
│   ├── requirements.txt
│   └── tests/
├── worker/
│   └── main.py                              # Redis 消费循环 → agent_core.workflow
├── agent/                                   # 检测引擎包（方案文档 5.2 结构落地）
│   ├── agent_core/
│   │   ├── task_manager.py                  # 队列交互、任务状态流转
│   │   ├── workflow.py                      # 管线编排（阶段调度）
│   │   └── device_manager.py                # 设备/Appium 节点管理（V1.0 含 Mock 实现）
│   ├── ai_explorer/
│   │   ├── appium_client.py                 # 页面采集 + 操作执行封装
│   │   ├── llm_controller.py                # OpenAI 兼容适配层 + MockLLM + 决策解析
│   │   ├── page_state.py                    # 页面指纹、遍历状态、路径树
│   │   ├── explorer.py                      # 遍历主循环、健壮性
│   │   └── prompts/explore_system_prompt.txt
│   ├── detection_engines/
│   │   ├── base.py                          # DetectionEngine 接口 + DetectionContext
│   │   ├── static_analyzer.py               # Androguard 权限/SDK/政策提取
│   │   ├── frida_monitor.py                 # Frida 隐私 API Hook（V1.0 先 Mock）
│   │   ├── traffic_analyzer.py              # mitmproxy 流量解析（V1.0 先 Mock）
│   │   ├── sdk_detector.py                  # SDK 特征识别（包名/类名特征库 YAML）
│   │   ├── policy_parser.py                 # 隐私政策原文提取（V1.0）+ 结构化解析（V1.1）
│   │   └── mock_engine.py                   # Mock 检测引擎（开发期替身）
│   ├── rule_engine/
│   │   ├── rule_loader.py  rule_matcher.py  evidence_aggregator.py  report_generator.py
│   ├── common/                              # utils.py logger.py exceptions.py
│   ├── config/rules/identification_method_rules.yaml
│   └── tests/
├── frontend/                                # Vue 3 + Vite + Element Plus
│   └── src/{views,router,stores,api,components}/
├── data/                                    # 运行期数据（gitignore）：app.db、APK 存储、证据、导出
├── scripts/                                 # 一键启动脚本：run_api / run_worker（本机原生运行）
├── .gitignore
└── README.md
```

## 5. 核心数据模型（SQLite / SQLAlchemy）

| 模型 | 关键字段 |
|------|---------|
| APKFile | filename、sha256、size、parse_status（解析中/成功/失败/格式无效）、app_name、package_name、version_name、permissions(JSON)、sdk_list(JSON)、policy_raw（结构化字段 V1.1）、storage_path（Fernet 加密存储）、uploaded_at |
| DetectionTask | apk_id、industry、mode（fast/deep）、status（见 §6）、queue_position、progress_snapshot(JSON)、pages_covered、scenarios_triggered、current_page、started_at、finished_at、failure_reason |
| Violation | task_id、category（1..6，对应《认定方法》第一至第六条）、category_name、rule_id、description、legal_basis（精确到条+项，如「第三条第（一）点」）、risk_level（高/中/低）、page、occurred_at、remediation_suggestion |
| Evidence | violation_id、type（screenshot/callstack/traffic/timeline）、file_path、meta(JSON) |
| Report | task_id、score、weight_breakdown(JSON)、summary(JSON)、report_no、pdf_path、generated_at |

- 无账号体系（§1）：单用户平台，数据全局可见；建议部署于本机或内网（§9）。
- 检测结果默认保留 90 天，由 Worker 内定时任务到期清理（APK 文件、证据文件、导出文件一并删除）。

## 6. 任务状态机与检测管线

### 6.1 状态流转（PRD 4.3.2）

```
排队中 → 环境准备 → 安装 → 静态分析 → AI遍历 → 数据分析 → 生成报告 → 完成
   └────────────── 任意执行态 ──────────────┘
          ├─→ 失败（记录 failure_reason 分类：App崩溃/设备异常/解析失败/超时/系统错误）
          └─→ 已取消（设备资源 1 分钟内释放；重跑自动复用原配置）
```

- 资源池容量 = 配置的 worker 并发数（`config.yaml` 中 `worker.max_concurrent`，默认 3，对应 PRD「单节点 ≥3 个深度任务并行」）；资源池已满时任务保持「排队中」并展示排队位置（PRD 4.3.1.3）。
- 状态变更由 Worker 写库，API 侧只读；前端轮询任务详情接口。

### 6.2 管线抽象与 Mock 替身

`agent_core/workflow.py` 仅编排阶段顺序与状态流转，各阶段调用引擎接口：

```python
class DetectionEngine(Protocol):
    def run(self, ctx: DetectionContext) -> EngineResult: ...
```

- **V1.0 开发期**：`mock_engine.MockDetector / MockExplorer / MockMonitor` 产出确定性的示例违规 + 证据 + 页面轨迹 + 评分，配合 MockLLM。账号 → 上传 → 任务 → 进度 → 报告 → 导出全链路在 M1 即可真实演示。
- **真实引擎接入顺序**：静态分析（M2，纯本地可跑，不等模拟器）→ AI 遍历（M3）→ Frida/流量（M4）→ 政策解析（M4）→ 全部切换（M6）。替换仅发生在 `agent/` 内部，Web 层零改动。
- 引擎与 Mock 的切换通过 config（`config.yaml` 中 `engines.static_analyzer: mock|real`）控制，便于阶段性验收。
- **边界澄清**：APK「上传时解析」（FR-4.2.1，backend 服务）自 M1 起即为**真实实现**（Androguard 解析权限/SDK/政策）；Mock 替身仅用于**检测任务管线**各阶段（遍历/动态监控/规则判定输入），两者不混淆。

## 7. AI 遍历引擎设计（方案文档 4.1 / 6.1 / 6.2 落地）

### 7.1 主循环

```
页面信息采集 → 页面指纹去重 → 大模型生成操作决策 → Appium 执行交互
（全程同步监控：隐私 API 调用、网络流量、权限申请行为）
循环直至终止条件：检测时长上限 / 最大页面数 / 连续无新页面阈值
```

### 7.2 子模块

| 子模块 | 设计要点 |
|--------|---------|
| 页面信息采集（appium_client） | UIAutomator2 驱动拉 XML DOM；抽取可交互元素（text/resource-id/clickable/bounds）；同步采集 Activity 名、页面截图、弹窗状态；过滤装饰性元素，控制输入 LLM 的信息体量 |
| 页面状态管理（page_state） | 指纹 = 核心特征（Activity + resource-id 集合，权重 70%）+ 辅助特征（页面文本哈希，30%）；相似度 >85% 判同一页；维护已遍历页面库、路径树、每页操作历史；死循环检测（同一页面连续 N=3 次操作无变化强制回溯） |
| LLM 决策（llm_controller） | OpenAI 兼容协议（base_url 可配）；输入 = 系统指令（遍历专家角色、「先深层后广度、优先隐私入口」）+ 当前页面元素结构化列表 + 遍历进度与历史；输出 = 强制 JSON `{action_type, target, reason, risk_flag}`；解析失败自动重试 1 次后回退到本地启发式（随机未访问元素） |
| 遍历执行（explorer） | 封装 Appium 操作；页面加载超时 15 秒跳过重新决策；App 崩溃 2 分钟内重启并恢复到崩溃前页面；弹窗策略（见 7.3）不中断主循环；终止条件可配置 |

### 7.3 弹窗处理策略（PRD 4.4.4）

- **系统权限弹窗**：记录「出现时间 → 用户选择」完整时间线（供「同意前收集」判定），默认选择「同意」继续深入。
- **App 内弹窗**：广告/推荐类优先关闭；隐私相关弹窗完整记录后按策略处理。
- 弹窗识别：DOM 特征（window/dialog 属性）+ 文本特征匹配。

### 7.4 遍历优先级（方案文档 6.2）

1. 权限申请弹窗、隐私政策弹窗、同意授权类交互
2. 个人中心、设置、账号安全、隐私设置页面
3. 核心业务功能入口（发布、上传、定位服务等）
4. 普通内容页面、推荐页面

## 8. 规则引擎与报告

### 8.1 规则配置化（方案文档 6.4）

`identification_method_rules.yaml` 定义官方六大类规则（对应《认定方法》第一至第六条），规则与代码解耦；**V1.0 共 14 条核心规则起步，V1.1 起逐步扩展**（补充仅加 YAML 配置与条件调试，零代码改动）。规则结构沿用方案文档示例：rule_id、rule_name、legal_basis（精确到「第X条第（X）点」，按《认定方法》官方条文逐项对齐）、risk_level、detection_condition（各引擎结果字段的条件表达式）、evidence_fields。评分权重与风险升级/降级条件同文件可配置。

### 8.2 合规评分（FR-4.6.1）

0–100 分，按 6 类违规加权扣分；评分计算过程记录 weight_breakdown，与违规明细联动可追溯。

### 8.3 证据链（方案文档 6.3 / FR-4.6.2）

每条违规 100% 附带：页面截图 +（调用栈 或 流量报文），另含时间线。证据文件落盘 `data/evidence/<task_id>/`，通过 API 可打开查看（截图/文本直读，流量报文格式化展示）。

### 8.4 报告与导出（FR-4.6.4）

- 报告结构：总览（评分、违规分布、检测概况）+ 违规明细 + 证据链 + 整改建议。
- 导出：**V1.0 仅 PDF**——Playwright + Chromium headless 打印（HTML→PDF，与网页预览共用同一 HTML 模板，中文渲染可靠、Windows 无额外运行时依赖；WeasyPrint 因 Windows 需 GTK 运行时被排除）；Word 导出（python-docx）放 V1.1。截图嵌入；含报告编号、检测时间、App 信息。
- 整改建议：LLM 生成（MockLLM 返回模板建议），中文、方案级、≤200 字（FR-4.6.3）。

## 9. 安全（平台自身，PRD 5.3）

> V1.0 无账号体系（用户决策，偏离 PRD 4.1）：打开即进入检测页面，单用户使用。**建议部署于本机或内网**；如需公网访问，由部署侧反向代理加 Basic Auth 保护，应用内不实现登录。PRD 5.3.1（账号安全）与 5.3.2（数据隔离）随之不适用。

- APK 落盘 Fernet 加密（密钥来自环境变量，缺失时自动生成并提示）。
- 大模型数据边界：仅发送页面 UI 结构文本与截图，接口层字段白名单校验（PRD 5.3.4）。
- 全站 HTTPS 于部署期配置；本地上传大小限制 500MB。
- 数据删除：可随时删除 APK、任务与报告，删除后不可恢复（PRD 5.3.5）。

## 10. 错误处理与可观测性

- 任务失败原因分类：App 崩溃无法恢复 / 设备异常 / APK 解析失败 / 检测超时 / 系统内部错误，界面明示（FR-4.3.2.3）。
- `common/logger.py` 统一结构化日志；每个任务一个日志文件 `data/logs/<task_id>.log`，任务详情页可下载（问题排查依据）。
- Worker 进程崩溃由本地 `run_worker` 脚本自动重启兜底；SQLite 轮询队列天然无消息丢失问题（任务状态幂等，重试即可恢复）。

## 11. 测试策略

| 层 | 内容 |
|----|------|
| 单元测试（pytest，agent/ + backend/） | 页面指纹去重与相似度阈值、规则引擎匹配与评分计算、LLM 决策 JSON 解析与回退逻辑、任务状态机流转、六类违规判定（构造检测数据断言） |
| 集成冒烟 | 上传 APK（静态分析真实执行）→ Mock 管线完整跑通 → 报告生成 → PDF 导出文件有效 |
| 前端 | 登录、APK 列表、任务进度、报告页组件冒烟（Vitest） |
| 验收（M6） | 按 PRD 6.1 KPI 逐项核对（需验证样本集与真实环境就绪） |

## 12. 里程碑（映射路线 B，合计约 9 周）

| 里程碑 | 交付内容 | 周次 |
|--------|---------|------|
| M1 平台骨架 | git 初始化；后端/前端脚手架（3 页面）；APK 上传（真实解析，Androguard）；SQLite 轮询队列；任务 + Mock 管线 + 报告 + PDF 导出全链路演示（本机一键启动） | 1 |
| M2 静态分析引擎 | 权限清单、SDK 特征识别、隐私政策原文提取接入真实管线；静态预检页 | 2 |
| M3 AI 遍历引擎 | Appium 封装、页面状态管理、LLM 适配器（Mock 先行）、遍历主循环与健壮性、弹窗策略 | 3–5 |
| M4 动态监控引擎 | Frida 隐私 API Hook、mitmproxy 流量解析接入 | 6–7 |
| M5 规则与报告 | 7 类规则集（每类 2 条起步，V1.1 扩至 ≥5 条）落地、证据链聚合、评分与报告打磨 | 8 |
| M6 测试与切换 | 验证样本集测试、真机环境切换、PRD KPI 核对、部署文档 | 9 |

> 依赖用户侧：Android 模拟器/Appium/Frida 环境安装（B 选择：后补）；真实 LLM API key（OpenAI 兼容）。二者就绪前对应模块以 Mock 运行。

## 13. 风险与应对（摘录，完整版见方案文档第八章）

| 风险 | 应对 |
|------|------|
| 大模型决策延迟 → 遍历效率低 | 精简页面输入；决策缓存；后续本地小模型分流（V1.1） |
| 页面去重不准 → 死循环 | 多特征加权指纹；连续重复操作检测强制回溯 |
| 控件无法识别 → 覆盖率下降 | 截图 + OCR 辅助；V1.1 人工标注引导 |
| Frida 被反调试检测 | Frida 隐藏方案；Xposed/LSPosed 备选；流量交叉验证 |
| 验证样本集建设滞后 | 样本集与开发并行推进（M6 验收门槛） |
| 大模型数据合规 | 仅传 UI 结构文本与截图；接口白名单校验 |
