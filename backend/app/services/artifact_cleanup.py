"""Safe cleanup of detection artifacts stored under configured directories."""

import shutil
import logging
from pathlib import Path

from backend.app.config import PROJECT_ROOT, config

logger = logging.getLogger(__name__)


def _within_root(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
        return resolved
    except (OSError, ValueError):
        return None


def delete_task_artifacts(task_id: int, report_paths: list[str | None]) -> None:
    """Remove the evidence directory and PDF/HTML reports for one task."""
    evidence_root = PROJECT_ROOT / config["storage"]["evidence_dir"]
    evidence_dir = _within_root(evidence_root / str(task_id), evidence_root)
    if evidence_dir and evidence_dir.exists():
        try:
            shutil.rmtree(evidence_dir)
        except OSError:
            logger.warning("Task %s database data was deleted but evidence cleanup will need retry", task_id, exc_info=True)

    delete_report_artifacts(report_paths, task_id=task_id)


def delete_report_artifacts(report_paths: list[str | None], task_id: int | None = None) -> None:
    """Remove generated reports while preserving resumable device evidence."""
    export_root = PROJECT_ROOT / config["storage"]["export_dir"]
    for report_path in report_paths:
        if not report_path:
            continue
        pdf_path = _within_root(PROJECT_ROOT / report_path, export_root)
        if pdf_path:
            try:
                pdf_path.unlink(missing_ok=True)
                pdf_path.with_suffix(".html").unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Task %s report cleanup will need retry",
                    task_id if task_id is not None else "unknown",
                    exc_info=True,
                )


def delete_stored_apk(storage_path: str | None) -> None:
    """Remove an APK only when its path is inside the configured APK root."""
    if not storage_path:
        return
    apk_root = PROJECT_ROOT / config["storage"]["apk_dir"]
    apk_path = _within_root(PROJECT_ROOT / storage_path, apk_root)
    if apk_path and apk_path.is_file():
        apk_path.unlink(missing_ok=True)
