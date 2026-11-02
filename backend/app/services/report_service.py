from backend.app.db import SessionLocal
from sqlalchemy.orm import joinedload

from backend.app.models import DetectionTask, Report, Violation


def get_report(task_id: int) -> tuple[Report, list[Violation]]:
    with SessionLocal() as s:
        report = s.query(Report).options(joinedload(Report.task).joinedload(DetectionTask.apk)).filter_by(task_id=task_id).one()
        violations = s.query(Violation).options(joinedload(Violation.evidences)).filter_by(task_id=task_id).all()
        return report, violations


def get_evidence_file(task_id: int, evidence_id: int):
    """Resolve one task-owned evidence file without permitting path traversal."""
    from pathlib import Path

    from backend.app.config import PROJECT_ROOT
    from backend.app.models import Evidence

    with SessionLocal() as s:
        row = (
            s.query(Evidence)
            .join(Violation, Evidence.violation_id == Violation.id)
            .filter(Evidence.id == evidence_id, Violation.task_id == task_id)
            .first()
        )
        if row is None:
            return None
        path = Path(row.file_path)
        resolved = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
        try:
            resolved.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            return None
        return resolved
