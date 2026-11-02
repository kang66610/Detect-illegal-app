from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Finding:
    """引擎产出的检测发现，供规则引擎匹配。kind 为规则条件引用的键。"""
    kind: str
    category: int  # 1..6，对应《认定方法》第一至第六条
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
    # workflow 会将加密 APK 解密到该临时路径，任务结束后立即删除。
    apk_path: Path | None = None
    # 在引擎间传递本次运行的短生命周期状态（如 Frida 会话、是否已取得同意）。
    runtime: dict = field(default_factory=dict)


class DetectionEngine(Protocol):
    def run(self, ctx: DetectionContext) -> EngineResult: ...
