"""Correlate device behavior and policy declarations into auditable evidence."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.detection_engines.frida_monitor import _policy_discloses_sdk_data


def _parse_time(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).replace(tzinfo=None)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def correlate_behavior_events(events: list[dict], timeline_records: list[dict], *, max_delta_seconds: float = 15) -> list[dict]:
    pages = [item for item in timeline_records if item.get("event_type") == "page_observed" and _parse_time(item.get("time"))]
    actions = [item for item in timeline_records if item.get("event_type") in {"action_completed", "click_completed", "back_completed"} and _parse_time(item.get("time"))]

    def nearest(records: list[dict], when: datetime) -> tuple[dict | None, float | None]:
        candidates = [(abs((_parse_time(item["time"]) - when).total_seconds()), item) for item in records]
        if not candidates:
            return None, None
        delta, item = min(candidates, key=lambda pair: pair[0])
        return (item, delta) if delta <= max_delta_seconds else (None, delta)

    rows = []
    for event in events:
        if event.get("type") not in {"api", "url", "native_load"}:
            continue
        when = _parse_time(event.get("observed_at") or event.get("time"))
        page, page_delta = nearest(pages, when) if when else (None, None)
        action, action_delta = nearest(actions, when) if when else (None, None)
        rows.append({
            **event,
            "page": (page or {}).get("page") or (page or {}).get("activity"),
            "action": (action or {}).get("action") or (action or {}).get("target"),
            "page_delta_seconds": page_delta,
            "action_delta_seconds": action_delta,
            "chain_complete": page is not None,
        })
    return rows


def build_declaration_actual_matrix(policy_text: str, correlated_events: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for event in correlated_events:
        actor = str(event.get("sdk") or "App 自身")
        data_type = str(event.get("data_type") or "")
        if not data_type:
            continue
        grouped.setdefault((actor, data_type), []).append(event)
    rows = []
    for (actor, data_type), events in sorted(grouped.items()):
        # SDK disclosure is legally actor-specific. App-self rows remain a
        # coverage matrix until purpose/scope extraction is independently proven.
        disclosed = _policy_discloses_sdk_data(policy_text, actor, data_type) if actor != "App 自身" else None
        rows.append({
            "actor": actor, "data_type": data_type, "disclosed": disclosed,
            "observed": True, "chain_complete": all(bool(item.get("chain_complete")) for item in events),
            "apis": sorted({str(item.get("api") or item.get("url") or "") for item in events if item.get("api") or item.get("url")}),
            "event_count": len(events),
        })
    return rows


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def enrich_behavior_evidence(ctx, findings, evidence_files: list[dict]) -> tuple[list[dict], list[str]]:
    timeline_records = []
    for path in sorted((ctx.data_dir / "timeline").glob("*.json")):
        record = _read_json(path)
        if isinstance(record, dict):
            timeline_records.append(record)
    events = []
    for item in evidence_files:
        if item.get("type") != "callstack":
            continue
        payload = _read_json(Path(item["path"]))
        if isinstance(payload, dict):
            events.extend(payload.get("events") or [])
    correlated = correlate_behavior_events(
        events,
        timeline_records,
        max_delta_seconds=float(
            (getattr(ctx, "cfg", {}) or {}).get("detection", {}).get("behavior_correlation_max_delta_seconds", 15)
        ),
    )

    dynamic_findings = [item for item in findings if item.kind in {
        "api_called_before_consent", "frequent_collection", "sdk_collection_not_disclosed", "overseas_transfer",
    }]
    tagged: list[str] = []
    gaps: list[str] = []
    delta_label = int(float(
        (getattr(ctx, "cfg", {}) or {}).get("detection", {}).get("behavior_correlation_max_delta_seconds", 15)
    ))
    for finding in dynamic_findings:
        matches = [row for row in correlated if (
            (finding.payload.get("registry_id") and row.get("registry_id") == finding.payload.get("registry_id"))
            or (finding.payload.get("api") and row.get("api") == finding.payload.get("api"))
            or (finding.payload.get("url") and row.get("url") == finding.payload.get("url"))
        )]
        if any(row.get("chain_complete") for row in matches):
            tagged.append(finding.kind)
        else:
            gaps.append(f"{finding.kind} 未找到 {delta_label} 秒内对应页面，已降级为待核验")

    ledger_path = ctx.data_dir / "behavior" / "behavior-ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps({"events": correlated}, ensure_ascii=False, indent=2), encoding="utf-8")

    from agent.detection_engines.policy_analyzer import _policy_source
    policy_text, _policy_source_name, policy_complete = _policy_source(ctx)
    if not policy_complete:
        policy_text = ""
    matrix = build_declaration_actual_matrix(policy_text, correlated)
    matrix_path = ctx.data_dir / "behavior" / "declaration-actual-matrix.json"
    matrix_path.write_text(json.dumps({"rows": matrix}, ensure_ascii=False, indent=2), encoding="utf-8")
    # Tag matrix for every SDK-disclosure finding present so lenient admission
    # can require the artifact even when time-correlation is incomplete.
    matrix_kinds = sorted({
        item.kind for item in findings
        if item.kind in {"sdk_collection_not_disclosed", "sdk_upload_undisclosed"}
    })
    undisclosed = sum(row.get("disclosed") is False for row in matrix)
    if (
        (matrix or correlated)
        and undisclosed == 0
        and not any(item.kind == "sdk_collection_not_disclosed" for item in findings)
    ):
        # Neutral completion for 3.9 when the matrix/correlation pass found no gap.
        ctx.runtime.setdefault("policy_audit_completions", [])
        if "declaration_behavior_reviewed" not in ctx.runtime["policy_audit_completions"]:
            ctx.runtime["policy_audit_completions"].append("declaration_behavior_reviewed")
    additions = [{
        "type": "behavior_ledger", "path": str(ledger_path),
        "meta": {"finding_kinds": tagged, "event_count": len(correlated), "correlated_count": sum(bool(row.get("chain_complete")) for row in correlated)},
    }, {
        "type": "consistency_matrix", "path": str(matrix_path),
        "meta": {"finding_kinds": matrix_kinds, "row_count": len(matrix), "undisclosed_count": undisclosed},
    }]
    return additions, gaps
