"""Optional, secret-safe test-account adapter for authenticated exploration."""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent.ai_explorer.action_executor import ActionExecutionResult
from agent.ai_explorer.decision_directive import DecisionDirective


@dataclass(frozen=True)
class LoginActionResult:
    entry_confirmed: bool = False


@dataclass(frozen=True)
class LoginAttempt:
    status: str
    username_target: str = ""
    password_target: str = ""
    submit_target: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ManualConsentCodeSnapshot:
    """A redacted UI-only observation of a login consent/code-request pair."""

    checkbox_target: str
    checkbox_checked: bool
    code_target: str
    code_enabled: bool
    code_label: str

    @property
    def armable(self) -> bool:
        return bool(self.checkbox_target and self.code_target and not self.checkbox_checked and self.code_enabled)

    def request_accepted_after(self, before: "ManualConsentCodeSnapshot | None") -> bool:
        """True only for an unchecked-to-countdown/disabled request transition."""
        if before is None or not before.armable or self.checkbox_checked:
            return False
        if before.code_target != self.code_target:
            return False
        countdown = bool(re.search(r"(?:^|\\s)\\d{1,3}\\s*(?:s|秒)(?:$|\\s)", self.code_label.lower()))
        changed = self.code_label != before.code_label
        return bool((not self.code_enabled or countdown) and changed)


class ManualConsentCodeProbe:
    """Observe a human-triggered SMS/code request without touching credentials."""

    _TERMS = ("隐私", "用户协议", "服务协议", "同意", "agree", "consent")
    _CODE = ("验证码", "verify", "sms", "code", "captcha")
    _REQUEST = ("获取", "发送", "重新", "send", "resend", "get")
    _CHECKBOX_HINTS = ("checkbox", "check_box", "cb_", "iv_check", "agree_check", "consent_check")

    @staticmethod
    def _identity(element: dict) -> str:
        return " ".join(str(element.get(key) or "") for key in (
            "resource_id", "text", "content_desc",
        )).lower()

    @staticmethod
    def _target(element: dict) -> str:
        return str(
            element.get("target") or element.get("resource_id")
            or element.get("text") or element.get("content_desc") or ""
        )

    def snapshot(self, elements: list[dict]) -> ManualConsentCodeSnapshot | None:
        page_identity = " ".join(self._identity(item) for item in elements)
        if not any(term in page_identity for term in self._TERMS):
            return None
        checkbox = next((
            item for item in elements
            if self._target(item) and (
                item.get("checkable")
                or any(term in str(item.get("class_name") or "").lower() for term in ("checkbox", "radiobutton", "compoundbutton"))
                or any(term in self._identity(item) for term in self._CHECKBOX_HINTS)
            )
        ), None)
        if checkbox is None:
            return None
        code_control = next((
            item for item in elements
            if item.get("clickable") and not item.get("editable") and self._target(item)
            and any(term in self._identity(item) for term in self._CODE)
            and any(term in self._identity(item) for term in self._REQUEST)
        ), None)
        if code_control is None:
            return None
        return ManualConsentCodeSnapshot(
            checkbox_target=self._target(checkbox),
            checkbox_checked=bool(checkbox.get("checked")),
            code_target=self._target(code_control),
            code_enabled=bool(code_control.get("enabled", True)),
            code_label=self._identity(code_control),
        )


