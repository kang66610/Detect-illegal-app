"""Database cleanup order for task-owned records under SQLite foreign keys."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Evidence, Report, Violation
from backend.app.models.review import ReviewItem, ServerAuditEvent


def delete_task_records(session: Session, task_id: int) -> None:
    """Delete evidence -> violations -> reports before deleting the task itself."""
    violation_ids = select(Violation.id).where(Violation.task_id == task_id)
    session.query(Evidence).filter(Evidence.violation_id.in_(violation_ids)).delete(synchronize_session=False)
    session.query(Violation).filter_by(task_id=task_id).delete(synchronize_session=False)
    session.query(Report).filter_by(task_id=task_id).delete(synchronize_session=False)
    session.query(ReviewItem).filter_by(task_id=task_id).delete(synchronize_session=False)
    session.query(ServerAuditEvent).filter_by(task_id=task_id).delete(synchronize_session=False)
    session.flush()
