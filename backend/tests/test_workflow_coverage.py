import subprocess
import sys

from agent.agent_core import workflow
from agent.agent_core.workflow import _requires_coverage_failure, _reset_probe_phase_runtime
from agent.common.exceptions import ExplorationError
from backend.app.config import PROJECT_ROOT
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask, Report
from backend.app.services.task_service import pause_task


def test_real_clean_result_with_unmet_coverage_still_generates_a_coverage_limited_report():
    """Coverage gaps constrain the conclusion; they must not abort the task."""
    assert not _requires_coverage_failure(
        findings=[],
        stats={"coverage_complete": False, "coverage_gaps": ["隐私政策未完整阅读"]},
    )


def test_probe_phase_reset_keeps_document_ledger_but_drops_login_and_navigation_state():
    runtime = {
        "read_document_kinds": {"privacy_policy", "user_agreement"},
        "read_document_titles": {"隐私政策", "用户协议"},
        "policy_text": "policy body",
        "completed_document_routes": {"third-party-sdk-row"},
        "privacy_hub_visited": True,
        "privacy_hub_audit_complete": True,
        "hub_settings_drilled": True,
        "logout_entry_explored": True,
        "manual_login_waited": True,
        "manual_login_verified": True,
        "login_gate_revisit_returned": True,
        "last_appium_action": {"target": "login"},
        "global_target_attempts": {"home|head_image": 6},
        "permission_denial_retry_targets": {"camera"},
    }

    _reset_probe_phase_runtime(runtime)

    assert runtime["read_document_kinds"] == {"privacy_policy", "user_agreement"}
    assert runtime["read_document_titles"] == {"隐私政策", "用户协议"}
    assert runtime["policy_text"] == "policy body"
    assert runtime["completed_document_routes"] == {"third-party-sdk-row"}
    assert runtime["privacy_hub_visited"] is True
    assert runtime["privacy_hub_audit_complete"] is True
    assert runtime["hub_settings_drilled"] is True
    assert runtime["logout_entry_explored"] is True
    for key in (
        "manual_login_waited", "manual_login_verified", "login_gate_revisit_returned",
        "last_appium_action", "global_target_attempts", "permission_denial_retry_targets",
    ):
        assert key not in runtime


def test_new_run_clears_stale_artifacts_before_any_engine(monkeypatch, tmp_path):
    """Reused numeric task ids must not inherit evidence from deleted tasks."""
    import uuid
    from agent.detection_engines.base import EngineResult

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="fresh.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1, parse_status="success", storage_path="data/apks/fresh.apk",
        )
        session.add(apk); session.commit()
        task = DetectionTask(apk_id=apk.id, status="queued")
        session.add(task); session.commit(); task_id = task.id

    calls = []
    monkeypatch.setattr(workflow, "delete_task_artifacts", lambda seen_id, paths: calls.append((seen_id, paths)))
    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "fresh.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [EngineResult()])
    monkeypatch.setattr(workflow, "_run_detection_engines", lambda _ctx: [EngineResult(stats={"coverage_complete": True})])
    monkeypatch.setattr("agent.rule_engine.report_generator.render_pdf", lambda _html, out, **_kwargs: out.write_bytes(b"%PDF-test"))

    workflow.run_task(task_id)

    assert calls[0] == (task_id, [])
    with SessionLocal() as session:
        completed = session.query(DetectionTask).filter_by(id=task_id).one()
        assert completed.status == "completed"
        assert completed.progress["stage"] == "completed"
        assert completed.progress["percent"] == 100
        assert completed.progress["timing_active_seconds"] >= 0


def test_static_and_device_engines_run_in_their_visible_ui_stages(monkeypatch, tmp_path):
    """A slow FlowDroid run must never make the UI look stuck in AI traversal."""
    import uuid
    from agent.detection_engines.base import EngineResult

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="stages.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1, parse_status="success", storage_path="data/apks/stages.apk",
        )
        session.add(apk); session.commit()
        task = DetectionTask(apk_id=apk.id, status="queued")
        session.add(task); session.commit(); task_id = task.id

    observed = []
    def capture(label):
        with SessionLocal() as session:
            observed.append((label, session.query(DetectionTask).filter_by(id=task_id).one().status))
        return [EngineResult(stats={"coverage_complete": True})]

    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: capture("static"))
    monkeypatch.setattr(workflow, "_run_detection_engines", lambda _ctx: capture("dynamic"))
    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "stages.apk")
    monkeypatch.setattr("agent.rule_engine.report_generator.render_pdf", lambda _html, out, **_kwargs: out.write_bytes(b"%PDF-test"))

    workflow.run_task(task_id)

    assert observed == [("static", "static_analysis"), ("dynamic", "traversing")]


