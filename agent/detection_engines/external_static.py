"""Optional static-analysis adapters behind one deep integration seam."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from agent.detection_engines.base import EngineResult
from agent.common.event_log import record_event


@dataclass
class AdapterResult:
    name: str
    status: str
    facts: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    error: str = ""
    cache_hit: bool = False


class FlowDroidAdapter:
    name = "flowdroid"
    CACHE_SCHEMA_VERSION = 1

    def __init__(self, cfg: dict, runner=None):
        self.cfg = cfg
        self.runner = runner

    @staticmethod
    def _run_interruptible(command, timeout: int, should_stop=None):
        """Run Java without an uninterruptible multi-minute subprocess call."""
        started = time.monotonic()
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, text=True)
            interrupted = False
            timed_out = False
            while process.poll() is None:
                if should_stop and should_stop():
                    interrupted = True
                    process.terminate()
                    break
                if time.monotonic() - started >= timeout:
                    timed_out = True
                    process.terminate()
                    break
                time.sleep(0.5)
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            log.seek(0)
            output = log.read()
        if interrupted:
            output += "\nFlowDroid interrupted because task was paused or canceled"
        elif timed_out:
            output += f"\nFlowDroid timed out after {timeout} seconds"
        return subprocess.CompletedProcess(command, process.returncode or (1 if interrupted or timed_out else 0), "", output)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _platforms_signature(platforms: Path) -> list[dict]:
        """Fingerprint the installed Android API set without hashing GBs of SDK files."""
        rows = []
        for android_jar in sorted(platforms.glob("android-*/android.jar")):
            stat = android_jar.stat()
            rows.append({
                "api": android_jar.parent.name,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            })
        return rows

    def _cache_descriptor(self, apk_path: Path, jar: Path, platforms: Path, sources: Path) -> dict:
        return {
            "schema": self.CACHE_SCHEMA_VERSION,
            "apk_sha256": self._sha256_file(apk_path),
            "flowdroid_jar_sha256": self._sha256_file(jar),
            "sources_sinks_sha256": self._sha256_file(sources),
            "android_platforms": self._platforms_signature(platforms),
            "java_path": str(self.cfg.get("java_path") or "java"),
        }

    def _cache_dir(self) -> Path | None:
        if self.cfg.get("cache_enabled", True) is False:
            return None
        raw = str(self.cfg.get("cache_dir") or "").strip()
        return Path(raw) if raw else None

    @staticmethod
    def _parse_output(output: Path, *, cache_key: str = "", cache_hit: bool = False) -> AdapterResult:
        root = ET.parse(output).getroot()
        facts = []
        for node in root.iter("Result"):
            # FlowDroid XML versions differ: Source/Sink may be nested below
            # Sources/Sinks. Descendant lookup stays compatible with real CLI.
            source = node.find(".//Source")
            sink = node.find(".//Sink")
            facts.append({
                "source": source.attrib.get("Statement", "") if source is not None else "",
                "sink": sink.attrib.get("Statement", "") if sink is not None else "",
            })
        return AdapterResult("flowdroid", "completed", facts=facts, evidence=[{
            "type": "taint_flow", "path": str(output),
            "meta": {"flow_count": len(facts), "producer": "flowdroid", "cache_hit": cache_hit, "cache_key": cache_key},
        }], cache_hit=cache_hit)

    @staticmethod
    def _cache_key(descriptor: dict) -> str:
        encoded = json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _restore_cache(self, cache_root: Path | None, cache_key: str, descriptor: dict, output: Path) -> AdapterResult | None:
        if cache_root is None:
            return None
        entry = cache_root / cache_key
        result_file, metadata_file = entry / "flowdroid-results.xml", entry / "metadata.json"
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            if metadata.get("descriptor") != descriptor or not result_file.is_file():
                return None
            shutil.copy2(result_file, output)
            return self._parse_output(output, cache_key=cache_key, cache_hit=True)
        except (OSError, ValueError, ET.ParseError):
            return None

    def _store_cache(self, cache_root: Path | None, cache_key: str, descriptor: dict, output: Path) -> None:
        if cache_root is None or not output.is_file():
            return
        entry = cache_root / cache_key
        entry.mkdir(parents=True, exist_ok=True)
        result_file, metadata_file = entry / "flowdroid-results.xml", entry / "metadata.json"
        suffix = f".{os.getpid()}.tmp"
        result_tmp, metadata_tmp = result_file.with_name(result_file.name + suffix), metadata_file.with_name(metadata_file.name + suffix)
        try:
            shutil.copy2(output, result_tmp)
            metadata_tmp.write_text(json.dumps({"descriptor": descriptor}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            os.replace(result_tmp, result_file)
            os.replace(metadata_tmp, metadata_file)
        finally:
            for temporary in (result_tmp, metadata_tmp):
                if temporary.exists():
                    temporary.unlink(missing_ok=True)

    def analyze(self, apk_path: Path, output_dir: Path, should_stop=None) -> AdapterResult:
        if not self.cfg.get("enabled"):
            return AdapterResult(self.name, "not_available")
        jar = Path(str(self.cfg.get("jar_path") or "")); platforms = Path(str(self.cfg.get("android_platforms") or ""))
        sources = Path(str(self.cfg.get("sources_sinks") or ""))
        if not jar.is_file() or not platforms.is_dir() or not sources.is_file():
            return AdapterResult(self.name, "not_available", error="FlowDroid JAR、Android platforms 或 SourcesAndSinks 未配置")
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "flowdroid-results.xml"
        # A cache key can only be trusted when the decrypted APK is readable.
        # Keep the adapter's pre-cache behaviour for callers that hand us a
        # path which is about to be produced (or a test seam): FlowDroid will
        # report its own actionable failure, rather than cache preparation
        # raising and aborting the whole workflow.
        descriptor = None
        cache_key = ""
        if apk_path.is_file():
            descriptor = self._cache_descriptor(apk_path, jar, platforms, sources)
            cache_key = self._cache_key(descriptor)
            cached = self._restore_cache(self._cache_dir(), cache_key, descriptor, output)
            if cached:
                return cached
        command = [str(self.cfg.get("java_path") or "java"), "-jar", str(jar), "-a", str(apk_path), "-p", str(platforms), "-s", str(sources), "-o", str(output)]
        try:
            timeout = int(self.cfg.get("timeout_seconds") or 900)
            completed = (
                self.runner(command, timeout)
                if self.runner else self._run_interruptible(command, timeout, should_stop)
            )
            if completed.returncode != 0 or not output.exists():
                raw_error = (completed.stderr or completed.stdout or "FlowDroid 无结果").strip()
                # Java tools usually print the actionable exception at the
                # end. Preserve both ends instead of hiding the root cause
                # behind startup logs.
                if len(raw_error) > 1800:
                    raw_error = f"{raw_error[:500]}\n...<truncated>...\n{raw_error[-1200:]}"
                if "No sources found" in raw_error:
                    return AdapterResult(
                        self.name, "inconclusive", error=
                        "FlowDroid 已构建调用图，但 APK 可达代码未命中隐私 Source；"
                        "可能存在加固、反射、动态加载或原生代码，不能据此判定无数据流。\n"
                        + raw_error,
                    )
                if "interrupted because task was paused or canceled" in raw_error:
                    return AdapterResult(self.name, "interrupted", error="任务已暂停或取消，静态污点分析已停止")
                return AdapterResult(self.name, "failed", error=raw_error)
            if descriptor is not None:
                self._store_cache(self._cache_dir(), cache_key, descriptor, output)
            return self._parse_output(output, cache_key=cache_key, cache_hit=False)
        except Exception as exc:
            return AdapterResult(self.name, "failed", error=f"{type(exc).__name__}: {exc}"[:500])


class ExternalStaticAnalysisHub:
    def __init__(self, adapters): self.adapters = adapters
    def run(self, ctx) -> EngineResult:
        statuses, evidence, gaps = {}, [], []
        for adapter in self.adapters:
            started = time.monotonic()
            record_event(
                ctx, adapter.name, "static_analysis_started",
                message="正在进行静态污点分析；大型 APK 可能需要数分钟",
            )
            should_stop = lambda: bool(
                (ctx.runtime.get("is_canceled") and ctx.runtime["is_canceled"]())
                or (ctx.runtime.get("is_paused") and ctx.runtime["is_paused"]())
                or (ctx.runtime.get("is_terminated") and ctx.runtime["is_terminated"]())
            ) if isinstance(getattr(ctx, "runtime", None), dict) else False
            result = adapter.analyze(
                Path(ctx.apk_path), ctx.data_dir / "static" / adapter.name,
                should_stop=should_stop,
            )
            statuses[adapter.name] = result.status; evidence.extend(result.evidence)
            if result.cache_hit:
                record_event(ctx, adapter.name, "static_analysis_cache_hit", cache_key=result.evidence[0]["meta"].get("cache_key"))
            record_event(
                ctx, adapter.name, "static_analysis_finished",
                status=result.status, flow_count=len(result.facts),
                elapsed_seconds=round(time.monotonic() - started, 1),
            )
            if result.status == "failed":
                gaps.append(f"{adapter.name} 静态分析失败：{result.error}")
            elif result.status == "inconclusive":
                gaps.append(f"{adapter.name} 静态分析证据不足：{result.error}")
            elif result.status == "interrupted":
                gaps.append(f"{adapter.name} 静态分析已中断：{result.error}")
            elif result.status == "not_available" and getattr(adapter, "cfg", {}).get("enabled"):
                gaps.append(f"{adapter.name} 已启用但不可用：{result.error}")
        runtime = getattr(ctx, "runtime", None)
        if isinstance(runtime, dict):
            runtime["external_static_status"] = statuses
        return EngineResult(evidence_files=evidence, stats={"external_static": statuses, "coverage_gaps": gaps})
