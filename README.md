# App 隐私合规自动化检测平台

对标《App违法违规收集使用个人信息行为认定方法》6 大类违规的自动化检测平台（V1.0 MVP）。
技术设计见 [docs/superpowers/specs/2026-08-14-app-privacy-compliance-platform-design.md](docs/superpowers/specs/2026-08-14-app-privacy-compliance-platform-design.md)。

> 本仓库内的 App 名称、包名、手机号均为占位示例（`案例A`、`com.example.*`），
> 真实客户数据、检测报告与基准清单只保留在本地 `data/` 目录，不纳入版本控制。

## 目录结构

```
agent/                  检测引擎本体，不被 backend 反向依赖
├─ agent_core/          任务状态机、六阶段管线编排、失败分类、审计契约
├─ ai_explorer/         Appium + LLM 页面遍历引擎
│  ├─ explorer_engine.py   主遍历循环（有行数门禁，见模块化契约测试）
│  └─ *_decision / *_navigation / *_state / *_recovery …
│                        页面语义、决策仲裁、文档会话、权限探针、运行时恢复
├─ detection_engines/   Frida 动态监测、静态/FlowDroid、政策文本分析、SDK 识别
├─ rule_engine/         规则匹配 → 证据链门禁 → 三态裁决 → HTML/PDF 报告
├─ config/              认定方法规则库、SDK 特征、行业权限基线、导航提示词
└─ evaluation/          基准评测

backend/                FastAPI 服务
├─ app/api/             apk / task / report / review 四个路由
├─ app/services/        任务编排、APK 加解密、报告 DOCX、证据 GC
├─ app/models/          SQLAlchemy 模型
└─ tests/               全量回归用例（裸跑 pytest 即可）

worker/                 SQLite 队列轮询 + 设备锁，一台设备同时只跑一个任务
frontend/               Vue3 + Element Plus（上传 / 进度 / 报告三页）
scripts/                API/Worker 启动、Appium 启动、基准评估、导入契约校验
benchmarks/             人工复核结论清单（脱敏版，真实清单在本地 data/）
docs/                   法规原文、PRD、设计与实施计划
data/                   运行期数据：数据库、加密 APK、证据、报告（不入库）
```

## 本地配置

所有运行参数走项目根目录的 `.env`（**不入库**），首次部署：

```powershell
Copy-Item .env.example .env      # 再按需填写设备、LLM、存储路径
```

`.env` 覆盖存储路径、Worker 并发、检测档位上限、Appium/Frida 设备、LLM 接入、
权限探针策略、证据 GC、报告抬头等全部开关；代码内 `backend/app/config.py` 提供同名默认值兜底，
删掉 `.env` 也能按默认值启动，但设备序列号与 `LLM_API_KEY` 必须显式提供。

## 快速开始（本机）

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt

# 终端 1：API 服务
.venv\Scripts\python scripts\run_api.py

# 终端 2：检测 Worker
.venv\Scripts\python scripts\run_worker.py

# 前端开发模式（可选；生产构建见下）
cd frontend && npm install && npm run dev
```

生产前端：`cd frontend && npm run build` 后由 API 服务直接托管，访问 http://127.0.0.1:8000

## 测试

```powershell
.venv\Scripts\python -m pytest backend\tests\ -v
.venv\Scripts\python backend\tests\smoke_e2e.py   # 端到端冒烟
```

### 企业级准确率门禁

人工复核结论保存在 `benchmarks/privacy_benchmark.yaml`，不会被注入自动报告。
同一 APK 至少重复检测 3 次，再以人工结论召回率、禁止误报命中数、结果稳定率和
认定方法条款覆盖率共同决定门禁。缺 APK 的人工报告只保存标签并标记
`artifact_missing`，不会参与门禁或制造虚假的通过率。

```powershell
.venv\Scripts\python scripts\evaluate_benchmarks.py `
  --results data\benchmark-runs `
  --output data\benchmark-summary.json
```

每次运行 JSON 至少包含 `detected_rule_ids` 和 31 项 `adjudication`。三态语义固定为：

- `violation`：已有完整证据链支持违规；
- `no_violation_evidence`：对应场景确实完成，但未形成违规证据，不等同于全面合规；
- `not_covered`：场景、工具或证据不足，必须补测。

## 静态污点、动态行为与网络证据

FlowDroid 是补充静态污点分析器，不直接作出法律结论。候选数据流需要和 Appium 页面、
Frida 敏感 API、权限弹窗及独立网络时间线关联后，才可进入违规证据链。真实 APK 分析通常
为分钟级；`inconclusive` 表示分析已执行但因加固、反射、动态加载、原生代码或未命中
Source 而证据不足，绝不能解释为“未发现问题”。

```ini
PRIVACY_FLOWDROID_ENABLED=true
PRIVACY_FLOWDROID_JAR_PATH=D:\Detect illegal app\tools\flowdroid\soot-infoflow-cmd-2.15.0-jar-with-dependencies.jar
PRIVACY_FLOWDROID_ANDROID_PLATFORMS=C:\Users\86188\AppData\Local\Android\Sdk\platforms
PRIVACY_FLOWDROID_SOURCES_SINKS=D:\Detect illegal app\agent\config\flowdroid\SourcesAndSinks.txt
```

服务端审计使用 `/api/tasks/{task_id}/reviews/server-events/import` 导入脱敏、带引用编号的
审计事件。接口执行类型白名单、幂等去重和 SHA-256 完整性记录；手机号、账号、设备标识、
位置等个人信息不得导入。

## 真实设备遍历

平台只提供真实检测管线，不存在模拟检测分支。运行任务前请启动 Appium（UiAutomator2）、连接 Android 设备或模拟器，并在 `.env` 配置 `LLM_API_KEY`：

```ini
PRIVACY_APPIUM_SERVER_URL=http://127.0.0.1:4725
PRIVACY_APPIUM_UDID=<adb devices 显示的设备序列号>
PRIVACY_FRIDA_DEVICE_ID=<Frida device id，可留空以使用 USB 设备>
```

启动 Worker 前，请先启动本机 Appium；也可在 `.env` 中设置
`PRIVACY_APPIUM_AUTO_START=true`，由真实设备 Worker 仅针对本机回环地址自动启动并健康检查：

```powershell
.\scripts\start_appium.ps1
```

### 登录态与权限核验

每个检测任务均会检查目标包名；若已安装则先卸载、再安装当前 APK，确保首次启动和权限状态
不受上一任务影响。因此，登录态不会跨任务保留。检测过程不会读取、输入或上传账号密码、验证码。

真实遍历会在 Android 系统权限弹窗处采集弹窗、前一页的目的说明及后续页面证据。默认
`PRIVACY_PERMISSION_PROBE_ACTION=deny`，用于验证拒绝权限后是否阻断业务；如需采集授权后的
真实敏感 API 调用，可改为 `allow` 后单独新建一次任务。需要登录后场景时，请在任务新装 App 后
自行登录测试账号，再继续或新建该场景任务。

安装依赖后，流程会：安装临时解密 APK → Frida 在冷启动阶段注入 Hook → Appium 采集页面 XML/截图 → OpenAI 兼容模型仅从当前页面元素白名单选择点击操作 → 写入截图、操作时间线、Frida 事件证据。设备、依赖或 API Key 缺失时任务会明确标记失败，不会生成模拟结果。