def test_dual_probe_aggregates_task_stats_and_resets_second_profile_state(monkeypatch, tmp_path):
    import uuid
    from agent.detection_engines.base import EngineResult

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="dual.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1, parse_status="success", storage_path="data/apks/dual.apk",
        )
        session.add(apk); session.commit()
        task = DetectionTask(
            apk_id=apk.id, status="queued",
            progress={"probe_profile": "dual", "probe_profiles": ["deny", "allow"]},
        )
        session.add(task); session.commit(); task_id = task.id

    profiles = []
    phase_plans = []

    def run_phase(ctx):
        profile = ctx.runtime["probe_profile"]
        profiles.append(profile)
        phase_plans.append({row["item"] for row in ctx.runtime["active_device_scenario_plan"]})
        if profile == "deny":
            ctx.runtime.update({
                "pages_covered": 41,
                "manual_login_waited": True,
                "manual_login_verified": True,
                "login_gate_revisit_returned": True,
                "global_target_attempts": {"home|head_image": 6},
                "read_document_kinds": {"privacy_policy"},
                "scenario_completed_items": ["1.1", "2.3", "3.8", "4.2"],
            })
            return [EngineResult(stats={
                "pages_covered": 41, "scenarios": 7,
                "current_page": ".HomeActivity", "coverage_complete": True,
            })]
        assert "manual_login_waited" not in ctx.runtime
        assert "manual_login_verified" not in ctx.runtime
        assert "login_gate_revisit_returned" not in ctx.runtime
        assert "global_target_attempts" not in ctx.runtime
        assert ctx.runtime["read_document_kinds"] == {"privacy_policy"}
        assert ctx.runtime["scenario_completed_items"] == []
        ctx.runtime["pages_covered"] = 3
        return [EngineResult(stats={
            "pages_covered": 3, "scenarios": 2,
            "current_page": ".LoginActivity", "coverage_complete": True,
        })]

    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "dual.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [EngineResult()])
    monkeypatch.setattr(workflow, "_run_detection_engines", run_phase)
    monkeypatch.setattr(
        "agent.rule_engine.report_generator.render_pdf",
        lambda _html, out, **_kwargs: out.write_bytes(b"%PDF-test"),
    )

    workflow.run_task(task_id)

    assert profiles == ["deny", "allow"]
    assert "1.1" in phase_plans[0]
    assert "1.1" not in phase_plans[1]
    assert "2.3" in phase_plans[1]
    with SessionLocal() as session:
        completed = session.query(DetectionTask).filter_by(id=task_id).one()
        assert completed.pages_covered == 44
        assert completed.scenarios_triggered == 9
        assert completed.current_page == ".LoginActivity"


def test_dual_probe_does_not_start_allow_when_deny_never_created_a_device_session(monkeypatch, tmp_path):
    """A retryable transport error is not evidence for a second permission posture."""
    import uuid
    from agent.detection_engines.base import EngineResult

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="device-session-failed.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1, parse_status="success", storage_path="data/apks/device-session-failed.apk",
        )
        session.add(apk)
        session.commit()
        task = DetectionTask(
            apk_id=apk.id, status="queued",
            progress={"probe_profile": "dual", "probe_profiles": ["deny", "allow"]},
        )
        session.add(task)
        session.commit()
        task_id = task.id

    profiles = []

    def run_phase(ctx):
        profiles.append(ctx.runtime["probe_profile"])
        return [EngineResult(stats={
            "coverage_complete": False,
            "coverage_gaps": ["device_unavailable"],
            "failure": {
                "category": "device_unavailable",
                "recoverable": True,
                "coverage_gap": "device_unavailable",
                "reason": "UiAutomator2 session reset",
            },
        })]

    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "device-session-failed.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [EngineResult()])
    monkeypatch.setattr(workflow, "_run_detection_engines", run_phase)
    monkeypatch.setattr(
        "agent.rule_engine.report_generator.render_pdf",
        lambda _html, out, **_kwargs: out.write_bytes(b"%PDF-test"),
    )

    workflow.run_task(task_id)

    assert profiles == ["deny"]
    with SessionLocal() as session:
        task = session.query(DetectionTask).filter_by(id=task_id).one()
        assert task.progress["phase_transition_blocked"]["from"] == "deny"
        assert task.progress["phase_transition_blocked"]["to"] == "allow"


