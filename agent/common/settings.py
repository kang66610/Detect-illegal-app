"""配置与项目路径的唯一入口。

`agent` 里此前有 9 处直接 `from backend.app.config import ...`。配置本身
和 Web 框架无关，但读取入口分散会让"到底谁能改配置"变得模糊，也让
logger、静态分析这些底层模块莫名依赖上 backend 包。

轻量模块（logger / utils / sdk_detector / rule_loader 等）从这里取配置；
需要任务状态机或报告落库的模块走 `agent.common.backend_ports`。
"""
from __future__ import annotations

from backend.app.config import PROJECT_ROOT, config

__all__ = ["PROJECT_ROOT", "config"]
