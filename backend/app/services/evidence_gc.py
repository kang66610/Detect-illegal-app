"""Safe garbage collection for task-owned evidence directories.

Evidence is written outside the database so a task can accumulate screenshots,
timelines and dynamic traces without inflating SQLite.  This module only
touches direct children whose names encode a numeric task id (including the
legacy ``<id>_...`` format).  Unknown names and live task ids are never
modified.  Candidates are quarantined first; a later pass permanently removes
only quarantine entries created by this module after the retention period.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import shutil
import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import PROJECT_ROOT, config
from backend.app.models import DetectionTask


logger = logging.getLogger(__name__)

DEFAULT_GRACE_HOURS = 72
DEFAULT_TRASH_RETENTION_DAYS = 7
DEFAULT_MAX_DIRS_PER_RUN = 500

_TASK_DIR_RE = re.compile(r"^(?P<task_id>\d+)(?:_.+)?$")
_TRASH_ENTRY_RE = re.compile(
    r"^orphan-(?P<stamp>\d{8}T\d{6}Z)-(?P<nonce>[0-9a-f]{8})--(?P<original>\d+(?:_.+)?)$"
)


def _task_id_from_name(name: str) -> int | None:
    match = _TASK_DIR_RE.fullmatch(str(name))
    if match is None:
        return None
    try:
        return int(match.group("task_id"))
    except (TypeError, ValueError):
        return None


def _epoch(value: float | int | datetime | None) -> float:
    if value is None:
        return time.time()
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return float(value)


def _direct_child(path: Path, root: Path) -> Path | None:
    try:
        resolved_root = root.resolve()
        resolved = path.resolve()
        if resolved.parent != resolved_root:
            return None
        return resolved
    except OSError:
        return None


def scan_orphan_directories(
    evidence_root: Path,
    *,
    live_task_ids: set[int],
    now: float | int | datetime | None = None,
    grace_seconds: float = DEFAULT_GRACE_HOURS * 3600,
) -> list[Path]:
    """Return expired, task-shaped directories with no live DB task owner."""
    root = evidence_root.resolve()
    if not root.is_dir():
        return []
    current = _epoch(now)
    candidates: list[Path] = []
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        logger.warning("无法读取证据目录：%s", root, exc_info=True)
        return []
    for child in children:
        if child.name == ".trash" or not child.is_dir():
            continue
        task_id = _task_id_from_name(child.name)
        if task_id is None or task_id in live_task_ids:
            continue
        safe_child = _direct_child(child, root)
        if safe_child is None:
            continue
        try:
            age = current - safe_child.stat().st_mtime
        except OSError:
            continue
        if age >= max(0.0, float(grace_seconds)):
            candidates.append(safe_child)
    return candidates


def quarantine_orphan_directories(
    candidates: list[Path],
    evidence_root: Path,
    *,
    now: float | int | datetime | None = None,
) -> dict:
    """Move validated orphan directories into a recoverable quarantine."""
    root = evidence_root.resolve()
    trash = root / ".trash"
    result = {"moved": 0, "errors": [], "moved_names": []}
    if not candidates:
        return result
    # Never follow a pre-existing symlink for a destructive move.  The
    # quarantine directory must remain directly under the configured root.
    if trash.exists() and trash.is_symlink():
        result["errors"].append("隔离目录是符号链接，已跳过以避免越界写入")
        return result
    try:
        trash.mkdir(parents=True, exist_ok=True)
        trash = trash.resolve()
        if trash.parent != root:
            result["errors"].append("隔离目录不在证据根目录内，已跳过")
            return result
    except OSError as exc:
        result["errors"].append(f"无法创建隔离目录：{exc}")
        return result
    stamp = datetime.fromtimestamp(_epoch(now), tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for candidate in candidates:
        safe_candidate = _direct_child(candidate, root)
        if safe_candidate is None or safe_candidate.name == ".trash" or _task_id_from_name(safe_candidate.name) is None:
            continue
        if not safe_candidate.is_dir():
            continue
        destination = trash / f"orphan-{stamp}-{uuid4().hex[:8]}--{safe_candidate.name}"
        try:
            shutil.move(str(safe_candidate), str(destination))
        except OSError as exc:
            result["errors"].append(f"{safe_candidate.name}: {exc}")
            logger.warning("孤儿证据目录隔离失败：%s", safe_candidate, exc_info=True)
            continue
        result["moved"] += 1
        result["moved_names"].append(safe_candidate.name)
    return result


def purge_quarantined_evidence(
    trash_root: Path,
    *,
    now: float | int | datetime | None = None,
    retention_seconds: float = DEFAULT_TRASH_RETENTION_DAYS * 86400,
) -> dict:
    """Permanently remove only managed quarantine entries past retention."""
    trash = trash_root.resolve()
    result = {"deleted": 0, "errors": [], "deleted_names": []}
    if not trash.is_dir():
        return result
    current = _epoch(now)
    try:
        children = sorted(trash.iterdir(), key=lambda item: item.name)
    except OSError:
        logger.warning("无法读取证据隔离目录：%s", trash, exc_info=True)
        return result
    for child in children:
        match = _TRASH_ENTRY_RE.fullmatch(child.name)
        if match is None or not child.is_dir() or _direct_child(child, trash) is None:
            continue
        try:
            created = datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if current - created < max(0.0, float(retention_seconds)):
            continue
        try:
            shutil.rmtree(child)
        except OSError as exc:
            result["errors"].append(f"{child.name}: {exc}")
            logger.warning("证据隔离目录永久清理失败：%s", child, exc_info=True)
            continue
        result["deleted"] += 1
        result["deleted_names"].append(child.name)
    return result


def cleanup_orphan_evidence(
    session: Session,
    *,
    evidence_root: Path | None = None,
    now: float | int | datetime | None = None,
    grace_hours: float = DEFAULT_GRACE_HOURS,
    trash_retention_days: float = DEFAULT_TRASH_RETENTION_DAYS,
    max_dirs: int = DEFAULT_MAX_DIRS_PER_RUN,
    dry_run: bool = False,
) -> dict:
    """Reconcile evidence directories against DB tasks and quarantine safely."""
    root = (evidence_root or (PROJECT_ROOT / config["storage"]["evidence_dir"])).resolve()
    live_task_ids = {
        int(task_id)
        for task_id in session.execute(select(DetectionTask.id)).scalars()
    }
    candidates = scan_orphan_directories(
        root,
        live_task_ids=live_task_ids,
        now=now,
        grace_seconds=max(0.0, float(grace_hours)) * 3600,
    )
    limit = max(0, int(max_dirs))
    limited = candidates[:limit] if limit else []
    result = {
        "root": str(root),
        "live_task_count": len(live_task_ids),
        "candidate_count": len(candidates),
        "limited_count": len(limited),
        "candidate_names": [path.name for path in limited],
        "dry_run": bool(dry_run),
        "moved": 0,
        "purged": 0,
        "errors": [],
    }
    if not dry_run:
        moved = quarantine_orphan_directories(limited, root, now=now)
        result["moved"] = moved["moved"]
        result["errors"].extend(moved["errors"])
        purged = purge_quarantined_evidence(
            root / ".trash",
            now=now,
            retention_seconds=max(0.0, float(trash_retention_days)) * 86400,
        )
        result["purged"] = purged["deleted"]
        result["errors"].extend(purged["errors"])
    return result