def test_dual_probe_recomputes_scenario_coverage_gaps_from_final_phase(monkeypatch, tmp_path):
    """A deny-phase pending gap must not survive after allow completes it."""
    import uuid
    from agent.detection_engines.base import EngineResult

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="coverage-merge.apk",
            sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1,
            parse_status="success",
            storage_path="data/apks/coverage-merge.apk",
        )
        session.add(apk)
        session.commit()
        task = DetectionTask(
            apk_id=apk.id,
            status="queued",
            progress={"probe_profile": "dual", "probe_profiles": ["deny", "allow"]},
        )
        session.add(task)
        session.commit()
        task_id = task.id

    def run_phase(ctx):
        item = {"item": "3.8", "state": "pending", "state_label": "待执行"}
        if ctx.runtime["probe_profile"] == "deny":
            ctx.runtime["scenario_coverage"] = {"planned": 1, "items": [item]}
            ctx.runtime["coverage_gaps"] = [
                "场景义务尚未完成：3.8",
                "运行时保留的外部证据缺口",
            ]
            return [EngineResult(stats={
                "coverage_complete": False,
                "coverage_gaps": [
                    "场景义务尚未完成：3.8",
                    "外部隐私政策未加载正文",
                ],
                "scenario_coverage": {"planned": 1, "items": [item]},
            })]

        ctx.runtime["scenario_completed_items"] = ["3.8"]
        ctx.runtime["scenario_coverage"] = {
            "planned": 1,
            "items": [{"item": "3.8", "state": "evidence_observed"}],
        }
        return [EngineResult(stats={
            "coverage_complete": True,
            "scenario_coverage": ctx.runtime["scenario_coverage"],
        })]

    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "coverage-merge.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [EngineResult()])
    monkeypatch.setattr(workflow, "_run_detection_engines", run_phase)
    monkeypatch.setattr(
        "agent.rule_engine.report_generator.render_pdf",
        lambda _html, out, **_kwargs: out.write_bytes(b"%PDF-test"),
    )

    workflow.run_task(task_id)

    with SessionLocal() as session:
        report = session.query(Report).filter_by(task_id=task_id).one()
        assert report.summary["scenario_coverage"]["remaining_items"] == []
        assert not any("场景义务尚未完成" in gap for gap in report.summary["coverage_gaps"])
        assert "运行时保留的外部证据缺口" in report.summary["coverage_gaps"]
        assert "外部隐私政策未加载正文" in report.summary["coverage_gaps"]
        assert report.summary["coverage_complete"] is False


def test_coverage_gap_does_not_discard_existing_evidence_findings():
    assert not _requires_coverage_failure(
        findings=[object()],
        stats={"coverage_complete": False},
    )


def test_frida_unavailable_does_not_abort_appium_traversal(monkeypatch, tmp_path):
    """Frida is optional evidence; its failure must leave the UI traversal running."""
    from agent.detection_engines.base import EngineResult
    from agent.common.exceptions import EngineUnavailableError

    class FakeClient:
        def activate(self, _package):
            return None

    class FakeExplorer:
        def __init__(self):
            self.client = FakeClient()

        def prepare(self, _ctx):
            return None

        def run(self, ctx):
            ctx.runtime["explorer_ran"] = True
            return EngineResult(stats={"pages_covered": 3, "coverage_complete": True})

    class FakeMonitor:
        last_failure_stage = "spawning"

        def start(self, _ctx, **_kwargs):
            raise EngineUnavailableError("Frida 操作超过 20 秒未返回")

    monkeypatch.setattr(workflow, "AppiumExplorerEngine", FakeExplorer)
    monkeypatch.setattr(workflow, "FridaMonitorEngine", FakeMonitor)
    monkeypatch.setattr(workflow, "record_event", lambda _ctx, source, event_type, **payload: {
        "type": "timeline", "path": str(tmp_path / f"{source}-{event_type}.json"),
        "meta": {"source": source, "event_type": event_type, **payload},
    })
    # The fallback is intentionally made unavailable as well; Appium must
    # still run and the returned contract must expose the coverage gap.
    monkeypatch.setattr(FakeClient, "activate", lambda _self, _package: (_ for _ in ()).throw(
        EngineUnavailableError("无法启动测试应用")
    ))

    ctx = type("Ctx", (), {
        "apk": type("Apk", (), {"package_name": "com.example.demo"})(),
        "cfg": {"frida": {"spawn_target": True}},
        "runtime": {},
        "data_dir": tmp_path,
    })()
    results = workflow._run_detection_engines(ctx)

    assert ctx.runtime["explorer_ran"] is True
    assert any(result.stats.get("frida_available") is False for result in results)
    assert any(result.stats.get("coverage_complete") is False for result in results)


