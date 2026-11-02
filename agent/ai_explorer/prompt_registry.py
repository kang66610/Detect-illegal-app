"""版本化导航提示词注册表。

导航策略文本从代码常量外置为 ``agent/config/prompts/navigation.yaml``，
版本号与正文指纹同源：修改正文必须递增 YAML 中的 ``version``，
指纹由正文自动计算，用于审计事件与回放对比时识别"模型当时看到的策略"。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path

import yaml

from backend.app.config import PROJECT_ROOT

_PROMPTS_DIR = PROJECT_ROOT / "agent" / "config" / "prompts"
_NAVIGATION_PROMPT_PATH = _PROMPTS_DIR / "navigation.yaml"


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: str
    system_prompt: str
    fingerprint: str
    path: str


def _load_prompt(path: Path) -> PromptSpec:
    if not path.is_file():
        raise FileNotFoundError(
            f"提示词配置缺失：{path}。导航提示词已外置，请随仓库携带该文件。"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    body = str((data or {}).get("system_prompt") or "")
    if not body.strip():
        raise ValueError(f"提示词配置 {path} 缺少非空 system_prompt")
    version = str((data or {}).get("version") or "").strip()
    if not version:
        raise ValueError(f"提示词配置 {path} 缺少 version 字段；修改正文时必须递增版本")
    fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    return PromptSpec(
        name=path.stem,
        version=version,
        system_prompt=body,
        fingerprint=fingerprint,
        path=str(path),
    )


@lru_cache(maxsize=None)
def _cached_load(path_str: str) -> PromptSpec:
    return _load_prompt(Path(path_str))


def load_navigation_prompt() -> PromptSpec:
    return _cached_load(str(_NAVIGATION_PROMPT_PATH))
