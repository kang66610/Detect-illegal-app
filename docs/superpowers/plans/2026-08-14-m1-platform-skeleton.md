# M1 平台骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建可本机一键运行的平台骨架：APK 上传（真实 Androguard 解析）+ SQLite 轮询任务队列 + Mock 检测管线 + 规则引擎（12 条规则）+ 报告与 PDF 导出 + Vue 3 三页面，全链路可演示、可测试。

**Architecture:** Monorepo 双进程：FastAPI API 服务（backend/）+ 检测 Worker（worker/，轮询 SQLite 领取任务）；检测引擎在 agent/ 包内实现统一接口 `run(ctx) -> EngineResult`，由 workflow.py 编排；V1.0 全部引擎用 Mock 实现（静态分析在上传时真实执行），后续里程碑替换实现、接口不变。

**Tech Stack:** Python 3.11（本机 3.11.15）、FastAPI + SQLAlchemy 2 + SQLite（WAL）、Androguard、Jinja2、Playwright（PDF，优先 msedge channel）、cryptography（Fernet）、pytest；前端 Vue 3 + Vite + Element Plus。

**Spec:** [docs/superpowers/specs/2026-08-14-app-privacy-compliance-platform-design.md](../specs/2026-08-14-app-privacy-compliance-platform-design.md)

## Global Constraints

- Python 3.11（venv：`.venv`，命令 `python -m venv .venv`，本机 python=3.11.15）
- 无账号体系、无 Redis、无 Docker：队列用 SQLite 轮询，本机原生运行
- 数据库文件 `data/app.db`（WAL 模式），运行期数据一律在 `data/`（gitignore）
- 报告只导出 PDF（Playwright `channel="msedge"` 优先，回退默认 chromium）
- 规则引擎：7 大类 × 每类 2 条 = 14 条规则，YAML 配置化；条件用 `field/op/value` 白名单操作符求值，**禁止 eval**（第 7 类 = 官方第二条「未明示收集使用个人信息的目的、方式和范围」）
- 违规输出统一字段：category、rule_id、description、legal_basis、risk_level、evidence；每条违规 100% 附证据
- 大模型：`llm_controller` 仅实现 OpenAI 兼容适配层 + MockLLM，V1.0 不上真实模型
- 所有中文文案用简体中文；代码注释中文
- 每个任务结束必须 commit（约定消息前缀：`feat:`/`test:`/`docs:`/`chore:`）
- 测试命令统一：`.venv/Scripts/python -m pytest backend/tests/ -v`（Windows venv 路径）
- 依赖版本偏差说明：方案文档钉死 `androguard==3.4.0a1`（2021 年 alpha，与 Python 3.11 不兼容），本计划改用 `androguard==4.1.1`；其余依赖沿用方案文档版本
- 测试数据注意：`APKFile.sha256` 有唯一约束，所有测试与冒烟脚本中构造的 APK 必须用 `f"{uuid.uuid4().hex}{uuid.uuid4().hex}"` 生成唯一 sha256（避免重复运行时唯一键冲突）

---

### Task 1: Python 项目骨架与配置

**Files:**
- Create: `backend/__init__.py`、`backend/app/__init__.py`、`backend/app/config.py`、`backend/requirements.txt`
- Create: `agent/__init__.py`、`agent/common/__init__.py`、`agent/common/logger.py`、`agent/common/exceptions.py`、`agent/common/utils.py`、`agent/config/config.yaml`
- Create: `backend/tests/__init__.py`、`backend/tests/test_config.py`
- Create: `backend/conftest.py`（pytest 根配置：`sys.path` 加入项目根）

**Interfaces:**
- Produces: `backend.app.config.load_config(path=None) -> dict`；`agent.common.logger.get_logger(name)`；`agent.common.exceptions.PlatformError`；`agent.common.utils.get_or_create_fernet_key(cfg) -> bytes`

- [ ] **Step 1: 创建 venv 并安装依赖**

```powershell
cd "d:\Detect illegal app"
python -m venv .venv
.venv\Scripts\python -m pip install -U pip
```

`backend/requirements.txt`：

```
fastapi==0.111.0
uvicorn==0.30.1
sqlalchemy==2.0.36
pydantic==2.8.2
pyyaml==6.0.1
python-multipart==0.0.9
cryptography==43.0.1
androguard==4.1.1
jinja2==3.1.4
playwright==1.47.0
pytest==8.3.3
httpx==0.27.2
```

```powershell
.venv\Scripts\python -m pip install -r backend\requirements.txt
```

- [ ] **Step 2: 写失败的测试**

`backend/conftest.py`：

```python
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
```

`backend/tests/test_config.py`：

```python
from backend.app.config import load_config


def test_load_config_returns_expected_defaults():
    cfg = load_config()
    assert cfg["worker"]["max_concurrent"] == 3
    assert cfg["storage"]["db_path"] == "data/app.db"
    assert cfg["llm"]["provider"] == "mock"


def test_load_config_missing_file_raises():
    import pytest
    from backend.app.config import load_config
    with pytest.raises(FileNotFoundError):
        load_config(Path("no_such_file.yaml"))
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv\Scripts\python -m pytest backend/tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: backend.app.config`）

- [ ] **Step 4: 实现配置与公共模块**

`agent/config/config.yaml`：

```yaml
app:
  name: app-privacy-compliance-platform
storage:
  db_path: data/app.db
  apk_dir: data/apks
  evidence_dir: data/evidence
  export_dir: data/exports
  log_dir: data/logs
  retention_days: 90
worker:
  max_concurrent: 3
  poll_interval_seconds: 2
mock_pipeline:
  stage_delay_seconds: 1.5
detection:
  mode_limits:
    fast: {max_duration_minutes: 30, max_pages: 60}
    deep: {max_duration_minutes: 120, max_pages: 300}
llm:
  provider: mock            # mock | openai_compatible
  base_url: ""
  api_key_env: LLM_API_KEY
  model: ""
report:
  pdf_channel: msedge       # msedge | chrome | null（null 用 playwright 自带 chromium）
  header:                   # 报告封面抬头（留空由用户在导出后自行填写）
    test_org: ""            # 检测单位
    subject_org: ""         # 受检单位
    entrust_org: ""         # 委托单位
encryption:
  key_file: data/fernet.key
```

`backend/app/config.py`：

```python
import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "agent" / "config" / "config.yaml"


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # 环境变量覆盖（后续部署时使用）
    if db := os.environ.get("PRIVACY_DB_PATH"):
        data.setdefault("storage", {})["db_path"] = db
    return data


config = load_config()
```

`agent/common/exceptions.py`：

```python
class PlatformError(Exception):
    """平台统一异常基类"""


class ApkValidationError(PlatformError):
    """APK 文件校验失败（非 APK/超限/损坏）"""


class ApkParseError(PlatformError):
    """APK 解析失败（加固/损坏等）"""


class TaskStateError(PlatformError):
    """任务状态流转非法"""


class RuleConfigError(PlatformError):
    """规则配置错误"""
```

`agent/common/logger.py`：

```python
import logging
import sys
from pathlib import Path

from backend.app.config import PROJECT_ROOT, config

_LOG_DIR = PROJECT_ROOT / config["storage"]["log_dir"]
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured
    logger = logging.getLogger(name)
    if _configured:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    fh = logging.FileHandler(_LOG_DIR / "platform.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    _configured = True
    return logger
```

`agent/common/utils.py`：

```python
import hashlib
from pathlib import Path

from cryptography.fernet import Fernet

from backend.app.config import PROJECT_ROOT, config


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_or_create_fernet_key(cfg: dict | None = None) -> bytes:
    cfg = cfg or config
    key_file = PROJECT_ROOT / cfg["encryption"]["key_file"]
    if key_file.exists():
        return key_file.read_bytes()
    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    return key


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    return Fernet(key).encrypt(data)


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    return Fernet(key).decrypt(data)


def decrypt_to_temp(enc_path: Path, key: bytes, tmp_dir: Path) -> Path:
    """解密加密 APK 到临时文件（供 Androguard 解析），用完由调用方删除。"""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / (enc_path.stem + ".tmp.apk")  # x.apk.enc → x.apk.tmp.apk
    out.write_bytes(decrypt_bytes(enc_path.read_bytes(), key))
    return out
```

`backend/__init__.py`、`backend/app/__init__.py`、`agent/__init__.py`、`agent/common/__init__.py`、`backend/tests/__init__.py`：空文件。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv\Scripts\python -m pytest backend/tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend agent backend/tests && git commit -m "feat: 项目骨架与配置模块（config/logger/exceptions/utils）"
```

---

### Task 2: SQLite 数据库与 ORM 模型

**Files:**
- Create: `backend/app/db.py`、`backend/app/models/__init__.py`、`backend/app/models/apk.py`、`backend/app/models/task.py`、`backend/app/models/violation.py`、`backend/app/models/evidence.py`、`backend/app/models/report.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: `backend.app.config.config`（Task 1）
- Produces: `backend.app.db.Base`、`backend.app.db.SessionLocal`、`backend.app.db.init_db()`；模型类 `APKFile / DetectionTask / Violation / Evidence / Report`（字段见各文件）

- [ ] **Step 1: 写失败的测试**

`backend/tests/test_models.py`：

```python
from backend.app.db import Base, SessionLocal, engine, init_db
from backend.app.models import APKFile, DetectionTask, Violation, Evidence, Report


def test_apk_and_task_roundtrip():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="demo.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=1024,
                      parse_status="success", storage_path="data/apks/x.enc",
                      permissions=["android.permission.READ_CONTACTS"])
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, industry="通用", mode="deep", status="queued")
        s.add(task)
        s.commit()
        assert task.id is not None
        got = s.query(DetectionTask).filter_by(id=task.id).one()
        assert got.status == "queued"
        assert got.apk.permissions == ["android.permission.READ_CONTACTS"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python -m pytest backend/tests/test_models.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现数据库与模型**

`backend/app/db.py`：

```python
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.config import PROJECT_ROOT, config

DB_PATH = PROJECT_ROOT / config["storage"]["db_path"]
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from backend.app import models  # noqa: F401  # 注册全部模型
    Base.metadata.create_all(engine)
```

`backend/app/models/apk.py`：

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class APKFile(Base):
    __tablename__ = "apk_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    md5: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 报告模板「MD5值」字段
    size_bytes: Mapped[int] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(String(20), default="parsing")  # parsing/success/failed/invalid
    parse_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    package_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    permissions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sdk_list: Mapped[list | None] = mapped_column(JSON, nullable=True)
    policy_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

`backend/app/models/task.py`：

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class DetectionTask(Base):
    __tablename__ = "detection_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    apk_id: Mapped[int] = mapped_column(ForeignKey("apk_files.id"))
    industry: Mapped[str] = mapped_column(String(32), default="通用")
    mode: Mapped[str] = mapped_column(String(16), default="deep")  # fast/deep
    # queued/preparing/installing/static_analysis/traversing/analyzing/reporting/completed/failed/canceled
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    queue_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    current_page: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pages_covered: Mapped[int] = mapped_column(Integer, default=0)
    scenarios_triggered: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    apk = relationship("APKFile")
```

`backend/app/models/violation.py`：

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("detection_tasks.id"))
    category: Mapped[int] = mapped_column(Integer)  # 1..6 对应《认定方法》六类
    category_name: Mapped[str] = mapped_column(String(100), default="")  # 显式标注第N类名称
    rule_id: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    legal_basis: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(8))  # 高/中/低
    page: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remediation_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    evidences = relationship("Evidence", back_populates="violation", cascade="all, delete-orphan")
```

`backend/app/models/evidence.py`：

```python
from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class Evidence(Base):
    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    violation_id: Mapped[int] = mapped_column(ForeignKey("violations.id"))
    type: Mapped[str] = mapped_column(String(20))  # screenshot/callstack/traffic/timeline
    file_path: Mapped[str] = mapped_column(String(500))
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    violation = relationship("Violation", back_populates="evidences")
```

`backend/app/models/report.py`：

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("detection_tasks.id"), unique=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    weight_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report_no: Mapped[str] = mapped_column(String(64))
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task = relationship("DetectionTask")
```

`backend/app/models/__init__.py`：

```python
from backend.app.models.apk import APKFile
from backend.app.models.evidence import Evidence
from backend.app.models.report import Report
from backend.app.models.task import DetectionTask
from backend.app.models.violation import Violation

__all__ = ["APKFile", "DetectionTask", "Violation", "Evidence", "Report"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python -m pytest backend/tests/test_models.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app && git commit -m "feat: SQLite 数据库与五张核心表 ORM 模型"
```

