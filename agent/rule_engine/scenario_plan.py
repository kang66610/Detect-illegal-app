"""Deterministic minimum scenarios for device-verifiable recognition items.

The LLM may choose a visible safe control, but it is not allowed to decide
that a scenario is unnecessary.  These goals are emitted into the timeline and
used as coverage obligations by the explorer/report.
"""
from __future__ import annotations

from agent.rule_engine.scenario_execution import ScenarioExecutionLedger


SCENARIO_PLAN = {
    # Every recognition item has a plan row.  ``executor=device`` means the
    # explorer may drive a visible safe control; ``executor=server`` is kept
    # in the same queue but is explicitly labelled as requiring audit data.
    "1.1": {"goal": "首次启动规则入口", "signals": ("隐私", "服务条款", "用户协议"), "executor": "device"},
    "1.2": {"goal": "首次运行显著提示阅读规则", "signals": ("隐私政策", "服务条款", "用户协议"), "executor": "device"},
    "1.3": {"goal": "规则入口点击层级", "signals": ("隐私", "设置", "我的"), "executor": "device"},
    "1.4": {"goal": "规则全文可读性与底部到达", "signals": ("隐私", "服务条款", "用户协议", "说明"), "executor": "device"},
    "2.1": {"goal": "收集个人信息目的、方式、范围逐项披露", "signals": ("隐私政策", "收集", "个人信息", "第三方"), "executor": "device"},
    "2.2": {"goal": "规则变更通知与版本差异", "signals": ("更新", "变更", "通知", "版本"), "executor": "server"},
    "2.3": {"goal": "权限申请前目的告知", "signals": ("权限", "定位", "相机", "电话", "照片", "存储", "头像", "拍照", "相册"), "executor": "device"},
    "2.4": {"goal": "规则内容语义清晰度", "signals": (), "executor": "device"},
    "3.1": {"goal": "同意前敏感 API/权限", "signals": ("隐私", "同意", "权限"), "executor": "device"},
    "3.2": {"goal": "拒绝后仍收集或重复索权", "signals": ("拒绝", "不允许", "权限", "再次"), "executor": "device"},
    "3.3": {"goal": "实际收集是否超出授权范围", "signals": ("上传", "照片", "位置", "相机", "权限"), "executor": "device"},
    "3.4": {"goal": "默认勾选同意", "signals": ("同意", "勾选", "checkbox", "隐私"), "executor": "device"},
    "3.5": {"goal": "权限状态变更与后台记录", "signals": ("权限", "设置", "授权"), "executor": "server"},
    "3.6": {"goal": "定向推送与非定向选项", "signals": ("关闭个性化", "关闭定向", "非定向", "广告推荐管理", "个性化广告"), "executor": "device"},
    "3.7": {"goal": "同意文案与实际动作一致性", "signals": (), "executor": "device"},
    "3.8": {"goal": "撤回同意与关闭授权入口", "signals": ("撤回同意", "撤回授权", "撤销授权", "授权管理", "撤回个人信息"), "executor": "device"},
    "3.9": {"goal": "声明规则与实际行为一致性", "signals": (), "executor": "device"},
    "4.1": {"goal": "同意后、业务触发前的权限必要性", "signals": ("定位", "相机", "电话", "存储", "麦克风"), "executor": "device"},
    "4.2": {
        "goal": "拒绝非必要权限后的业务可用性",
        "signals": (
            "客服", "投诉", "举报", "反馈", "帮助支持", "报料", "救援", "工单", "语音", "麦克风", "录音", "拍照",
            "相机", "相册", "图片", "上传", "头像", "文件", "voice", "microphone",
            "record", "camera", "photo", "upload",
        ), "executor": "device",
    },
    "4.3": {"goal": "新增功能权限范围与原功能影响", "signals": ("新功能", "升级", "权限", "设置"), "executor": "server"},
    "4.4": {"goal": "敏感 API 收集频次", "signals": ("位置", "定位", "后台"), "executor": "device"},
    "4.5": {"goal": "以改善服务等理由强制同意", "signals": (), "executor": "device"},
    "4.6": {"goal": "多权限捆绑同意", "signals": ("权限", "同意", "允许"), "executor": "device"},
    "5.1": {"goal": "未经同意向第三方传输且未匿名化", "signals": ("上传", "网络", "分享", "第三方", "SDK"), "executor": "device"},
    "5.2": {"goal": "后台第三方共享与服务端记录", "signals": ("第三方", "SDK", "上传", "网络"), "executor": "server"},
    "5.3": {"goal": "接入第三方应用前的同意", "signals": (), "executor": "device"},
    "6.1": {"goal": "更正、删除、注销入口", "signals": ("注销", "删除", "更正", "账号"), "executor": "device"},
    "6.2": {"goal": "删除、更正、注销条件", "signals": ("注销", "删除", "更正", "条件"), "executor": "device"},
    "6.3": {"goal": "投诉举报请求是否及时响应", "signals": ("投诉", "举报", "客服", "反馈", "帮助支持", "工单", "报料", "申诉"), "executor": "server"},
    "6.4": {"goal": "客户端请求与后台完成状态", "signals": ("删除", "更正", "注销", "请求"), "executor": "server"},
    "6.5": {"goal": "投诉举报渠道是否承诺核查处理时效", "signals": (), "executor": "device"},
}


