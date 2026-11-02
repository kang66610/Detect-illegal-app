"""Export a completed DetectionTask into the compact benchmark-run JSON shape."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.db import SessionLocal, init_db
from backend.app.models import DetectionTask, Report, Violation


def export_task_run(task_id: int) -> dict:
    init_db()
    with SessionLocal() as session:
        task = session.query(DetectionTask).filter_by(id=task_id).one()
        report = session.query(Report).filter_by(task_id=task_id).one()
        violations = session.query(Violation).filter_by(task_id=task_id).all()
        summary = dict(report.summary or {})
        adjudication_rows = summary.get("adjudication") or []
        adjudication = {
            str(row.get("legal_key")): str(row.get("state"))
            for row in adjudication_rows
            if row.get("legal_key")
        }
        return {
            "source": "real_task",
            "task_id": task_id,
            "package_name": getattr(task.apk, "package_name", None),
            "probe_profile": (task.progress or {}).get("probe_profile"),
            "detected_rule_ids": sorted({item.rule_id for item in violations if item.rule_id}),
            "adjudication": adjudication,
            "score": report.score,
            "report_no": report.report_no,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = export_task_run(args.task_id)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
