import copy
import json
import time
from datetime import datetime
from pathlib import Path

from agent.agent_core.task_manager import (
    TIMING_PROGRESS_KEYS,
    freeze_active_timing,
    set_status,
)
from agent.agent_core.stage_dispatch import StageDispatcher
from agent.agent_core.workflow_stages import run_reporting_stage, run_static_analysis_stage
from agent.agent_core.audit_contract import finish_audit, start_audit, summarize_evidence
from agent.agent_core.failure_classification import (
    FailureCategory,
    classify_failure,
    failure_progress,
)
from agent.common.exceptions import EngineUnavailableError
from agent.common.event_log import record_event
from agent.common.logger import get_logger
from agent.detection_engines.base import DetectionContext, EngineResult
from agent.detection_engines.appium_explorer import AppiumExplorerEngine
from agent.detection_engines.frida_monitor import FridaMonitorEngine
from agent.detection_engines.external_static import ExternalStaticAnalysisHub, FlowDroidAdapter
from agent.rule_engine.scenario_plan import scenario_plan_for_probe
from agent.ai_explorer.runtime_state import DetectionRunState, ProbePhase
from agent.common.utils import decrypt_to_temp, get_or_create_fernet_key
from agent.common.backend_ports import (
    PROJECT_ROOT,
    DetectionTask,
    SessionLocal,
    config,
    delete_task_artifacts,
)

logger = get_logger("workflow")

STAGES = ["preparing", "installing", "static_analysis", "traversing", "analyzing", "reporting"]


def _requires_coverage_failure(findings: list, stats: dict) -> bool:
    """Coverage gaps constrain a report; they are not a task failure.

    A traversal can finish every reachable safe route while an external
    browser, a login gate, or a device permission path remains unavailable.
    The report generator already records this as a coverage-limited result.
    Treating the absence of findings as an exception discarded that useful
    audit output and made the UI falsely say the inspection was interrupted.
    """
    return False


def _run_static_engines(ctx: DetectionContext) -> list:
    """Run static engines in the UI's static-analysis stage.

    FlowDroid can take several minutes on a production APK. It must never run
    inside the Appium/LLM traversal stage, otherwise the UI falsely appears to
    be stuck in AI traversal before a device session even exists.
    """
    results = []
    if not ctx.apk_path:
        return results
    static_result = ExternalStaticAnalysisHub([
        FlowDroidAdapter(ctx.cfg.get("flowdroid", {})),
    ]).run(ctx)
    results.append(static_result)
    external_gaps = static_result.stats.get("coverage_gaps") or []
    if external_gaps:
        ctx.runtime.setdefault("coverage_gaps", []).extend(external_gaps)
        ctx.runtime["coverage_complete"] = False
    return results


def _run_detection_engines(ctx: DetectionContext) -> list:
    """Run the production Appium + Frida + LLM evidence pipeline."""
    results = []
    explorer = AppiumExplorerEngine()
    monitor = FridaMonitorEngine()

    def engine_failure_result(error: Exception, *, stage: str) -> EngineResult:
        classification = classify_failure(
            error,
            stage=stage,
            recovery_attempted=bool(ctx.runtime.get("runtime_session_recovery_attempted")),
        )
        # Unknown programming errors must still reach workflow's code-bug
        # handling. Device/runtime/LLM failures are coverage facts and should
        # leave a truthful, reportable result instead of discarding the audit.
        if classification.category not in {
            FailureCategory.DEVICE_UNAVAILABLE,
            FailureCategory.SESSION_LOST,
            FailureCategory.RECOVERY_EXHAUSTED,
            FailureCategory.LLM_UNAVAILABLE,
        }:
            raise error
        failure = {
            "category": classification.category.value,
            "recoverable": classification.recoverable,
            "coverage_gap": classification.coverage_gap,
            "reason": classification.reason,
        }
        ctx.runtime["engine_failure"] = failure
        failures = ctx.runtime.setdefault("engine_failures", [])
        if failure not in failures:
            failures.append(dict(failure))
        ctx.runtime.update(failure_progress(ctx.runtime, classification))
        event = record_event(
            ctx,
            "appium" if stage == "traversing" else "engine",
            "engine_failure_classified",
            category=classification.category.value,
            recoverable=classification.recoverable,
            coverage_gap=classification.coverage_gap,
            reason=classification.reason,
        )
        return EngineResult(
            evidence_files=[event],
            stats={
                "coverage_complete": False,
                "coverage_gaps": [classification.coverage_gap],
                "failure": {
                    "category": classification.category.value,
                    "recoverable": classification.recoverable,
                    "coverage_gap": classification.coverage_gap,
                    "reason": classification.reason,
                },
            },
        )

    # 先安装 APK，Frida 再 spawn，才能捕获 App 冷启动的敏感调用。
    try:
        explorer.prepare(ctx)
    except Exception as exc:
        return [engine_failure_result(exc, stage="preparing")]
    frida_started = False
    frida_unavailable: str | None = None
    profile = str(ctx.runtime.get("probe_profile") or "observe")
    try:
        monitor.start(ctx)
        frida_started = True
    except EngineUnavailableError as exc:
        # Frida is an evidence adapter, not the traversal controller.  A
        # bounded spawn/attach failure must not prevent Appium from exploring
        # the app and producing a coverage-limited report.
        failure_stage = getattr(monitor, "last_failure_stage", None)
        package = str(getattr(ctx.apk, "package_name", "") or "")
        if failure_stage == "spawning" and getattr(explorer, "client", None) is not None:
            fallback_event = record_event(
                ctx, "frida", "spawn_fallback_starting", package=package,
                reason="spawn 未返回，先由 Appium 启动应用，再附加已运行进程",
            )
            try:
                explorer.client.activate(package)
                monitor.start(ctx, spawn_target_override=False)
                frida_started = True
                record_event(ctx, "frida", "spawn_fallback_succeeded", package=package)
            except EngineUnavailableError as fallback_exc:
                frida_unavailable = str(fallback_exc)[:500]
                fallback_event = record_event(
                    ctx, "frida", "spawn_fallback_failed", package=package,
                    error=frida_unavailable,
                )
        else:
            frida_unavailable = str(exc)[:500]
            fallback_event = record_event(
                ctx, "frida", "monitor_unavailable", package=package,
                stage=failure_stage or "startup", error=frida_unavailable,
            )
        if not frida_started:
            ctx.runtime.setdefault("frida_phase_status", {})[profile] = {
                "available": False,
                "error": frida_unavailable or str(exc)[:300],
                "event_count": 0,
            }
            gap = f"Frida 动态监测未附加（{frida_unavailable or str(exc)[:300]}），本次仅形成 Appium/静态证据"
            ctx.runtime.setdefault("coverage_gaps", []).append(gap)
            ctx.runtime["coverage_complete"] = False
            results.append(EngineResult(
                evidence_files=[fallback_event],
                stats={
                    "frida_available": False,
                    "frida_events": 0,
                    "coverage_complete": False,
                    "coverage_gaps": [gap],
                },
            ))
    try:
        try:
            results.append(explorer.run(ctx))
        except Exception as exc:
            results.append(engine_failure_result(exc, stage="traversing"))
    finally:
        if frida_started:
            monitor_result = monitor.stop(ctx)
            results.append(monitor_result)
            ctx.runtime.setdefault("frida_phase_status", {})[profile] = {
                "available": True,
                "error": "",
                "event_count": int(monitor_result.stats.get("frida_events") or 0),
            }
    return results


