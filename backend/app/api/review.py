from fastapi import APIRouter, HTTPException

from agent.common.exceptions import TaskStateError
from backend.app.schemas.review import ReviewUpdate, ServerAuditImport
from backend.app.services import review_service

router = APIRouter(prefix="/api/tasks/{task_id}/reviews", tags=["review"])


@router.get("")
def get_reviews(task_id: int):
    try:
        return review_service.list_reviews(task_id)
    except TaskStateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{legal_key}")
def update_review(task_id: int, legal_key: str, body: ReviewUpdate):
    try:
        return review_service.save_review(task_id, legal_key, body.status, body.notes, body.evidence_ref)
    except TaskStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/server-events")
def get_server_events(task_id: int):
    try:
        return review_service.list_server_events(task_id)
    except TaskStateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/server-events/import")
def import_server_events(task_id: int, body: ServerAuditImport):
    try:
        return review_service.import_server_events(task_id, [event.model_dump() for event in body.events])
    except TaskStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
