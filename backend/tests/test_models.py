from backend.app.db import Base, SessionLocal, engine, init_db
from backend.app.models import APKFile, DetectionTask, Violation, Evidence, Report


def test_apk_and_task_roundtrip():
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="demo.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=1024,
                      parse_status="success", storage_path="data/apks/x.enc",
                      permissions=["android.permission.READ_CONTACTS"])
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, industry="通用", mode="deep", status="queued")
        s.add(task)
        s.commit()
        assert task.id is not None
        got = s.query(DetectionTask).filter_by(id=task.id).one()
        assert got.status == "queued"
        assert got.apk.permissions == ["android.permission.READ_CONTACTS"]