---

### Task 3: APK 上传、校验与真实解析（Androguard）

**Files:**
- Create: `agent/detection_engines/__init__.py`、`agent/detection_engines/static_analyzer.py`、`agent/detection_engines/sdk_detector.py`、`agent/config/sdk_features.yaml`
- Create: `backend/app/services/__init__.py`、`backend/app/services/apk_service.py`
- Create: `backend/tests/test_apk_validation.py`、`backend/tests/test_static_analyzer.py`

**Interfaces:**
- Consumes: `APKFile`（Task 2）、`get_or_create_fernet_key / sha256_of_file / encrypt_bytes / decrypt_bytes`（Task 1）、`config`（Task 1）
- Produces:
  - `agent.detection_engines.static_analyzer.analyze_apk(apk_path: Path) -> dict`（含 app_name/package_name/version_name/permissions/policy_raw/sdk_list；失败抛 `ApkParseError`）
  - `agent.detection_engines.sdk_detector.detect_sdks(manifest_meta: dict, permissions: list[str]) -> list[dict]`
  - `backend.app.services.apk_service.save_apk(file: UploadFile) -> APKFile`、`list_apks() -> list[APKFile]`、`delete_apk(apk_id: int) -> None`

- [ ] **Step 1: 写失败的测试**

`backend/tests/test_apk_validation.py`：

```python
import io

import pytest
from agent.common.exceptions import ApkValidationError
from backend.app.db import init_db
from backend.app.services.apk_service import validate_apk_upload


def test_rejects_non_zip_file(tmp_path):
    fake = tmp_path / "fake.apk"
    fake.write_bytes(b"this is not a zip file at all")
    with pytest.raises(ApkValidationError, match="文件格式无效"):
        validate_apk_upload(fake, "fake.apk")


def test_rejects_zip_without_manifest(tmp_path):
    import zipfile
    fake = tmp_path / "notapk.apk"
    with zipfile.ZipFile(fake, "w") as z:
        z.writestr("hello.txt", "hello")
    with pytest.raises(ApkValidationError, match="文件格式无效"):
        validate_apk_upload(fake, "notapk.apk")


def test_rejects_oversized(tmp_path):
    big = tmp_path / "big.apk"
    big.write_bytes(b"\x00" * 100)
    with pytest.raises(ApkValidationError, match="超过"):
        validate_apk_upload(big, "big.apk", max_bytes=50)
```

`backend/tests/test_static_analyzer.py`：

```python
from agent.detection_engines.sdk_detector import detect_sdks


def test_detect_sdks_by_meta_and_permissions():
    meta = {
        "com.amap.api.v2.apikey": "dummy",
        "UMENG_APPKEY": "dummy",
    }
    sdks = detect_sdks(meta, ["android.permission.ACCESS_FINE_LOCATION"])
    names = {s["name"] for s in sdks}
    assert "高德地图" in names
    assert "友盟" in names


def test_detect_sdks_empty_when_nothing_matches():
    assert detect_sdks({}, []) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python -m pytest backend/tests/test_apk_validation.py backend/tests/test_static_analyzer.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 SDK 特征库与检测**

`agent/config/sdk_features.yaml`：

```yaml
# SDK 特征库（V1.0 起步 ~20 个常见 SDK，后续扩充）
# meta_keys: AndroidManifest meta-data 常见 key；permissions: 该 SDK 特征权限
sdk_features:
  - name: 高德地图
    meta_keys: ["com.amap.api.v2.apikey"]
    permissions: []
    collected: ["定位信息"]
  - name: 百度地图
    meta_keys: ["com.baidu.lbsapi.API_KEY"]
    permissions: []
    collected: ["定位信息"]
  - name: 友盟
    meta_keys: ["UMENG_APPKEY"]
    permissions: []
    collected: ["设备标识", "应用列表"]
  - name: 腾讯 Bugly
    meta_keys: ["BUGLY_APPID", "TencentMapSDK"]
    permissions: []
    collected: ["设备标识", "崩溃日志"]
  - name: 极光推送
    meta_keys: ["JPUSH_APPKEY", "JPUSH_CHANNEL"]
    permissions: []
    collected: ["设备标识", "应用列表"]
  - name: 个推
    meta_keys: ["PUSH_APPID", "GETUI_APPID"]
    permissions: []
    collected: ["设备标识"]
  - name: 微博 SDK
    meta_keys: ["com.sina.weibo.sdk.APP_KEY"]
    permissions: []
    collected: ["设备标识"]
  - name: 微信开放平台
    meta_keys: ["WX_APPID", "com.tencent.mm.appid"]
    permissions: []
    collected: ["设备标识"]
  - name: QQ 互联
    meta_keys: ["QQ_APPID"]
    permissions: []
    collected: ["设备标识"]
  - name: 讯飞语音
    meta_keys: ["appid_android", "IFLYTEK_APPKEY"]
    permissions: []
    collected: ["语音数据"]
  - name: 声网 Agora
    meta_keys: ["agora_app_id"]
    permissions: ["android.permission.RECORD_AUDIO", "android.permission.CAMERA"]
    collected: ["音视频数据"]
  - name: 穿山甲/巨量引擎
    meta_keys: ["TT_APPID", "BaiduMobAd_APP_ID"]
    permissions: ["android.permission.ACCESS_FINE_LOCATION"]
    collected: ["设备标识", "定位信息"]
  - name: 腾讯广告
    meta_keys: ["TencentAd"]
    permissions: []
    collected: ["设备标识"]
  - name: 阿里推送
    meta_keys: ["com.alibaba.app.appkey"]
    permissions: []
    collected: ["设备标识"]
  - name: 华为 HMS
    meta_keys: ["com.huawei.hms.client.appid"]
    permissions: []
    collected: ["设备标识"]
  - name: 小米推送
    meta_keys: ["XMPUSH_APPID", "XMPUSH_APPKEY"]
    permissions: []
    collected: ["设备标识"]
```

`agent/detection_engines/sdk_detector.py`：

```python
from pathlib import Path

import yaml

from backend.app.config import PROJECT_ROOT

_FEATURES_PATH = PROJECT_ROOT / "agent" / "config" / "sdk_features.yaml"