class LoginSurfaceClassifier:
    """UI-evidence classifier for login boundaries, independent of Activities."""

    _FIELDS = ("password", "phone", "mobile", "account", "email", "verify", "code", "账号", "密码", "手机号", "验证码")
    _SUBMIT = ("login", "signin", "sign in", "register", "登录", "注册", "下一步", "获取验证码")
    _MAINTENANCE = (
        "注销账号", "账号注销", "删除账号", "确认注销", "暂不注销",
        "更换手机号", "修改手机号", "换绑手机号", "绑定新手机号", "解绑手机号",
        "安全验证", "身份验证", "验证身份", "cancelaccount", "deleteaccount",
        "unregister", "changephone", "changemobile", "rebindphone", "rebindmobile",
        "accountverification",
    )
    _LOGOUT = ("退出登录", "退出账号", "退出账户", "安全退出", "注销登录", "sign out", "log out", "logout")
    _PROFILE = ("我的", "个人中心", "账户中心", "账号管理", "消息中心", "我的报料", "我的救援")
    _SUCCESS = ("登录成功", "成功登录", "登陆成功", "成功登陆", "已成功登录", "欢迎回来", "login successful", "logged in successfully", "signed in successfully")
    _LOGGED_OUT = (
        "未登录", "未登陆", "尚未登录", "请先登录", "游客模式", "游客身份",
        "not logged in", "sign in to continue", "guest mode",
    )
    _PROFILE_ENTRY = (
        "点击此处登录", "点击登录", "立即登录", "去登录", "登录/注册", "请先登录",
        "点击头像登录", "未登录", "未登陆", "login / register", "sign in",
        "not logged in", "log in",
    )

    @staticmethod
    def _identity(item: dict) -> str:
        return " ".join(str(item.get(key) or "") for key in (
            "text", "content_desc", "resource_id",
        )).lower()

    def authenticated(self, elements: list[dict], extra_text: str = "") -> bool:
        combined = f"{' '.join(self._identity(item) for item in elements)} {extra_text.lower()}"
        compact = re.sub(r"[\s!！。．.，,]+", "", combined)
        if any(term in combined for term in self._LOGOUT):
            return True
        if any(re.sub(r"\s+", "", term) in compact for term in self._SUCCESS):
            return True
        digits = "".join(re.findall(r"\d", combined))
        has_mobile = bool(re.search(r"1\d{10}", digits))
        has_profile = any(term in combined for term in ("我的", "个人中心", "账户中心"))
        anchors = sum(term in combined for term in self._PROFILE)
        return (has_mobile and has_profile) or (anchors >= 2 and (has_mobile or "用户" in combined or "user" in combined))

    def is_login_gate(self, activity: str, elements: list[dict]) -> bool:
        if self.authenticated(elements):
            return False
        identity = " ".join(self._identity(item) for item in elements)
        compact = re.sub(r"\s+", "", identity)
        if any(marker in compact for marker in self._MAINTENANCE):
            return False
        fields = 0
        submit = False
        for item in elements:
            item_identity = self._identity(item)
            widget = str(item.get("class_name") or "").lower()
            editable = bool(item.get("editable")) or "edittext" in widget or "input" in widget
            if editable and any(term in item_identity for term in self._FIELDS):
                fields += 1
            if item.get("clickable") and any(term in item_identity for term in self._SUBMIT):
                submit = True
        if fields >= 2 or (fields >= 1 and submit):
            return True
        options = sum(
            1 for item in elements
            if item.get("clickable") and any(term in self._identity(item) for term in (
                "qq", "微信", "手机号", "手机登录", "短信验证码", "password", "phone",
            ))
        )
        return options >= 1 and ("登录方式" in identity or "login" in identity or "手机号" in identity)

    @staticmethod
    def _target(item: dict) -> str:
        return str(
            item.get("target") or item.get("resource_id")
            or item.get("text") or item.get("content_desc") or ""
        )

    def invitation_target(self, elements: list[dict], page_text: str = "") -> str | None:
        text = str(page_text or "").lower()
        required = (
            ("需要" in text and "登录" in text) or "登录后" in text
            or "please log in" in text or "login required" in text
        )
        if not required:
            return None
        positive = ("前往登录", "去登录", "立即登录", "登录/注册", "login now", "go to login")
        decline = ("取消", "不同意", "暂不", "以后再说", "cancel", "not now")
        for item in elements:
            identity = self._identity(item)
            if item.get("clickable") and not any(term in identity for term in decline):
                if any(term in identity for term in positive):
                    return self._target(item) or None
        return None

    def bypass_target(self, elements: list[dict]) -> str | None:
        terms = ("游客", "暂不登录", "随便看看", "先逛逛", "跳过登录", "关闭登录")
        for item in elements:
            label = re.sub(r"\s+", "", " ".join(
                str(item.get(key) or "") for key in ("text", "content_desc")
            ))
            if item.get("clickable") and 0 < len(label) <= 12 and any(term in label for term in terms):
                return self._target(item) or None
        return None

    def logged_out_profile(self, elements: list[dict], extra_text: str = "") -> bool:
        if self.authenticated(elements, extra_text=extra_text):
            return False
        blob = f"{' '.join(self._identity(item) for item in elements)} {extra_text.lower()}"
        compact = re.sub(r"\s+", "", blob)
        return any(term.replace(" ", "") in compact for term in self._LOGGED_OUT)

    @staticmethod
    def _bounds(value: str) -> tuple[int, int, int, int] | None:
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", str(value or ""))
        if not match:
            return None
        left, top, right, bottom = (int(item) for item in match.groups())
        return (left, top, right, bottom) if right > left and bottom > top else None

    def profile_entry(self, elements: list[dict], extra_text: str = "") -> str | None:
        has_field = any(
            item.get("editable")
            or "edittext" in str(item.get("class_name") or "").lower()
            or "input" in str(item.get("class_name") or "").lower()
            for item in elements
        )
        if has_field or self.authenticated(elements, extra_text=extra_text):
            return None
        terms = tuple(term.lower() for term in (*self._PROFILE_ENTRY, *self._LOGGED_OUT))
        for item in elements:
            if item.get("clickable") and any(term in self._identity(item) for term in terms):
                return self._target(item) or None
        # Prefer the tightest clickable ancestor of a non-clickable “未登录”.
        labels = [item for item in elements if any(term in self._identity(item) for term in terms)]
        for label in labels:
            child = self._bounds(str(label.get("bounds") or ""))
            if not child:
                continue
            parents: list[tuple[int, str]] = []
            for item in elements:
                parent = self._bounds(str(item.get("bounds") or ""))
                if not item.get("clickable") or not parent:
                    continue
                if parent[0] <= child[0] and parent[1] <= child[1] and parent[2] >= child[2] and parent[3] >= child[3]:
                    target = self._target(item)
                    if target:
                        parents.append(((parent[2] - parent[0]) * (parent[3] - parent[1]), target))
            if parents:
                parents.sort()
                return parents[0][1]
        if not self.logged_out_profile(elements, extra_text=extra_text):
            return None
        avatars: list[tuple[int, str]] = []
        headers: list[tuple[int, str]] = []
        for item in elements:
            if not item.get("clickable"):
                continue
            identity = self._identity(item)
            if any(term in identity for term in ("navi_", "tab_", "首页", "场景", "home", "scene")):
                continue
            rect = self._bounds(str(item.get("bounds") or ""))
            top = rect[1] if rect else 0
            if top > 1100:
                continue
            target = self._target(item)
            if not target:
                continue
            class_name = str(item.get("class_name") or "").lower()
            if "image" in class_name or any(term in identity for term in (
                "avatar", "head", "portrait", "user_icon", "iv_user", "iv_head", "ll_user", "cl_user",
            )):
                avatars.append((top, target))
            elif top < 700 and not any(term in identity for term in (
                "固件", "设置", "家庭", "firmware", "setting", "family",
            )):
                headers.append((top, target))
        avatars.sort()
        headers.sort()
        return avatars[0][1] if avatars else (headers[0][1] if headers else None)


