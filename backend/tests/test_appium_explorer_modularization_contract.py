"""Behavior baselines and ratcheting architecture gates for explorer modularization."""
import re
from pathlib import Path

from agent.detection_engines.page_semantics import (
    PageFacts,
    PageObservation,
    PageRole,
    classify_observation,
)


EXPLORER_PATH = Path(__file__).resolve().parents[2] / "agent" / "detection_engines" / "appium_explorer.py"


def test_consent_catalog_and_role_baseline_are_stable():
    elements = (
        {"text": "同意", "content_desc": "", "target": "agree", "clickable": True, "displayed": True},
        {"text": "不同意", "content_desc": "", "target": "decline", "clickable": True, "displayed": True},
        {"text": "隐私政策", "content_desc": "", "target": "policy", "clickable": True, "displayed": True},
    )

    page = classify_observation(PageObservation(
        activity="com.example.MainActivity",
        elements=elements,
        facts=PageFacts(consent_dialog=True, main_content=True),
    ))

    assert page.role is PageRole.CONSENT_DIALOG
    assert [item.kind.value for item in page.targets] == ["consent", "decline", "document"]
    assert [item.value for item in page.blocked_roles] == ["main_content"]


def test_explorer_has_no_legacy_direct_action_boundary():
    source = EXPLORER_PATH.read_text(encoding="utf-8")

    assert "self.client.perform(decision)" not in source


def test_engine_facade_has_no_direct_domain_execution_or_state_writes():
    source = EXPLORER_PATH.read_text(encoding="utf-8")

    assert "self.client.perform(" not in source
    assert "scenario_frontier.mark_completed(" not in source
    assert not re.search(r"ctx\.runtime\[[^\]]+\]\s*=", source)
    assert len(source.splitlines()) <= 700


# The exploration loop now lives in the implementation module. These ratchets
# keep its remaining imperative surface measurable and decreasing-only until
# the phase E/F decomposition lands.
ENGINE_PATH = Path(__file__).resolve().parents[2] / "agent" / "ai_explorer" / "explorer_engine.py"

# Frozen at the post-migration baseline. The only allowed direction is down.
DIRECT_RUNTIME_WRITE_BUDGET = 117
DIRECT_CLIENT_ACTION_BUDGET = 0  # replay moved to agent.ai_explorer.navigation_replay
# 10,744 = 10,737 + 7（blocked-route 阻断转候选的提案构造与门控开销）。
# 10,766 = 10,744 + 12（global_target_attempts 计数否决块移到仲裁之后、
# 改写适配为 final_action replace 的结构开销）+ 10（transaction 阻断转候选的
# 提案构造与门控开销）。
# 10,435 = 10,766 - 331（第四刀：同意簇 12 函数 + 10 词表逐字迁出为
# consent_vocabulary.py（375 行），引擎按 22 个别名回导消费）。
# 10,501 = 10,435 + 66（root override 两组与深搜兄弟改写转候选的提案构造与
# 门控注释开销）。
# 10,513 = 10,501 + 12（修正：两处根页纯等待保持命令式——下游连续等待熔断器
# 与枢纽等待改写仍以 decision 为 wait 为键，候选化会使其失明）。
# 10,545 = 10,513 + 32（frontier 候选折叠注销/退出确认守卫：旧级联的下游
# click 守卫对候选胜出者失明，退出登录边界与退出确认框的裁决必须在
# 提案生成处复刻，守护 test_root_frontier_cannot_rewrite_logout_back_into_a_click）。
# 10,563 = 10,545 + 18（后置已读守卫泛化为裁决全部待选 click 候选——兄弟/root
# 候选绕过它会重开已完成条款（263 套件 sdk-entry 用例捕获）；stop/wait 级联
# 处理块加 sibling_proposal is None 门控复刻兄弟改写的先占）。
# 10,585 = 10,563 + 22（第三方/退出确认 click/破坏性/注销 7 处转候选的提案
# 构造开销；退出确认的 2 处 wait 分支按约束保持命令式）。
# 10,353 = 10,585 - 232（第五刀前置 B：未读家族 9 函数 + consent_or_decline/
# element_locator 归位——纯文档词表下沉 target_catalog、未读家族与安全宿主
# 谓词迁入 document_state、consent_or_decline_control 迁入 consent_vocabulary，
# 引擎按别名回导消费）。
# 10,222 = 10,353 - 131（第五刀前置 C：redress 观察家族归位——redress_entry/
# complaint_or_cs_entry/page_visible_text/privacy_path_observations 与
# 投诉/注销/撤回/障碍词表迁入 redress_media_probe，element_semantic_identity
# 下沉 target_catalog，引擎按别名回导消费）。
# 9,756 = 10,222 - 466（第五刀主刀 D：枢纽导航家族迁出为 hub_navigation.py——
# 15 个 hub 函数 + 4 组词表 + SETTINGS_HUB_NAVIGATOR 实例，global_target_key/
# authenticated_logout_target 分别归位 target_catalog/consent_vocabulary，
# 低审计裁剪经 low_audit_route_check 注入，引擎按别名回导消费）。
# 9,767 = 9,756 + 11（连续等待熔断转候选：有效动作驱动 + 4 处改写转为
# priority=160 候选的开销）。
# 9,783 = 9,767 + 16（F.1a：客服媒体早退与穷尽分支改为获选后才写账本/事件的
# 候选回调；纯候选选择迁入 redress_media_probe.py，回调保留在页面周期以持有
# 本轮 evidence、surface 与 runtime 所有者）。
# 9,789 = 9,783 + 6（F.1b：合并文档重定向改为候选并接入后置已读守卫；纯选
# 择迁入 document_state.py，获选事件回调保留在页面周期）。
# 9,796 = 9,789 + 7（F.1b：已读条款后的枢纽注销/授权行改为候选；后置已读
# 守卫改读候选，避免旧已读目标抢占重定向）。
# 9,801 = 9,796 + 5（F.1c：登出仅观察改为候选，获选后才标记入口与记录事件）。
# 9,815 = 9,801 + 14（F.1c：deny 阶段延后登出/注销改为候选，获选后才标记原
# 入口并记录 4.2 事件；后续破坏性/注销确认链以有效候选门控）。
# 9,850 = 9,815 + 35（F.1c：破坏性确认与登出确认改为候选；登出确认状态与
# 事件仅在获选时提交，保持会话边界链的无损顺序）。
# 9,866 = 9,850 + 16（F.1c：已探索登出入口的重复进入保护改为候选，获选时才
# 记录阻断事件）。
# 后续转化的净增行数将在 F.1 装配迁移与后续分解中被吸收。
# 分解切片只允许把行数迁出；E.1/E.3 各点转化按实际开销凭据调整本行并留痕。
EXPLORER_ENGINE_LINE_BUDGET = 9866
# E.1/E.3 baseline: imperative `decision` rewrites inside the phase cycle.
# Converting one override site into a pipeline candidate must decrease this.
# 67 = 68 - 1（F.1c：重复登出入口保护改为候选）。
# 68 = 70 - 2（F.1c：destructive_confirmation 与 logout_confirmation 改为候选）。
# 70 = 71 - 1（F.1c：defer_session_boundary 改为候选）。
# 71 = 72 - 1（F.1c：logout_observation_only 改为候选）。
# 72 = 73 - 1（F.1b：已读条款后的 hub_row 改为候选）。
# 73 = 74 - 1（F.1b：combined_document_redirected 改为候选）。
# 74 = 76 - 2（F.1a：sensitive_media_assist 与
#          customer_service_surface_exhausted 改为延迟提交的候选）。
# 76 = 80 - 4（连续等待熔断转候选：hub_wait_redirected、hub_wait_exhausted、
#          wait_loop_home_redirected、wait_loop_broken；计数改为对有效动作
#          记账——root/exit 的命令式 wait 经有效动作照常计数，sibling 候选
#          在场时按其 click 重置；熔断改写以 priority=160 压过等待候选）。
ENGINE_DECISION_REWRITE_BUDGET = 67


