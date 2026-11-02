"""Privacy-safe network observations correlated with sensitive API events."""
from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

from agent.detection_engines.sdk_detector import identify_sdk_from_stack


def normalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path or "/", "", ""))
    except ValueError:
        return ""


def build_network_evidence(ctx, events: list[dict], finding_kinds: list[str]) -> dict:
    api_events = [event for event in events if event.get("type") == "api"]
    third_party = [str(item).lower() for item in ctx.cfg.get("network", {}).get("third_party_domains", [])]
    overseas = [str(item).lower() for item in ctx.cfg.get("network", {}).get("overseas_domains", [])]
    rows = []
    for event in events:
        if event.get("type") != "url": continue
        when = float(event.get("time") or 0)
        preceding = {
            str(item.get("data_type")) for item in api_events
            if item.get("data_type") and 0 <= when - float(item.get("time") or 0) <= 5000
        }
        normalized = normalize_url(str(event.get("url") or "")); host = (urlsplit(normalized).hostname or "").lower()
        sdk = identify_sdk_from_stack(
            str(event.get("stack") or ""),
            app_package=getattr(getattr(ctx, "apk", None), "package_name", None),
        )
        rows.append({
            "time": event.get("time"), "observed_at": event.get("observed_at"), "url": normalized,
            "host": host, "third_party": any(host == domain or host.endswith("." + domain) for domain in third_party),
            "overseas": any(host == domain or host.endswith("." + domain) for domain in overseas),
            "sdk": (sdk or {}).get("name"), "preceding_data_types": sorted(preceding),
            "transport": str(event.get("transport") or urlsplit(normalized).scheme or "").lower(),
            "method": str(event.get("method") or ""),
            "credential_fields": sorted({str(item) for item in event.get("credential_fields") or [] if item}),
            "authorization_present": bool(event.get("authorization_present")),
            "body_class": str(event.get("body_class") or "")[:160],
        })
    runtime = getattr(ctx, "runtime", {}) or {}
    profile = str(runtime.get("probe_profile") or "observe")
    rows = [{**row, "probe_profile": profile} for row in rows]
    path = ctx.data_dir / "traffic" / profile / "network-events.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"probe_profile": profile, "events": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    aggregate = ctx.data_dir / "traffic" / "network-events.json"
    previous = []
    if aggregate.is_file():
        try:
            previous = list(json.loads(aggregate.read_text(encoding="utf-8")).get("events") or [])
        except (OSError, json.JSONDecodeError):
            previous = []
    aggregate.write_text(json.dumps({"events": previous + rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"type": "traffic", "path": str(path), "meta": {
        "finding_kinds": finding_kinds, "event_count": len(rows),
        "third_party_count": sum(row["third_party"] for row in rows), "overseas_count": sum(row["overseas"] for row in rows),
    }}
