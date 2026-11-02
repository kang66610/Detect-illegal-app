import io

import pytest
from agent.common.exceptions import ApkValidationError
from agent.common.utils import encrypt_bytes, get_or_create_fernet_key
from backend.app.config import PROJECT_ROOT, config
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask
from backend.app.services import apk_service
from backend.app.services.apk_service import validate_apk_upload


def test_rejects_non_zip_file(tmp_path):
    fake = tmp_path / "fake.apk"
    fake.write_bytes(b"this is not a zip file at all")
    with pytest.raises(ApkValidationError, match="文件格式无效"):
        validate_apk_upload(fake, "fake.apk")


def test_rejects_zip_without_manifest(tmp_path):
    import zipfile
    fake = tmp_path / "notapk.apk"
    with zipfile.ZipFile(fake, "w") as z:
        z.writestr("hello.txt", "hello")
    with pytest.raises(ApkValidationError, match="文件格式无效"):
        validate_apk_upload(fake, "notapk.apk")


def test_rejects_oversized(tmp_path):
    big = tmp_path / "big.apk"
    big.write_bytes(b"\x00" * 100)
    with pytest.raises(ApkValidationError, match="超过"):
        validate_apk_upload(big, "big.apk", max_bytes=50)


# --- Task 8 遗留项修复回归测试（RED 先行） ---


def test_save_apk_duplicate_content_returns_same_row():
    """修复 1：同内容上传两次 → 第二次返回同一行（幂等），且库中仅一行，不抛 IntegrityError。"""
    import uuid

    from fastapi import UploadFile

    init_db()
    payload = f"not an apk {uuid.uuid4()}".encode()
    first = apk_service.save_apk(UploadFile(file=io.BytesIO(payload), filename="dup.apk"))
    second = apk_service.save_apk(UploadFile(file=io.BytesIO(payload), filename="dup.apk"))
    assert second.id == first.id
    with SessionLocal() as s:
        rows = s.query(APKFile).filter_by(sha256=first.sha256).all()
    assert len(rows) == 1


def test_reupload_existing_unreferenced_apk_refreshes_static_profile(monkeypatch):
    """同内容且尚无检测任务时，重新上传应刷新静态画像而不新增 APK 行。"""
    import hashlib
    import uuid

    from fastapi import UploadFile

    init_db()
    payload = (f"profile-refresh-{uuid.uuid4()}".encode() * 160)[:2048]
    sha = hashlib.sha256(payload).hexdigest()
    with SessionLocal() as s:
        row = APKFile(
            filename="profile.apk", sha256=sha, size_bytes=len(payload),
            parse_status="success", storage_path="data/apks/profile-refresh.apk.enc",
            static_summary={"analysis_version": "basic-2", "old": True},
        )
        s.add(row)
        s.commit()
        apk_id = row.id

    refreshed = []
    monkeypatch.setattr(apk_service, "parse_apk", lambda row_id: refreshed.append(row_id))
    out = apk_service.save_apk(UploadFile(file=io.BytesIO(payload), filename="profile.apk"))

    assert out.id == apk_id
    assert refreshed == [apk_id]
    with SessionLocal() as s:
        assert s.query(APKFile).filter_by(sha256=sha).count() == 1


def test_reupload_existing_apk_with_task_keeps_historical_profile(monkeypatch):
    """已有检测任务时不重新解析，保证历史报告引用的静态画像不被改写。"""
    import hashlib
    import uuid

    from fastapi import UploadFile

    init_db()
    payload = (f"profile-history-{uuid.uuid4()}".encode() * 160)[:2048]
    sha = hashlib.sha256(payload).hexdigest()
    with SessionLocal() as s:
        row = APKFile(
            filename="history.apk", sha256=sha, size_bytes=len(payload),
            parse_status="success", storage_path="data/apks/profile-history.apk.enc",
            static_summary={"analysis_version": "basic-2", "old": True},
        )
        s.add(row)
        s.flush()
        apk_id = row.id
        s.add(DetectionTask(apk_id=apk_id, status="completed"))
        s.commit()

    refreshed = []
    monkeypatch.setattr(apk_service, "parse_apk", lambda row_id: refreshed.append(row_id))
    out = apk_service.save_apk(UploadFile(file=io.BytesIO(payload), filename="history.apk"))

    assert out.id == apk_id
    assert refreshed == []


def test_save_apk_tmp_name_survives_path_traversal_filename():
    """修复 2：客户端文件名含 .. 时临时文件不逃逸 apk_dir，storage_path 不含路径穿越。"""
    import uuid

    from fastapi import UploadFile

    init_db()
    payload = f"not an apk {uuid.uuid4()}".encode()
    row = apk_service.save_apk(UploadFile(file=io.BytesIO(payload), filename="..\\..\\evil.apk"))
    assert ".." not in row.storage_path
    apk_dir = (PROJECT_ROOT / config["storage"]["apk_dir"]).resolve()
    assert (PROJECT_ROOT / row.storage_path).resolve().parent == apk_dir


def test_parse_apk_unknown_exception_marks_failed(monkeypatch):
    """修复 3：解析期抛未知异常（非 ApkParseError）→ 行置 failed 且 parse_message 非空，不滞留 parsing。"""
    import uuid

    init_db()
    sha = uuid.uuid4().hex
    apk_dir = PROJECT_ROOT / config["storage"]["apk_dir"]
    apk_dir.mkdir(parents=True, exist_ok=True)
    enc_path = apk_dir / f"{sha}.apk.enc"
    enc_path.write_bytes(encrypt_bytes(b"\x00" * 2048, get_or_create_fernet_key()))

    def boom(_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(apk_service, "analyze_apk", boom)
    with SessionLocal() as s:
        row = APKFile(filename="a.apk", sha256=sha, size_bytes=2048,
                      parse_status="parsing", storage_path=str(enc_path.relative_to(PROJECT_ROOT)))
        s.add(row)
        s.commit()
        apk_id = row.id
    out = apk_service.parse_apk(apk_id)
    assert out.parse_status == "failed"
    assert out.parse_message and "RuntimeError" in out.parse_message


def test_parse_apk_persists_static_summary(monkeypatch):
    """增强后的上传期静态摘要应保存到 APK 行，供接口和后续检测使用。"""
    import uuid

    init_db()
    sha = uuid.uuid4().hex
    apk_dir = PROJECT_ROOT / config["storage"]["apk_dir"]
    apk_dir.mkdir(parents=True, exist_ok=True)
    enc_path = apk_dir / f"{sha}.apk.enc"
    enc_path.write_bytes(encrypt_bytes(b"\x00" * 2048, get_or_create_fernet_key()))
    expected_summary = {"analysis_version": "basic-2", "indicators": []}

    monkeypatch.setattr(apk_service, "analyze_apk", lambda _path: {
        "app_name": "demo",
        "package_name": "com.example.demo",
        "version_name": "1.0",
        "md5": "0" * 32,
        "permissions": [],
        "policy_raw": None,
        "sdk_list": [],
        "static_summary": expected_summary,
    })
    with SessionLocal() as s:
        row = APKFile(
            filename="summary.apk", sha256=sha, size_bytes=2048,
            parse_status="parsing", storage_path=str(enc_path.relative_to(PROJECT_ROOT)),
        )
        s.add(row)
        s.commit()
        apk_id = row.id

    out = apk_service.parse_apk(apk_id)

    assert out.parse_status == "success"
    assert out.static_summary == expected_summary
