"""Recover Appium/Android runtime loss without discarding traversal state."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import inspect
from typing import Callable

from agent.common.exceptions import ExplorationError
from agent.ai_explorer.android_device import is_local_emulator_udid


class RecoveryDisposition(str, Enum):
    RETRY_READ = "retry_read"
    RECOVERED_WITHOUT_RETRY = "recovered_without_retry"
    REDECIDE = "redecide"
    FAILED = "failed"


@dataclass(frozen=True)
class RuntimeRecoveryResult:
    recovered: bool
    disposition: RecoveryDisposition
    checkpoint_replayed: bool = False

    def __bool__(self) -> bool:
        return self.recovered


class RuntimeRecoveryCoordinator:
    """Own the bounded recovery transaction and its checkpoint invariants."""

    def __init__(
        self,
        *,
        client,
        package_name: str,
        runtime: dict,
        permission_probes,
        save_checkpoint: Callable[[], str],
        replay_navigation: Callable[[], bool],
        is_document_target: Callable[[str], bool],
        emit: Callable[..., None],
        note_recovery: Callable[[], None],
        permission_probe_steps: int,
        max_recoveries: int = 1,
    ) -> None:
        self.client = client
        self.package_name = package_name
        self.runtime = runtime
        self.permission_probes = permission_probes
        self.save_checkpoint = save_checkpoint
        self.replay_navigation = replay_navigation
        self.is_document_target = is_document_target
        self.emit = emit
        self.note_recovery = note_recovery
        self.permission_probe_steps = int(permission_probe_steps)
        self.max_recoveries = int(max_recoveries)
        # A resumed worker gets a new coordinator instance.  Restore the
        # counters so a checkpoint cannot silently reset the recovery budget
        # and loop forever across process/device restarts.
        self.recoveries = max(0, int(runtime.get("runtime_session_recoveries", 0) or 0))
        self.recovery_attempts = max(0, int(runtime.get("runtime_session_recovery_attempts", 0) or 0))

    def _stop_requested(self) -> bool:
        """Return whether the user has asked the recovery transaction to stop."""
        return any(
            callable(check) and check()
            for check in (
                self.runtime.get("is_canceled"),
                self.runtime.get("is_paused"),
                self.runtime.get("is_terminated"),
            )
        )

    def read_page(self, step: int) -> tuple[str, str]:
        try:
            return self.client.page()
        except ExplorationError as exc:
            result = self.recover_runtime_loss_result(step, exc, operation="read")
            if not result:
                raise
            try:
                return self.client.page()
            except ExplorationError as page_error:
                # Do not leave a false ``recovered`` status when the fresh
                # session still cannot produce a page.  The caller will
                # classify the original operation as a recovery failure.
                self.runtime["runtime_session_recovery_status"] = "failed"
                self.emit(
                    "runtime_session_recovery_failed",
                    step=step,
                    reason=f"恢复后页面仍不可读：{str(page_error)[:400]}",
                )
                raise

    def perform_safe_action(
        self,
        step: int,
        decision: dict,
        *,
        recovery_kind: str = "normal",
    ) -> bool:
        """Run one idempotent navigation action through the recovery boundary.

        A direct Appium ``back`` can lose the UiAutomator2 proxy before the
        explorer gets another chance to read the page.  Recovering only on the
        next read therefore aborts external Custom Tabs and Android Settings.
        Recovery itself restores the audited package and semantic checkpoint.
        For external/system returns that is the requested outcome, so no second
        Android ``back`` is sent.  Clicks may submit, consent, purchase, delete
        or change state and must likewise be re-decided after recovery.
        """
        try:
            self.client.perform(decision)
            return True
        except ExplorationError as exc:
            action = str(decision.get("action") or "")
            result = self.recover_runtime_loss_result(
                step, exc, operation=action, recovery_kind=recovery_kind,
            )
            if not result:
                raise
            if result.disposition is RecoveryDisposition.RECOVERED_WITHOUT_RETRY:
                self.emit(
                    "runtime_safe_action_satisfied_by_recovery",
                    step=step,
                    action=action,
                    recovery_kind=recovery_kind,
                    reason="会话恢复已回到被测应用检查点，避免再次返回而离开恢复路径",
                )
                return True
            self.emit(
                "runtime_safe_action_not_retried",
                step=step,
                action=action,
                recovery_kind=recovery_kind,
                reason="恢复后不自动重试可能改变业务状态的动作",
            )
            return False

    def recover_runtime_loss(self, step: int, error: ExplorationError) -> bool:
        """Recover an operation that failed outside ``read_page``.

        Document scrolling and nested disclosure clicks are still runtime
        operations, so they must use the exact same checkpoint, wait, replay,
        budget and permission-probe state machine as page reads/actions.
        """
        return bool(self.recover_runtime_loss_result(step, error))

    def replay_after_reactivation(self, step: int, *, reason: str) -> bool:
        """Replay the latest safe route after an App crash/foreground drift.

        ``activateApp`` only restores the package root.  Treating that as a
        successful recovery discards the DFS location and makes the explorer
        repeat root controls.  Reuse the same semantic replay callback as a
        dropped Appium session, but do not retry a business click here.
        """
        # Foreground drift can recur while a route itself launches another
        # package.  Retrying the same breadcrumb on every launcher observation
        # creates an activation storm.  One guarded replay per run is enough;
        # subsequent observations fall back to ordinary DFS at the app root.
        if self.runtime.get("reactivation_replay_attempted"):
            self.runtime["runtime_session_recovery_status"] = "reactivation_replay_already_attempted"
            return False
        self.runtime["reactivation_replay_attempted"] = True
        try:
            replayed = bool(self.replay_navigation())
        except Exception as exc:
            self.runtime["runtime_checkpoint_replayed"] = False
            self.runtime["runtime_session_recovery_status"] = "reactivation_replay_failed"
            self.emit(
                "navigation_replay_after_reactivation_failed",
                step=step, reason=f"{reason}；回放异常：{str(exc)[:300]}",
            )
            return False
        self.runtime["runtime_checkpoint_replayed"] = replayed
        if replayed:
            self.runtime["runtime_session_recovery_status"] = "reactivation_replayed"
            self.note_recovery()
            self.emit("navigation_replay_after_reactivation", step=step, reason=str(reason))
            return True
        self.runtime["runtime_session_recovery_status"] = "reactivation_replay_unavailable"
        self.emit(
            "navigation_replay_after_reactivation_failed",
            step=step, reason=f"{reason}；未能回放最近安全导航节点",
        )
        return False

    def recover_runtime_loss_result(
        self,
        step: int,
        error: ExplorationError,
        *,
        operation: str = "",
        recovery_kind: str = "normal",
    ) -> RuntimeRecoveryResult:
        """Recover once and expose how the caller must resume safely."""
        recovered = bool(self._recover_after_runtime_loss(step, error))
        replayed = bool(self.runtime.get("runtime_checkpoint_replayed"))
        if not recovered:
            return RuntimeRecoveryResult(False, RecoveryDisposition.FAILED, replayed)
        if str(operation or "") == "read":
            return RuntimeRecoveryResult(True, RecoveryDisposition.RETRY_READ, replayed)
        if str(operation or "") == "back" and recovery_kind in {"external_return", "system_return"}:
            return RuntimeRecoveryResult(True, RecoveryDisposition.RECOVERED_WITHOUT_RETRY, replayed)
        return RuntimeRecoveryResult(True, RecoveryDisposition.REDECIDE, replayed)

    def _recover_after_runtime_loss(self, step: int, error: ExplorationError) -> bool:
        """Restore a dropped runtime session and replay its safe checkpoint."""
        self.runtime["runtime_session_recovery_attempted"] = True
        self.recovery_attempts += 1
        self.runtime["runtime_session_recovery_attempts"] = self.recovery_attempts
        recover = getattr(self.client, "recover_runtime_session", None)
        if self.recovery_attempts > self.max_recoveries:
            self.runtime["runtime_session_recovery_status"] = "exhausted"
            self.emit("runtime_session_recovery_failed", step=step, reason=str(error)[:500])
            return False
        if not callable(recover):
            self.runtime["runtime_session_recovery_status"] = "unavailable"
            self.emit("runtime_session_recovery_failed", step=step, reason=str(error)[:500])
            return False
        try:
            checkpoint = self.save_checkpoint()
        except Exception as checkpoint_error:
            self.runtime["runtime_session_recovery_status"] = "checkpoint_failed"
            self.emit(
                "runtime_session_recovery_failed",
                step=step,
                reason=f"恢复前检查点保存失败：{str(checkpoint_error)[:400]}",
            )
            return False
        self.runtime["runtime_recovery_checkpoint"] = str(checkpoint)
        self.runtime["runtime_session_recovery_status"] = "waiting"
        self.emit(
            "runtime_session_lost", step=step, reason=str(error)[:500],
            navigation_checkpoint=str(checkpoint),
        )
        device = getattr(self.client, "_device", None)
        udid = str(getattr(device, "udid", "") or "")
        self.emit(
            "runtime_session_waiting_for_recovery",
            step=step,
            recovery_kind=("emulator_boot_wait" if is_local_emulator_udid(udid) else "uiautomator2_restart"),
            package=self.package_name,
        )
        if self._stop_requested():
            self.runtime["runtime_session_recovery_status"] = "canceled"
            self.emit(
                "runtime_session_recovery_canceled",
                step=step,
                reason="用户已请求停止，未继续等待模拟器恢复",
            )
            return False
        try:
            try:
                parameters = inspect.signature(recover).parameters.values()
                accepts_stop = any(
                    parameter.name == "should_stop"
                    or parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                )
            except (TypeError, ValueError):
                accepts_stop = False
            recovered = bool(
                recover(self.package_name, error, should_stop=self._stop_requested)
                if accepts_stop else recover(self.package_name, error)
            )
        except Exception as recovery_error:
            self.runtime["runtime_session_recovery_status"] = "failed"
            self.emit(
                "runtime_session_recovery_failed",
                step=step,
                reason=f"运行时恢复调用异常：{str(recovery_error)[:400]}",
            )
            return False
        if not recovered:
            self.runtime["runtime_session_recovery_status"] = "failed"
            self.emit("runtime_session_recovery_failed", step=step, reason=str(error)[:500])
            return False
        self._remember_interrupted_document(step)
        try:
            replayed = bool(self.replay_navigation())
        except Exception as replay_error:
            self.runtime["runtime_checkpoint_replayed"] = False
            self.runtime["runtime_session_recovery_status"] = "replay_failed"
            self.emit(
                "runtime_session_replay_failed",
                step=step,
                package=self.package_name,
                checkpoint=str(checkpoint),
                reason=f"检查点回放异常：{str(replay_error)[:400]}",
            )
            return False
        self.runtime["runtime_checkpoint_replayed"] = bool(replayed)
        if not replayed:
            # A session lost at the application root has no navigation edge to
            # replay. Appium's recovery already reactivated the audited app;
            # record this explicitly as a root recovery instead of pretending
            # a route was replayed. A non-empty route must replay successfully.
            if not self.runtime.get("navigation_replay_required", False):
                self.recoveries += 1
                self.runtime["runtime_session_recoveries"] = self.recoveries
                self.runtime["runtime_session_recovery_status"] = "root_recovered"
                self.note_recovery()
                self.emit(
                    "runtime_session_recovered",
                    step=step,
                    package=self.package_name,
                    checkpoint_replayed=False,
                    recovery_scope="application_root",
                )
            else:
                self.runtime["runtime_session_recovery_status"] = "replay_failed"
                self.emit(
                    "runtime_session_replay_failed",
                    step=step,
                    package=self.package_name,
                    checkpoint=str(checkpoint),
                    reason="会话已重建但未能回放到中断前的安全检查点",
                )
                return False
        else:
            self.recoveries += 1
            self.runtime["runtime_session_recoveries"] = self.recoveries
            self.runtime["runtime_session_recovery_status"] = "recovered"
            self.note_recovery()
            self.emit(
                "runtime_session_recovered", step=step, package=self.package_name,
                checkpoint_replayed=True,
            )
        if self.permission_probes.active:
            self.permission_probes.refresh_after_recovery(
                minimum_steps=self.permission_probe_steps,
                route_replayed=replayed,
            )
            self.emit(
                "permission_denial_probe_session_recovered",
                step=step,
                permission=self.permission_probes.active.permission,
                trigger_target=self.permission_probes.active.trigger_target,
                navigation_replayed=replayed,
            )
        return True

    def _remember_interrupted_document(self, step: int) -> None:
        last_action = self.runtime.get("last_appium_action") or {}
        target = str(last_action.get("target") or "")
        if (
            str(last_action.get("action") or "") == "click"
            and self.is_document_target(target)
            and target
            and not self.runtime.get("external_document_interrupted_target")
        ):
            self.runtime["external_document_interrupted_target"] = target
            self.emit(
                "external_document_interrupted", step=step, target=target,
                reason="运行时会话在外部条款页面建立前丢失，保留一次恢复后重试",
            )
