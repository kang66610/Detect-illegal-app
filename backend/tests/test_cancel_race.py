import threading
import time

from agent.agent_core import workflow
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask
from backend.app.services.task_service import cancel_task, terminate_task


def test_cancel_during_pipeline_keeps_canceled(monkeypatch, tmp_path):
    """取消竞态回归：worker 运行中 API 侧取消，最终状态必须保持 canceled，
    不能被阶段循环的内存旧状态或收尾的 completed 覆盖。"""
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(
            filename="race.apk",
            sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=2048,
            parse_status="success",
            storage_path="data/apks/race.apk",
            permissions=["android.permission.READ_CONTACTS", "android.permission.ACCESS_FINE_LOCATION"],
        )
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, status="queued")
        s.add(task)
        s.commit()
        task_id = task.id

    from agent.detection_engines.base import EngineResult

    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "race.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [EngineResult()])

    def wait_for_cancel(ctx):
        for _ in range(100):
            if ctx.runtime["is_canceled"]():
                break
            time.sleep(0.02)
        return [EngineResult(stats={"coverage_complete": True})]

    monkeypatch.setattr(workflow, "_run_detection_engines", wait_for_cancel)
    th = threading.Thread(target=workflow.run_task, args=(task_id,), daemon=True)
    th.start()
    time.sleep(0.5)  # 等 worker 进入阶段循环后取消
    cancel_task(task_id)
    th.join(timeout=60)

    with SessionLocal() as s:
        row = s.query(DetectionTask).filter_by(id=task_id).one()
        assert row.status == "canceled", f"取消后被覆盖为 {row.status}"


def test_terminate_during_traversal_generates_partial_report_before_canceled(monkeypatch, tmp_path):
    """终止请求停止后续遍历，但分析/报告仍消费终止前的结果。"""
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(
            filename="terminate-report.apk",
            sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=2048, parse_status="success", storage_path="data/apks/terminate-report.apk",
        )
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, status="queued")
        s.add(task)
        s.commit()
        task_id = task.id

    from agent.detection_engines.base import EngineResult

    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "terminate-report.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [])
    generated = []

    def wait_for_termination(ctx):
        while not ctx.runtime["is_terminated"]():
            time.sleep(0.02)
        return [EngineResult(stats={"coverage_complete": False, "coverage_gaps": ["用户提前终止"]})]

    def capture_report(state, *, generate):
        generated.append((
            list(state["matched"]),
            list(state["evidence"]),
            dict(state["ctx"].runtime.get("audit_execution", {}).get("termination") or {}),
        ))

    monkeypatch.setattr(workflow, "_run_detection_engines", wait_for_termination)
    monkeypatch.setattr(workflow, "run_reporting_stage", capture_report)
    th = threading.Thread(target=workflow.run_task, args=(task_id,), daemon=True)
    th.start()
    for _ in range(100):
        with SessionLocal() as s:
            status = s.query(DetectionTask.status).filter_by(id=task_id).scalar()
        if status == "traversing":
            break
        time.sleep(0.02)
    terminate_task(task_id)
    th.join(timeout=60)

    with SessionLocal() as s:
        row = s.query(DetectionTask).filter_by(id=task_id).one()
        assert row.status == "canceled"
        assert row.progress["termination_report_ready"] is True
    assert len(generated) == 1
    assert generated[0][2]["kind"] in {"terminated", "user_terminated"}