def test_engine_loop_completes_rules_only_with_legal_evidence():
    """Every rule completion in the loop must carry evidence_source or finding_kind."""
    source = ENGINE_PATH.read_text(encoding="utf-8")
    for match in re.finditer(r"scenario_frontier\.mark_completed\(", source):
        depth = 0
        for index in range(match.end() - 1, len(source)):
            if source[index] == "(":
                depth += 1
            elif source[index] == ")":
                depth -= 1
                if depth == 0:
                    args = source[match.end():index]
                    assert (
                        "evidence_source" in args or "finding_kind" in args
                    ), f"无证据完成调用: {args.strip()[:120]}"
                    break


def test_engine_loop_direct_write_and_action_surface_only_shrinks():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    direct_writes = len(re.findall(r"ctx\.runtime\[[^\]]+\]\s*=", source))
    direct_actions = len(re.findall(r"client\.perform\(|client\.back\(", source))

    assert direct_writes <= DIRECT_RUNTIME_WRITE_BUDGET, (
        f"主循环直接 runtime 写入增加: {direct_writes} > {DIRECT_RUNTIME_WRITE_BUDGET}；"
        "领域状态应迁给所有者后再合并"
    )
    assert direct_actions <= DIRECT_CLIENT_ACTION_BUDGET, (
        f"主循环直接设备动作增加: {direct_actions} > {DIRECT_CLIENT_ACTION_BUDGET}"
    )
    assert len(source.splitlines()) <= EXPLORER_ENGINE_LINE_BUDGET, (
        f"实现模块行数回升: {len(source.splitlines())} > {EXPLORER_ENGINE_LINE_BUDGET}；"
        "分解切片只允许把行数迁出"
    )


def test_engine_loop_decision_rewrites_only_shrink():
    """E.1/E.3: 每把一个顺序覆盖改写点转成 pipeline 候选，该数字必须下降。"""
    import ast as ast_module

    source = ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast_module.parse(source)
    count = 0
    for node in ast_module.walk(tree):
        if isinstance(node, ast_module.ClassDef):
            for item in node.body:
                if isinstance(item, ast_module.FunctionDef) and item.name == "_run_phase_cycle":
                    for inner in ast_module.walk(item):
                        if isinstance(inner, ast_module.Assign):
                            count += sum(
                                1 for target in inner.targets
                                if isinstance(target, ast_module.Name) and target.id == "decision"
                            )
    assert count <= ENGINE_DECISION_REWRITE_BUDGET, (
        f"decision 命令式改写增加: {count} > {ENGINE_DECISION_REWRITE_BUDGET}；"
        "覆盖点应转成 ActionPipeline 候选而不是新增改写"
    )