class TestAccountLoginAdapter:
    """Use opt-in environment credentials without persisting or emitting them."""

    __test__ = False

    def __init__(self, config: dict, runtime: dict, client) -> None:
        self.config = config
        self.runtime = runtime
        self.client = client

    def attempt(self, elements: list[dict]) -> LoginAttempt:
        if not self.config.get("test_account_enabled", False):
            return LoginAttempt("disabled", reason="未启用安全测试账号")
        if self.runtime.get("test_account_login_attempted"):
            return LoginAttempt("already_attempted", reason="本次运行已尝试一次")
        username = os.getenv(str(self.config.get("test_account_username_env") or ""), "")
        password = os.getenv(str(self.config.get("test_account_password_env") or ""), "")
        if not username or not password:
            return LoginAttempt("credentials_unavailable", reason="测试账号环境变量未配置完整")
        editable = [item for item in elements if item.get("editable") and item.get("target")]
        password_field = next((item for item in editable if item.get("password")), None)
        username_terms = ("phone", "mobile", "account", "username", "手机号", "账号", "用户名")
        username_field = next((
            item for item in editable
            if item is not password_field and any(
                term in " ".join(str(item.get(key) or "") for key in ("resource_id", "text", "content_desc")).lower()
                for term in username_terms
            )
        ), next((item for item in editable if item is not password_field), None))
        submit_terms = ("login", "signin", "登录", "立即登录", "确定")
        submit = next((
            item for item in elements if item.get("clickable") and item.get("target")
            and any(term in " ".join(str(item.get(key) or "") for key in ("resource_id", "text", "content_desc")).lower() for term in submit_terms)
        ), None)
        if not username_field or not password_field or not submit:
            return LoginAttempt("form_unsupported", reason="登录表单缺少可安全定位的账号、密码或提交控件")
        self.runtime["test_account_login_attempted"] = True
        self.client.enter_text(str(username_field["target"]), username)
        self.client.enter_text(str(password_field["target"]), password)
        self.client.perform({"action": "click", "target": str(submit["target"]), "reason": "提交安全测试账号"})
        return LoginAttempt(
            "submitted",
            username_target=str(username_field["target"]),
            password_target=str(password_field["target"]),
            submit_target=str(submit["target"]),
            reason="已提交专用测试账号，凭据未写入日志",
        )