_DISTRACTOR_LABELS = (
    "通知设置", "推送设置", "消息设置", "消息通知", "推送通知",
    "清除缓存", "清理缓存", "缓存清理", "检查更新", "版本更新", "给个好评",
    "clear cache", "check for updates", "rate app",
)
_TERMINAL_STATES = {"evidence_observed", "blocked_external", "requires_login", "requires_server_audit", "not_applicable"}
_STATE_LABELS = {
    "pending": "待执行",
    "attempted": "已尝试，尚未形成证据",
    "evidence_observed": "已形成设备证据",
    "blocked_external": "外部页面或系统页面阻塞",
    "requires_login": "需要登录后继续核验",
    "requires_server_audit": "需要服务端审计",
    "not_applicable": "当前应用场景不适用",
}


def device_scenario_plan() -> list[dict]:
    return [{"item": item, **definition} for item, definition in SCENARIO_PLAN.items()]


# The deny pass is the discovery pass.  The allow pass exists only to compare
# behaviour that can change after a permission is granted; it must not spend a
# second traversal on policies, withdrawal, deletion, complaint or login-only
# obligations already explored by the deny pass.
_ALLOW_PROBE_ITEMS = frozenset({"2.3", "3.3", "3.9", "4.1", "4.4", "4.6", "5.1"})


def scenario_plan_for_probe(profile: str) -> list[dict]:
    """Return the phase-local deterministic obligations for a probe profile."""
    plan = device_scenario_plan()
    if str(profile or "").lower() != "allow":
        return plan
    return [row for row in plan if str(row.get("item")) in _ALLOW_PROBE_ITEMS]


