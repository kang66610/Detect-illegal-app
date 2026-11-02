import json
import os
import re
from datetime import datetime
from pathlib import Path

from agent.ai_explorer.runtime_state import DetectionRunState, LoginStatus

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from agent.rule_engine.rule_matcher import MatchedViolation
from agent.common.backend_ports import (
    PROJECT_ROOT,
    Evidence,
    Report,
    Violation,
    config,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def report_confidence(runtime: dict) -> dict:
    """Decide whether the numeric score is a final or provisional result."""
    coverage = dict(runtime.get("scenario_coverage") or {})
    remaining = int(coverage.get("remaining") or len(coverage.get("remaining_items") or []))
    downgraded = sum(
        str(row.get("status") or "") == "downgraded"
        for row in (runtime.get("evidence_chain_adjudication") or [])
    )
    reasons: list[str] = []
    if not bool(runtime.get("coverage_complete", False)) or remaining:
        reasons.append(f"场景覆盖未完成（尚有 {remaining} 项）" if remaining else "存在覆盖缺口")
    if downgraded:
        reasons.append(f"有 {downgraded} 个候选缺少完整证据链")
    final = not reasons
    return {
        "status": "final" if final else "provisional",
        "final_score_available": final,
        "reason": "；".join(reasons) if reasons else "覆盖与证据链均满足最终报告门槛",
    }


def evidence_for_match(match: MatchedViolation, evidence_files: list[dict]) -> list[dict]:
    """Return only evidence explicitly emitted for this rule finding.

    A task may contain many screens and events. Associating all of them with
    every violation made historic reports look supported when they were not.
    Evidence producers tag ``finding_kind``/``finding_kinds``; unscoped
    artifacts remain available in the task timeline but are not rule evidence.
    """
    allowed_types = set(match.rule.evidence_fields)
    selected = []
    for evidence in evidence_files:
        if evidence.get("type") not in allowed_types:
            continue
        meta = evidence.get("meta") or {}
        kinds = {str(meta.get("finding_kind") or "")}
        kinds.update(str(kind) for kind in (meta.get("finding_kinds") or []))
        if match.finding.kind in kinds:
            selected.append(evidence)
    # Put directly inspectable screenshots first. Text/timeline/callstack
    # artifacts remain available as supporting evidence and are used when no
    # screenshot was emitted for this finding.
    return sorted(
        selected,
        key=lambda item: (0 if item.get("type") == "screenshot" else 1),
    )


def _evidence_fallback(match: MatchedViolation) -> str:
    """Human-readable proof when a finding has no screenshot artifact."""
    payload = dict(match.payload or {})
    preferred = (
        "page", "activity", "permission", "permission_label", "message",
        "business_action", "probe_action", "data_type", "sdk", "host",
        "count", "reason", "evidence_source",
    )
    parts = []
    for key in preferred:
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (dict, list, tuple, set)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        parts.append(f"{key}={value}")
        if len(parts) >= 6:
            break
    if parts:
        return "未取得可用截图；根据已记录的页面、操作和动态证据文字确认：" + "；".join(parts) + "。"
    return "未取得可用截图；该结论依据已记录的页面、操作或动态监测文字形成，请结合操作时间线核验。"


def _evidence_item(evidence: dict) -> dict:
    meta = evidence.get("meta") or {}
    event_type = str(meta.get("event_type") or "")
    labels = {
        "permission_prompt_without_purpose": "权限申请前置说明与系统弹窗",
        "permission_requested_immediately_after_consent": "同意隐私政策后立即申请权限",
        "permission_denial_function_blocked": "拒绝权限后的业务功能结果",
        "privacy_consent_clicked": "用户同意隐私政策",
    }
    artifact_labels = {
        "behavior_ledger": "页面—操作—敏感行为时间线",
        "consistency_matrix": "隐私政策声明—实际行为一致性矩阵",
        "callstack": "敏感 API 调用栈",
        "traffic": "网络传输记录",
    }
    useful = {key: value for key, value in meta.items() if key not in {
        "finding_kind", "finding_kinds", "event_type", "source", "timestamp"
    } and value not in (None, "", [], {})}
    detail = "；".join(f"{key}={value}" for key, value in useful.items())
    return {"type": evidence.get("type", "evidence"),
            "label": labels.get(event_type, event_type or artifact_labels.get(evidence.get("type"), evidence.get("type", "证据"))),
            "detail": detail or "已记录原始证据文件"}


def generate_report(session: Session, task, apk, matched: list[MatchedViolation],
                    score: int, breakdown: dict, evidence_files: list[dict], ctx) -> Report:
    """写入违规/证据/报告，渲染 HTML 并导出 PDF。"""
    # The workflow applies this gate before scoring; keep it at the report
    # boundary too so direct callers cannot emit an evidence-free violation.
    from agent.rule_engine.evidence_chain import keep_only_evidence_bound_matches
    matched, unbound_matches = keep_only_evidence_bound_matches(matched, evidence_files)
    if unbound_matches:
        ctx.runtime["unbound_rule_candidates"] = list(
            ctx.runtime.get("unbound_rule_candidates") or []
        ) + [item for item in unbound_matches if item not in (ctx.runtime.get("unbound_rule_candidates") or [])]
        ctx.runtime.setdefault("coverage_gaps", []).extend(
            f"{item['rule_id']} {item['reason']}" for item in unbound_matches
        )
        ctx.runtime["coverage_complete"] = False
        from agent.rule_engine.rule_loader import load_rules
        from agent.rule_engine.scoring import compute_score
        score, breakdown = compute_score(matched, load_rules())
    # 1. 违规 + 证据落库（每条违规 100% 附证据）
    now = datetime.utcnow()
    for i, m in enumerate(matched):
        v = Violation(
            task_id=task.id, category=m.rule.category, category_name=m.rule.category_name,
            rule_id=m.rule.rule_id,
            description=m.rule.rule_name, legal_basis=m.rule.legal_basis,
            risk_level=m.rule.risk_level, page=m.payload.get("page"),
            occurred_at=now, remediation_suggestion=m.rule.suggestion,
            detail=m.payload,
        )
        session.add(v)
        session.flush()
        # Only attach artifacts emitted for this finding, never all task files.
        for ev in evidence_for_match(m, evidence_files):
            rel = Path(ev["path"]).relative_to(PROJECT_ROOT) if Path(ev["path"]).is_absolute() else Path(ev["path"])
            session.add(Evidence(violation_id=v.id, type=ev["type"], file_path=str(rel), meta=ev["meta"]))

    # 2. 汇总 + 评分
    run_state = DetectionRunState.from_context(ctx)
    authenticated_paths_covered = bool(
        ctx.runtime.get("any_probe_login_verified")
        or run_state.login_status is LoginStatus.VERIFIED
    )
    summary = {
        "total": len(matched),
        "by_risk": {"高": 0, "中": 0, "低": 0},
        "by_category": {str(c): 0 for c in range(1, 7)},
        "coverage_gaps": list(dict.fromkeys(ctx.runtime.get("coverage_gaps", []))),
        "coverage_complete": bool(ctx.runtime.get("coverage_complete", not ctx.runtime.get("coverage_gaps"))),
        "engine_failure": dict(
            ctx.runtime.get("engine_failure") or ctx.runtime.get("failure") or {}
        ),
        "engine_failures": [
            dict(item) for item in (ctx.runtime.get("engine_failures") or [])
            if isinstance(item, dict)
        ],
        "external_static_status": dict(ctx.runtime.get("external_static_status") or {}),
        "scenario_coverage": dict(ctx.runtime.get("scenario_coverage") or {}),
        "evidence_chain_adjudication": list(ctx.runtime.get("evidence_chain_adjudication") or []),
        "evidence_cases": list(ctx.runtime.get("evidence_cases") or []),
        "unbound_rule_candidates": list(ctx.runtime.get("unbound_rule_candidates") or []),
        # Fixed six-dimensional method description and the concrete outcome
        # make a report reviewable without guessing how this particular run
        # was driven or why traversal ended.
        "audit_method": dict(ctx.runtime.get("audit_method") or {}),
        "audit_execution": dict(ctx.runtime.get("audit_execution") or {}),
        "authentication_scope": {
            "authenticated_paths_covered": authenticated_paths_covered,
            "login_gate_seen": bool(
                ctx.runtime.get("any_probe_login_gate_seen")
                or ctx.runtime.get("manual_login_waited")
                or ctx.runtime.get("manual_login_timed_out")
            ),
            "explanation": (
                "已覆盖登录后页面；首次启动、隐私政策、APK静态与启动期Frida证据不依赖登录。"
                if authenticated_paths_covered else
                "未覆盖登录后专属页面；首次启动、隐私政策、APK静态与启动期Frida证据仍可独立成立，账号内UI结论不得据此推断。"
            ),
        },
    }
    summary["report_confidence"] = report_confidence(ctx.runtime)
    from agent.rule_engine.capability_status import automatic_capability_status
    summary["automatic_capability_status"] = automatic_capability_status(
        ctx.runtime, [m.finding for m in matched], evidence_files,
    )
    for m in matched:
        summary["by_risk"][m.rule.risk_level] += 1
        summary["by_category"][str(m.rule.category)] += 1
    from agent.rule_engine.manual_baseline import compare_manual_baseline, compare_timeline_baseline
    baseline = compare_manual_baseline(getattr(apk, "package_name", None), {m.rule.rule_id for m in matched})
    if baseline:
        # A missing baseline rule is a recall gap, never a reason to fabricate
        # a violation in the automatic report.
        summary["manual_baseline"] = baseline
        missing = baseline["false_negative"]
        if missing:
            baseline_gap = "人工基准回归漏报：未形成以下已知问题的自动证据 " + "、".join(missing)
            summary["coverage_gaps"] = list(dict.fromkeys([
                *summary["coverage_gaps"],
                baseline_gap,
            ]))
            summary["coverage_complete"] = False
            ctx.runtime.setdefault("coverage_gaps", []).append(baseline_gap)
            ctx.runtime["coverage_complete"] = False
    timeline_baseline = compare_timeline_baseline(
        getattr(apk, "package_name", None), evidence_files,
    )
    if timeline_baseline:
        summary["timeline_baseline"] = timeline_baseline
        if not timeline_baseline["passed"]:
            timeline_gap = "固定时间线回归未通过：关键导航/场景决策链未完整重放"
            summary["coverage_gaps"] = list(dict.fromkeys([
                *summary["coverage_gaps"], timeline_gap,
            ]))
            summary["coverage_complete"] = False
            ctx.runtime.setdefault("coverage_gaps", []).append(timeline_gap)
            ctx.runtime["coverage_complete"] = False
    from agent.rule_engine.quality_metrics import build_quality_metrics
    summary["quality_metrics"] = build_quality_metrics(
        matched, evidence_files, ctx.runtime, baseline,
    )
    from agent.common.backend_ports import (
        ReviewItem,
        ServerAuditEvent,
        derive_server_audit_review_states,
    )
    review_states = {
        row.legal_key: row.status for row in session.query(ReviewItem).filter_by(task_id=task.id).all()
    }
    review_states.update(derive_server_audit_review_states(
        session.query(ServerAuditEvent).filter_by(task_id=task.id).all()
    ))
    from agent.rule_engine.adjudication import adjudication_counts, build_adjudication_matrix
    # 三态判定：默认只有真正形成证据才不算 not_covered。
    rule_cfg = config.get("rule_engine") or {}
    summary["adjudication"] = build_adjudication_matrix(
        matched, ctx.runtime, review_states,
        attempted_as_covered=bool(rule_cfg.get("attempted_scenario_as_covered", False)),
    )
    summary["adjudication_counts"] = adjudication_counts(summary["adjudication"])
    summary["report_confidence"] = report_confidence(ctx.runtime)
    app_label = apk.app_name or Path(apk.filename).stem or "APP"
    app_label = re.sub(r'[\\/:*?"<>|]+', "_", app_label).strip(" ._")[:32] or "APP"
    report_no = f"{app_label}-RPT-{now.strftime('%Y%m%d')}-{task.id:04d}"

    # 3. HTML + PDF
    export_dir = PROJECT_ROOT / config["storage"]["export_dir"]
    export_dir.mkdir(parents=True, exist_ok=True)
    html_path = export_dir / f"{report_no}.html"
    pdf_path = export_dir / f"{report_no}.pdf"
    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("report.html")
    for m in matched:
        scoped = evidence_for_match(m, evidence_files)
        screenshot_rows = [
            e for e in scoped
            if e["type"] == "screenshot" and Path(str(e.get("path") or "")).exists()
        ]
        m.screenshots = [Path(e["path"]).resolve().as_uri() for e in screenshot_rows]
        m.evidence_items = [_evidence_item(e) for e in scoped if e["type"] != "screenshot"]
        m.evidence_fallback = _evidence_fallback(m)
        m.evidence_limit = str(m.payload.get("evidence_limit") or "该结论仅适用于本次自动化实际覆盖的页面、操作和动态监测时间窗。")
    html_path.write_text(tpl.render(
        report_no=report_no, task=task, apk=apk, score=score, breakdown=breakdown,
        summary=summary, matched=matched, now=now,
        cn_numbers=list("一二三四五六七八九十") + ["十一", "十二", "十三", "十四", "十五", "十六"],
        header=config["report"].get("header") or {},
    ), encoding="utf-8")
    render_pdf(html_path, pdf_path, channel=config["report"].get("pdf_channel"))

    report = Report(task_id=task.id, score=score, weight_breakdown=breakdown,
                    summary=summary, report_no=report_no,
                    pdf_path=str(pdf_path.relative_to(PROJECT_ROOT)))
    session.add(report)
    session.commit()
    return report


def render_pdf(html_path: Path, out_path: Path, channel: str | None = "msedge") -> None:
    """HTML → PDF。channel 优先系统 Edge/Chrome，失败回退 playwright 自带 chromium。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = None
        launch_errors: list[str] = []
        try:
            if channel:
                try:
                    browser = p.chromium.launch(channel=channel)
                except Exception as exc:
                    launch_errors.append(str(exc).splitlines()[0])
            # Desktop Windows installations can have Edge installed but not
            # registered as a Playwright channel.  Use its explicit path
            # before requiring the optional Playwright browser download.
            if browser is None and os.name == "nt":
                for executable in (
                    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
                ):
                    if not executable.exists():
                        continue
                    try:
                        browser = p.chromium.launch(executable_path=str(executable))
                        break
                    except Exception as exc:
                        launch_errors.append(str(exc).splitlines()[0])
            if browser is None:
                browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(html_path.as_uri())
            page.pdf(
                path=str(out_path), format="A4", print_background=True,
                prefer_css_page_size=True,
            )
        except Exception as exc:
            detail = "; ".join(launch_errors[-2:])
            raise RuntimeError(f"无法启动 PDF 浏览器：{detail or str(exc).splitlines()[0]}") from exc
        finally:
            if browser is not None:
                browser.close()
