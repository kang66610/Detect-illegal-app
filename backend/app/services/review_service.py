"""Evidence-assisted manual and server-side reviews for the 31 legal checkpoints."""
from datetime import datetime
import hashlib
import json

from agent.rule_engine.recognition_coverage import ITEM_BY_KEY, RECOGNITION_ITEMS, category_name
from agent.common.exceptions import TaskStateError
from backend.app.db import SessionLocal
from backend.app.models import DetectionTask
from backend.app.models.review import ReviewItem, ServerAuditEvent

REVIEW_STATUSES = {"pending", "no_evidence_found", "violation", "not_applicable", "needs_server_evidence"}
SENSITIVE_DETAIL_KEYS = {"phone", "mobile", "imei", "imsi", "id_card", "account", "name", "location", "address", "email"}
ALLOWED_AUDIT_EVENT_TYPES = {
    "delete_requested", "delete_completed", "delete_failed",
    "account_delete_requested", "account_delete_completed", "account_delete_failed",
    "complaint_received", "complaint_completed", "complaint_overdue",
    "permission_changed", "consent_changed", "collection_started", "collection_stopped",
    "third_party_transfer", "third_party_delete_completed", "policy_changed",
}


def _task_or_raise(session, task_id: int) -> DetectionTask:
    task = session.query(DetectionTask).filter_by(id=task_id).first()
    if task is None:
        raise TaskStateError("检测任务不存在")
    return task


def list_reviews(task_id: int) -> list[dict]:
    with SessionLocal() as session:
        _task_or_raise(session, task_id)
        saved = {row.legal_key: row for row in session.query(ReviewItem).filter_by(task_id=task_id).all()}
        events = session.query(ServerAuditEvent).filter_by(task_id=task_id).order_by(ServerAuditEvent.occurred_at.desc()).all()
        derived_states = derive_server_audit_review_states(events)
        return [{
            "legal_key": item.key, "category": item.category, "category_name": category_name(item.category),
            "legal_basis": item.legal_basis, "title": item.title, "verification": item.verification,
            "evidence_scope": item.evidence_scope,
            "status": (
                saved[item.key].status
                if item.key in saved and saved[item.key].status not in {"pending", "needs_server_evidence"}
                else derived_states.get(item.key, saved[item.key].status if item.key in saved else "pending")
            ),
            "notes": saved[item.key].notes if item.key in saved else "",
            "evidence_ref": saved[item.key].evidence_ref if item.key in saved else "",
            "reviewed_at": saved[item.key].reviewed_at if item.key in saved else None,
            "server_event_count": _related_event_count(item.key, events),
            "tri_state": _tri_state_status(
                saved[item.key].status
                if item.key in saved and saved[item.key].status not in {"pending", "needs_server_evidence"}
                else derived_states.get(item.key, saved[item.key].status if item.key in saved else "pending")
            ),
        } for item in RECOGNITION_ITEMS]


def save_review(task_id: int, legal_key: str, status: str, notes: str = "", evidence_ref: str = "") -> dict:
    item = ITEM_BY_KEY.get(legal_key)
    if item is None:
        raise TaskStateError("认定条款编号不存在")
    if status not in REVIEW_STATUSES:
        raise TaskStateError("核验状态不合法")
    if status == "violation" and not (notes.strip() or evidence_ref.strip()):
        raise TaskStateError("标记发现违规时，必须填写核验说明或证据编号")
    with SessionLocal() as session:
        _task_or_raise(session, task_id)
        row = session.query(ReviewItem).filter_by(task_id=task_id, legal_key=legal_key).first()
        if row is None:
            row = ReviewItem(task_id=task_id, legal_key=legal_key)
            session.add(row)
        row.status = status
        row.notes = notes.strip()[:4000]
        row.evidence_ref = evidence_ref.strip()[:255]
        row.reviewed_at = datetime.utcnow()
        session.commit()
        return _review_payload(item, row, 0)