class ManualLoginWaiter:
    """Own the human-login checkpoint without granting page transitions trust."""

    def __init__(
        self,
        *,
        client,
        runtime: dict,
        detection_config: dict,
        package_name: str,
        parse_page: Callable,
        authenticated_visible: Callable[..., bool],
        is_login_gate: Callable[[str, list[dict]], bool],
        looks_like_main_content: Callable[[str, list[dict], str], bool],
        screenshot_path: Callable[[], Path],
        screenshot_ready: Callable[[Path], bool],
        extract_screen_text: Callable[[Path], str],
        emit: Callable[..., None],
        interrupted: Callable[[], bool],
    ) -> None:
        self.client = client
        self.runtime = runtime
        self.config = detection_config
        self.package_name = package_name
        self.parse_page = parse_page
        self.authenticated_visible = authenticated_visible
        self.is_login_gate = is_login_gate
        self.looks_like_main_content = looks_like_main_content
        self.screenshot_path = screenshot_path
        self.screenshot_ready = screenshot_ready
        self.extract_screen_text = extract_screen_text
        self.emit = emit
        self.interrupted = interrupted

    def wait(self, seconds: int) -> bool:
        deadline = time.monotonic() + max(seconds, 0)
        ocr_blob = str(self.runtime.get("manual_login_ocr_blob") or "")
        consent_code_probe = ManualConsentCodeProbe()
        prior_consent_code_snapshot: ManualConsentCodeSnapshot | None = None
        while time.monotonic() < deadline:
            if self.interrupted():
                return False
            activity, xml = self.client.page()
            page = self.parse_page(activity, xml)
            shot = self.screenshot_path()
            try:
                shot.parent.mkdir(parents=True, exist_ok=True)
                if self.client.screenshot(shot) and self.screenshot_ready(shot):
                    probed = self.extract_screen_text(shot)
                    if probed:
                        ocr_blob = probed
                        self.runtime["manual_login_ocr_blob"] = ocr_blob
            except Exception:
                # OCR is supporting evidence. It must never destroy the Appium
                # session or turn a transition into authenticated proof.
                pass
            consent_code_snapshot = consent_code_probe.snapshot(page.elements)
            if consent_code_snapshot and consent_code_snapshot.armable:
                armed = self.runtime.get("manual_auth_consent_probe_armed") or {}
                if armed.get("code_target") != consent_code_snapshot.code_target:
                    self.runtime["manual_auth_consent_probe_armed"] = {
                        "checkbox_target": consent_code_snapshot.checkbox_target,
                        "code_target": consent_code_snapshot.code_target,
                        "armed_at_ms": int(time.time() * 1000),
                    }
                    self.emit(
                        "manual_login_consent_code_probe_armed",
                        activity=activity,
                        checkbox_target=consent_code_snapshot.checkbox_target,
                        code_target=consent_code_snapshot.code_target,
                        reason="人工可取消条款勾选后手动点击验证码入口；系统仅观察状态变化与动态请求，不输入凭据",
                    )
            if consent_code_snapshot and consent_code_snapshot.request_accepted_after(prior_consent_code_snapshot):
                armed = dict(self.runtime.get("manual_auth_consent_probe_armed") or {})
                if armed.get("code_target") == consent_code_snapshot.code_target:
                    evidence_shot = shot.with_name("manual-login-consent-code-request.png")
                    try:
                        if shot.is_file():
                            shutil.copyfile(shot, evidence_shot)
                    except OSError:
                        evidence_shot = shot
                    observation = {
                        **armed,
                        "activity": activity,
                        "probe_profile": str(self.runtime.get("probe_profile") or "observe"),
                        "checkbox_target": consent_code_snapshot.checkbox_target,
                        "code_target": consent_code_snapshot.code_target,
                        "observed_at_ms": int(time.time() * 1000),
                        "screenshot_path": str(evidence_shot),
                    }
                    observations = self.runtime.setdefault(
                        "manual_auth_consent_code_request_observations", [],
                    )
                    if not any(
                        item.get("code_target") == observation["code_target"]
                        and item.get("observed_at_ms") == observation["observed_at_ms"]
                        for item in observations
                    ):
                        observations.append(observation)
                        self.emit(
                            "manual_login_consent_code_request_observed",
                            finding_kind="api_called_before_consent",
                            **observation,
                            reason="人工在未勾选登录条款时触发验证码请求；待关联同一时间窗的设备侧网络证据后再认定",
                        )
            prior_consent_code_snapshot = consent_code_snapshot
            if self.authenticated_visible(page.elements, extra_text=ocr_blob):
                self.runtime["manual_login_proof"] = "session_notice_or_profile"
                return True
            if not page.elements or self.is_login_gate(activity, page.elements):
                time.sleep(1)
                continue
            if (
                not self.runtime.get("sdk_observation_dwell_done")
                and self.looks_like_main_content(activity, page.elements, self.package_name)
                and not (
                    self.runtime.get("consent_dialog_seen")
                    and not self.runtime.get("consent_accepted")
                )
            ):
                dwell = max(0.0, float(self.config.get("sdk_observation_dwell_seconds", 15)))
                self.emit(
                    "sdk_observation_dwelled", activity=activity, seconds=dwell,
                    reason="登录等待期间主内容页已出现，停留以便观察 SDK 采集",
                )
                if dwell:
                    time.sleep(dwell)
                self.runtime["sdk_observation_dwell_done"] = True
            if self.authenticated_visible(page.elements, extra_text=ocr_blob):
                return True
            time.sleep(1)
        return False


