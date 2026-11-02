"""Stage-local workflow operations with no database lifecycle ownership."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def run_static_analysis_stage(
    state: dict[str, Any], *, decrypt: Callable[[], Any], run_static: Callable[[], list[Any]],
) -> None:
    """Ensure the temporary APK exists, then append static engine results."""
    if state.get("decrypted_apk") is None:
        state["decrypted_apk"] = decrypt()
    state.setdefault("results", []).extend(run_static())


def run_reporting_stage(
    state: dict[str, Any], *, generate: Callable[..., None],
) -> None:
    """Render the report from the final accumulated pipeline state."""
    generate(
        state["session"], state["task"], state["apk"], state["matched"],
        state["score"], state["breakdown"], state["evidence"], state["ctx"],
    )