def _emit_deferred_finding_evidence(ctx: DetectionContext, findings: list) -> list[dict]:
    """Persist deterministic deferred facts with the same rule-scoped contract."""
    evidence: list[dict] = []
    for finding in findings:
        kind = str(getattr(finding, "kind", "") or "")
        if kind == "permission_industry_mismatch":
            path = ctx.data_dir / "behavior" / "permission-list.json"
        elif kind in {"no_delete_entry", "targeted_push_no_opt_out", "first_run_notice_missing"}:
            screenshot = Path(str((
                ctx.runtime.get("privacy_hub_screenshot")
                if kind != "first_run_notice_missing"
                else ctx.runtime.get("initial_surface_screenshot")
            ) or ""))
            try:
                screenshot.resolve().relative_to(ctx.data_dir.resolve())
            except (OSError, ValueError):
                continue
            if not screenshot.is_file():
                continue
            evidence.append({
                "type": "screenshot", "path": str(screenshot),
                "meta": {"finding_kind": kind, "source": (
                    "initial_surface_observation"
                    if kind == "first_run_notice_missing" else "privacy_hub_observation"
                )},
            })
            if kind in {"targeted_push_no_opt_out", "first_run_notice_missing"}:
                timeline_path = ctx.data_dir / "behavior" / f"{kind}.json"
                timeline_path.parent.mkdir(parents=True, exist_ok=True)
                timeline_path.write_text(
                    json.dumps(dict(finding.payload or {}), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                evidence.append({
                    "type": "timeline", "path": str(timeline_path),
                    "meta": {"finding_kind": kind, "source": "deferred_observation"},
                })
            continue
        else:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(dict(finding.payload or {}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        evidence.append({
            "type": "permission_list",
            "path": str(path),
            "meta": {"finding_kind": kind, "source": "manifest_permissions"},
        })
    return evidence


def _is_task_canceled(task_id: int) -> bool:
    """供长时间的真实遍历轮询取消状态，避免 API 取消要等到整条遍历结束。"""
    with SessionLocal() as check_session:
        task = check_session.query(DetectionTask).filter_by(id=task_id).first()
        # A task may be deleted after it has been paused. Treat a missing
        # record as a stop signal so a worker cannot resume writing artifacts.
        return task is None or task.status == "canceled"


def _is_task_termination_requested(task_id: int) -> bool:
    """Read the cooperative termination flag without racing the worker session."""
    with SessionLocal() as check_session:
        task = check_session.query(DetectionTask).filter_by(id=task_id).first()
        return bool(
            task is None
            or task.status == "canceled"
            or (task.progress or {}).get("termination_requested")
        )


def _is_task_paused(task_id: int) -> bool:
    with SessionLocal() as check_session:
        task = check_session.query(DetectionTask).filter_by(id=task_id).first()
        return task is not None and task.status == "paused"


_PROBE_PROGRESS_KEYS = ("probe_profile", "probe_profiles", "pair_group", "pair_role", "pair_label")
_COVERAGE_STATE_RANK = {
    "pending": 0,
    "attempted": 1,
    "requires_login": 2,
    "blocked_external": 2,
    "requires_server_audit": 2,
    "not_applicable": 2,
    "evidence_observed": 3,
}
_SCENARIO_COVERAGE_GAP_PREFIX = "场景义务尚未完成："
_FRIDA_GENERIC_GAP_PREFIX = "Frida 动态监测未附加（"

# These values describe one installed Appium session/navigation pass.  They
# must not leak from the deny profile into the allow profile.  Evidence and
# document ledgers are intentionally absent: policies already read in profile
# one stay de-duplicated. Profile two starts a fresh traversal/Appium session,
# while the installed app data and authenticated state remain available.
_PROBE_PHASE_RUNTIME_KEYS = {
    "pages_covered", "seen_text", "last_screen_text", "last_appium_action",
    "last_business_trigger_action", "pending_deep_probe",
    "background_probe_started_ms", "traversal_termination",
    "runtime_session_recovery_attempted", "runtime_session_recovery_attempts",
    "runtime_session_recoveries", "runtime_session_recovery_status",
    "runtime_recovery_checkpoint", "runtime_checkpoint_replayed",
    "reactivation_replay_attempted",
    "navigation_replay_required",
    "manual_login_waited", "manual_login_verified", "manual_login_timed_out",
    "manual_login_waited_gate_fingerprints",
    "manual_login_ocr_blob", "manual_login_proof", "login_gate_revisit_returned",
    "login_skip_back_done", "skip_third_party_channel_login",
    "public_app_surface_seen", "home_idle_cycles", "root_route_attempts",
    "global_target_attempts", "frontier_recovery_attempts",
    "frontier_back_loop_deferred", "frontier_back_loop_deferred_count",
    "generic_scroll_attempts", "generic_scroll_exhausted",
    "hub_privacy_scrolls", "privacy_hub_search_exhausted",
    "hub_reentry_honors", "visited_privacy_hub_tabs", "visited_top_level_route_keys",
    "document_scroll_progress", "external_document_progress",
    "logout_confirmation_dismiss_attempts",
    "privacy_path_route_keys", "redress_entry_route_keys",
    "consecutive_wait_fingerprint", "consecutive_waits", "app_exit_cancel_done",
    "consent_dialog_seen", "consent_observed", "consent_accepted",
    "consent_timestamp_ms", "consent_checkbox_clicks", "consent_button_retries",
    "initial_consent_baseline_seen", "initial_consent_surface", "prechecked_consent_reported",
    "consent_policy_docs_deferred_to_hub", "permission_prompt_seen_after_consent",
    "permission_denied_at_ms", "permission_denied_labels",
    "permission_denial_retry_targets", "sensitive_permission_probe_attempts",
    "pending_permission_denial_probe", "permission_denial_probe_status",
    "permission_denial_probe_terminal",
    "sensitive_permission_probe_targets", "business_trigger_retry_attempts",
    "permission_rationale_retries",
    "special_permissions_observed", "special_permission_probe_results",
    "file_picker_camera_probed", "screen_text_by_surface", "screenshot_by_surface",
    "interaction_failures", "target_interaction_failures",
    "pending_action_validation", "action_no_effect_counts",
    "sdk_observation_dwell_armed", "sdk_observation_dwell_done",
    "sdk_observe_backs", "sdk_observe_waits", "sdk_observation_permissions_granted",
    "allow_permission_verified", "last_permission_label", "last_permission_rationale_text",
    "business_action_sequence",
}


def _reset_probe_phase_runtime(runtime: dict) -> None:
    """Reset only per-session state before another permission profile."""
    for key in _PROBE_PHASE_RUNTIME_KEYS:
        runtime.pop(key, None)


def _with_probe_progress(current: dict | None, **updates) -> dict:
    merged = dict(current or {})
    meta = {key: merged[key] for key in _PROBE_PROGRESS_KEYS if key in merged}
    merged.update(updates)
    merged.update(meta)
    return merged


def _probe_profiles_for_task(task, cfg: dict) -> list[str]:
    progress = dict(task.progress or {})
    profiles = [str(item) for item in (progress.get("probe_profiles") or []) if item]
    if profiles:
        if len(profiles) == 2 and set(profiles) == {"allow", "deny"}:
            return ["deny", "allow"]
        return profiles
    probe = str(progress.get("probe_profile") or "")
    if probe in {"allow", "deny", "observe"}:
        return [probe]
    if probe == "dual":
        return ["deny", "allow"]
    action = str((cfg.get("detection") or {}).get("permission_probe_action") or "deny")
    return [action] if action in {"allow", "deny", "observe"} else ["deny"]


def _merge_scenario_coverage(left: dict | None, right: dict | None) -> dict:
    left = dict(left or {})
    right = dict(right or {})
    if not left:
        return right
    if not right:
        return left
    items = {str(row.get("item")): dict(row) for row in left.get("items") or []}
    for row in right.get("items") or []:
        item = str(row.get("item") or "")
        current = items.get(item)
        if current is None or _COVERAGE_STATE_RANK.get(str(row.get("state")), 0) >= _COVERAGE_STATE_RANK.get(str(current.get("state")), 0):
            items[item] = dict(row)
    rows = list(items.values())
    terminal = {"evidence_observed", "blocked_external", "requires_login", "requires_server_audit", "not_applicable"}
    completed = [str(row.get("item")) for row in rows if row.get("state") == "evidence_observed"]
    remaining = [str(row.get("item")) for row in rows if str(row.get("state") or "pending") not in terminal]
    attempted = sorted(set(left.get("attempted_items") or []) | set(right.get("attempted_items") or []))
    return {
        "planned": max(int(left.get("planned") or 0), int(right.get("planned") or 0), len(rows)),
        "attempted": len(attempted),
        "attempted_items": attempted,
        "completed": len(completed),
        "completed_items": sorted(set(completed)),
        "remaining": len(remaining),
        "remaining_items": remaining,
        "items": rows,
    }


def _is_scenario_coverage_gap(gap: str) -> bool:
    return str(gap or "").startswith(_SCENARIO_COVERAGE_GAP_PREFIX)


def _reconcile_scenario_coverage_gaps(runtime: dict, scenario_coverage: dict) -> None:
    """Rebuild scenario gaps from the final merged coverage snapshot.

    Appium emits a snapshot-level gap at the end of each permission phase.
    Those phase-local messages must not survive when a later phase completes
    the same scenario. Other gaps (documents, Frida, login, evidence chains)
    remain durable and are intentionally preserved.
    """
    remaining = [
        str(item)
        for item in (scenario_coverage.get("remaining_items") or [])
        if str(item)
    ]
    gaps = [
        str(gap)
        for gap in (runtime.get("coverage_gaps") or [])
        if gap and not _is_scenario_coverage_gap(str(gap))
    ]
    if remaining:
        gaps.append(_SCENARIO_COVERAGE_GAP_PREFIX + ", ".join(dict.fromkeys(remaining)))
    runtime["coverage_gaps"] = list(dict.fromkeys(gaps))
    runtime["coverage_complete"] = not bool(runtime["coverage_gaps"])


def _reconcile_frida_phase_coverage(runtime: dict) -> None:
    """Replace stale task-wide Frida failure copy with phase-scoped truth."""
    statuses = dict(runtime.get("frida_phase_status") or {})
    if not statuses:
        return
    available = [name for name, row in statuses.items() if bool((row or {}).get("available"))]
    failed = [name for name, row in statuses.items() if not bool((row or {}).get("available"))]
    runtime["frida_available_any"] = bool(available)
    runtime["frida_available_all"] = not bool(failed)
    labels = {"deny": "拒绝权限阶段", "allow": "允许权限阶段", "observe": "观察阶段"}
    gaps = [
        str(gap) for gap in (runtime.get("coverage_gaps") or [])
        if gap and not str(gap).startswith(_FRIDA_GENERIC_GAP_PREFIX)
    ]
    for name in failed:
        error = str((statuses.get(name) or {}).get("error") or "未知错误")[:240]
        gaps.append(f"{labels.get(name, name)} Frida 动态监测未附加（{error}）")
    runtime["coverage_gaps"] = list(dict.fromkeys(gaps))
    if failed:
        runtime["coverage_complete"] = False


def _update_traversal_progress(task_id: int, step: int, pages_covered: int,
                               page_limit: int, current_page: str) -> None:
    """Publish page-level progress while real Appium/LLM traversal is running."""
    with SessionLocal() as progress_session:
        task = progress_session.query(DetectionTask).filter_by(id=task_id).first()
        if task is None or task.status != "traversing":
            return
        task.current_page = current_page
        task.pages_covered = pages_covered
        task.progress = _with_probe_progress(
            task.progress,
            stage="traversing",
            percent=min(70, 50 + int(step * 20 / max(page_limit, 1))),
            step=step,
            limit=page_limit,
        )
        progress_session.commit()


def run_task(task_id: int) -> None:
    """运行真实设备检测、规则匹配、评分与报告生成管线。"""
    with SessionLocal() as s:
        task = s.query(DetectionTask).filter_by(id=task_id).first()
        if task is None:
            logger.error("任务不存在：%s", task_id)
            return
        apk = task.apk
        # ruling（controller）：queued=测试/直调路径，preparing=worker 领取路径
        if task.status not in ("queued", "preparing"):
            logger.info("任务 %s 状态为 %s，跳过", task_id, task.status)
            return
        cfg = copy.deepcopy(config)
        probe_profiles = _probe_profiles_for_task(task, cfg)
        data_dir = PROJECT_ROOT / cfg["storage"]["evidence_dir"] / str(task_id)
        resume_requested = bool((task.progress or {}).get("resume_requested"))
        # Display numbers/task ids may be reused after deletion. Never let a
        # new run inherit screenshots or evidence from an older task
        # that previously owned the same numeric directory.
        if not resume_requested:
            delete_task_artifacts(task_id, [])
        ctx = DetectionContext(task=task, apk=apk, cfg=cfg, data_dir=data_dir)
        ctx.runtime["resume_requested"] = resume_requested
        start_audit(ctx)
        ctx.runtime["is_canceled"] = lambda: _is_task_canceled(task_id)
        ctx.runtime["is_terminated"] = lambda: _is_task_termination_requested(task_id)
        ctx.runtime["is_paused"] = lambda: _is_task_paused(task_id)
        ctx.runtime["update_traversal"] = lambda step, pages, limit, page: _update_traversal_progress(
            task_id, step, pages, limit, page
        )
        decrypted_apk = None
        try:
            results = []
            findings = []
            evidence_files = []
            matched = []
            score = 100
            breakdown = {"base": 100, "total_deduction": 0, "items": []}
            stage_dispatcher = StageDispatcher({
                "preparing": lambda _state: None,
                "installing": lambda _state: None,
                "static_analysis": lambda state: run_static_analysis_stage(
                    state, decrypt=state["decrypt"], run_static=state["run_static"],
                ),
                "reporting": lambda state: run_reporting_stage(
                    state, generate=state["generate"],
                ),
            })
            for stage in STAGES:
                # 取消竞态防护：每轮先从库中重查状态，避免内存旧状态覆盖 API 侧的 canceled
                current_status = s.query(DetectionTask.status).filter_by(id=task_id).scalar()
                if current_status is None:
                    logger.info("Task %s was deleted; stopping pipeline", task_id)
                    return
                if current_status == "canceled":
                    logger.info("任务 %s 已被取消，停止管线", task_id)
                    return
                if current_status == "paused":
                    logger.info("任务 %s 已暂停，停止管线", task_id)
                    return
                if _is_task_termination_requested(task_id):
                    # A termination request is cooperative: finish the
                    # current safe boundary, but do not start another costly
                    # static/device phase.  Analysis/reporting still run so
                    # evidence already collected can become a partial report.
                    ctx.runtime["termination_requested"] = True
                    ctx.runtime.setdefault("audit_execution", {})["termination"] = {
                        "kind": "user_terminated",
                        "reason": "用户提前终止检测，报告仅覆盖终止前已形成的证据",
                    }
                # ruling（controller）：已处于该 stage 时跳过自环（状态机无自环，Task 4 已定设计）
                task = s.query(DetectionTask).filter_by(id=task_id).one()
                if stage != current_status:
                    set_status(s, task, stage)
                task.progress = _with_probe_progress(
                    task.progress, stage=stage, percent=STAGES.index(stage) * 100 // len(STAGES),
                )
                s.commit()

                if stage in {"preparing", "installing"}:
                    stage_dispatcher.dispatch(stage, {})
                elif stage == "traversing":
                    if ctx.runtime.get("termination_requested"):
                        logger.info("任务 %s 已请求终止，跳过新的设备遍历阶段", task_id)
                        continue
                    # Appium/Frida 需要临时明文 APK，任务结束后立即清理。
                    if decrypted_apk is None:
                        decrypted_apk = decrypt_to_temp(
                            PROJECT_ROOT / apk.storage_path,
                            get_or_create_fernet_key(cfg),
                            data_dir / "runtime",
                        )
                        ctx.apk_path = decrypted_apk
                    merged_coverage = dict(ctx.runtime.get("scenario_coverage") or {})
                    merged_completed = set(ctx.runtime.get("scenario_completed_items") or [])
                    merged_seen = str(ctx.runtime.get("seen_text") or "")
                    total_pages = 0
                    total_scenarios = 0
                    last_current_page = ""
                    for index, profile in enumerate(probe_profiles):
                        if index:
                            ctx.runtime["prior_probe_login_timed_out"] = bool(
                                ctx.runtime.get("manual_login_timed_out")
                            )
                            ctx.runtime["prior_probe_login_verified"] = bool(
                                ctx.runtime.get("manual_login_verified")
                            )
                            ctx.runtime["prior_probe_login_gate_fingerprints"] = sorted({
                                str(item).strip()
                                for item in (ctx.runtime.get("manual_login_waited_gate_fingerprints") or [])
                                if str(item).strip()
                            })
                            _reset_probe_phase_runtime(ctx.runtime)
                            # Phase two must obtain fresh allow-side evidence for
                            # its comparison items.  The aggregate is retained in
                            # ``merged_completed`` and merged back after the run.
                            ctx.runtime["scenario_completed_items"] = []
                        ctx.cfg.setdefault("detection", {})["permission_probe_action"] = profile
                        DetectionRunState.from_context(ctx).begin_phase(ProbePhase(profile))
                        ctx.runtime["permission_only_phase"] = profile == "allow" and len(probe_profiles) > 1
                        ctx.runtime["active_device_scenario_plan"] = scenario_plan_for_probe(profile)
                        task = s.query(DetectionTask).filter_by(id=task_id).one()
                        phase_label = "拒绝权限阶段" if profile == "deny" else (
                            "允许权限阶段" if profile == "allow" else "仅观察阶段"
                        )
                        task.progress = _with_probe_progress(
                            task.progress,
                            active_probe_profile=profile,
                            phase_index=index + 1,
                            phase_count=len(probe_profiles),
                            message=f"第 {index + 1}/{len(probe_profiles)} 阶段：{phase_label}",
                        )
                        s.commit()
                        page_offset = total_pages
                        ctx.runtime["update_traversal"] = (
                            lambda step, pages, limit, page, *, _index=index, _offset=page_offset:
                            _update_traversal_progress(
                                task_id,
                                _index * limit + step,
                                _offset + pages,
                                max(1, len(probe_profiles) * limit),
                                page,
                            )
                        )
                        phase_results = _run_detection_engines(ctx)
                        ctx.runtime["any_probe_login_gate_seen"] = bool(
                            ctx.runtime.get("any_probe_login_gate_seen")
                            or ctx.runtime.get("manual_login_waited")
                            or ctx.runtime.get("manual_login_timed_out")
                        )
                        if profile == "allow" and not ctx.runtime.get("allow_permission_verified"):
                            gap = "允许权限阶段未形成经过系统状态核验的授权结果"
                            ctx.runtime.setdefault("coverage_gaps", []).append(gap)
                            ctx.runtime["coverage_complete"] = False
                        ctx.runtime["any_probe_login_verified"] = bool(
                            ctx.runtime.get("any_probe_login_verified")
                            or ctx.runtime.get("manual_login_verified")
                            or ctx.runtime.get("prior_probe_login_verified")
                        )
                        for item in phase_results:
                            item.stats["probe_profile"] = profile
                        results.extend(phase_results)
                        merged_seen = f"{merged_seen} {ctx.runtime.get('seen_text') or ''}".strip()
                        ctx.runtime["seen_text"] = merged_seen
                        merged_completed |= set(ctx.runtime.get("scenario_completed_items") or [])
                        ctx.runtime["scenario_completed_items"] = sorted(merged_completed)
                        merged_coverage = _merge_scenario_coverage(
                            merged_coverage, ctx.runtime.get("scenario_coverage") or {},
                        )
                        ctx.runtime["scenario_coverage"] = merged_coverage
                        phase_pages = max(
                            [int(item.stats.get("pages_covered") or 0) for item in phase_results]
                            or [int(ctx.runtime.get("pages_covered") or 0)]
                        )
                        phase_scenarios = max(
                            [int(item.stats.get("scenarios") or 0) for item in phase_results]
                            or [0]
                        )
                        phase_current_page = next((
                            str(item.stats.get("current_page") or "")
                            for item in reversed(phase_results)
                            if item.stats.get("current_page")
                        ), "")
                        total_pages += phase_pages
                        total_scenarios += phase_scenarios
                        last_current_page = phase_current_page or last_current_page
                        ctx.runtime["pages_covered"] = total_pages
                        if callable(ctx.runtime.get("is_terminated")) and ctx.runtime["is_terminated"]():
                            ctx.runtime["termination_requested"] = True
                            logger.info("任务 %s 收到终止请求，停止后续权限阶段", task_id)
                            break
                        if index + 1 < len(probe_profiles):
                            from agent.agent_core.probe_phase_integrity import assess_phase_integrity

                            integrity = assess_phase_integrity(
                                phase_results,
                                current_profile=profile,
                                next_profile=probe_profiles[index + 1],
                            )
                            if not integrity.allow_next_phase:
                                ctx.runtime["phase_transition_blocked"] = {
                                    "from": profile,
                                    "to": probe_profiles[index + 1],
                                    "coverage_gap": integrity.coverage_gap,
                                    "reason": integrity.reason,
                                }
                                ctx.runtime.setdefault("coverage_gaps", []).append(
                                    integrity.coverage_gap
                                )
                                ctx.runtime["coverage_complete"] = False
                                task = s.query(DetectionTask).filter_by(id=task_id).one()
                                task.progress = _with_probe_progress(
                                    task.progress,
                                    coverage_complete=False,
                                    phase_transition_blocked=dict(
                                        ctx.runtime["phase_transition_blocked"],
                                    ),
                                    coverage_gaps=list(dict.fromkeys([
                                        *(task.progress or {}).get("coverage_gaps", []),
                                        integrity.coverage_gap,
                                    ])),
                                    message=integrity.reason,
                                )
                                s.commit()
                                logger.warning("任务 %s %s", task_id, integrity.reason)
                                break
                    engine_failures = [
                        dict(result.stats.get("failure") or {})
                        for result in results
                        if isinstance(result.stats.get("failure"), dict)
                    ]
                    if engine_failures:
                        # EngineResult is the adapter contract boundary.  Do
                        # not rely on an individual explorer mutating ctx: the
                        # report generator reads runtime, so aggregate typed
                        # failures here for every adapter implementation.
                        ctx.runtime["engine_failure"] = dict(engine_failures[-1])
                        runtime_failures = ctx.runtime.setdefault("engine_failures", [])
                        for failure in engine_failures:
                            if failure not in runtime_failures:
                                runtime_failures.append(dict(failure))
                        # Operational engine failures are coverage-limited,
                        # not necessarily task failures. Preserve their
                        # machine-readable classification in task progress so
                        # the UI/report does not lose it at terminalization.
                        task = s.query(DetectionTask).filter_by(id=task_id).one()
                        failure_gaps = list(dict.fromkeys([
                            *[str(gap) for gap in (task.progress or {}).get("coverage_gaps") or [] if gap],
                            *[
                                str(failure.get("coverage_gap"))
                                for failure in engine_failures
                                if failure.get("coverage_gap")
                            ],
                        ]))
                        task.progress = _with_probe_progress(
                            task.progress,
                            failure=engine_failures[-1],
                            failures=engine_failures,
                            coverage_complete=False,
                            coverage_gaps=failure_gaps,
                        )
                        s.commit()
                    findings = [f for result in results for f in result.findings]
                    evidence_files = [e for result in results for e in result.evidence_files]
                    # Engine results are the contract boundary.  The real
                    # Appium explorer also writes these values to runtime,
                    # but merging them here keeps coverage truth intact for
                    # every engine and for future adapters.
                    engine_coverage_gaps = [
                        str(gap)
                        for result in results
                        for gap in (result.stats.get("coverage_gaps") or [])
                        if gap
                    ]
                    engine_reports_incomplete_coverage = any(
                        result.stats.get("coverage_complete") is False for result in results
                    )
                    engine_non_scenario_gaps = [
                        gap for gap in engine_coverage_gaps
                        if not _is_scenario_coverage_gap(gap)
                    ]
                    if engine_non_scenario_gaps:
                        ctx.runtime.setdefault("coverage_gaps", []).extend(engine_non_scenario_gaps)
                    if engine_non_scenario_gaps or (engine_reports_incomplete_coverage and not engine_coverage_gaps):
                        ctx.runtime["coverage_complete"] = False
                    _reconcile_frida_phase_coverage(ctx.runtime)
                    scenario_coverage = dict(ctx.runtime.get("scenario_coverage") or {})
                    if scenario_coverage:
                        completed_items = set(ctx.runtime.get("scenario_completed_items") or [])
                        attempted_items = set(scenario_coverage.get("attempted_items") or [])
                        queue_items = [dict(row) for row in scenario_coverage.get("items") or []]
                        for row in queue_items:
                            # Frida can complete a scenario after Appium has
                            # produced its snapshot.  Synchronise that one
                            # fact without erasing a more informative blocked
                            # state such as an unavailable external document.
                            if str(row.get("item")) in completed_items and row.get("state") != "blocked_external":
                                row["state"] = "evidence_observed"
                                row["state_label"] = "已形成设备证据"
                                row["reason"] = "已取得该场景对应的设备侧观察证据"
                        terminal = {"evidence_observed", "blocked_external", "requires_login", "requires_server_audit", "not_applicable"}
                        remaining_items = [
                            str(row.get("item")) for row in queue_items if str(row.get("state") or "pending") not in terminal
                        ]
                        completed_queue_items = [
                            str(row.get("item")) for row in queue_items if row.get("state") == "evidence_observed"
                        ]
                        scenario_coverage.update({
                            "planned": len(queue_items) or int(scenario_coverage.get("planned") or 0),
                            "attempted": len(attempted_items),
                            "completed": len(completed_queue_items),
                            "completed_items": sorted(set(completed_queue_items) | completed_items),
                            "remaining": len(remaining_items),
                            "remaining_items": remaining_items,
                            "items": queue_items,
                        })
                        ctx.runtime["scenario_coverage"] = scenario_coverage
                        _reconcile_scenario_coverage_gaps(ctx.runtime, scenario_coverage)
                    from agent.rule_engine.behavior_evidence import enrich_behavior_evidence
                    behavior_evidence, behavior_gaps = enrich_behavior_evidence(ctx, findings, evidence_files)
                    evidence_files.extend(behavior_evidence)
                    if behavior_gaps:
                        ctx.runtime.setdefault("coverage_gaps", []).extend(behavior_gaps)
                        ctx.runtime["coverage_complete"] = False
                    from agent.rule_engine.evidence_chain import (
                        build_evidence_chain_adjudication,
                        keep_only_complete_evidence_chains,
                    )
                    # Preserve a decision for every candidate before the
                    # admission gate removes incomplete chains.  This is
                    # operational audit data, not a violation list.
                    # 证据链准入口径走配置，默认 strict（与 config.py 一致）；
                    # 需要放宽时显式设置 PRIVACY_EVIDENCE_CHAIN_MODE=lenient，
                    # 不要把宽松当成隐式默认——报告的可信度取决于这里。
                    chain_mode = str((ctx.cfg.get("rule_engine") or {}).get("evidence_chain_mode") or "strict")
                    ctx.runtime["evidence_chain_adjudication"] = build_evidence_chain_adjudication(
                        findings, evidence_files, strict_ui=True, mode=chain_mode,
                    )
                    from agent.rule_engine.evidence_reconciliation import reconcile_evidence
                    ctx.runtime["evidence_cases"] = reconcile_evidence(
                        findings, evidence_files, ctx.runtime["evidence_chain_adjudication"],
                    )
                    findings, chain_gaps = keep_only_complete_evidence_chains(
                        findings, evidence_files, strict_ui=True, mode=chain_mode,
                    )
                    if chain_gaps:
                        ctx.runtime.setdefault("coverage_gaps", []).extend(chain_gaps)
                        ctx.runtime["coverage_complete"] = False
                    stats = {key: value for result in results for key, value in result.stats.items()}
                    stats.update({
                        "pages_covered": total_pages,
                        "scenarios": total_scenarios,
                        "current_page": last_current_page,
                        "probe_profiles": list(probe_profiles),
                    })
                    termination = dict(ctx.runtime.get("traversal_termination") or {})
                    finish_audit(
                        ctx,
                        kind=str(termination.get("kind") or "adapter_completed"),
                        reason=str(termination.get("reason") or "遍历适配器已完成本次可安全执行的路径"),
                        stats=stats,
                    )
                    ctx.runtime["audit_execution"]["evidence_counts"] = summarize_evidence(evidence_files)
                    task.pages_covered = int(stats.get("pages_covered", 0))
                    task.scenarios_triggered = int(stats.get("scenarios", 0))
                    task.current_page = stats.get("current_page")
                    s.commit()
                    if _requires_coverage_failure(findings, stats):
                        # Kept as a defensive compatibility branch.  Coverage
                        # gaps are report metadata, never an engine failure.
                        logger.warning("Task %s has a legacy coverage failure signal", task_id)
                elif stage == "static_analysis":
                    if ctx.runtime.get("termination_requested"):
                        logger.info("任务 %s 已请求终止，跳过新的静态分析阶段", task_id)
                        continue
                    stage_state = {
                        "decrypted_apk": decrypted_apk,
                        "results": results,
                        "decrypt": lambda: decrypt_to_temp(
                            PROJECT_ROOT / apk.storage_path,
                            get_or_create_fernet_key(cfg), data_dir / "runtime",
                        ),
                        "run_static": lambda: _run_static_engines(ctx),
                    }
                    stage_dispatcher.dispatch(stage, stage_state)
                    decrypted_apk = stage_state["decrypted_apk"]
                    ctx.apk_path = decrypted_apk
                elif stage == "analyzing":
                    from agent.detection_engines.policy_analyzer import run_policy_audit
                    from agent.rule_engine.rule_matcher import match_rules
                    from agent.rule_engine.rule_loader import load_rules
                    from agent.rule_engine.scoring import compute_score

                    policy_findings, policy_evidence, policy_gaps = run_policy_audit(ctx)
                    findings.extend(policy_findings)
                    evidence_files.extend(policy_evidence)
                    if policy_gaps:
                        ctx.runtime.setdefault("coverage_gaps", []).extend(policy_gaps)
                        ctx.runtime["coverage_complete"] = False
                    from agent.rule_engine.deferred_findings import collect_deferred_findings
                    from agent.rule_engine.recognition_contract import apply_completions
                    deferred, completions = collect_deferred_findings(ctx)
                    evidence_files.extend(_emit_deferred_finding_evidence(ctx, deferred))
                    known = {item.kind for item in findings}
                    findings.extend([item for item in deferred if item.kind not in known])
                    # Policy/deferred candidates are created after the Appium
                    # stage, so they must pass the same admission gate here.
                    # Without this second pass, RULE_2_1_SDK/3.8 could reach
                    # scoring with zero scoped artifacts.
                    from agent.rule_engine.evidence_chain import (
                        build_evidence_chain_adjudication,
                        keep_only_complete_evidence_chains,
                    )
                    chain_mode = str(
                        (ctx.cfg.get("rule_engine") or {}).get("evidence_chain_mode") or "strict"
                    )
                    ctx.runtime["evidence_chain_adjudication"] = build_evidence_chain_adjudication(
                        findings, evidence_files, strict_ui=True, mode=chain_mode,
                    )
                    from agent.rule_engine.evidence_reconciliation import reconcile_evidence
                    ctx.runtime["evidence_cases"] = reconcile_evidence(
                        findings, evidence_files, ctx.runtime["evidence_chain_adjudication"],
                    )
                    findings, final_chain_gaps = keep_only_complete_evidence_chains(
                        findings, evidence_files, strict_ui=True, mode=chain_mode,
                    )
                    if final_chain_gaps:
                        ctx.runtime.setdefault("coverage_gaps", []).extend(final_chain_gaps)
                        ctx.runtime["coverage_complete"] = False
                    apply_completions(ctx.runtime, [
                        *completions,
                        *[item.kind for item in findings],
                        *(ctx.runtime.get("policy_audit_completions") or []),
                    ])
                    if not policy_findings and ctx.runtime.get("policy_document_read_complete"):
                        apply_completions(ctx.runtime, [
                            "purpose_disclosed", "complaint_channel_ok", "complaint_deadline_disclosed",
                        ])
                    rules = load_rules()
                    matched = match_rules(rules, findings)
                    from agent.rule_engine.evidence_chain import keep_only_evidence_bound_matches
                    matched, unbound_matches = keep_only_evidence_bound_matches(
                        matched, evidence_files,
                    )
                    if unbound_matches:
                        ctx.runtime["unbound_rule_candidates"] = unbound_matches
                        ctx.runtime.setdefault("evidence_chain_adjudication", []).extend(
                            {
                                "finding_kind": row["finding_kind"],
                                "rule_id": row["rule_id"],
                                "status": "downgraded",
                                "reason": row["reason"],
                                "requirements": {"rule_scoped_artifact": True},
                                "missing": ["规则专属证据"],
                                "notes": [],
                            }
                            for row in unbound_matches
                        )
                        ctx.runtime.setdefault("coverage_gaps", []).extend(
                            f"{row['rule_id']} {row['reason']}" for row in unbound_matches
                        )
                        ctx.runtime["coverage_complete"] = False
                    score, breakdown = compute_score(matched, rules)
                elif stage == "reporting":
                    from agent.rule_engine.report_generator import generate_report
                    stage_dispatcher.dispatch(stage, {
                        "session": s, "task": task, "apk": apk, "matched": matched,
                        "score": score, "breakdown": breakdown,
                        "evidence": evidence_files, "ctx": ctx,
                        "generate": generate_report,
                    })

                # Cooperative yield between stages without an artificial demo delay.
                time.sleep(0)
            # 取消竞态防护：落 completed 前再查一次库，取消则不再覆盖状态
            # Refresh after the reporting stage: a user can pause/cancel from
            # the UI while the PDF renderer is still returning.
            s.expire_all()
            task = s.query(DetectionTask).filter_by(id=task_id).first()
            if task is None:
                logger.info("Task %s was deleted; not marking complete", task_id)
                return
            if task.status == "paused":
                logger.info("任务 %s 在收尾阶段已是 %s，放弃写入完成状态", task_id, task.status)
                return
            termination_requested = bool(
                (task.progress or {}).get("termination_requested")
            ) or bool(ctx.runtime.get("termination_requested")) or task.status == "canceled"
            if termination_requested:
                task.progress = {
                    **dict(task.progress or {}),
                    "termination_report_ready": True,
                }
                set_status(
                    s,
                    task,
                    "canceled",
                    reason="用户终止检测；已生成终止前的违规情况报告，Worker 已释放设备",
                )
            else:
                set_status(s, task, "completed")
            # ``set_status`` records the terminal timestamp but intentionally
            # leaves stage-specific progress untouched.  Publish the terminal
            # progress explicitly so a completed task cannot remain displayed
            # as ``reporting · 83%`` after the report has been generated.
            terminal_progress_meta = {
                key: (task.progress or {})[key]
                for key in (
                    *_PROBE_PROGRESS_KEYS,
                    *TIMING_PROGRESS_KEYS,
                    "failure", "failures", "coverage_complete", "coverage_gaps",
                    "phase_transition_blocked",
                    "termination_requested", "termination_reason", "termination_report_ready",
                )
                if key in (task.progress or {})
            }
            task.progress = {
                **terminal_progress_meta,
                    "stage": "completed", "percent": 100,
                    "message": (
                        "检测已终止，终止前违规报告已生成"
                        if termination_requested else "检测完成，报告已生成"
                    ),
                }
            if not any(key in (task.progress or {}) for key in _PROBE_PROGRESS_KEYS):
                task.progress.pop("message", None)
            s.commit()
        except Exception as e:
            logger.exception("任务 %s 失败", task_id)
            try:
                # 丢弃 generate_report 已 add 未 commit 的违规/证据/报告行，失败任务不残留半截产物
                s.rollback()
                # Pause/cancel can be committed by the API through another
                # session while a device call is in flight.  Expire this
                # worker's identity map before reading it, otherwise the
                # stale in-memory "traversing" value can overwrite the
                # user's newer command as "failed".
                s.expire_all()
                task = s.query(DetectionTask).filter_by(id=task_id).first()
                if task is None:
                    logger.info("Task %s was deleted; not marking failed", task_id)
                    return
                if task.status in {"canceled", "paused"}:
                    logger.info("任务 %s 已被取消，跳过失败标记", task_id)
                    return
                classification = classify_failure(
                    e,
                    stage=str(task.status or "unknown"),
                    recovery_attempted=bool(ctx.runtime.get("runtime_session_recovery_attempted")),
                )
                task.progress = failure_progress(task.progress, classification)
                set_status(
                    s,
                    task,
                    "failed",
                    reason=f"{classification.category.value}: {classification.reason}",
                )
            except Exception:
                task.status = "failed"
                classification = classify_failure(
                    e,
                    stage=str(getattr(task, "status", "unknown") or "unknown"),
                    recovery_attempted=bool(ctx.runtime.get("runtime_session_recovery_attempted")),
                )
                task.failure_reason = f"{classification.category.value}: {classification.reason}"
                task.progress = failure_progress(task.progress, classification)
                now = datetime.utcnow()
                task.progress = freeze_active_timing(
                    task.progress, task.started_at, now, finalized=True,
                )
                task.finished_at = now
                s.commit()
        finally:
            if decrypted_apk is not None:
                decrypted_apk.unlink(missing_ok=True)
