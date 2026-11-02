from datetime import datetime

import pytest

from agent.common.exceptions import TaskStateError
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask
from backend.app.services import review_service
from backend.app.services.task_cleanup import delete_task_records


def _task_id() -> int:
    init_db()
    with SessionLocal() as session:
        apk = APKFile(filename="review.apk", sha256="review-" + datetime.utcnow().isoformat(), size_bytes=1024,
                      parse_status="success", storage_path="data/apks/review.apk.enc")
        session.add(apk)
        session.flush()
        task = DetectionTask(apk_id=apk.id, status="completed")
        session.add(task)
        session.commit()
        return task.id


def test_review_checklist_has_all_31_items_and_requires_evidence_for_violation():
    task_id = _task_id()

    reviews = review_service.list_reviews(task_id)
    assert len(reviews) == 31
    assert {row["category"] for row in reviews} == {1, 2, 3, 4, 5, 6}
    with pytest.raises(TaskStateError, match="证据"):
        review_service.save_review(task_id, "6.1", "violation")

    saved = review_service.save_review(task_id, "6.1", "violation", notes="注销入口点击后无响应", evidence_ref="CASE-42")
    assert saved["status"] == "violation"
    assert saved["evidence_ref"] == "CASE-42"


def test_server_audit_import_requires_redaction_and_links_relevant_checkpoints():
    task_id = _task_id()
    imported = review_service.import_server_events(task_id, [{
        "event_type": "delete_completed", "occurred_at": datetime.utcnow(), "outcome": "completed",
        "reference": "AUDIT-2026-001", "details": {"request_hash": "a1b2c3"},
    }])
    assert imported["imported"] == 1
    assert {"6.1", "6.4"} <= set(imported["related_legal_keys"])
    assert review_service.list_server_events(task_id)[0]["reference"] == "AUDIT-2026-001"
    review_by_key = {item["legal_key"]: item for item in review_service.list_reviews(task_id)}
    assert review_by_key["6.4"]["status"] == "no_evidence_found"
    assert review_by_key["6.4"]["tri_state"] == "no_violation_evidence"

    with pytest.raises(TaskStateError, match="个人信息"):
        review_service.import_server_events(task_id, [{
            "event_type": "delete_completed", "occurred_at": datetime.utcnow(), "details": {"phone": "13800000000"},
        }])


def test_server_audit_import_is_idempotent_and_rejects_unknown_event_types():
    task_id = _task_id()
    event = {
        "event_type": "account_delete_completed", "occurred_at": datetime.utcnow(),
        "outcome": "completed", "reference": "AUDIT-IDEMPOTENT-1", "details": {"request_hash": "abc"},
    }
    first = review_service.import_server_events(task_id, [event])
    second = review_service.import_server_events(task_id, [event])
    assert first["imported"] == 1
    assert second["imported"] == 0
    assert second["duplicates"] == 1

    with pytest.raises(TaskStateError, match="不支持"):
        review_service.import_server_events(task_id, [{
            "event_type": "arbitrary_event", "occurred_at": datetime.utcnow(), "reference": "X",
        }])


def test_server_audit_events_derive_tri_state_only_for_semantically_decisive_outcomes():
    states = review_service.derive_server_audit_review_states([
        {"event_type": "account_delete_completed", "outcome": "completed"},
        {"event_type": "complaint_overdue", "outcome": "overdue"},
        {"event_type": "third_party_transfer", "outcome": "observed"},
    ])
    assert states["6.4"] == "no_evidence_found"
    assert states["6.3"] == "violation"
    assert "6.5" not in states
    assert "5.1" not in states
