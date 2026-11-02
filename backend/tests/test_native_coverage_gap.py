from types import SimpleNamespace
from pathlib import Path

from agent.detection_engines.base import DetectionContext
from agent.rule_engine.deferred_findings import collect_deferred_findings


def test_native_library_without_matching_java_api_is_coverage_gap(tmp_path: Path):
    callstack = tmp_path / "callstack"
    callstack.mkdir()
    (callstack / "frida-events.json").write_text(
        '{"events": [{"type": "native_load", "library": "foo", "time": 1}]}',
        encoding="utf-8",
    )
    ctx = DetectionContext(
        task=SimpleNamespace(industry="通用", mode="fast"),
        apk=SimpleNamespace(
            permissions=["android.permission.READ_PHONE_STATE"],
            native_libs=["lib/arm64-v8a/libfoo.so"],
            policy_raw=None,
            package_name="com.example.app",
        ),
        cfg={},
        data_dir=tmp_path,
    )
    ctx.runtime["traversal_termination"] = {"kind": "page_limit_reached"}
    findings, _ = collect_deferred_findings(ctx)
    assert ctx.runtime.get("native_coverage_gap") is True
    assert any("native" in gap.lower() or "native" in gap for gap in ctx.runtime.get("coverage_gaps", []))
    assert not any(finding.kind == "native_collection" for finding in findings)
