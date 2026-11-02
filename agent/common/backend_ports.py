"""agent → backend 的唯一适配点。

`agent` 被视为检测引擎包，理想上与 Web 框架无关；但它确实需要配置、
任务状态机、报告落库这些属于 backend 的能力。此前这些 import 散落在
10 个文件、16 处，谁也不知道边界在哪，也没法替换。

现在收敛到这里：

- agent 内部**只允许**从这个模块取后端能力；
- `grep -r "from backend" agent/` 应当只剩本文件的 import；
- 将来要把配置或持久化下沉成独立包，只需要改这一个文件，而不是 16 处。

`backend/app/services/` 里的 APK 加解密、证据 GC 等仍由 backend 自己调用，
不在 agent 的职责范围内。
"""
from __future__ import annotations

# 配置与路径
from backend.app.config import PROJECT_ROOT, config

# 任务持久化
from backend.app.db import SessionLocal
from backend.app.models import DetectionTask

# 报告落库所需的模型
from backend.app.models import Evidence, Report, Violation
from backend.app.models.review import ReviewItem, ServerAuditEvent

# 后端服务
from backend.app.services.artifact_cleanup import delete_task_artifacts


def derive_server_audit_review_states(events):
    """后端复核状态推导，延迟导入。

    ``backend.app.services.review_service`` 自身会 import
    ``agent.rule_engine.recognition_coverage``，在模块顶层导入它就会形成
    agent → backend → agent 的循环。这里保持函数内导入，把循环挡在调用期。
    """
    from backend.app.services.review_service import (
        derive_server_audit_review_states as _impl,
    )

    return _impl(events)


__all__ = [
    "PROJECT_ROOT",
    "config",
    "SessionLocal",
    "DetectionTask",
    "Evidence",
    "Report",
    "Violation",
    "ReviewItem",
    "ServerAuditEvent",
    "delete_task_artifacts",
    "derive_server_audit_review_states",
]