class ScenarioFrontier:
    """Small deterministic frontier in front of the probabilistic LLM.

    It never invents controls: recommendations are selected exclusively from
    the current Appium element whitelist. The model remains useful for
    ambiguous pages, but it cannot end traversal while a visible, safe target
    advances an outstanding recognition-method scenario.
    """

    def __init__(self, plan: list[dict] | None = None):
        self.plan = plan or device_scenario_plan()
        self.executions = ScenarioExecutionLedger(self.plan)
        self.attempted_items: set[str] = set()
        self.completed_items: set[str] = set()
        self.attempt_counts: dict[str, int] = {}
        self.attempted_item_targets: set[tuple[str, str]] = set()
        self.attempted_item_target_counts: dict[tuple[str, str], int] = {}
        self._items = {
            str(scenario["item"]): {
                "item": str(scenario["item"]),
                "goal": str(scenario.get("goal") or ""),
                "state": "requires_server_audit" if str(scenario.get("executor") or "device") == "server" else "pending",
                "reason": (
                    "需要导入服务端审计事件后核验"
                    if str(scenario.get("executor") or "device") == "server"
                    else "尚未执行对应的自动化检测场景"
                ),
                "attempts": 0,
                "targets": [],
                "evidence_sources": [],
                "executor": str(scenario.get("executor") or "device"),
            }
            for scenario in self.plan
        }

    @staticmethod
    def _identity(element: dict) -> str:
        return " ".join(str(element.get(key) or "") for key in ("target", "resource_id", "text", "content_desc")).lower()

    def recommend(self, elements: list[dict], visited_targets: set[str]) -> dict | None:
        from agent.detection_engines.ui_roles import roles_for_element, scenarios_for_roles
        from agent.rule_engine.recognition_contract import CONTRACT

        for scenario in self.plan:
            item = scenario["item"]
            contract = CONTRACT.get(str(item))
            # 没有完成条件的条款不要抢点击，否则空转项会饿死后面的真实检测器。
            if contract is not None and not contract.complete_if:
                continue
            if self._items[str(item)]["state"] in _TERMINAL_STATES or str(scenario.get("executor") or "device") != "device":
                continue
            signals = tuple(str(term).lower() for term in scenario.get("signals") or ())
            for element in elements:
                target = str(element.get("target") or element.get("resource_id") or element.get("text") or element.get("content_desc") or "")
                if not element.get("clickable") or not target or target in visited_targets:
                    continue
                identity = self._identity(element)
                if any(term in identity for term in _DISTRACTOR_LABELS):
                    continue
                roles = roles_for_element(element)
                role_hit = str(item) in scenarios_for_roles(roles)
                signal_hit = bool(signals) and any(signal in self._identity(element) for signal in signals)
                if not role_hit and not signal_hit:
                    continue
                related = [
                    item["item"] for item in self.plan
                    if self._items[str(item["item"])]["state"] not in _TERMINAL_STATES
                    and (
                        str(item["item"]) in scenarios_for_roles(roles)
                        or any(str(term).lower() in self._identity(element) for term in item.get("signals") or ())
                    )
                ]
                fresh_related = [
                    str(related_item) for related_item in (related or [str(item)])
                    if self.attempted_item_target_counts.get((str(related_item), target), 0) < 2
                ]
                if not fresh_related:
                    continue
                return {
                    "target": target, "scenario_items": fresh_related,
                    "reason": f"规则场景前沿：{scenario['item']} {scenario['goal']}",
                }
        return None

    def mark_attempted(self, target: str, scenario_items: list[str]) -> None:
        for raw_item in scenario_items:
            item = str(raw_item)
            # A frontier is phase-local.  Shared explorer callbacks may carry
            # obligations from the other probe phase; they must not index the
            # phase ledger or turn an out-of-plan observation into a crash.
            if item not in self._items:
                continue
            self.executions.begin(item, target=target)
            self.attempted_items.add(item)
            self.attempt_counts[item] = self.attempt_counts.get(item, 0) + 1
            row = self._items.get(item)
            if row and row["state"] not in _TERMINAL_STATES:
                row["state"] = "attempted"
                row["reason"] = "已选择可见、安全的目标，等待页面或行为证据"
                row["attempts"] = self.attempt_counts[item]
                if target and target not in row["targets"]:
                    row["targets"].append(target)
            if target:
                self.attempted_item_targets.add((item, target))
                key = (item, target)
                self.attempted_item_target_counts[key] = self.attempted_item_target_counts.get(key, 0) + 1

    def mark_completed(
        self, scenario_items: list[str] | set[str] | tuple[str, ...] | set,
        *, evidence_source: str = "device", finding_kind: str | None = None,
    ) -> None:
        from agent.rule_engine.recognition_contract import completion_allowed

        for raw_item in scenario_items:
            item = str(raw_item)
            # Completion events can be emitted by common navigation code even
            # when the active phase deliberately excludes that obligation.
            # Ignore those events at the frontier boundary; the deny phase
            # remains responsible for its own item and its evidence.
            if item not in self._items:
                continue
            if not completion_allowed(item, evidence_source=evidence_source, finding_kind=finding_kind):
                continue
            self.executions.observe_evidence(
                item, source=str(finding_kind or evidence_source or "device"),
            )
            self.completed_items.add(item)
            row = self._items.get(item)
            if row:
                row["state"] = "evidence_observed"
                row["reason"] = "已取得该场景对应的设备侧观察证据"
                source = finding_kind or evidence_source
                if source and source not in row["evidence_sources"]:
                    row["evidence_sources"].append(source)

    def mark_blocked(
        self, scenario_items: list[str] | set[str] | tuple[str, ...], state: str, reason: str,
    ) -> None:
        """Record why a planned check was not executable instead of hiding it.

        The state is deliberately narrower than a generic failure.  A report
        can distinguish an unavailable policy WebView from a login-gated path
        and from a server-side-only conclusion.
        """
        if state not in _TERMINAL_STATES - {"evidence_observed"}:
            raise ValueError(f"unsupported scenario state: {state}")
        for raw_item in scenario_items:
            row = self._items.get(str(raw_item))
            if row and row["state"] != "evidence_observed":
                self.executions.block(str(raw_item), state=state, reason=str(reason))
                row["state"] = state
                row["reason"] = str(reason)

    def snapshot(self) -> dict:
        planned = len(self.plan)
        attempted = len(self.attempted_items)
        items = [
            {
                **self._items[str(scenario["item"])],
                "step": self.executions.row(str(scenario["item"]))["step"],
                "state_label": _STATE_LABELS[self._items[str(scenario["item"])]["state"]],
            }
            for scenario in self.plan
        ]
        completed = [row["item"] for row in items if row["state"] == "evidence_observed"]
        remaining = [row["item"] for row in items if row["state"] not in _TERMINAL_STATES]
        return {
            "planned": planned, "attempted": attempted, "remaining": len(remaining),
            "attempted_items": sorted(self.attempted_items),
            "completed": len(completed), "completed_items": sorted(completed),
            "remaining_items": remaining,
            "items": items,
        }
