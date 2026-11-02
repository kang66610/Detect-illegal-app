import pytest
from agent.agent_core.task_manager import can_transition
from agent.common.exceptions import TaskStateError
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask, Evidence, Report, Violation
from backend.app.services.task_service import cancel_task, delete_task, pause_task, resume_task, retry_task, terminate_task


def test_flow_allows_normal_chain():
    chain = ["queued", "preparing", "installing", "static_analysis",
             "traversing", "analyzing", "reporting", "completed"]
    for cur, nxt in zip(chain, chain[1:]):
        assert can_transition(cur, nxt), f"{cur} -> {nxt}"


def test_flow_rejects_skip_and_backward():
    assert not can_transition("queued", "traversing")
    assert not can_transition("reporting", "traversing")


def test_cancel_task():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="a.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=1, parse_status="success", storage_path="x")
        s.add(apk)
        s.commit()
        t = DetectionTask(apk_id=apk.id, status="traversing")
        s.add(t)
        s.commit()
        cancel_task(t.id)
        s.expire_all()
        assert s.query(DetectionTask).filter_by(id=t.id).one().status == "canceled"


def test_terminate_task_requests_safe_stop_before_terminal_report():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="terminate.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=1,
                      parse_status="success", storage_path="x")
        s.add(apk)
        s.commit()
        t = DetectionTask(apk_id=apk.id, status="traversing", progress={"percent": 55, "timing_active_seconds": 12})
        s.add(t)
        s.commit()
        task_id = t.id

    terminate_task(task_id)

    with SessionLocal() as s:
        row = s.query(DetectionTask).filter_by(id=task_id).one()
        assert row.status == "traversing"
        assert row.finished_at is None
        assert row.progress["termination_requested"] is True
        assert "终止" in row.failure_reason


def test_retry_failed_task():
    """失败任务重跑：复用原配置回到排队，清空失败痕迹并重置计数（controller ruling：retry 仅 failed→queued）。"""
    import uuid
    from datetime import datetime
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="a.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=1, parse_status="success", storage_path="x")
        s.add(apk)
        s.commit()
        t = DetectionTask(apk_id=apk.id, industry="金融", mode="fast", status="failed",
                          failure_reason="模拟失败", progress={"step": 3},
                          pages_covered=5, scenarios_triggered=2,
                          finished_at=datetime.utcnow())
        s.add(t)
        s.commit()
        retry_task(t.id)
        s.expire_all()
        row = s.query(DetectionTask).filter_by(id=t.id).one()
        assert row.status == "queued"
        assert row.industry == "金融" and row.mode == "fast"  # 复用原配置
        assert row.failure_reason is None
        assert row.progress is None
        assert row.pages_covered == 0
        assert row.scenarios_triggered == 0
        assert row.finished_at is None


def test_retry_canceled_task_reuses_the_original_configuration():
    import uuid

    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="canceled.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=1,
                      parse_status="success", storage_path="x")
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, industry="通用", mode="deep", status="canceled")
        s.add(task)
        s.commit()
        task_id = task.id

    retry_task(task_id)

    with SessionLocal() as s:
        row = s.query(DetectionTask).filter_by(id=task_id).one()
        assert row.status == "queued"
        assert row.mode == "deep"


def test_retry_clears_old_violations():
    """重跑前清除上次运行的违规与报告，避免重跑成功后新旧产物叠加。"""
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="retry.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
                      size_bytes=2048, parse_status="success", storage_path="data/apks/retry.apk",
                      permissions=["android.permission.READ_CONTACTS"])
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, status="failed")
        s.add(task)
        s.flush()
        task_id = task.id
        s.add(Report(task_id=task_id, report_no=f"retry-{task_id}", pdf_path="data/exports/retry.pdf"))
        violation = Violation(
            task_id=task_id, category=1, category_name="test", rule_id="RULE_TEST",
            description="old finding", legal_basis="test", risk_level="low",
        )
        s.add(violation)
        s.flush()
        s.add(Evidence(violation_id=violation.id, type="timeline", file_path="data/evidence/old.json"))
        s.commit()

    retry_task(task_id)
    with SessionLocal() as s:
        row = s.query(DetectionTask).filter_by(id=task_id).one()
        assert row.status == "queued"
        assert s.query(Violation).filter_by(task_id=task_id).count() == 0
        assert s.query(Report).filter_by(task_id=task_id).count() == 0


def test_delete_terminal_task_removes_task_and_reports():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="delete.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
                      size_bytes=1, parse_status="success", storage_path="data/apks/delete.apk.enc")
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, status="completed")
        s.add(task)
        s.commit()
        s.add(Report(task_id=task.id, report_no="delete-test", pdf_path="data/exports/delete-test.pdf"))
        violation = Violation(task_id=task.id, category=1, category_name="test", rule_id="R-1",
                              description="test", legal_basis="test", risk_level="low")
        s.add(violation)
        s.flush()
        s.add(Evidence(violation_id=violation.id, type="timeline", file_path="data/evidence/test.json"))
        s.commit()
        task_id = task.id

    delete_task(task_id)
    with SessionLocal() as s:
        assert s.query(DetectionTask).filter_by(id=task_id).first() is None
        assert s.query(Report).filter_by(task_id=task_id).first() is None
        assert s.query(Violation).filter_by(task_id=task_id).first() is None


def test_delete_active_task_is_rejected():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="active.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
                      size_bytes=1, parse_status="success", storage_path="data/apks/active.apk.enc")
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, status="traversing")
        s.add(task)
        s.commit()
        task_id = task.id

    with pytest.raises(TaskStateError):
        delete_task(task_id)


def test_delete_paused_task_removes_task():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="paused-delete.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
                      size_bytes=1, parse_status="success", storage_path="data/apks/paused-delete.apk.enc")
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, status="paused", progress={"percent": 56})
        s.add(task)
        s.commit()
        task_id = task.id

    delete_task(task_id)

    with SessionLocal() as s:
        assert s.query(DetectionTask).filter_by(id=task_id).first() is None


def test_pause_and_resume_task_returns_to_queue():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="pause.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
                      size_bytes=1, parse_status="success", storage_path="data/apks/pause.apk.enc")
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, status="traversing", progress={"percent": 56})
        s.add(task)
        s.commit()
        task_id = task.id

    pause_task(task_id)
    with SessionLocal() as s:
        assert s.query(DetectionTask).filter_by(id=task_id).one().status == "paused"

    resume_task(task_id)
    with SessionLocal() as s:
        task = s.query(DetectionTask).filter_by(id=task_id).one()
        assert task.status == "queued"
        assert task.progress["resume_requested"] is True
        assert task.progress["resume_count"] == 1
