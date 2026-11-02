import sys
from pathlib import Path
from types import SimpleNamespace

from agent.detection_engines.external_static import ExternalStaticAnalysisHub, FlowDroidAdapter


class _Runner:
    def __call__(self, command, timeout):
        output = Path(command[command.index("-o") + 1])
        output.write_text('<DataFlowResults><Result><Sink Statement="network"/><Source Statement="getImei"/></Result></DataFlowResults>', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class _NestedFlowDroidRunner:
    def __call__(self, command, timeout):
        output = Path(command[command.index("-o") + 1])
        output.write_text(
            '<DataFlowResults><Result><Sink Statement="network"/>'
            '<Sources><Source Statement="getAndroidId"/></Sources></Result></DataFlowResults>',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class _NoSourcesRunner:
    def __call__(self, command, timeout):
        return SimpleNamespace(returncode=1, stdout="", stderr="analysis\nNo sources found, aborting analysis")


class _CountingRunner(_Runner):
    def __init__(self):
        self.calls = 0

    def __call__(self, command, timeout):
        self.calls += 1
        return super().__call__(command, timeout)


def test_flowdroid_adapter_emits_taint_flow_evidence(tmp_path):
    apk = tmp_path / "demo.apk"; apk.write_bytes(b"apk")
    jar = tmp_path / "flowdroid.jar"; jar.write_bytes(b"jar")
    platforms = tmp_path / "platforms"; platforms.mkdir()
    sources = tmp_path / "SourcesAndSinks.txt"; sources.write_text("", encoding="utf-8")
    adapter = FlowDroidAdapter({"enabled": True, "jar_path": str(jar), "android_platforms": str(platforms), "sources_sinks": str(sources), "timeout_seconds": 30}, runner=_Runner())

    result = adapter.analyze(apk, tmp_path / "evidence")

    assert result.status == "completed"
    assert result.facts[0]["source"] == "getImei"
    assert result.evidence[0]["type"] == "taint_flow"


def test_flowdroid_reuses_completed_result_for_same_apk_and_analysis_configuration(tmp_path):
    apk = tmp_path / "demo.apk"; apk.write_bytes(b"same-apk")
    jar = tmp_path / "flowdroid.jar"; jar.write_bytes(b"jar")
    platforms = tmp_path / "platforms"; platforms.mkdir()
    sources = tmp_path / "SourcesAndSinks.txt"; sources.write_text("source -> sink", encoding="utf-8")
    runner = _CountingRunner()
    cfg = {
        "enabled": True, "jar_path": str(jar), "android_platforms": str(platforms),
        "sources_sinks": str(sources), "cache_dir": str(tmp_path / "static-cache"),
    }
    adapter = FlowDroidAdapter(cfg, runner=runner)

    first = adapter.analyze(apk, tmp_path / "task-1" / "flowdroid")
    second = adapter.analyze(apk, tmp_path / "task-2" / "flowdroid")

    assert runner.calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.facts == first.facts
    assert (tmp_path / "task-2" / "flowdroid" / "flowdroid-results.xml").is_file()


def test_flowdroid_cache_invalidates_when_source_sink_rules_change(tmp_path):
    apk = tmp_path / "demo.apk"; apk.write_bytes(b"same-apk")
    jar = tmp_path / "flowdroid.jar"; jar.write_bytes(b"jar")
    platforms = tmp_path / "platforms"; platforms.mkdir()
    sources = tmp_path / "SourcesAndSinks.txt"; sources.write_text("first rules", encoding="utf-8")
    runner = _CountingRunner()
    cfg = {
        "enabled": True, "jar_path": str(jar), "android_platforms": str(platforms),
        "sources_sinks": str(sources), "cache_dir": str(tmp_path / "static-cache"),
    }
    adapter = FlowDroidAdapter(cfg, runner=runner)

    adapter.analyze(apk, tmp_path / "task-1" / "flowdroid")
    sources.write_text("changed rules", encoding="utf-8")
    adapter.analyze(apk, tmp_path / "task-2" / "flowdroid")

    assert runner.calls == 2


def test_flowdroid_adapter_parses_nested_real_world_source_nodes(tmp_path):
    apk = tmp_path / "demo.apk"; apk.write_bytes(b"apk")
    jar = tmp_path / "flowdroid.jar"; jar.write_bytes(b"jar")
    platforms = tmp_path / "platforms"; platforms.mkdir()
    sources = tmp_path / "SourcesAndSinks.txt"; sources.write_text("", encoding="utf-8")
    adapter = FlowDroidAdapter({
        "enabled": True, "jar_path": str(jar), "android_platforms": str(platforms),
        "sources_sinks": str(sources),
    }, runner=_NestedFlowDroidRunner())

    result = adapter.analyze(apk, tmp_path / "evidence")

    assert result.facts == [{"source": "getAndroidId", "sink": "network"}]


def test_flowdroid_no_sources_is_inconclusive_not_clean_or_generic_failure(tmp_path):
    apk = tmp_path / "demo.apk"; apk.write_bytes(b"apk")
    jar = tmp_path / "flowdroid.jar"; jar.write_bytes(b"jar")
    platforms = tmp_path / "platforms"; platforms.mkdir()
    sources = tmp_path / "SourcesAndSinks.txt"; sources.write_text("", encoding="utf-8")
    result = FlowDroidAdapter({
        "enabled": True, "jar_path": str(jar), "android_platforms": str(platforms),
        "sources_sinks": str(sources),
    }, runner=_NoSourcesRunner()).analyze(apk, tmp_path / "evidence")

    assert result.status == "inconclusive"
    assert "不能据此判定无数据流" in result.error


def test_flowdroid_process_can_be_interrupted_by_pause_or_cancel():
    result = FlowDroidAdapter._run_interruptible(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout=10,
        should_stop=lambda: True,
    )

    assert result.returncode != 0
    assert "interrupted because task was paused or canceled" in result.stderr


def test_hub_preserves_each_adapter_status(tmp_path):
    hub = ExternalStaticAnalysisHub([FlowDroidAdapter({"enabled": False})])
    result = hub.run(SimpleNamespace(apk_path=tmp_path / "demo.apk", data_dir=tmp_path))
    assert result.stats["external_static"] == {"flowdroid": "not_available"}