def test_appium_unavailable_is_recorded_as_coverage_failure_not_uncaught_error(monkeypatch, tmp_path):
    """A missing device/Appium service must produce a typed engine result."""
    from agent.detection_engines.base import EngineResult
    from agent.common.exceptions import EngineUnavailableError

    class FakeExplorer:
        def __init__(self):
            self.client = None

        def prepare(self, _ctx):
            raise EngineUnavailableError("Appium 服务未就绪：http://127.0.0.1:4725")

    class FakeMonitor:
        last_failure_stage = None

        def start(self, _ctx, **_kwargs):
            raise AssertionError("Frida must not start when Appium preparation is unavailable")

    monkeypatch.setattr(workflow, "AppiumExplorerEngine", FakeExplorer)
    monkeypatch.setattr(workflow, "FridaMonitorEngine", FakeMonitor)

    ctx = type("Ctx", (), {
        "apk": type("Apk", (), {"package_name": "com.example.demo"})(),
        "cfg": {"frida": {"spawn_target": True}},
        "runtime": {},
        "data_dir": tmp_path,
    })()

    results = workflow._run_detection_engines(ctx)

    assert len(results) == 1
    assert results[0].stats["failure"]["category"] == "device_unavailable"
    assert results[0].stats["coverage_complete"] is False
    assert ctx.runtime["engine_failure"]["category"] == "device_unavailable"


def test_code_contract_failure_is_persisted_with_code_bug_category(monkeypatch, tmp_path):
    """Unexpected programming errors remain failed, but with a stable category."""
    import uuid
    from agent.detection_engines.base import EngineResult

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="code-bug.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1, parse_status="success", storage_path="data/apks/code-bug.apk",
        )
        session.add(apk)
        session.commit()
        task = DetectionTask(apk_id=apk.id, status="queued")
        session.add(task)
        session.commit()
        task_id = task.id

    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "code-bug.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [EngineResult()])
    monkeypatch.setattr(workflow, "_run_detection_engines", lambda _ctx: (_ for _ in ()).throw(KeyError("1.2")))

    workflow.run_task(task_id)

    with SessionLocal() as session:
        task = session.query(DetectionTask).filter_by(id=task_id).one()
        assert task.status == "failed"
        assert task.failure_reason.startswith("code_bug:")
        assert task.progress["failure"]["category"] == "code_bug"
        assert task.progress["coverage_complete"] is False


def test_operational_engine_failure_category_survives_completed_progress(monkeypatch, tmp_path):
    """A coverage-limited device failure remains visible after report generation."""
    import uuid
    from agent.detection_engines.base import EngineResult

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="device-unavailable.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1, parse_status="success", storage_path="data/apks/device-unavailable.apk",
        )
        session.add(apk)
        session.commit()
        task = DetectionTask(apk_id=apk.id, status="queued")
        session.add(task)
        session.commit()
        task_id = task.id

    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "device-unavailable.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [EngineResult()])
    monkeypatch.setattr(
        workflow,
        "_run_detection_engines",
        lambda _ctx: [EngineResult(stats={
            "coverage_complete": False,
            "coverage_gaps": ["device_unavailable"],
            "failure": {
                "category": "device_unavailable",
                "recoverable": True,
                "coverage_gap": "device_unavailable",
                "reason": "traversing 阶段设备或 Appium 不可用",
            },
        })],
    )
    monkeypatch.setattr(
        "agent.rule_engine.report_generator.render_pdf",
        lambda _html, out, **_kwargs: out.write_bytes(b"%PDF-test"),
    )

    workflow.run_task(task_id)

    with SessionLocal() as session:
        task = session.query(DetectionTask).filter_by(id=task_id).one()
        assert task.status == "completed"
        assert task.progress["failure"]["category"] == "device_unavailable"
        assert task.progress["coverage_complete"] is False
        assert "device_unavailable" in task.progress["coverage_gaps"]
        report = session.query(Report).filter_by(task_id=task.id).one()
        assert report.summary["engine_failure"]["category"] == "device_unavailable"
        assert report.summary["engine_failures"][0]["category"] == "device_unavailable"


