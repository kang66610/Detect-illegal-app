"""Append-only, user-visible audit events for real detection engines."""

import json
from datetime import datetime


def record_event(ctx, source: str, event_type: str, **payload) -> dict:
    now = datetime.utcnow()
    directory = ctx.data_dir / "timeline"
    directory.mkdir(parents=True, exist_ok=True)
    record = {"time": now.isoformat(), "source": source, "event_type": event_type, **payload}
    stem = f"{now.strftime('%Y%m%dT%H%M%S%f')}-{source}-{event_type}"
    path = directory / f"{stem}.json"
    # Windows can expose the same wall-clock microsecond to consecutive calls.
    # Preserve the append-only timeline by disambiguating only collisions;
    # normal event filenames remain backward-compatible.
    sequence = 1
    while path.exists():
        path = directory / f"{stem}-{sequence:03d}.json"
        sequence += 1
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return {"type": "timeline", "path": str(path), "meta": record}