def _load_features() -> list[dict]:
    with open(_FEATURES_PATH, "r", encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("sdk_features", [])


def detect_sdks(manifest_meta: dict, permissions: list[str]) -> list[dict]:
    """根据 manifest meta-data 与权限特征识别 SDK，返回 [{name, collected, matched_by}]。"""
    result = []
    meta_keys = set(manifest_meta.keys())
    for feat in _load_features():
        matched_by = [k for k in feat["meta_keys"] if k in meta_keys]
        if not matched_by:
            hit_perm = [p for p in feat["permissions"] if p in permissions]
            if hit_perm:
                matched_by = [f"权限:{','.join(hit_perm)}"]
        if matched_by:
            result.append({
                "name": feat["name"],
                "collected": feat["collected"],
                "matched_by": matched_by,
            })
    return result
```

- [ ] **Step 4: 实现静态分析引擎（Androguard）**

`agent/detection_engines/static_analyzer.py`：

```python
from pathlib import Path

from androguard.core.apk import APK

from agent.common.exceptions import ApkParseError
from agent.detection_engines.sdk_detector import detect_sdks

# 隐私政策文件名关键词（assets/res/raw 中搜索）
_POLICY_KEYWORDS = ["privacy", "policy", "隐私", "政策", "agreement", "用户协议"]
# 危险权限清单（PRD 4.2.2.2）
DANGEROUS_PERMISSIONS = {
    "android.permission.ACCESS_FINE_LOCATION": "精确定位",
    "android.permission.ACCESS_COARSE_LOCATION": "粗略定位",
    "android.permission.READ_CONTACTS": "通讯录读取",
    "android.permission.WRITE_CONTACTS": "通讯录写入",
    "android.permission.RECORD_AUDIO": "麦克风",
    "android.permission.CAMERA": "相机",
    "android.permission.READ_EXTERNAL_STORAGE": "存储读取",
    "android.permission.WRITE_EXTERNAL_STORAGE": "存储写入",
    "android.permission.READ_PHONE_STATE": "设备标识",
    "android.permission.READ_SMS": "短信读取",
    "android.permission.SEND_SMS": "短信发送",
    "android.permission.CALL_LOG": "通话记录",
    "android.permission.READ_CALENDAR": "日历读取",
    "android.permission.BODY_SENSORS": "身体传感器",
    "android.permission.ACTIVITY_RECOGNITION": "运动状态",
}


def analyze_apk(apk_path: Path) -> dict:
    """解析 APK 基本信息。失败抛 ApkParseError。"""
    try:
        apk = APK(str(apk_path))
    except Exception as e:  # androguard 对损坏/加固 APK 抛各种异常
        raise ApkParseError(f"APK 解析失败（可能已加固或文件损坏）：{type(e).__name__}") from e
    permissions = apk.get_permissions() or []
    manifest_meta = _extract_meta(apk)
    return {
        "app_name": apk.get_app_name(),
        "package_name": apk.get_package(),
        "version_name": apk.get_androidversion_name(),
        "md5": _md5_of_file(apk_path),
        "permissions": permissions,
        "permission_flags": {p: DANGEROUS_PERMISSIONS[p] for p in permissions if p in DANGEROUS_PERMISSIONS},
        "sdk_list": detect_sdks(manifest_meta, permissions),
        "policy_raw": _extract_policy_text(apk),
        "meta": manifest_meta,
    }


def _md5_of_file(path: Path) -> str:
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()  # 报告模板 MD5 为大写


def _extract_meta(apk: APK) -> dict:
    """解析 AndroidManifest 中 application 下的 meta-data（SDK 特征识别输入）。"""
    meta = {}
    try:
        xml = apk.get_android_manifest_axml()
        root = xml.get_xml_obj() if hasattr(xml, "get_xml_obj") else None
        if root is None:
            return meta
        ns = "http://schemas.android.com/apk/res/android"
        for elem in root.iter():
            if elem.tag.rsplit("}", 1)[-1] == "meta-data":
                name = elem.get(f"{{{ns}}}name") or elem.get("name")
                value = elem.get(f"{{{ns}}}value") or elem.get("value")
                if name:
                    meta[name] = value
    except Exception:
        pass  # meta 提取失败不影响主流程（加固 APK 常见）
    return meta


def _extract_policy_text(apk: APK) -> str | None:
    """在 assets 中查找隐私政策文本文件，返回原文（截断至 50KB）。"""
    files = apk.get_files() or []
    for name in files:
        low = name.lower()
        if any(k.lower() in low for k in _POLICY_KEYWORDS):
            try:
                raw = apk.get_file(name)
                text = raw.decode("utf-8", errors="replace")
                return text[:50000]
            except Exception:
                continue
    return None
```

> 注：`_extract_meta` 中 androguard 4.1 的 API 兼容分支保持简单（try/except 兜底），meta 提取失败不影响主流程。

- [ ] **Step 5: 实现 APK 上传服务（校验 + 加密落盘 + 解析）**

`backend/app/services/apk_service.py`：

```python
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from agent.common.exceptions import ApkParseError, ApkValidationError
from agent.common.utils import encrypt_bytes, get_or_create_fernet_key, sha256_of_file
from agent.detection_engines.static_analyzer import analyze_apk
from backend.app.config import PROJECT_ROOT, config
from backend.app.db import SessionLocal
from backend.app.models import APKFile, DetectionTask, Report

MAX_APK_BYTES = 500 * 1024 * 1024  # 500MB（PRD 4.2.1.1）


def validate_apk_upload(tmp_path: Path, filename: str, max_bytes: int = MAX_APK_BYTES) -> None:
    if not filename.lower().endswith(".apk"):
        raise ApkValidationError("文件格式无效：仅支持 .apk 文件")
    size = tmp_path.stat().st_size
    if size > max_bytes:
        raise ApkValidationError(f"文件超过大小限制（{max_bytes // 1024 // 1024}MB）")
    if size < 1024:
        raise ApkValidationError("文件格式无效：文件过小")
    # APK 是 zip 容器，且必须含 AndroidManifest.xml 或 META-INF
    import zipfile
    try:
        with zipfile.ZipFile(tmp_path) as z:
            names = set(z.namelist())
            if "AndroidManifest.xml" not in names and not any(n.startswith("META-INF/") for n in names):
                raise ApkValidationError("文件格式无效：不是有效的 APK（zip 容器内无清单文件）")
            if z.testzip() is not None:
                raise ApkValidationError("文件格式无效：zip 容器损坏")
    except zipfile.BadZipFile as e:
        raise ApkValidationError("文件格式无效：不是有效的 APK") from e


def save_apk(file: UploadFile) -> APKFile:
    """上传流程：校验 → 落盘加密 → 真实解析 → 入库。校验失败也入库（invalid 状态，界面可见原因）。"""
    cfg = config
    apk_dir = PROJECT_ROOT / cfg["storage"]["apk_dir"]
    apk_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = apk_dir / f".tmp_{file.filename}"
    with open(tmp_path, "wb") as f:
        f.write(file.file.read())
    try:
        sha256 = sha256_of_file(tmp_path)  # 唯一键：任何路径都用真实哈希
        validate_apk_upload(tmp_path, file.filename)
        key = get_or_create_fernet_key(cfg)
        enc_path = apk_dir / f"{sha256}.apk.enc"
        enc_path.write_bytes(encrypt_bytes(tmp_path.read_bytes(), key))
        row = APKFile(
            filename=file.filename, sha256=sha256, size_bytes=tmp_path.stat().st_size,
            parse_status="parsing", storage_path=str(enc_path.relative_to(PROJECT_ROOT)),
        )
        with SessionLocal() as s:
            s.add(row)
            s.commit()
            s.refresh(row)
            parse_apk(row.id)
            s.add(row)
            s.commit()
            return s.query(APKFile).filter_by(id=row.id).one()
    except ApkValidationError as e:
        with SessionLocal() as s:
            row = APKFile(filename=file.filename, sha256=sha256, size_bytes=tmp_path.stat().st_size,
                          parse_status="invalid", parse_message=str(e),
                          storage_path=str(tmp_path.relative_to(PROJECT_ROOT)))
            s.add(row)
            s.commit()
            return s.query(APKFile).filter_by(id=row.id).one()
    finally:
        tmp_path.unlink(missing_ok=True)


def parse_apk(apk_id: int) -> APKFile:
    """解析 APK 并回写解析结果（真实 Androguard；加密存储先解密到临时文件）。"""
    with SessionLocal() as s:
        row = s.query(APKFile).filter_by(id=apk_id).one()
        if row.parse_status in ("invalid",):
            return row
        tmp_dir = PROJECT_ROOT / config["storage"]["apk_dir"] / "tmp"
        tmp = decrypt_to_temp(PROJECT_ROOT / row.storage_path, get_or_create_fernet_key(), tmp_dir)
        try:
            result = analyze_apk(tmp)
        except ApkParseError as e:
            row.parse_status = "failed"
            row.parse_message = str(e)
            s.commit()
            return row
        finally:
            tmp.unlink(missing_ok=True)
        row.parse_status = "success"
        row.parse_message = None
        row.app_name = result["app_name"]
        row.package_name = result["package_name"]
        row.version_name = result["version_name"]
        row.md5 = result["md5"]
        row.permissions = result["permissions"]
        row.policy_raw = result["policy_raw"]
        row.sdk_list = result["sdk_list"]
        s.commit()
        return row


def list_apks() -> list[APKFile]:
    with SessionLocal() as s:
        return s.query(APKFile).order_by(APKFile.uploaded_at.desc()).all()


def delete_apk(apk_id: int) -> None:
    """删除 APK 及其关联任务/违规/证据/报告（PRD 4.2.3.2 确认后执行）。"""
    with SessionLocal() as s:
        tasks = s.query(DetectionTask).filter_by(apk_id=apk_id).all()
        for t in tasks:
            for v in s.query(Violation).filter_by(task_id=t.id):
                s.delete(v)  # 证据随 violation 级联删除
            s.query(Report).filter_by(task_id=t.id).delete()
            s.delete(t)
        apk = s.query(APKFile).filter_by(id=apk_id).one()
        (PROJECT_ROOT / apk.storage_path).unlink(missing_ok=True)
        s.delete(apk)
        s.commit()
```

> 注：`parse_apk` 解析的是加密存储路径——V1.0 简化：解析时解密到临时文件再交给 androguard（下一任务实现 `decrypt_to_temp`），此处先按临时解密实现；若解析失败也回写 failed。

- [ ] **Step 6: 跑测试确认通过**

Run: `.venv\Scripts\python -m pytest backend/tests/test_apk_validation.py backend/tests/test_static_analyzer.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add agent backend/app/services backend/tests && git commit -m "feat: APK 校验、加密存储与真实静态解析（Androguard+SDK 特征库）"
```

---

### Task 4: 检测任务 CRUD 与 SQLite 轮询队列

**Files:**
- Create: `agent/agent_core/__init__.py`、`agent/agent_core/task_manager.py`
- Create: `backend/app/services/task_service.py`
- Create: `backend/tests/test_state_machine.py`、`backend/tests/test_queue_claim.py`

**Interfaces:**
- Consumes: `DetectionTask`（Task 2）、`APKFile`（Task 2）
- Produces:
  - `agent.agent_core.task_manager.can_transition(current: str, nxt: str) -> bool`
  - `agent.agent_core.task_manager.claim_next_task(session: Session) -> int | None`（原子领取，返回 task id）
  - `agent.agent_core.task_manager.set_status(session, task, status, reason=None)`（非法流转抛 `TaskStateError`）
  - `backend.app.services.task_service.create_task(apk_id, industry, mode) -> DetectionTask`、`list_tasks(status=None)`、`get_task(task_id)`、`cancel_task(task_id)`、`retry_task(task_id)`

- [ ] **Step 1: 写失败的测试**

`backend/tests/test_state_machine.py`：

```python
import pytest
from agent.agent_core.task_manager import can_transition
from agent.common.exceptions import TaskStateError
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask
from backend.app.services.task_service import cancel_task, retry_task


def test_flow_allows_normal_chain():
    chain = ["queued", "preparing", "installing", "static_analysis",
             "traversing", "analyzing", "reporting", "completed"]
    for cur, nxt in zip(chain, chain[1:]):
        assert can_transition(cur, nxt), f"{cur} -> {nxt}"


def test_flow_rejects_skip_and_backward():
    assert not can_transition("queued", "traversing")
    assert not can_transition("reporting", "traversing")


def test_cancel_and_retry():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="a.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=1, parse_status="success", storage_path="x")
        s.add(apk)
        s.commit()
        t = DetectionTask(apk_id=apk.id, status="traversing")
        s.add(t)
        s.commit()
        cancel_task(t.id)
        s.expire_all()
        assert s.query(DetectionTask).filter_by(id=t.id).one().status == "canceled"
        retry_task(t.id)
        s.expire_all()
        assert s.query(DetectionTask).filter_by(id=t.id).one().status == "queued"
```

`backend/tests/test_queue_claim.py`：

```python
import threading

from agent.agent_core.task_manager import claim_next_task
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask


def test_claim_is_atomic_two_sessions():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="a.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=1, parse_status="success", storage_path="x")
        s.add(apk)
        s.commit()
        for i in range(2):
            s.add(DetectionTask(apk_id=apk.id, status="queued"))
        s.commit()
        s.add(DetectionTask(apk_id=apk.id, status="traversing"))  # 不可领取
        s.commit()

    claimed = []
    lock = threading.Lock()

    def claim():
        with SessionLocal() as s:
            tid = claim_next_task(s)
            with lock:
                claimed.append(tid)

    threads = [threading.Thread(target=claim) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    got = [c for c in claimed if c is not None]
    assert len(got) == 2  # 2 个排队任务最终被全部领取（重试候选后无遗漏）
    assert len(set(got)) == 2  # 无重复领取
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python -m pytest backend/tests/test_state_machine.py backend/tests/test_queue_claim.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现任务状态机与队列**

`agent/agent_core/task_manager.py`：

```python
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from agent.common.exceptions import TaskStateError
from backend.app.models import DetectionTask

STATUS_FLOW = {
    "queued": {"preparing", "canceled"},
    "preparing": {"installing", "failed", "canceled"},
    "installing": {"static_analysis", "failed", "canceled"},
    "static_analysis": {"traversing", "failed", "canceled"},
    "traversing": {"analyzing", "failed", "canceled"},
    "analyzing": {"reporting", "failed", "canceled"},
    "reporting": {"completed", "failed", "canceled"},
    "completed": set(),
    "failed": set(),
    "canceled": set(),
}


def can_transition(current: str, nxt: str) -> bool:
    return nxt in STATUS_FLOW.get(current, set())


def set_status(session: Session, task: DetectionTask, status: str, reason: str | None = None) -> None:
    if not can_transition(task.status, status):
        raise TaskStateError(f"非法状态流转：{task.status} -> {status}（task_id={task.id}）")
    task.status = status
    if status == "preparing":
        task.started_at = datetime.utcnow()
    if status in ("completed", "failed", "canceled"):
        task.finished_at = datetime.utcnow()
    if reason:
        task.failure_reason = reason
    session.commit()


def claim_next_task(session: Session, max_attempts: int = 3) -> int | None:
    """原子领取一个排队任务：候选行 + 条件 UPDATE，rowcount==1 才算领取成功。

    候选被其他 worker 抢走时重试下一个候选（最多 max_attempts 次），
    避免「候选被抢 → 本次白跑一趟」导致领取率下降。
    """
    for _ in range(max_attempts):
        candidate = (
            session.query(DetectionTask)
            .filter(DetectionTask.status == "queued")
            .order_by(DetectionTask.created_at, DetectionTask.id)
            .first()
        )
        if candidate is None:
            return None
        result = session.execute(
            update(DetectionTask)
            .where(DetectionTask.id == candidate.id, DetectionTask.status == "queued")
            .values(status="preparing", started_at=datetime.utcnow())
        )
        session.commit()
        if result.rowcount == 1:
            return candidate.id
        # 被其他 worker 抢走，重试下一个候选
    return None
```

`backend/app/services/task_service.py`：

```python
from sqlalchemy.orm import Session

from agent.agent_core.task_manager import can_transition, set_status
from agent.common.exceptions import TaskStateError
from backend.app.db import SessionLocal
from backend.app.models import APKFile, DetectionTask


def create_task(apk_id: int, industry: str = "通用", mode: str = "deep") -> DetectionTask:
    with SessionLocal() as s:
        apk = s.query(APKFile).filter_by(id=apk_id).first()
        if apk is None:
            raise TaskStateError("APK 不存在")
        if apk.parse_status != "success":
            raise TaskStateError("APK 尚未解析成功，不能创建检测任务")
        if mode not in ("fast", "deep"):
            raise TaskStateError("检测档位必须是 fast 或 deep")
        task = DetectionTask(apk_id=apk_id, industry=industry, mode=mode, status="queued")
        s.add(task)
        s.commit()
        s.refresh(task)
        return task


def list_tasks(status: str | None = None) -> list[DetectionTask]:
    with SessionLocal() as s:
        q = s.query(DetectionTask).order_by(DetectionTask.created_at.desc())
        if status:
            q = q.filter(DetectionTask.status == status)
        return q.all()


def get_task(task_id: int) -> DetectionTask:
    with SessionLocal() as s:
        return s.query(DetectionTask).filter_by(id=task_id).one()


def cancel_task(task_id: int) -> DetectionTask:
    with SessionLocal() as s:
        t = s.query(DetectionTask).filter_by(id=task_id).one()
        set_status(s, t, "canceled")
        return t


def retry_task(task_id: int) -> DetectionTask:
    """失败任务一键重跑：复用原配置回到排队。"""
    with SessionLocal() as s:
        t = s.query(DetectionTask).filter_by(id=task_id).one()
        if t.status != "failed":
            raise TaskStateError("仅失败任务可以重跑")
        t.status = "queued"
        t.failure_reason = None
        t.finished_at = None
        t.progress = None
        t.pages_covered = 0
        t.scenarios_triggered = 0
        s.commit()
        return t
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python -m pytest backend/tests/test_state_machine.py backend/tests/test_queue_claim.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add agent/agent_core backend/app/services backend/tests && git commit -m "feat: 任务状态机与 SQLite 原子轮询队列"
```

---

### Task 5: Mock 检测管线（workflow 编排）

**Files:**
- Create: `agent/detection_engines/base.py`、`agent/detection_engines/mock_engine.py`
- Create: `agent/agent_core/workflow.py`
- Create: `worker/__init__.py`、`worker/main.py`
- Create: `backend/tests/test_workflow.py`

**Interfaces:**
- Consumes: `DetectionTask/APKFile`（Task 2）、`set_status`（Task 4）、`config`（Task 1）
- Produces:
  - `agent.detection_engines.base.Finding(kind, category, payload)`、`EngineResult(findings, evidence_files, stats)`、`DetectionContext(task, apk, cfg, data_dir)`
  - `agent.detection_engines.mock_engine.MockStaticEngine/MockExplorerEngine/MockMonitorEngine`（均实现 `run(ctx) -> EngineResult`）
  - `agent.agent_core.workflow.run_task(task_id: int) -> None`（跑完整管线并落库违规/证据/报告，状态置 completed/failed）

- [ ] **Step 1: 写失败的测试**

`backend/tests/test_workflow.py`：

```python
from pathlib import Path

from agent.agent_core.workflow import run_task
from backend.app.config import PROJECT_ROOT
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask, Evidence, Report, Violation


def _make_apk(perms=None, policy=True):
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(
            filename="demo.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=2048, parse_status="success",
            storage_path="data/apks/x.enc", app_name="DemoApp", package_name="com.demo.app",
            version_name="1.0.0",
            permissions=perms or ["android.permission.READ_CONTACTS"],
            sdk_list=[{"name": "友盟", "collected": ["设备标识"]}],
            policy_raw="隐私政策原文……" if policy else None,
        )
        s.add(apk)
        s.commit()
        return apk


def test_mock_pipeline_produces_violations_and_report():
    apk = _make_apk()
    with SessionLocal() as s:
        task = DetectionTask(apk_id=apk.id, industry="工具", mode="fast")
        s.add(task)
        s.commit()
        task_id = task.id
    run_task(task_id)
    with SessionLocal() as s:
        t = s.query(DetectionTask).filter_by(id=task_id).one()
        assert t.status == "completed"
        assert t.pages_covered > 0
        violations = s.query(Violation).filter_by(task_id=task_id).all()
        assert len(violations) >= 2
        for v in violations:
            assert v.description and v.legal_basis and v.risk_level
            assert s.query(Evidence).filter_by(violation_id=v.id).count() >= 1  # 100% 附证据
        report = s.query(Report).filter_by(task_id=task_id).one()
        assert 0 <= report.score <= 100
        assert report.pdf_path and (PROJECT_ROOT / report.pdf_path).exists()


def test_mock_pipeline_marks_failed_on_missing_apk():
    init_db()
    run_task(999999)
    # 不存在的任务：workflow 静默返回，不抛异常（日志记录）
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python -m pytest backend/tests/test_workflow.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现引擎接口与 Mock 引擎**

`agent/detection_engines/base.py`：

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Finding:
    """引擎产出的检测发现，供规则引擎匹配。kind 为规则条件引用的键。"""
    kind: str
    category: int  # 1..6
    payload: dict = field(default_factory=dict)


@dataclass
class EngineResult:
    findings: list[Finding] = field(default_factory=list)
    evidence_files: list[dict] = field(default_factory=list)  # {type, path, meta}
    stats: dict = field(default_factory=dict)


@dataclass
class DetectionContext:
    task: object
    apk: object
    cfg: dict
    data_dir: Path


class DetectionEngine(Protocol):
    def run(self, ctx: DetectionContext) -> EngineResult: ...
```

`agent/detection_engines/mock_engine.py`：

```python
import json
import time
from datetime import datetime

from agent.detection_engines.base import DetectionContext, EngineResult, Finding

def _screenshot_svg(page_name: str) -> str:
    """mock 截图占位：SVG 文本占位图（Chromium 可直接渲染，无需图像库）。"""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">'
        f'<rect width="100%" height="100%" fill="#e8e8e8"/>'
        f'<text x="50%" y="50%" text-anchor="middle" font-size="22" fill="#555" font-family="Microsoft YaHei, sans-serif">'
        f'证据截图占位（页面：{page_name}，Mock 阶段）</text></svg>'
    )

# 工具类 App 不应申请的高危权限（行业-必要权限基准，V1.0 内置一小表）
_INDUSTRY_BASELINE = {
    "工具": set(),
    "金融理财": {"android.permission.READ_PHONE_STATE"},
    "电商购物": {"android.permission.ACCESS_COARSE_LOCATION"},
    "社交通讯": {"android.permission.READ_CONTACTS", "android.permission.CAMERA", "android.permission.RECORD_AUDIO"},
    "医疗健康": {"android.permission.BODY_SENSORS"},
    "教育": {"android.permission.CAMERA", "android.permission.RECORD_AUDIO"},
    "出行": {"android.permission.ACCESS_FINE_LOCATION", "android.permission.ACCESS_COARSE_LOCATION"},
}
_SENSITIVE_API_LIST = [
    "android.telephony.TelephonyManager.getDeviceId",
    "android.telephony.TelephonyManager.getImei",
    "android.location.LocationManager.requestLocationUpdates",
    "android.provider.ContactsContract.Contacts.query",
    "android.media.MediaRecorder.start",
    "android.hardware.Camera.open",
]


def _write_evidence(data_dir, ev_type, name, meta):
    (data_dir / ev_type).mkdir(parents=True, exist_ok=True)
    path = data_dir / ev_type / name
    if ev_type == "screenshot":
        path.write_text(_screenshot_svg(meta.get("page", "未知页面")), encoding="utf-8")
    else:
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"type": ev_type, "path": str(path), "meta": meta}


class MockStaticEngine:
    """基于上传时真实解析结果的静态检测（权限-行业匹配、政策缺失）。"""
    def run(self, ctx: DetectionContext) -> EngineResult:
        findings = []
        baseline = _INDUSTRY_BASELINE.get(ctx.task.industry, set())
        for perm in ctx.apk.permissions or []:
            if perm.startswith("android.permission.") and perm not in baseline and (
                "LOCATION" in perm or "CONTACTS" in perm or "RECORD_AUDIO" in perm
                or "CAMERA" in perm or "READ_PHONE_STATE" in perm or "READ_SMS" in perm
            ):
                findings.append(Finding(
                    kind="permission_industry_mismatch", category=3,
                    payload={"permission": perm, "industry": ctx.task.industry},
                ))
        if not ctx.apk.policy_raw:
            findings.append(Finding(kind="policy_missing", category=1, payload={}))
        else:
            # V1.0 政策仅提取原文（结构化解析 V1.1），此发现由 mock 产出模拟真实引擎结果
            findings.append(Finding(kind="purpose_not_disclosed", category=7,
                                    payload={"reason": "政策原文中未提取到目的/方式/范围结构化字段（V1.1 起由政策解析引擎真实判定）"}))
        if ctx.apk.permissions:
            findings.append(Finding(kind="permission_purpose_not_informed", category=7,
                                    payload={"permission": ctx.apk.permissions[0], "page": "权限申请弹窗"}))
        return EngineResult(findings=findings, stats={"static": "mock(真实解析结果)"})


class MockExplorerEngine:
    """模拟遍历：确定性页面轨迹 + 隐私场景事件。"""
    def run(self, ctx: DetectionContext) -> EngineResult:
        delay = ctx.cfg["mock_pipeline"]["stage_delay_seconds"]
        time.sleep(delay)
        pages = ["首页", "登录注册页", "个人中心", "设置", "关于我们", "隐私政策页"]
        findings = []
        evs = []
        # 隐私政策弹窗出现在首启（模拟）
        if ctx.apk.policy_raw:
            evs.append(_write_evidence(ctx.data_dir, "timeline", "policy_popup.json",
                                       {"event": "隐私政策弹窗", "page": "首页", "choice": "同意"}))
        # 权限申请弹窗（定位）
        evs.append(_write_evidence(ctx.data_dir, "timeline", "permission_popup.json",
                                   {"event": "权限申请弹窗", "permission": "android.permission.ACCESS_FINE_LOCATION",
                                    "page": "个人中心", "choice": "同意", "time": datetime.utcnow().isoformat()}))
        evs.append(_write_evidence(ctx.data_dir, "screenshot", "permission_popup.png",
                                   {"page": "个人中心"}))
        # 未发现注销入口 → 违规发现
        findings.append(Finding(kind="no_delete_entry", category=5, payload={"page": "设置"}))
        # 未发现投诉举报渠道
        findings.append(Finding(kind="no_complaint_channel", category=6, payload={"page": "关于我们"}))
        # 超频次收集：定位 1 分钟内被读 8 次
        findings.append(Finding(kind="frequent_collection", category=3,
                                payload={"api": "LocationManager.requestLocationUpdates", "count": 8, "window_minutes": 1}))
        return EngineResult(
            findings=findings, evidence_files=evs,
            stats={"pages": pages, "pages_covered": len(pages), "scenarios": 3,
                   "current_page": "隐私政策页"},
        )


class MockMonitorEngine:
    """模拟 Frida + 流量监控：同意前 API 调用 + 第三方传输。"""
    def run(self, ctx: DetectionContext) -> EngineResult:
        findings = []
        evs = []
        call = {
            "api": "android.telephony.TelephonyManager.getDeviceId",
            "time": datetime.utcnow().isoformat(), "before_consent": True,
            "stack": "com.demo.app.MainActivity.onCreate(MainActivity.java:42)",
        }
        evs.append(_write_evidence(ctx.data_dir, "callstack", "getDeviceId_before_consent.json", call))
        findings.append(Finding(kind="api_called_before_consent", category=2, payload={**call, "api_name": call["api"]}))
        traffic = {
            "url": "https://track.example-overseas.com/collect",
            "fields": ["imei", "oaid", "location"], "domain": "track.example-overseas.com",
            "overseas": True,
        }
        evs.append(_write_evidence(ctx.data_dir, "traffic", "overseas_transfer.json", traffic))
        findings.append(Finding(kind="overseas_transfer", category=4, payload=traffic))
        if ctx.apk.sdk_list:
            findings.append(Finding(kind="sdk_upload_undisclosed", category=4,
                                    payload={"sdk": ctx.apk.sdk_list[0]["name"], "url": "https://ulogs.umeng.com/api"}))
        # 超出授权范围收集（对照已出具报告真实案例：MAC 地址、Android ID）
        findings.append(Finding(kind="collected_beyond_authorization", category=2,
                                payload={"collected": ["MAC地址", "Android ID"], "page": "首页"}))
        return EngineResult(findings=findings, evidence_files=evs, stats={"api_calls": 1, "traffic": 1})
```

- [ ] **Step 4: 实现管线编排 workflow**

`agent/agent_core/workflow.py`：

```python
import time
from datetime import datetime
from pathlib import Path

from agent.agent_core.task_manager import set_status
from agent.common.logger import get_logger
from agent.detection_engines.base import DetectionContext
from agent.detection_engines.mock_engine import MockExplorerEngine, MockMonitorEngine, MockStaticEngine
from backend.app.config import PROJECT_ROOT, config
from backend.app.db import SessionLocal
from backend.app.models import DetectionTask

logger = get_logger("workflow")

STAGES = ["preparing", "installing", "static_analysis", "traversing", "analyzing", "reporting"]


def run_task(task_id: int) -> None:
    """跑完整检测管线：Mock 引擎 → 规则匹配 → 评分 → 报告 → 落库。"""
    with SessionLocal() as s:
        task = s.query(DetectionTask).filter_by(id=task_id).first()
        if task is None:
            logger.error("任务不存在：%s", task_id)
            return
        apk = task.apk
        if task.status not in ("queued", "preparing"):
            logger.info("任务 %s 状态为 %s，跳过", task_id, task.status)
            return
        cfg = config
        data_dir = PROJECT_ROOT / cfg["storage"]["evidence_dir"] / str(task_id)
        ctx = DetectionContext(task=task, apk=apk, cfg=cfg, data_dir=data_dir)
        try:
            for stage in STAGES:
                if stage != task.status:  # 已被 worker 领取（preparing）时跳过自环
                    set_status(s, task, stage)
                task.progress = {"stage": stage, "percent": STAGES.index(stage) * 100 // len(STAGES)}
                s.commit()
                time.sleep(cfg["mock_pipeline"]["stage_delay_seconds"])

            # 运行引擎（V1.0：静态结果来自上传解析 + Mock 遍历/监控）
            results = [MockStaticEngine().run(ctx), MockExplorerEngine().run(ctx), MockMonitorEngine().run(ctx)]
            findings = [f for r in results for f in r.findings]
            evidence_files = [e for r in results for e in r.evidence_files]
            stats = {k: v for r in results for k, v in r.stats.items()}
            task.pages_covered = int(stats.get("pages_covered", 0))
            task.scenarios_triggered = int(stats.get("scenarios", 0))
            task.current_page = stats.get("current_page")

            from agent.rule_engine.rule_matcher import match_rules
            from agent.rule_engine.rule_loader import load_rules
            from agent.rule_engine.scoring import compute_score
            from agent.rule_engine.report_generator import generate_report

            rules = load_rules()
            matched = match_rules(rules, findings)
            score, breakdown = compute_score(matched, rules)
            generate_report(s, task, apk, matched, score, breakdown, evidence_files, ctx)
            set_status(s, task, "completed")
        except Exception as e:
            logger.exception("任务 %s 失败", task_id)
            try:
                set_status(s, task, "failed", reason=f"{type(e).__name__}: {e}")
            except Exception:
                task.status = "failed"
                task.failure_reason = f"{type(e).__name__}: {e}"
                task.finished_at = datetime.utcnow()
                s.commit()
```

> 注：`generate_report` 的签名在 Task 7 中定义并实现；Task 5 提交时 Task 7 尚未存在——**按顺序执行时先跳过 `test_mock_pipeline_marks_failed_on_missing_apk` 中 pdf 断言**，实际执行时 Task 5、6、7 连续完成后统一跑测试（执行说明见 Task 7 末尾）。

`worker/main.py`：

```python
import threading
import time

from agent.agent_core.task_manager import claim_next_task
from agent.agent_core.workflow import run_task
from agent.common.logger import get_logger
from backend.app.config import config
from backend.app.db import SessionLocal

logger = get_logger("worker")


def worker_loop() -> None:
    running: dict[int, threading.Thread] = {}
    while True:
        finished = [tid for tid, th in running.items() if not th.is_alive()]
        for tid in finished:
            del running[tid]
        while len(running) < config["worker"]["max_concurrent"]:
            with SessionLocal() as s:
                task_id = claim_next_task(s)
            if task_id is None:
                break
            logger.info("领取任务 %s，当前并发 %s", task_id, len(running) + 1)
            th = threading.Thread(target=run_task, args=(task_id,), daemon=True)
            th.start()
            running[task_id] = th
        time.sleep(config["worker"]["poll_interval_seconds"])


if __name__ == "__main__":
    worker_loop()
```

- [ ] **Step 5: Commit（workflow 与 mock 引擎，暂不跑 pdf 断言）**

```bash
git add agent worker && git commit -m "feat: Mock 检测管线（静态/遍历/监控三引擎）与 workflow 编排"
```

---

### Task 6: 规则引擎与评分（12 条规则）

**Files:**
- Create: `agent/rule_engine/__init__.py`、`agent/rule_engine/rule_loader.py`、`agent/rule_engine/rule_matcher.py`、`agent/rule_engine/scoring.py`
- Create: `agent/config/rules/identification_method_rules.yaml`
- Create: `backend/tests/test_rules.py`、`backend/tests/test_scoring.py`

**Interfaces:**
- Consumes: `Finding`（Task 5）
- Produces:
  - `agent.rule_engine.rule_loader.load_rules(path=None) -> list[Rule]`（pydantic：Rule{rule_id,rule_name,category,legal_basis,risk_level,conditions,evidence_fields,weight,suggestion}）
  - `agent.rule_engine.rule_matcher.match_rules(rules, findings) -> list[MatchedViolation]`（MatchedViolation{rule,finding,payload}）
  - `agent.rule_engine.scoring.compute_score(matched, rules) -> tuple[int, dict]`（0–100 与明细）

- [ ] **Step 1: 写失败的测试**

`backend/tests/test_rules.py`：

```python
import pytest

from agent.common.exceptions import RuleConfigError
from agent.detection_engines.base import Finding
from agent.rule_engine.rule_loader import load_rules
from agent.rule_engine.rule_matcher import match_rules


# 七大类 ↔ 《认定方法》条号映射（官方条文 + 已出具报告模板实证）
CATEGORY_TO_ARTICLE = {1: "一", 2: "三", 3: "四", 4: "五", 5: "六", 6: "六", 7: "二"}


def test_loads_14_rules_covering_7_categories():
    rules = load_rules()
    assert len(rules) == 14
    assert {r.category for r in rules} == {1, 2, 3, 4, 5, 6, 7}  # 七大类一条都不能少（含官方第二条）
    for r in rules:
        assert r.rule_id and r.legal_basis and r.risk_level in ("高", "中", "低") and r.weight > 0
        assert r.category_name  # 每类必须有类别名称，违规输出显式标注「第N类」
        assert f"第{CATEGORY_TO_ARTICLE[r.category]}条" in r.legal_basis  # 法规条款须具体到正确的第几条
        assert "第（" in r.legal_basis and "）点" in r.legal_basis  # 须具体到第（X）点


def test_rule_fires_on_matching_finding():
    rules = load_rules()
    f = Finding(kind="policy_missing", category=1, payload={})
    matched = match_rules(rules, [f])
    assert len(matched) == 1
    assert matched[0].rule.rule_id == "RULE_1_1"


def test_rule_requires_all_conditions():
    rules = load_rules()
    f = Finding(kind="frequent_collection", category=3,
                payload={"count": 2, "window_minutes": 1})  # 未超阈值
    assert match_rules(rules, [f]) == []


def test_unknown_operator_raises():
    from agent.rule_engine.rule_matcher import _eval_condition
    with pytest.raises(RuleConfigError):
        _eval_condition({"field": "x", "op": "explode", "value": 1}, {"x": 1})
```

`backend/tests/test_scoring.py`：

```python
from agent.detection_engines.base import Finding
from agent.rule_engine.rule_loader import load_rules
from agent.rule_engine.rule_matcher import match_rules
from agent.rule_engine.scoring import compute_score


def test_clean_app_scores_100():
    rules = load_rules()
    score, breakdown = compute_score([], rules)
    assert score == 100
    assert breakdown["total_deduction"] == 0


def test_score_deduction_and_floor():
    rules = load_rules()
    findings = [Finding(kind=r.conditions[0]["field"], category=r.category,
                        payload=_payload_for(r)) for r in rules]
    matched = match_rules(rules, findings)
    score, breakdown = compute_score(matched, rules)
    assert score < 100
    assert breakdown["total_deduction"] == sum(m.rule.weight for m in matched)
    # 全部违规扣到 0
    assert compute_score(matched, rules, base=10)[0] == 0


def _payload_for(rule):
    return {c["field"]: c["value"] for c in rule.conditions}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python -m pytest backend/tests/test_rules.py backend/tests/test_scoring.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写规则配置（12 条）**

`agent/config/rules/identification_method_rules.yaml`：

```yaml
# 对标《App违法违规收集使用个人信息行为认定方法》六类违规
# V1.0：每类 2 条核心规则（共 12 条），六大类一条都不能少；V1.1 起逐步扩至每类 ≥5 条
# conditions: 全部满足才命中；op 支持 eq/ne/gt/gte/lt/lte/contains/not_exists
# 条号映射（以《认定方法》官方条文与已出具报告模板为准，用户模板实证）：
#   第1类 未公开收集使用规则 → 第一条；第2类 未经用户同意收集使用个人信息 → 第三条；
#   第3类 违反必要原则 → 第四条；第4类 未经同意向他人提供个人信息 → 第五条；
#   第5类 未提供删除/更正功能 → 第六条（一）～（三）；第6类 未公布投诉举报方式 → 第六条（四）
# 违规输出须显式标注「第N类（类别名），违反《认定方法》第X条第（X）点」
score_base: 100
category_names:
  1: 未公开收集使用规则
  2: 未经用户同意收集使用个人信息
  3: 违反必要原则，收集与其提供的服务无关的个人信息
  4: 未经同意向他人提供个人信息
  5: 未按法律规定提供删除或者更正个人信息功能
  6: 未公布投诉、举报方式等信息
  7: 未明示收集使用个人信息的目的、方式和范围
rules:
  # ── 一、未公开收集使用规则 ──
  - rule_id: RULE_1_1
    rule_name: 未公开收集使用规则（无隐私政策）
    category: 1
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第一条第（一）点
    risk_level: 高
    weight: 15
    conditions:
      - {field: policy_missing, op: eq, value: true}
    evidence_fields: [policy]
    suggestion: 应在 App 首次启动或设置页显著位置公布隐私政策（收集使用规则），并取得用户同意。
  - rule_id: RULE_1_2
    rule_name: 隐私政策入口不可达
    category: 1
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第一条第（三）点
    risk_level: 中
    weight: 8
    conditions:
      - {field: policy_entry_not_found, op: eq, value: true}
    evidence_fields: [screenshot]
    suggestion: 隐私政策入口应常驻设置页并可正常打开，避免仅在首次启动展示。

  # ── 二、未经用户同意收集个人信息 ──
  - rule_id: RULE_2_1
    rule_name: 同意前调用敏感隐私 API
    category: 2
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第三条第（一）点
    risk_level: 高
    weight: 15
    conditions:
      - {field: api_called_before_consent, op: eq, value: true}
    evidence_fields: [callstack, timeline]
    suggestion: 所有个人信息收集应在用户首次明确同意之后进行，检查启动流程中的 SDK 初始化时机。
  - rule_id: RULE_2_2
    rule_name: 实际收集的个人信息超出用户授权范围
    category: 2
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第三条第（三）点
    risk_level: 高
    weight: 15
    conditions:
      - {field: collected_beyond_authorization, op: eq, value: true}
    evidence_fields: [callstack, traffic]
    suggestion: App 实际收集的个人信息（如 MAC 地址、Android ID）不得超出用户授权范围，超出部分应停止采集或单独取得用户同意。

  # ── 三、违反必要原则收集无关信息 ──
  - rule_id: RULE_3_1
    rule_name: 申请权限与所属行业必要权限不匹配
    category: 3
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第四条第（一）点
    risk_level: 中
    weight: 8
    conditions:
      - {field: permission_industry_mismatch, op: eq, value: true}
    evidence_fields: [permission_list]
    suggestion: 仅申请与业务功能直接相关的权限，删除与核心功能无关的危险权限。
  - rule_id: RULE_3_2
    rule_name: 超频次收集个人信息
    category: 3
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第四条第（四）点
    risk_level: 中
    weight: 8
    conditions:
      - {field: frequent_collection, op: eq, value: true}
      - {field: count, op: gte, value: 5}
    evidence_fields: [timeline]
    suggestion: 限制敏感信息的采集频次，仅在用户主动触发对应功能时采集。

  # ── 四、未经同意向他人提供个人信息 ──
  - rule_id: RULE_4_1
    rule_name: 向境外传输个人信息
    category: 4
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第五条第（二）点
    risk_level: 高
    weight: 15
    conditions:
      - {field: overseas_transfer, op: eq, value: true}
    evidence_fields: [traffic]
    suggestion: 个人信息原则上应境内存储，确需出境应通过安全评估并单独取得用户同意。
  - rule_id: RULE_4_2
    rule_name: 第三方 SDK 传输数据未在隐私政策披露
    category: 4
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第五条第（一）点
    risk_level: 高
    weight: 15
    conditions:
      - {field: sdk_upload_undisclosed, op: eq, value: true}
    evidence_fields: [traffic, sdk_list]
    suggestion: 在隐私政策第三方共享清单中披露该 SDK 的名称、收集信息与用途。

  # ── 五、未提供删除/更正个人信息功能 ──
  - rule_id: RULE_5_1
    rule_name: 未提供账号注销入口
    category: 5
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第六条第（一）点
    risk_level: 中
    weight: 8
    conditions:
      - {field: no_delete_entry, op: eq, value: true}
    evidence_fields: [screenshot]
    suggestion: 在设置/个人中心提供注销账号入口，注销后及时删除或匿名化个人信息。
  - rule_id: RULE_5_2
    rule_name: 注销流程设置不合理条件
    category: 5
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第六条第（二）点
    risk_level: 中
    weight: 8
    conditions:
      - {field: delete_obstacle, op: eq, value: true}
    evidence_fields: [screenshot]
    suggestion: 注销不得要求线下客服办理或收取费用，不得要求提供超出必要范围的信息。

  # ── 六、未公布投诉举报方式 ──
  - rule_id: RULE_6_1
    rule_name: 未公布投诉举报渠道
    category: 6
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第六条第（五）点
    risk_level: 低
    weight: 3
    conditions:
      - {field: no_complaint_channel, op: eq, value: true}
    evidence_fields: [screenshot]
    suggestion: 在帮助页/关于页公布客服电话或邮箱等投诉举报渠道。
  - rule_id: RULE_6_2
    rule_name: 公布的联系方式格式无效
    category: 6
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第六条第（五）点
    risk_level: 低
    weight: 3
    conditions:
      - {field: invalid_contact_format, op: eq, value: true}
    evidence_fields: [screenshot]
    suggestion: 核对公布的客服电话位数与邮箱格式，确保渠道真实可用。

  # ── 七、未明示收集使用个人信息的目的、方式和范围（官方第二条，用户补充） ──
  - rule_id: RULE_7_1
    rule_name: 未逐一列出收集使用个人信息的目的、方式、范围
    category: 7
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第二条第（一）点
    risk_level: 中
    weight: 8
    conditions:
      - {field: purpose_not_disclosed, op: eq, value: true}
    evidence_fields: [policy]
    suggestion: 在隐私政策中逐一列出（含第三方 SDK）收集使用个人信息的目的、方式和范围。
  - rule_id: RULE_7_2
    rule_name: 申请可收集个人信息权限时未同步告知目的
    category: 7
    legal_basis: 《App违法违规收集使用个人信息行为认定方法》第二条第（三）点
    risk_level: 中
    weight: 8
    conditions:
      - {field: permission_purpose_not_informed, op: eq, value: true}
    evidence_fields: [screenshot]
    suggestion: 在申请打开可收集个人信息的权限时，同步、明确告知用户收集目的。
```

- [ ] **Step 4: 实现规则加载/匹配/评分**

`agent/rule_engine/rule_loader.py`：

```python
from pathlib import Path

import yaml
from pydantic import BaseModel

from agent.common.exceptions import RuleConfigError
from backend.app.config import PROJECT_ROOT

_RULES_PATH = PROJECT_ROOT / "agent" / "config" / "rules" / "identification_method_rules.yaml"


class Condition(BaseModel):
    field: str
    op: str
    value: object


class Rule(BaseModel):
    rule_id: str
    rule_name: str
    category: int
    category_name: str = ""  # 由 load_rules 从 category_names 映射填充
    legal_basis: str
    risk_level: str
    weight: int
    conditions: list[Condition]
    evidence_fields: list[str]
    suggestion: str


class RuleSet(BaseModel):
    score_base: int = 100
    category_names: dict[int, str] = {}
    rules: list[Rule]


_CATEGORY_NAMES = {
    1: "未公开收集使用规则",
    2: "未经用户同意收集使用个人信息",
    3: "违反必要原则，收集与其提供的服务无关的个人信息",
    4: "未经同意向他人提供个人信息",
    5: "未按法律规定提供删除或者更正个人信息功能",
    6: "未公布投诉、举报方式等信息",
    7: "未明示收集使用个人信息的目的、方式和范围",
}


def load_rules(path: Path | None = None) -> list[Rule]:
    p = path or _RULES_PATH
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    try:
        ruleset = RuleSet.model_validate(data)
    except Exception as e:
        raise RuleConfigError(f"规则配置解析失败：{e}") from e
    # 类别名称：优先 YAML 内 category_names，缺省用内置映射兜底（六大类一条都不能少）
    names = {int(k): v for k, v in ruleset.category_names.items()} or _CATEGORY_NAMES
    for rule in ruleset.rules:
        rule.category_name = names.get(rule.category, f"第{rule.category}类")
    return ruleset.rules
```

`agent/rule_engine/rule_matcher.py`：

```python
from dataclasses import dataclass

from agent.common.exceptions import RuleConfigError
from agent.detection_engines.base import Finding
from agent.rule_engine.rule_loader import Condition, Rule

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "contains": lambda a, b: b in a if a is not None else False,
    "not_exists": lambda a, b: a is None,
}


@dataclass
class MatchedViolation:
    rule: Rule
    finding: Finding
    payload: dict


def _eval_condition(cond: dict, payload: dict) -> bool:
    op = _OPS.get(cond["op"])
    if op is None:
        raise RuleConfigError(f"不支持的操作符：{cond['op']}")
    try:
        return op(payload.get(cond["field"]), cond["value"])
    except TypeError:
        return False


def _findings_as_payloads(findings: list[Finding]) -> list[dict]:
    """展开：payload 平铺为顶层键 + kind 标记，供条件引用（如 frequent_collection_count）。"""
    out = []
    for f in findings:
        p = dict(f.payload)
        p.setdefault(f.kind, True)
        out.append(p)
    return out


def match_rules(rules: list[Rule], findings: list[Finding]) -> list[MatchedViolation]:
    payloads = _findings_as_payloads(findings)
    matched = []
    for rule in rules:
        for finding, p in zip(findings, payloads):
            if all(_eval_condition(c.model_dump(), p) for c in rule.conditions):
                matched.append(MatchedViolation(rule=rule, finding=finding, payload=p))
                break  # 一条规则命中一次即可
    return matched
```

`agent/rule_engine/scoring.py`：

```python
from agent.rule_engine.rule_matcher import MatchedViolation
from agent.rule_engine.rule_loader import Rule


def compute_score(matched: list[MatchedViolation], rules: list[Rule], base: int | None = None) -> tuple[int, dict]:
    base = base if base is not None else 100
    total = sum(m.rule.weight for m in matched)
    score = max(0, base - total)
    breakdown = {
        "base": base,
        "total_deduction": total,
        "items": [
            {"rule_id": m.rule.rule_id, "rule_name": m.rule.rule_name,
             "category": m.rule.category, "risk_level": m.rule.risk_level,
             "weight": m.rule.weight}
            for m in matched
        ],
    }
    return score, breakdown
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv\Scripts\python -m pytest backend/tests/test_rules.py backend/tests/test_scoring.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add agent/rule_engine agent/config/rules backend/tests && git commit -m "feat: 规则引擎（12 条 YAML 规则）、条件匹配与合规评分"
```

---

### Task 7: 报告生成与 PDF 导出

**Files:**
- Create: `agent/rule_engine/report_generator.py`、`agent/rule_engine/templates/report.html`
- Create: `backend/app/services/report_service.py`
- Create: `backend/tests/test_report_pdf.py`

**Interfaces:**
- Consumes: `MatchedViolation`（Task 6）、`DetectionTask/APKFile/Violation/Evidence/Report`（Task 2）、`compute_score`（Task 6）
- Produces: `agent.rule_engine.report_generator.generate_report(session, task, apk, matched, score, breakdown, evidence_files, ctx) -> Report`（写违规/证据/报告行 + HTML + PDF 文件）

- [ ] **Step 1: 写失败的测试**

`backend/tests/test_report_pdf.py`：

```python
from pathlib import Path

from agent.rule_engine.report_generator import render_pdf


def test_render_pdf_creates_valid_pdf(tmp_path):
    html = tmp_path / "r.html"
    html.write_text("<html><head><meta charset='utf-8'></head><body><h1>检测报告</h1><p>测试</p></body></html>", encoding="utf-8")
    out = tmp_path / "r.pdf"
    render_pdf(html, out)
    assert out.exists() and out.stat().st_size > 500
    assert out.read_bytes()[:4] == b"%PDF"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python -m pytest backend/tests/test_report_pdf.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现报告生成器**

`agent/rule_engine/report_generator.py`：

```python
import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from agent.rule_engine.rule_matcher import MatchedViolation
from backend.app.config import PROJECT_ROOT, config
from backend.app.models import Evidence, Report, Violation

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_report(session: Session, task, apk, matched: list[MatchedViolation],
                    score: int, breakdown: dict, evidence_files: list[dict], ctx) -> Report:
    """写入违规/证据/报告，渲染 HTML 并导出 PDF。"""
    # 1. 违规 + 证据落库（每条违规 100% 附证据）
    now = datetime.utcnow()
    for i, m in enumerate(matched):
        v = Violation(
            task_id=task.id, category=m.rule.category, category_name=m.rule.category_name,
            rule_id=m.rule.rule_id,
            description=m.rule.rule_name, legal_basis=m.rule.legal_basis,
            risk_level=m.rule.risk_level, page=m.payload.get("page"),
            occurred_at=now, remediation_suggestion=m.rule.suggestion,
            detail=m.payload,
        )
        session.add(v)
        session.flush()
        # 证据归属：把引擎证据文件全量挂到每条违规（V1.0 mock 简化；真实引擎按 evidence_fields 精确挂载）
        for ev in evidence_files:
            rel = Path(ev["path"]).relative_to(PROJECT_ROOT) if Path(ev["path"]).is_absolute() else Path(ev["path"])
            session.add(Evidence(violation_id=v.id, type=ev["type"], file_path=str(rel), meta=ev["meta"]))

    # 2. 汇总 + 评分
    summary = {
        "total": len(matched),
        "by_risk": {"高": 0, "中": 0, "低": 0},
        "by_category": {str(c): 0 for c in range(1, 8)},
    }
    for m in matched:
        summary["by_risk"][m.rule.risk_level] += 1
        summary["by_category"][str(m.rule.category)] += 1
    report_no = f"RPT-{now.strftime('%Y%m%d')}-{task.id:04d}"

    # 3. HTML + PDF
    export_dir = PROJECT_ROOT / config["storage"]["export_dir"]
    export_dir.mkdir(parents=True, exist_ok=True)
    html_path = export_dir / f"{report_no}.html"
    pdf_path = export_dir / f"{report_no}.pdf"
    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("report.html")
    # 为每条违规挂载截图证据（file:// URI，Chromium 可直接渲染；SVG/PNG 均可）
    screenshots = [e["path"] for e in evidence_files if e["type"] == "screenshot"]
    for m in matched:
        m.screenshots = [Path(p).resolve().as_uri() for p in screenshots]
    html_path.write_text(tpl.render(
        report_no=report_no, task=task, apk=apk, score=score, breakdown=breakdown,
        summary=summary, matched=matched, now=now,
        header=config["report"].get("header") or {},
    ), encoding="utf-8")
    render_pdf(html_path, pdf_path, channel=config["report"].get("pdf_channel"))

    report = Report(task_id=task.id, score=score, weight_breakdown=breakdown,
                    summary=summary, report_no=report_no,
                    pdf_path=str(pdf_path.relative_to(PROJECT_ROOT)))
    session.add(report)
    session.commit()
    return report


def render_pdf(html_path: Path, out_path: Path, channel: str | None = "msedge") -> None:
    """HTML → PDF。channel 优先系统 Edge/Chrome，失败回退 playwright 自带 chromium。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel=channel) if channel else p.chromium.launch()
        except Exception:
            browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.as_uri())
        page.pdf(path=str(out_path), format="A4", print_background=True)
        browser.close()
```

`agent/rule_engine/templates/report.html`（结构对齐用户提供的检测报告模板：封面 → 评估对象基本信息 → 评估结果问题列表 → 评估参考范围）：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{{ report_no }} 检测报告</title>
<style>
  body { font-family: "Microsoft YaHei", "SimSun", sans-serif; margin: 40px; color: #222; }
  .cover { text-align: center; margin-top: 80px; }
  .cover h1 { font-size: 32px; letter-spacing: 10px; }
  .cover table { margin: 48px auto; border-collapse: collapse; font-size: 15px; }
  .cover td { border: 1px solid #444; padding: 10px 32px; }
  .cover .label { background: #f0f0f0; font-weight: 600; }
  .page-break { page-break-before: always; }
  h2.doc-title { text-align: center; font-size: 22px; margin: 24px 0; }
  h3 { font-size: 16px; margin: 20px 0 10px; }
  table.info { width: 100%; border-collapse: collapse; font-size: 14px; }
  table.info th, table.info td { border: 1px solid #444; padding: 8px 10px; text-align: left; }
  table.info th { background: #f0f0f0; width: 120px; }
  .issue { margin: 20px 0; }
  .issue h4 { font-size: 15px; border-left: 4px solid #c0392b; padding-left: 8px; margin: 16px 0 6px; }
  .issue p { margin: 6px 0; font-size: 14px; line-height: 1.7; }
  .issue img { max-width: 100%; border: 1px solid #ddd; }
  .suggestion { background: #fdf6e3; padding: 8px 10px; }
  .refs p { font-size: 13px; line-height: 1.9; margin: 4px 0; }
</style>
</head>
<body>

<!-- 封面 -->
<div class="cover">
  <h1>检 测 报 告</h1>
  <table>
    <tr><td class="label">软件名称</td><td>{{ apk.app_name or apk.filename }}</td></tr>
    <tr><td class="label">软件版本</td><td>{{ apk.version_name or '—' }}</td></tr>
    <tr><td class="label">受检单位</td><td>{{ header.subject_org or '' }}</td></tr>
    <tr><td class="label">检测单位</td><td>{{ header.test_org or '' }}</td></tr>
    <tr><td class="label">委托单位</td><td>{{ header.entrust_org or '' }}</td></tr>
    <tr><td class="label">检测时间</td><td>{{ now.strftime('%Y-%m-%d') }}</td></tr>
  </table>
</div>

<!-- 正文 -->
<div class="page-break"></div>
<h2 class="doc-title">“{{ apk.app_name or apk.filename }}”个人信息合规检测报告</h2>

<h3>一、评估对象基本信息</h3>
<table class="info">
  <tr><th>App名称</th><td>{{ apk.app_name or '—' }}</td><th>版本</th><td>{{ apk.version_name or '—' }}</td></tr>
  <tr><th>包名</th><td>{{ apk.package_name or '—' }}</td><th>MD5值</th><td>{{ apk.md5 or '—' }}</td></tr>
  <tr><th>下载渠道</th><td></td><th>下载地址</th><td></td></tr>
  <tr><th>运营者名称</th><td></td><th>检测档位</th><td>{{ '快速模式' if task.mode == 'fast' else '深度模式' }}</td></tr>
</table>

<h3>二、评估结果</h3>
{% if matched %}
<p>经过评估，“{{ apk.app_name or apk.filename }}”App在处理个人信息活动以及个人信息保护的活动中，存在以下问题：</p>
{% for m in matched %}
<div class="issue">
  <h4>{{ loop.index }}、第{{ m.rule.category }}类 {{ m.rule.category_name }}</h4>
  <p><b>问题描述：</b>{{ m.rule.rule_name }}，违反{{ m.rule.legal_basis }}。</p>
  <p><b>证据截图：</b></p>
  {% for shot in m.screenshots %}
  <img src="{{ shot }}" />
  {% endfor %}
  <p class="suggestion"><b>修复建议：</b>{{ m.rule.suggestion }}</p>
</div>
{% endfor %}
{% else %}
<p>经过评估，未发现违反《App违法违规收集使用个人信息行为认定方法》的收集使用个人信息行为。</p>
{% endif %}

<h3>三、评估参考范围</h3>
<div class="refs">
  <p>《中华人民共和国网络安全法》（2025年10月28日第十四届全国人民代表大会常务委员会第十八次会议《关于修改〈中华人民共和国网络安全法〉的决定》修正）</p>
  <p>《中华人民共和国个人信息保护法》（2021年8月20日第十三届全国人民代表大会常务委员会第三十次会议通过）</p>
  <p>《个人信息保护合规审计管理办法》（国家互联网信息办公室令第18号）（国家互联网信息办公室）</p>
  <p>《常见类型移动互联网应用程序必要个人信息范围规定》（国信办秘字〔2021〕14号）（国家互联网信息办公室、工业和信息化部、公安部、国家市场监督管理总局）</p>
  <p>《App违法违规收集使用个人信息行为认定方法》（国信办秘字〔2019〕191号）（国家互联网信息办公室秘书局）</p>
  <p>《中央网信办、工业和信息化部、公安部关于开展2026年个人信息保护系列专项行动的公告》（中央网信办、工业和信息化部、公安部）</p>
  <p>《工业和信息化部关于开展纵深推进App侵害用户权益专项整治行动的通知》（工信部信管函〔2020〕164号）（中华人民共和国工业和信息化部）</p>
  <p>《工业和信息化部关于进一步提升移动互联网应用服务能力的通知》（工信部信管函〔2023〕26号）（中华人民共和国工业和信息化部）</p>
  <p>《工业和信息化部关于开展App侵害用户权益专项整治工作的通知》（工信部信管函〔2019〕337号）（中华人民共和国工业和信息化部）</p>
  <p>《工业和信息化部关于开展信息通信服务感知提升行动的通知》（工信部信管函〔2021〕292号）（中华人民共和国工业和信息化部）</p>
  <p>《信息安全技术 个人信息安全规范》（GB/T 35273-2020）（国家市场监督管理总局、国家标准化管理委员会）</p>
  <p>《信息安全技术 移动互联网应用程序（App）收集个人信息基本要求》（GB/T 41391-2022）（国家市场监督管理总局、国家标准化管理委员会）</p>
  <p>《App收集使用个人信息最小必要评估规范》（T/TAF 2020）（电信终端产业协会）</p>
  <p>《移动互联网应用程序（App）用户权益保护测评规范》（YD/T 4184，报批稿）（中华人民共和国工业和信息化部）</p>
  <p>《App用户权益保护测评规范》（T/TAF 2026）（电信终端产业协会）</p>
  <p>《移动智能终端与应用软件用户个人信息保护实施指南》（T/TAF 2020）（电信终端产业协会）</p>
</div>

<p style="font-size:11px;color:#888">报告编号：{{ report_no }}　本报告由 App 隐私合规自动化检测平台自动生成。</p>
</body>
</html>
```

`backend/app/services/report_service.py`：

```python
from backend.app.db import SessionLocal
from backend.app.models import Report, Violation


def get_report(task_id: int) -> tuple[Report, list[Violation]]:
    with SessionLocal() as s:
        report = s.query(Report).filter_by(task_id=task_id).one()
        violations = s.query(Violation).filter_by(task_id=task_id).all()
        return report, violations
```

- [ ] **Step 4: 跑测试确认通过（含 Task 5 的全部测试）**

Run: `.venv\Scripts\python -m pytest backend/tests/test_report_pdf.py backend/tests/test_workflow.py -v`
Expected: 3 passed（若 msedge channel 不可用，`render_pdf` 回退 chromium；若回退也失败，先跑 `playwright install chromium` 再跑）

- [ ] **Step 5: Commit**

```bash
git add agent/rule_engine backend/app/services && git commit -m "feat: 报告生成（HTML 模板 + Playwright PDF 导出）与证据落库"
```

---

### Task 8: FastAPI API 路由

**Files:**
- Create: `backend/app/api/__init__.py`、`backend/app/api/apk.py`、`backend/app/api/task.py`、`backend/app/api/report.py`
- Create: `backend/app/schemas/__init__.py`、`backend/app/schemas/apk.py`、`backend/app/schemas/task.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `apk_service / task_service / report_service`（Task 3/4/7）、`init_db`（Task 2）
- Produces: `backend.app.main.app`（FastAPI 实例，路由挂载 + 静态托管 frontend/dist）

- [ ] **Step 1: 写失败的测试**

`backend/tests/test_api.py`：

```python
import io

from fastapi.testclient import TestClient

from backend.app.main import app


def test_upload_invalid_file_returns_400_with_reason():
    import uuid
    client = TestClient(app)
    # 内容唯一：sha256 有唯一约束，重复上传同一内容会撞键
    payload = f"not an apk {uuid.uuid4()}".encode()
    resp = client.post("/api/apks", files={"file": ("fake.apk", payload, "application/octet-stream")})
    assert resp.status_code == 200  # 校验失败也入库（invalid 状态），见 apk_service 设计
    data = resp.json()
    assert data["parse_status"] == "invalid"
    assert "文件" in data["parse_message"]  # 校验失败原因（过小/非 zip/无清单）


def test_task_create_requires_parsed_apk():
    client = TestClient(app)
    resp = client.post("/api/tasks", json={"apk_id": 99999, "industry": "通用", "mode": "fast"})
    assert resp.status_code in (400, 404)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python -m pytest backend/tests/test_api.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 schemas 与路由**

`backend/app/schemas/apk.py`：

```python
from datetime import datetime

from pydantic import BaseModel


class APKOut(BaseModel):
    id: int
    filename: str
    sha256: str
    size_bytes: int
    parse_status: str
    parse_message: str | None = None
    app_name: str | None = None
    package_name: str | None = None
    version_name: str | None = None
    permissions: list | None = None
    sdk_list: list | None = None
    has_policy: bool = False
    uploaded_at: datetime

    class Config:
        from_attributes = True
```

`backend/app/schemas/task.py`：

```python
from datetime import datetime

from pydantic import BaseModel


class TaskCreate(BaseModel):
    apk_id: int
    industry: str = "通用"
    mode: str = "deep"


class TaskOut(BaseModel):
    id: int
    apk_id: int
    industry: str
    mode: str
    status: str
    progress: dict | None = None
    current_page: str | None = None
    pages_covered: int
    scenarios_triggered: int
    failure_reason: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    class Config:
        from_attributes = True
```

`backend/app/api/apk.py`：

```python
from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.app.schemas.apk import APKOut
from backend.app.services import apk_service

router = APIRouter(prefix="/api/apks", tags=["apk"])


@router.post("", response_model=APKOut)
def upload_apk(file: UploadFile = File(...)):
    return apk_service.save_apk(file)


@router.get("", response_model=list[APKOut])
def list_apks():
    return [_to_out(a) for a in apk_service.list_apks()]


@router.delete("/{apk_id}")
def delete_apk(apk_id: int):
    apk_service.delete_apk(apk_id)
    return {"ok": True}


def _to_out(a) -> APKOut:
    out = APKOut.model_validate(a)
    out.has_policy = bool(a.policy_raw)
    return out
```

`backend/app/api/task.py`：

```python
from fastapi import APIRouter, HTTPException, Query

from agent.common.exceptions import TaskStateError
from backend.app.schemas.task import TaskCreate, TaskOut
from backend.app.services import task_service

router = APIRouter(prefix="/api/tasks", tags=["task"])


@router.post("", response_model=TaskOut)
def create_task(body: TaskCreate):
    try:
        return task_service.create_task(body.apk_id, body.industry, body.mode)
    except TaskStateError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=list[TaskOut])
def list_tasks(status: str | None = Query(default=None)):
    return task_service.list_tasks(status)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int):
    try:
        return task_service.get_task(task_id)
    except Exception:
        raise HTTPException(status_code=404, detail="任务不存在")


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: int):
    try:
        return task_service.cancel_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/retry", response_model=TaskOut)
def retry_task(task_id: int):
    try:
        return task_service.retry_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
```

`backend/app/api/report.py`：

```python
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.app.config import PROJECT_ROOT
from backend.app.services import report_service

router = APIRouter(prefix="/api/reports", tags=["report"])


@router.get("/{task_id}")
def get_report(task_id: int):
    try:
        report, violations = report_service.get_report(task_id)
    except Exception:
        raise HTTPException(status_code=404, detail="报告不存在")
    return {
        "report_no": report.report_no, "score": report.score,
        "summary": report.summary, "weight_breakdown": report.weight_breakdown,
        "generated_at": report.generated_at,
        "violations": [
            {
                "id": v.id, "category": v.category, "category_name": v.category_name,
                "rule_id": v.rule_id,
                "description": v.description, "legal_basis": v.legal_basis,
                "risk_level": v.risk_level, "page": v.page,
                "suggestion": v.remediation_suggestion, "detail": v.detail,
            }
            for v in violations
        ],
    }


@router.get("/{task_id}/pdf")
def download_pdf(task_id: int):
    try:
        report, _ = report_service.get_report(task_id)
    except Exception:
        raise HTTPException(status_code=404, detail="报告不存在")
    path = PROJECT_ROOT / report.pdf_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    return FileResponse(path, filename=f"{report.report_no}.pdf", media_type="application/pdf")
```

`backend/app/main.py`：

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api import apk, report, task
from backend.app.db import init_db

app = FastAPI(title="App 隐私合规自动化检测平台", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # 开发期 vite
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

app.include_router(apk.router)
app.include_router(task.router)
app.include_router(report.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 生产构建产物托管（frontend/dist 存在时）
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python -m pytest backend/tests/test_api.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app && git commit -m "feat: FastAPI 路由（APK/任务/报告/PDF 下载）与入口"
```

---

### Task 9: 前端三页面（Vue 3）

**Files:**
- Create: `frontend/`（Vite 脚手架 + 以下文件）
  - `frontend/vite.config.js`（代理 /api → localhost:8000）
  - `frontend/src/main.js`、`frontend/src/App.vue`、`frontend/src/router.js`、`frontend/src/api.js`
  - `frontend/src/views/DetectHome.vue`、`frontend/src/views/TaskProgress.vue`、`frontend/src/views/ReportDetail.vue`

**Interfaces:**
- Consumes: API 路由（Task 8）
- Produces: `npm run build` 产物 `frontend/dist/`（FastAPI 静态托管）

- [ ] **Step 1: 脚手架**

```powershell
cd "d:\Detect illegal app"
npm create vite@latest frontend -- --template vue
cd frontend
npm install
npm install element-plus axios vue-router@4
```

- [ ] **Step 2: 配置与入口**

`frontend/vite.config.js`：

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
```

`frontend/src/api.js`：

```js
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })
export default api
```

`frontend/src/router.js`：

```js
import { createRouter, createWebHistory } from 'vue-router'
import DetectHome from './views/DetectHome.vue'
import TaskProgress from './views/TaskProgress.vue'
import ReportDetail from './views/ReportDetail.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: DetectHome },
    { path: '/tasks', component: TaskProgress },
    { path: '/report/:taskId', component: ReportDetail },
  ],
})
```

`frontend/src/main.js`：

```js
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'

createApp(App).use(router).use(ElementPlus).mount('#app')
```

`frontend/src/App.vue`：

```vue
<template>
  <el-container style="min-height: 100vh">
    <el-header style="border-bottom: 1px solid #eee; display: flex; align-items: center">
      <span style="font-size: 18px; font-weight: 600">App 隐私合规自动化检测平台</span>
      <el-menu mode="horizontal" :default-active="$route.path" router style="margin-left: 24px; border: none">
        <el-menu-item index="/">检测首页</el-menu-item>
        <el-menu-item index="/tasks">检测任务</el-menu-item>
      </el-menu>
    </el-header>
    <el-main><router-view /></el-main>
  </el-container>
</template>
```

- [ ] **Step 3: 检测首页**

`frontend/src/views/DetectHome.vue`：

```vue
<template>
  <div>
    <el-upload drag :auto-upload="false" accept=".apk" :limit="1" :on-change="onFile" style="margin-bottom: 20px">
      <div>拖拽或点击上传 APK（≤500MB）</div>
    </el-upload>
    <el-button type="primary" :disabled="!file" :loading="uploading" @click="upload">上传并解析</el-button>

    <el-table :data="apks" style="margin-top: 24px">
      <el-table-column prop="filename" label="文件名" />
      <el-table-column prop="app_name" label="应用名" />
      <el-table-column prop="package_name" label="包名" />
      <el-table-column label="解析状态" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.parse_status === 'success'" type="success">成功</el-tag>
          <el-tag v-else-if="row.parse_status === 'invalid'" type="danger" :title="row.parse_message">格式无效</el-tag>
          <el-tag v-else type="warning">{{ row.parse_status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="危险权限" width="100">
        <template #default="{ row }">{{ (row.permissions || []).length }} 项</template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button size="small" type="primary" :disabled="row.parse_status !== 'success'" @click="openCreate(row)">创建检测任务</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createVisible" title="创建检测任务" width="420px">
      <el-form label-width="90px">
        <el-form-item label="所属行业">
          <el-select v-model="form.industry">
            <el-option v-for="i in industries" :key="i" :label="i" :value="i" />
          </el-select>
        </el-form-item>
        <el-form-item label="检测档位">
          <el-radio-group v-model="form.mode">
            <el-radio value="fast">快速模式（约 30 分钟）</el-radio>
            <el-radio value="deep">深度模式（1–2 小时）</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="createTask">启动检测</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const router = useRouter()

const file = ref(null)
const uploading = ref(false)
const apks = ref([])
const createVisible = ref(false)
const industries = ['通用', '金融理财', '电商购物', '社交通讯', '工具', '医疗健康', '教育', '出行']
const form = ref({ industry: '通用', mode: 'deep', apkId: null })

function onFile(f) { file.value = f.raw }
async function upload() {
  uploading.value = true
  const fd = new FormData()
  fd.append('file', file.value)
  try {
    await api.post('/apks', fd)
    ElMessage.success('上传成功')
    load()
  } finally { uploading.value = false }
}
function openCreate(row) { form.value.apkId = row.id; createVisible.value = true }
async function createTask() {
  const r = await api.post('/tasks', { apk_id: form.value.apkId, industry: form.value.industry, mode: form.value.mode })
  createVisible.value = false
  ElMessage.success('检测任务已创建')
  router.push('/tasks')
}
async function load() { apks.value = (await api.get('/apks')).data }
onMounted(load)
</script>
```

- [ ] **Step 4: 任务进度页**

`frontend/src/views/TaskProgress.vue`：

```vue
<template>
  <div>
    <el-table :data="tasks">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="industry" label="行业" width="90" />
      <el-table-column prop="mode" label="档位" width="90" />
      <el-table-column label="阶段" width="220">
        <template #default="{ row }">
          <el-steps :active="stageIndex(row.status)" simple style="max-width: 460px">
            <el-step title="排队" /><el-step title="安装" /><el-step title="静态分析" />
            <el-step title="AI遍历" /><el-step title="报告" />
          </el-steps>
        </template>
      </el-table-column>
      <el-table-column prop="pages_covered" label="覆盖页面" width="90" />
      <el-table-column prop="scenarios_triggered" label="触发场景" width="90" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button v-if="row.status === 'completed'" size="small" type="primary" @click="$router.push(`/report/${row.id}`)">查看报告</el-button>
          <el-button v-if="row.status === 'failed'" size="small" @click="retry(row)">重跑</el-button>
          <el-button v-if="['queued','preparing','installing','static_analysis','traversing','analyzing','reporting'].includes(row.status)" size="small" type="danger" @click="cancel(row)">取消</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import api from '../api'

const tasks = ref([])
let timer = null
const STATUS_TEXT = { queued: '排队中', preparing: '环境准备', installing: '安装', static_analysis: '静态分析', traversing: 'AI遍历', analyzing: '数据分析', reporting: '生成报告', completed: '已完成', failed: '失败', canceled: '已取消' }
function statusText(s) { return STATUS_TEXT[s] || s }
function statusType(s) { return s === 'completed' ? 'success' : s === 'failed' ? 'danger' : s === 'canceled' ? 'info' : 'primary' }
function stageIndex(s) { const idx = ['queued','preparing','installing','static_analysis','traversing','analyzing','reporting'].indexOf(s); return idx < 0 ? 5 : idx }
async function load() { tasks.value = (await api.get('/tasks')).data }
async function retry(row) { await api.post(`/tasks/${row.id}/retry`); load() }
async function cancel(row) { await api.post(`/tasks/${row.id}/cancel`); load() }
onMounted(() => { load(); timer = setInterval(load, 3000) })
onUnmounted(() => clearInterval(timer))
</script>
```

- [ ] **Step 5: 报告详情页**

`frontend/src/views/ReportDetail.vue`：

```vue
<template>
  <div v-if="report">
    <el-card style="margin-bottom: 16px">
      <div style="display: flex; align-items: center; gap: 32px">
        <div>
          <div style="font-size: 14px; color: #888">合规评分</div>
          <div :style="{ fontSize: '44px', fontWeight: 700, color: scoreColor }">{{ report.score }}</div>
        </div>
        <div>
          <div style="font-size: 14px; color: #888">违规分布</div>
          <div>高风险 {{ report.summary.by_risk['高'] }} · 中风险 {{ report.summary.by_risk['中'] }} · 低风险 {{ report.summary.by_risk['低'] }}</div>
        </div>
        <div>
          <div style="font-size: 14px; color: #888">报告编号</div>
          <div>{{ report.report_no }}</div>
        </div>
        <el-button type="primary" @click="downloadPdf">导出 PDF</el-button>
      </div>
    </el-card>

    <el-table :data="report.violations" row-key="id">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div style="padding: 12px 24px">
            <p><b>法规依据：</b>{{ row.legal_basis }}</p>
            <p><b>发生页面：</b>{{ row.page || '—' }}</p>
            <p><b>检测详情：</b>{{ JSON.stringify(row.detail) }}</p>
            <el-alert type="warning" :closable="false" show-icon :title="'整改建议：' + row.suggestion" />
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="category" label="类别" width="200">
        <template #default="{ row }">第{{ row.category }}类 · {{ row.category_name }}</template>
      </el-table-column>
      <el-table-column prop="description" label="违规描述" />
      <el-table-column prop="risk_level" label="风险等级" width="100">
        <template #default="{ row }">
          <el-tag :type="row.risk_level === '高' ? 'danger' : row.risk_level === '中' ? 'warning' : 'success'">{{ row.risk_level }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api'

const route = useRoute()
const report = ref(null)
const scoreColor = computed(() => report.value.score >= 80 ? '#27ae60' : report.value.score >= 60 ? '#d35400' : '#c0392b')
async function load() { report.value = (await api.get(`/reports/${route.params.taskId}`)).data }
function downloadPdf() { window.open(`/api/reports/${route.params.taskId}/pdf`) }
onMounted(load)
</script>
```

- [ ] **Step 6: 构建冒烟**

Run: `cd frontend && npm run build`
Expected: 构建成功，产出 `frontend/dist/`（此后 FastAPI 自动托管）

- [ ] **Step 7: Commit**

```bash
git add frontend && git commit -m "feat: Vue3 三页面（检测首页/任务进度/报告详情）"
```

---

### Task 10: 启动脚本与端到端冒烟

**Files:**
- Create: `scripts/run_api.py`、`scripts/run_worker.py`、`backend/tests/smoke_e2e.py`
- Create: `README.md`

**Interfaces:**
- Consumes: 全部 Task 1–9
- Produces: 一键启动（`scripts/run_api.py` + `scripts/run_worker.py`）、冒烟脚本输出（可直接用于汇报测试情况）

- [ ] **Step 1: 启动脚本**

`scripts/run_api.py`：

```python
"""一键启动 API 服务：.venv/Scripts/python scripts/run_api.py"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=False)
```

`scripts/run_worker.py`：

```python
"""一键启动检测 Worker：.venv/Scripts/python scripts/run_worker.py"""
from worker.main import worker_loop

if __name__ == "__main__":
    worker_loop()
```

- [ ] **Step 2: 端到端冒烟脚本**

`backend/tests/smoke_e2e.py`：

```python
"""端到端冒烟：不走网络，直接跑服务层 + 管线，打印测试摘要。

用法：.venv/Scripts/python backend/tests/smoke_e2e.py
"""
import uuid

from agent.agent_core.workflow import run_task
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask, Evidence, Report, Violation


def smoke() -> dict:
    init_db()
    with SessionLocal() as s:
        apk = APKFile(
            filename="demo-tool.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=4096, parse_status="success",
            storage_path="data/apks/x.enc", app_name="演示工具App", package_name="com.demo.tool",
            version_name="1.0.0",
            permissions=["android.permission.READ_CONTACTS", "android.permission.ACCESS_FINE_LOCATION"],
            sdk_list=[{"name": "友盟", "collected": ["设备标识"]}],
            policy_raw=None,  # 无隐私政策 → 触发第 1 类违规
        )
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, industry="工具", mode="deep")
        s.add(task)
        s.commit()
        task_id = task.id

    run_task(task_id)

    with SessionLocal() as s:
        t = s.query(DetectionTask).filter_by(id=task_id).one()
        violations = s.query(Violation).filter_by(task_id=task_id).all()
        report = s.query(Report).filter_by(task_id=task_id).one()
        evidence_count = sum(s.query(Evidence).filter_by(violation_id=v.id).count() for v in violations)
        result = {
            "task_status": t.status,
            "pages_covered": t.pages_covered,
            "scenarios_triggered": t.scenarios_triggered,
            "violation_count": len(violations),
            "evidence_count": evidence_count,
            "score": report.score,
            "report_no": report.report_no,
            "pdf_exists": bool(report.pdf_path and (__import__('pathlib').Path(__file__).resolve().parents[2] / report.pdf_path).exists()),
        }
    return result


if __name__ == "__main__":
    r = smoke()
    print("=" * 50)
    print("端到端冒烟测试结果")
    print("=" * 50)
    for k, v in r.items():
        print(f"  {k}: {v}")
    ok = r["task_status"] == "completed" and r["violation_count"] >= 3 and r["pdf_exists"]
    print(f"结论: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)
```

- [ ] **Step 3: README**

`README.md`：

```markdown
# App 隐私合规自动化检测平台

对标《App违法违规收集使用个人信息行为认定方法》6 大类违规的自动化检测平台（V1.0 MVP）。
技术设计见 [docs/superpowers/specs/2026-08-14-app-privacy-compliance-platform-design.md](docs/superpowers/specs/2026-08-14-app-privacy-compliance-platform-design.md)。

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
```

- [ ] **Step 4: 跑全部测试 + 冒烟**

Run: `.venv\Scripts\python -m pytest backend/tests/ -v`
Expected: 全部 PASS（约 24 个用例）
Run: `.venv\Scripts\python backend/tests/smoke_e2e.py`
Expected: 冒烟 PASS，输出摘要（任务完成、违规 ≥3、PDF 存在）

- [ ] **Step 5: Commit**

```bash
git add scripts README.md backend/tests && git commit -m "feat: 一键启动脚本与端到端冒烟测试；README"
```

---

## 执行说明（Task 5 依赖注记）

Task 5 的 workflow 引用了 Task 6/7 才创建的 `rule_engine` 模块，因此执行顺序必须是 1→2→3→4→5→6→7→8→9→10，且 **Task 5 提交时不跑 `test_workflow.py`，待 Task 7 完成后统一跑** `backend/tests/test_workflow.py` 与 `backend/tests/test_report_pdf.py`（Task 7 Step 4 已覆盖）。
