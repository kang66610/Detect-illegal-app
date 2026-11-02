"""分层契约：agent 只能通过两个适配模块接触 backend。

此前 agent 里散落 16 处 `from backend...`，谁也不知道边界在哪，也没法替换。
收敛之后用这条测试守住：新增的反向依赖会立刻失败，逼你走适配层。
"""
from __future__ import annotations

import re
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"

# 只有这两个地方允许知道 backend 的存在
ALLOWED = {
    "agent/common/settings.py",
    "agent/common/backend_ports.py",
}

BACKEND_IMPORT = re.compile(r"^\s*(?:from|import)\s+backend", re.M)


def _offenders() -> list[str]:
    offenders = []
    for path in AGENT_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(AGENT_DIR.parent).as_posix()
        if rel in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in BACKEND_IMPORT.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{rel}:{line}")
    return offenders


def test_agent_reaches_backend_only_through_the_adapter_modules():
    offenders = _offenders()
    assert offenders == [], (
        "agent 不允许直接依赖 backend，请改用 agent.common.settings（配置）"
        f"或 agent.common.backend_ports（持久化）：{offenders}"
    )


def test_adapter_modules_actually_export_what_agent_uses():
    """适配层不能变成空壳：配置和任务模型必须真的从这里能拿到。"""
    from agent.common import backend_ports, settings

    assert settings.PROJECT_ROOT == backend_ports.PROJECT_ROOT
    assert callable(backend_ports.delete_task_artifacts)
    assert callable(backend_ports.derive_server_audit_review_states)
    assert backend_ports.DetectionTask is not None