def test_coverage_limited_zero_finding_run_completes_and_keeps_gaps(monkeypatch, tmp_path):
    """A reachable-route audit is valuable even when an external policy is unavailable."""
    import uuid
    from agent.detection_engines.base import EngineResult

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="coverage-limited.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1, parse_status="success", storage_path="data/apks/coverage-limited.apk",
        )
        session.add(apk); session.commit()
        task = DetectionTask(apk_id=apk.id, status="queued")
        session.add(task); session.commit(); task_id = task.id

    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "coverage-limited.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [EngineResult()])
    monkeypatch.setattr(
        workflow,
        "_run_detection_engines",
        lambda _ctx: [EngineResult(stats={
            "coverage_complete": False,
            "coverage_gaps": ["外部隐私政策未加载正文"],
            "pages_covered": 7,
            "scenarios": 11,
        })],
    )
    monkeypatch.setattr("agent.rule_engine.report_generator.render_pdf", lambda _html, out, **_kwargs: out.write_bytes(b"%PDF-test"))

    workflow.run_task(task_id)

    with SessionLocal() as session:
        task = session.query(DetectionTask).filter_by(id=task_id).one()
        report = session.query(Report).filter_by(task_id=task_id).one()
        assert task.status == "completed"
        assert report.summary["coverage_complete"] is False
        assert "外部隐私政策未加载正文" in report.summary["coverage_gaps"]
        assert set(report.summary["audit_method"]["dimensions"]) == {
            "driver", "page_state", "evidence", "traversal", "result", "stability",
        }
        assert report.summary["audit_execution"]["termination"]["kind"] == "adapter_completed"


def test_failure_after_a_pause_does_not_overwrite_paused_task(monkeypatch, tmp_path):
    """A device error racing with Pause must preserve the user's pause command."""
    import uuid

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="pause-race.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1, parse_status="success", storage_path="data/apks/pause-race.apk",
        )
        session.add(apk)
        session.commit()
        task = DetectionTask(apk_id=apk.id, status="queued")
        session.add(task)
        session.commit()
        task_id = task.id

    def pause_then_fail(ctx):
        pause_task(ctx.task.id)
        raise ExplorationError("simulated device failure after pause")

    monkeypatch.setattr(workflow, "_run_detection_engines", pause_then_fail)
    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "pause.apk")
    workflow.run_task(task_id)

    with SessionLocal() as session:
        task = session.query(DetectionTask).filter_by(id=task_id).one()
        assert task.status == "paused"
        assert session.query(Report).filter_by(task_id=task_id).count() == 0


def test_device_lock_blocks_a_second_worker_process(tmp_path):
    """The real AVD is a singleton resource, even when a second Worker starts."""
    from worker.device_lock import DeviceLock

    lock_path = tmp_path / "emulator-5554.lock"
    lease = DeviceLock(lock_path)
    assert lease.acquire() is True
    try:
        probe = (
            "from pathlib import Path; from worker.device_lock import DeviceLock; "
            f"print(DeviceLock(Path(r'{lock_path}')).acquire())"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe], cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=10, check=True,
        )
        assert result.stdout.strip() == "False"
    finally:
        lease.release()


def test_real_device_mode_forces_serial_worker_execution():
    from worker.main import effective_max_concurrent

    cfg = {"worker": {"max_concurrent": 3}, "detection": {"engines": {"explorer": "real", "monitor": "real"}}}
    assert effective_max_concurrent(cfg) == 1


def test_final_completion_does_not_overwrite_a_pause(monkeypatch, tmp_path):
    """Pause arriving after report generation still wins over completed."""
    import uuid
    from agent.detection_engines.base import EngineResult
    from agent.rule_engine import report_generator

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="final-pause.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1, parse_status="success", storage_path="data/apks/final-pause.apk",
        )
        session.add(apk)
        session.commit()
        task = DetectionTask(apk_id=apk.id, status="queued")
        session.add(task)
        session.commit()
        task_id = task.id

    monkeypatch.setattr(workflow, "_run_detection_engines", lambda _ctx: [EngineResult()])
    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "final-pause.apk")
    monkeypatch.setattr(report_generator, "render_pdf", lambda _html, out, **_kwargs: out.write_bytes(b"%PDF-test"))
    original_generate_report = report_generator.generate_report

    def generate_then_pause(*args, **kwargs):
        result = original_generate_report(*args, **kwargs)
        pause_task(task_id)
        return result

    monkeypatch.setattr(report_generator, "generate_report", generate_then_pause)
    workflow.run_task(task_id)

    with SessionLocal() as session:
        task = session.query(DetectionTask).filter_by(id=task_id).one()
        assert task.status == "paused"
        assert session.query(Report).filter_by(task_id=task_id).count() == 1
