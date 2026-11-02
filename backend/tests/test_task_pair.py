import uuid

from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask
from backend.app.services.task_service import create_task


def test_create_task_enqueues_one_dual_path_job():
    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="pair.apk",
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            size_bytes=1024,
            parse_status="success",
            storage_path="data/apks/pair.enc",
        )
        session.add(apk)
        session.commit()
        apk_id = apk.id

    task = create_task(apk_id, industry="工具", mode="fast")
    assert task.progress["probe_profiles"] == ["deny", "allow"]
    assert task.progress["probe_profile"] == "dual"
    assert task.progress["pair_label"] == "拒绝权限 + 允许权限"

    with SessionLocal() as session:
        tasks = session.query(DetectionTask).filter_by(apk_id=apk_id).all()
        assert len(tasks) == 1
        assert tasks[0].id == task.id


def test_dual_path_task_runs_deny_then_allow_in_one_job(monkeypatch, tmp_path):
    from agent.agent_core import workflow
    from agent.detection_engines.base import EngineResult

    init_db()
    with SessionLocal() as session:
        apk = APKFile(
            filename="dual.apk",
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            size_bytes=1,
            parse_status="success",
            storage_path="data/apks/dual.apk",
        )
        session.add(apk)
        session.commit()
        apk_id = apk.id

    task = create_task(apk_id, industry="通用", mode="fast")
    seen = []

    def capture(ctx):
        seen.append(ctx.cfg["detection"]["permission_probe_action"])
        return [EngineResult(stats={"coverage_complete": True, "pages_covered": 3})]

    monkeypatch.setattr(workflow, "decrypt_to_temp", lambda *_args: tmp_path / "dual.apk")
    monkeypatch.setattr(workflow, "_run_static_engines", lambda _ctx: [EngineResult()])
    monkeypatch.setattr(workflow, "_run_detection_engines", capture)
    monkeypatch.setattr(
        "agent.rule_engine.report_generator.render_pdf",
        lambda _html, out, **_kwargs: out.write_bytes(b"%PDF-test"),
    )

    workflow.run_task(task.id)
    assert seen == ["deny", "allow"]