def import_server_events(task_id: int, events: list[dict]) -> dict:
    if len(events) > 1000:
        raise TaskStateError("单次最多导入 1000 条服务端审计事件")
    with SessionLocal() as session:
        _task_or_raise(session, task_id)
        rows = []
        duplicates = 0
        related: set[str] = set()
        for event in events:
            details = dict(event.get("details") or {})
            _ensure_redacted(details)
            event_type = str(event["event_type"]).strip()[:64]
            if event_type not in ALLOWED_AUDIT_EVENT_TYPES:
                raise TaskStateError(f"不支持的服务端审计事件类型：{event_type}")
            reference = str(event.get("reference") or "").strip()[:255]
            if not reference:
                raise TaskStateError("服务端审计事件必须提供脱敏审计编号 reference")
            duplicate = session.query(ServerAuditEvent).filter_by(
                task_id=task_id, event_type=event_type, reference=reference,
            ).first()
            if duplicate:
                duplicates += 1
                related.update(_related_keys(event_type))
                continue
            canonical = json.dumps({
                "event_type": event_type, "occurred_at": event["occurred_at"].isoformat(),
                "outcome": str(event.get("outcome") or "observed"), "reference": reference, "details": details,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            details["_integrity_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            row = ServerAuditEvent(
                task_id=task_id, event_type=event_type,
                occurred_at=event["occurred_at"], outcome=str(event.get("outcome") or "observed")[:48],
                reference=reference, details=details,
            )
            session.add(row)
            rows.append(row)
            related.update(_related_keys(event_type))
        session.commit()
        return {"imported": len(rows), "duplicates": duplicates, "related_legal_keys": sorted(related)}


def list_server_events(task_id: int) -> list[dict]:
    with SessionLocal() as session:
        _task_or_raise(session, task_id)
        rows = session.query(ServerAuditEvent).filter_by(task_id=task_id).order_by(ServerAuditEvent.occurred_at.desc()).all()
        return [{
            "id": row.id, "event_type": row.event_type, "occurred_at": row.occurred_at,
            "outcome": row.outcome, "reference": row.reference, "details": row.details,
            "related_legal_keys": sorted(_related_keys(row.event_type)),
        } for row in rows]


def derive_server_audit_review_states(events) -> dict[str, str]:
    """Translate only semantically decisive, redacted audit outcomes.

    Merely observing collection or transfer is not automatically compliant or
    non-compliant; those events remain evidence until consent/scope is known.
    """
    states: dict[str, str] = {}
    for event in events:
        event_type = event.get("event_type") if isinstance(event, dict) else event.event_type
        outcome = str(event.get("outcome") if isinstance(event, dict) else event.outcome).lower()
        if event_type in {"delete_completed", "account_delete_completed"} and outcome == "completed":
            states["6.4"] = "no_evidence_found"
        elif event_type in {"delete_failed", "account_delete_failed"}:
            states["6.4"] = "violation"
        elif event_type == "complaint_completed" and outcome == "completed":
            states["6.3"] = "no_evidence_found"
        elif event_type == "complaint_overdue":
            states["6.3"] = "violation"
        elif event_type == "third_party_transfer" and outcome in {"unauthorized", "without_consent"}:
            states["5.1"] = "violation"
        elif event_type == "collection_started" and outcome == "before_consent":
            states["3.1"] = "violation"
    return states


def _review_payload(item, row: ReviewItem, server_event_count: int) -> dict:
    return {
        "legal_key": item.key, "category": item.category, "category_name": category_name(item.category),
        "legal_basis": item.legal_basis, "title": item.title, "verification": item.verification,
        "evidence_scope": item.evidence_scope, "status": row.status, "notes": row.notes,
        "evidence_ref": row.evidence_ref, "reviewed_at": row.reviewed_at,
        "server_event_count": server_event_count,
        "tri_state": _tri_state(row),
    }


def _tri_state(row: ReviewItem | None) -> str:
    return _tri_state_status(row.status if row is not None else "pending")


def _tri_state_status(status: str) -> str:
    if status in {"pending", "needs_server_evidence"}:
        return "not_covered"
    if status == "violation":
        return "violation"
    return "no_violation_evidence"


def _related_keys(event_type: str) -> set[str]:
    if event_type.startswith("delete_") or event_type.startswith("account_"):
        return {"6.1", "6.2", "6.3", "6.4"}
    if event_type.startswith("complaint_"):
        return {"6.3"}
    if event_type.startswith("permission_"):
        return {"2.2", "3.5"}
    if event_type.startswith("consent_") or event_type.startswith("collection_"):
        return {"3.1", "3.2", "3.3", "4.4"}
    if event_type.startswith("third_party_"):
        return {"5.1", "5.2", "5.3"}
    if event_type.startswith("policy_"):
        return {"1.2", "2.2"}
    return set()


def _related_event_count(legal_key: str, events: list[ServerAuditEvent]) -> int:
    return sum(legal_key in _related_keys(event.event_type) for event in events)


def _ensure_redacted(value) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SENSITIVE_DETAIL_KEYS:
                raise TaskStateError(f"服务端审计详情不得包含个人信息字段：{key}；请改为哈希或脱敏引用")
            _ensure_redacted(child)
    elif isinstance(value, list):
        for child in value:
            _ensure_redacted(child)
