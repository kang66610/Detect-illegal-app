import io
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.main import app


def test_upload_invalid_file_returns_400_with_reason():
    import uuid
    client = TestClient(app)
    # 内容唯一：sha256 有唯一约束，重复上传同一内容会撞键
    payload = f"not an apk {uuid.uuid4()}".encode()
    resp = client.post("/api/apks", files={"file": ("fake.apk", payload, "application/octet-stream")})
    assert resp.status_code == 200  # 校验失败也入库（invalid 状态），见 apk_service 设计
    data = resp.json()
    assert data["parse_status"] == "invalid"
    assert "文件" in data["parse_message"]  # 校验失败原因（过小/非 zip/无清单）


def test_task_create_requires_parsed_apk():
    client = TestClient(app)
    resp = client.post("/api/tasks", json={"apk_id": 99999, "industry": "通用", "mode": "fast"})
    assert resp.status_code in (400, 404)


def test_runtime_endpoint_exposes_modes_without_exposing_secrets():
    client = TestClient(app)
    resp = client.get("/api/system/runtime")
    assert resp.status_code == 200
    data = resp.json()
    assert data["explorer"] == "real"
    assert data["monitor"] == "real"
    assert isinstance(data["llm_configured"], bool)
    assert "api_key" not in data


def test_task_delete_does_not_mask_internal_errors_as_not_found(monkeypatch):
    """A cleanup failure must not be presented to users as a missing task."""
    from backend.app.api import task as task_api

    def fail_delete(_task_id: int):
        raise RuntimeError("evidence file is locked")

    monkeypatch.setattr(task_api.task_service, "delete_task", fail_delete)
    client = TestClient(app)
    response = client.delete("/api/tasks/123")
    assert response.status_code == 500
    assert "删除任务失败" in response.json()["detail"]


def test_task_terminate_endpoint_requests_early_stop(monkeypatch):
    from backend.app.api import task as task_api

    monkeypatch.setattr(
        task_api.task_service,
        "terminate_task",
        lambda task_id: SimpleNamespace(
            id=task_id, apk_id=1, app_name="Demo", package_name="com.demo",
            industry="通用", mode="deep", status="canceled", queue_position=None,
            progress={"termination_requested": True}, current_page=None,
            pages_covered=0, scenarios_triggered=0, failure_reason="用户终止检测",
            created_at=datetime.utcnow(), started_at=None, finished_at=datetime.utcnow(),
        ),
    )
    client = TestClient(app)

    response = client.post("/api/tasks/123/terminate")

    assert response.status_code == 200
    assert response.json()["status"] == "canceled"


def test_report_evidence_endpoint_serves_task_owned_file(monkeypatch, tmp_path):
    from backend.app.api import report as report_api

    proof = tmp_path / "proof.png"
    proof.write_bytes(b"proof")
    monkeypatch.setattr(report_api.report_service, "get_evidence_file", lambda _task_id, _evidence_id: proof)

    response = TestClient(app).get("/api/reports/123/evidence/7")

    assert response.status_code == 200
    assert response.content == b"proof"


def test_report_docx_endpoint_returns_generated_document_after_evidence_wiring(monkeypatch):
    from backend.app.api import report as report_api

    report = SimpleNamespace(report_no="Demo-RPT-1")
    violation = SimpleNamespace(id=9, evidences=[])
    monkeypatch.setattr(report_api.report_service, "get_report", lambda _task_id: (report, [violation]))
    monkeypatch.setattr(report_api.review_service, "list_reviews", lambda _task_id: [])
    monkeypatch.setattr(report_api.review_service, "list_server_events", lambda _task_id: [])
    monkeypatch.setattr(
        report_api.report_docx,
        "build_report_docx",
        lambda *_args, **_kwargs: io.BytesIO(b"docx-bytes"),
    )

    response = TestClient(app).get("/api/reports/123/docx")

    assert response.status_code == 200
    assert response.content == b"docx-bytes"
    assert "filename*=UTF-8''Demo-RPT-1.docx" in response.headers["content-disposition"]
