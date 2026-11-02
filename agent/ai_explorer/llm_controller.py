"""OpenAI 兼容模型的受限页面操作决策器。"""
from __future__ import annotations

import json
import os
import re
import base64
import mimetypes
from io import BytesIO
from pathlib import Path

from agent.ai_explorer.prompt_registry import load_navigation_prompt
from agent.common.exceptions import EngineUnavailableError

_ACTIONS = {"click", "back", "wait", "stop"}

# 导航策略正文的唯一来源是 agent/config/prompts/navigation.yaml：
# 版本号+内容指纹由注册表统一管理，修改策略必须递增 YAML 的 version 字段。
SYSTEM_PROMPT = load_navigation_prompt().system_prompt




class LLMController:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    @staticmethod
    def parse_decision(raw: str, elements: list[dict]) -> dict:
        """严格白名单化模型输出，模型不能注入任意 XPath 或 shell 指令。"""
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
        data = json.loads(cleaned)
        action = data.get("action")
        if action not in _ACTIONS:
            raise ValueError("LLM 返回了不支持的 action")
        target = str(data.get("target") or "")
        clickable = [element for element in elements if element.get("clickable")]
        aliases: dict[str, str] = {}
        for element in clickable:
            execution_target = str(
                element.get("execution_target") or element.get("target")
                or element.get("resource_id") or element.get("text")
                or element.get("content_desc") or ""
            )
            catalog_entry = bool(element.get("execution_target"))
            for value in (
                element.get("action_id"), element.get("target"), element.get("resource_id"),
                element.get("text"), element.get("content_desc"),
            ):
                if value and execution_target:
                    aliases[str(value)] = execution_target if catalog_entry else str(value)
        if action == "click":
            if target not in aliases:
                non_clickable = {
                    str(value)
                    for element in elements if not element.get("clickable")
                    for value in (element.get("action_id"), element.get("target"), element.get("resource_id"))
                    if value
                }
                if target in non_clickable:
                    raise ValueError("LLM target 不是当前页面可点击元素")
                raise ValueError("LLM target 不在当前页面可点击白名单，必须精确匹配 action_id")
            target = aliases[target]
        return {"action": action, "target": target, "reason": str(data.get("reason") or "")[:300]}

    @staticmethod
    def _action_catalog(elements: list[dict]) -> list[dict]:
        """Expose opaque, exact action ids while retaining only useful visible metadata."""
        catalog: list[dict] = []
        for index, element in enumerate(item for item in elements if item.get("clickable")):
            execution_target = str(
                element.get("target") or element.get("resource_id")
                or element.get("text") or element.get("content_desc") or ""
            )
            if not execution_target:
                continue
            action_id = f"a{index:03d}"
            catalog.append({
                "action_id": action_id,
                "target": action_id,
                "execution_target": execution_target,
                "text": str(element.get("text") or "")[:160],
                "content_desc": str(element.get("content_desc") or "")[:160],
                "class_name": str(element.get("class_name") or "")[:120],
                "bounds": str(element.get("bounds") or "")[:80],
                "visual_hint": str(
                    element.get("visual_hint") or element.get("content_desc")
                    or element.get("text") or "unlabeled_control"
                )[:160],
                "roles": sorted(str(role) for role in (element.get("roles") or [])),
                "clickable": True,
                "visited": False,
                "recommended_for": [],
            })
        return catalog

    @classmethod
    def _action_context(cls, page: dict, visited_targets: set[str]) -> tuple[list[dict], dict]:
        """Map recommendations, media families and history to action ids.

        The model must never reconcile opaque action ids with raw Appium
        locators. Execution targets remain private to the controller.
        """
        catalog = cls._action_catalog(page.get("elements") or [])
        by_execution: dict[str, dict] = {
            str(item.get("execution_target") or ""): item for item in catalog
            if item.get("execution_target")
        }
        visited_actions: list[str] = []
        for target in visited_targets:
            item = by_execution.get(str(target))
            if item:
                item["visited"] = True
                visited_actions.append(str(item["action_id"]))

        guided = page.get("rule_guided_target") or None
        guided_action = None
        if isinstance(guided, dict):
            item = by_execution.get(str(guided.get("target") or ""))
            if item:
                scenarios = sorted(str(value) for value in (guided.get("scenario_items") or []))
                item["recommended_for"] = scenarios
                guided_action = {
                    "action_id": item["action_id"],
                    "scenario_items": scenarios,
                    "reason": str(guided.get("reason") or "")[:300],
                }

        sensitive_actions: list[dict] = []
        for row in page.get("sensitive_media_families") or []:
            if not isinstance(row, dict):
                continue
            item = by_execution.get(str(row.get("target") or ""))
            if not item:
                continue
            family = str(row.get("family") or "other")
            item["media_family"] = family
            sensitive_actions.append({"action_id": item["action_id"], "family": family})
        return catalog, {
            "visited_actions": sorted(set(visited_actions)),
            "rule_guided_action": guided_action,
            "sensitive_media_actions": sensitive_actions,
        }

    @staticmethod
    def _user_content(prompt: dict, screenshot_path: str = ""):
        """Build a multimodal observation when a captured viewport is available."""
        text = json.dumps(prompt, ensure_ascii=False)
        path = Path(str(screenshot_path or ""))
        if not screenshot_path or not path.is_file():
            return text
        try:
            image_bytes = path.read_bytes()
            # Draw action ids over the exact Appium bounds. The model can now
            # recognise an unlabeled camera/microphone/attachment icon visually
            # while still being constrained to an opaque current-page action id.
            try:
                from PIL import Image, ImageDraw
                image = Image.open(BytesIO(image_bytes)).convert("RGB")
                draw = ImageDraw.Draw(image)
                catalog = ((prompt.get("untrusted_page_data") or {}).get("elements") or [])
                for item in catalog:
                    match = re.fullmatch(
                        r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                        str(item.get("bounds") or ""),
                    )
                    if not match:
                        continue
                    left, top, right, bottom = (int(value) for value in match.groups())
                    if right <= left or bottom <= top:
                        continue
                    color = "#8a8a8a" if item.get("visited") else (
                        "#ff8c00" if item.get("recommended_for") else "#00a86b"
                    )
                    draw.rectangle((left, top, right, bottom), outline=color, width=3)
                    label = str(item.get("action_id") or "")
                    if label:
                        label_top = max(0, top - 18)
                        draw.rectangle((left, label_top, left + 46, top), fill=color)
                        draw.text((left + 2, label_top + 2), label, fill="white")
                rendered = BytesIO()
                image.save(rendered, format="PNG")
                image_bytes = rendered.getvalue()
            except Exception:
                # Pillow/image decoding is optional; raw screenshot plus bounds
                # metadata remains a valid multimodal observation.
                pass
            payload = base64.b64encode(image_bytes).decode("ascii")
        except OSError:
            return text
        mime = "image/png" if payload else (mimetypes.guess_type(path.name)[0] or "image/png")
        return [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{payload}"}},
        ]

    @staticmethod
    def _vision_unsupported(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(marker in message for marker in (
            "image_url", "multimodal", "vision", "image input", "content must be a string",
        ))

    @staticmethod
    def _response_format_unsupported(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(marker in message for marker in (
            "response_format", "json_object", "structured output", "unsupported parameter",
            "unknown parameter", "not supported",
        ))

    def choose_action(self, page: dict, visited_targets: set[str]) -> dict:
        llm = self.cfg["llm"]
        api_key = os.environ.get(llm["api_key_env"], "")
        if not api_key:
            raise EngineUnavailableError(f"未配置 {llm['api_key_env']}，无法使用真实 AI 遍历")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EngineUnavailableError("缺少 openai 依赖，请安装 backend/requirements.txt") from exc
        action_catalog, action_context = self._action_context(page, visited_targets)
        untrusted_page = dict(page)
        for raw_key in (
            "rule_guided_target", "sensitive_media_candidates", "sensitive_media_families",
            "screenshot_path",
        ):
            untrusted_page.pop(raw_key, None)
        untrusted_page["elements"] = [
            {key: value for key, value in element.items() if key != "execution_target"}
            for element in action_catalog
        ]
        prompt = {
            "role": "App 隐私合规测试员",
            "goal": (
                "像人类检测员探索：先认 page_role。同意弹窗只勾选/同意；条款在设置枢纽读；"
                "枢纽逐项钻设置/注销/关于/退出登录确认框。Appium 做安全边界与机械步骤。"
            ),
            "untrusted_page_data": untrusted_page,
            **action_context,
            "unread_document_links": page.get("unread_document_links") or [],
            "outstanding_rule_scenarios": page.get("outstanding_rule_scenarios") or [],
            "response_schema": {"action": "click|back|wait|stop", "target": "click 时必须为当前元素的 action_id", "reason": "简短理由"},
        }
        client = OpenAI(api_key=api_key, base_url=llm["base_url"], timeout=llm["timeout_seconds"])
        user_content = self._user_content(prompt, str(page.get("screenshot_path") or ""))
        request = {
            "model": llm["model"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "max_tokens": 420,
        }
        try:
            response = client.chat.completions.create(**request, response_format={"type": "json_object"})
        except Exception as exc:
            if isinstance(user_content, list) and self._vision_unsupported(exc):
                request["messages"][-1]["content"] = json.dumps(prompt, ensure_ascii=False)
                try:
                    response = client.chat.completions.create(
                        **request, response_format={"type": "json_object"},
                    )
                except Exception as text_exc:
                    if not self._response_format_unsupported(text_exc):
                        raise
                    response = client.chat.completions.create(**request)
            elif self._response_format_unsupported(exc):
                response = client.chat.completions.create(**request)
            else:
                raise
        raw = response.choices[0].message.content or ""
        return self.parse_decision(raw, action_catalog)

    def assess_login_state(self, page: dict) -> bool:
        """Classify the visible page after the human-login wait expires.

        This never reads credentials and has no action capability.  A failed or
        ambiguous model response is deliberately treated as not logged in.
        """
        llm = self.cfg["llm"]
        api_key = os.environ.get(llm["api_key_env"], "")
        if not api_key:
            return False
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=llm["base_url"], timeout=llm["timeout_seconds"])
            response = client.chat.completions.create(
                model=llm["model"], temperature=0, max_tokens=40,
                messages=[
                    {"role": "system", "content": "仅根据可见 UI 和 screen_text 判断是否已登录。出现“登录成功/成功登录/登陆成功/欢迎回来”即已登录，即使登录表单还在。出现“未登录/未登陆/请先登录/游客”表示未登录。登录表单、验证码、登录按钮且没有成功提示表示未登录。个人昵称、退出登录、账户资料页表示已登录。只输出 JSON。"},
                    {"role": "user", "content": json.dumps({"page": page, "response_schema": {"logged_in": "boolean"}}, ensure_ascii=False)},
                ], response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content or "{}").get("logged_in") is True
        except Exception:
            return False

    @staticmethod
    def fallback_action(
        elements: list[dict],
        visited_targets: set[str],
        allow_dialog_actions: bool = False,
        *,
        page_role: str = "",
        sdk_dwell_pending: bool = False,
        hub_pending: bool = False,
        consent_dialog: bool = False,
    ) -> dict:
        """LLM 短暂不可用时的安全兜底。

        不在同意弹窗、SDK 静默观察未完成、或设置枢纽仍有确定性待办时抢点
        「隐私/设置」——那些场景由 Appium 确定性层处理，避免与确定性语义冲突。
        """
        if sdk_dwell_pending:
            return {"action": "wait", "target": "", "reason": "SDK 观察未完成，LLM 不可用时暂留，避免抢点设置"}
        if consent_dialog or page_role == "consent_dialog":
            return {"action": "wait", "target": "", "reason": "同意弹窗应由确定性层勾选/同意，LLM 兜底不抢点条款外链"}
        if hub_pending and page_role in {"document_hub", "app_page"}:
            return {"action": "wait", "target": "", "reason": "设置枢纽仍有待办，LLM 兜底暂留由确定性层滚动/择路"}

        priorities = (
            "隐私", "用户协议", "服务条款", "服务协议", "政策", "设置", "更多设置", "我的",
            "账号", "撤回", "授权管理", "注销", "退出登录", "关于", "投诉",
        )
        credential_terms = (
            "password", "phone", "mobile", "account", "username", "verify", "code", "login", "register",
            "submit", "send", "checkbox", "edittext", "et_", "btn_login", "btn_register", "tvsendcode",
            "密码", "手机号", "账号", "验证码", "登录", "注册", "发送", "提交", "勾选",
        )
        decline_terms = ("不同意", "拒绝", "取消", "退出", "暂不", "以后再说", "decline", "not now", "cancel", "exit")
        dialog_ids = (
            "btn_positive", "btn_negative", "btn_agree", "btn_confirm", "privacy_agree",
            "ok_btn", "btn_ok", "agree_btn", "btn_accept",
        )
        # Splash book-title links must never be a fallback click.
        document_link_terms = (
            "隐私政策", "隐私协议", "用户协议", "服务协议", "服务条款", "使用条款",
            "第三方sdk", "sdk目录", "收集清单", "《",
        )

        def is_account_operation(element: dict) -> bool:
            identity = " ".join(str(element.get(key) or "") for key in ("resource_id", "text", "content_desc")).lower()
            return any(term.lower() in identity for term in credential_terms)

        def is_unsafe_dialog_action(element: dict) -> bool:
            identity = " ".join(str(element.get(key) or "") for key in ("resource_id", "text", "content_desc")).lower()
            if any(term.lower() in identity for term in decline_terms):
                return True
            return not allow_dialog_actions and any(dialog_id in identity for dialog_id in dialog_ids)

        def is_document_link(element: dict) -> bool:
            identity = " ".join(str(element.get(key) or "") for key in ("resource_id", "text", "content_desc"))
            return any(term.lower() in identity.lower() for term in document_link_terms)

        candidates = [
            e for e in elements
            if e.get("clickable")
            and not is_account_operation(e)
            and not is_unsafe_dialog_action(e)
            and not is_document_link(e)
        ]
        candidates.sort(key=lambda e: 0 if any(p in " ".join((e.get("text", ""), e.get("content_desc", ""))) for p in priorities) else 1)
        for element in candidates:
            target = element.get("target") or element.get("resource_id") or element.get("text") or element.get("content_desc")
            if target and target not in visited_targets:
                return {"action": "click", "target": target, "reason": "本地启发式兜底"}
        return {"action": "back", "target": "", "reason": "无安全的未访问入口，避免触发账号或数据操作"}