class LoginDecisionModule:
    """Own safe entry/exit proposals around authenticated exploration."""

    def observe_action_result(
        self, result: ActionExecutionResult, *, entry_target: str = "",
    ) -> LoginActionResult:
        """Confirm whether an executed click landed on the proposed entry.

        The manual login handoff itself stays observation-driven; this only
        records that the entry tap the module proposed actually executed.
        """
        return LoginActionResult(entry_confirmed=bool(
            entry_target and result.succeeded and result.action == "click"
            and result.target == entry_target
        ))

    def propose_guest_entry(self, *, target: str, already_visited: bool) -> DecisionDirective | None:
        """Enter the public path exposed beside a first-run login choice."""
        if not target or already_visited:
            return None
        return DecisionDirective(
            "click", target,
            "首次入口同时提供登录/注册与游客/先逛逛，优先进入公开主界面继续检测",
            "deterministic_guest_entry", "guest_entry_prioritized",
        )

    def propose_entry(
        self, *, target: str, already_visited: bool, logged_out: bool,
    ) -> DecisionDirective | None:
        if not target or already_visited:
            return None
        return DecisionDirective(
            "click", target,
            (
                "页面显示未登录，先进入登录再核验注销/撤回；自动化不填写凭据"
                if logged_out else
                "优先进入可见登录入口，核验登录前协议与登录后场景边界"
            ),
            "deterministic_login_entry",
            "logged_out_login_prioritized" if logged_out else "profile_login_entry_prioritized",
        )

    def propose_timeout_exit(
        self, *, bypass_target: str, bypass_visited: bool, back_already_done: bool,
    ) -> DecisionDirective:
        if bypass_target and not bypass_visited:
            return DecisionDirective(
                "click", bypass_target, "登录超时后点击游客/跳过，进入无需登录路径",
                "deterministic_login_bypass", "login_bypass_followed",
            )
        if back_already_done:
            return DecisionDirective(
                "stop", "", "登录超时且未能进入无需登录的主界面，已停止在登录门禁",
                "deterministic_login_gate", "login_gate_unresolved",
                effects=("terminate_login_gate_unresolved",),
            )
        return DecisionDirective(
            "back", "", "跳过登录页",
            "deterministic_login_bypass", "action_completed",
            {"reason": "跳过登录页后继续检测"},
        )
