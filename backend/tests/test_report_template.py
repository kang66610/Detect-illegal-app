from datetime import datetime
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape

from agent.rule_engine.report_generator import _TEMPLATE_DIR
from agent.rule_engine.report_generator import evidence_for_match
from agent.rule_engine.rule_loader import Condition, Rule
from agent.rule_engine.rule_matcher import MatchedViolation
from agent.detection_engines.base import Finding


def test_auto_report_template_follows_human_audit_report_structure():
    template = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape(["html"]),
    ).get_template("report.html")

    html = template.render(
        report_no="Demo-RPT-0001",
        task=SimpleNamespace(mode="fast"),
        apk=SimpleNamespace(app_name="Demo", filename="demo.apk", version_name="1.0", package_name="com.demo", md5="x"),
        matched=[], now=datetime(2026, 8, 14), header={},
    )

    assert "一、评估对象基本信息" in html
    assert "二、评估结果" in html
    assert "三、评估参考范围" in html
    assert "软件名称：" in html
    assert "不代表 App 合规" in html
    assert "外部静态分析状态" not in html


def test_auto_report_renders_rule_specific_timeline_evidence_not_only_screenshots():
    template = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape(["html"]),
    ).get_template("report.html")
    matched = SimpleNamespace(
        rule=SimpleNamespace(category=4, category_name="违反必要原则", rule_name="拒绝权限后功能受阻",
                             legal_basis="认定方法第四条", suggestion="按需申请"),
        screenshots=[], evidence_items=[
            {"type": "timeline", "label": "拒绝权限后业务操作结果", "detail": "拒绝存储权限后，点击上传头像，页面提示暂无存储权限"},
        ], evidence_limit="该结论仅覆盖已执行的上传头像路径。",
    )

    html = template.render(
        report_no="Demo-RPT-0002", task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(app_name="Demo", filename="demo.apk", version_name="1.0", package_name="com.demo", md5="x"),
        matched=[matched], summary={"coverage_gaps": []}, now=datetime(2026, 8, 17), header={},
    )

    assert "证据说明" in html
    assert "拒绝存储权限后，点击上传头像" in html
    assert "修复建议" in html


def test_report_evidence_orders_screenshots_before_text_artifacts():
    rule = Rule(
        rule_id="RULE_4_2", rule_name="拒绝权限后功能受阻", category=4,
        legal_basis="第四条第（二）点", risk_level="中", weight=1,
        conditions=[Condition(field="permission_denial_blocks_function", op="eq", value=True)],
        evidence_fields=["timeline", "screenshot"], suggestion="按需申请",
    )
    finding = Finding(kind="permission_denial_blocks_function", category=4, payload={})
    match = MatchedViolation(rule=rule, finding=finding, payload={})
    evidence = [
        {"type": "timeline", "path": "timeline.json", "meta": {"finding_kind": finding.kind}},
        {"type": "screenshot", "path": "proof.png", "meta": {"finding_kind": finding.kind}},
    ]

    assert [item["type"] for item in evidence_for_match(match, evidence)] == ["screenshot", "timeline"]


def test_report_template_uses_text_fallback_when_no_screenshot_exists():
    matched = SimpleNamespace(
        rule=SimpleNamespace(category=3, category_name="未经同意收集", rule_name="未经用户同意收集个人信息",
                             legal_basis="认定方法第三条", suggestion="取得同意"),
        screenshots=[], evidence_items=[], evidence_fallback="根据页面操作时间线确认：用户同意前已触发敏感信息收集。",
        evidence_limit="该结论仅覆盖本次已执行路径。",
    )
    template = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape(["html"]),
    ).get_template("report.html")

    html = template.render(
        report_no="Demo-RPT-0003", task=SimpleNamespace(mode="deep"),
        apk=SimpleNamespace(app_name="Demo", filename="demo.apk", version_name="1.0", package_name="com.demo", md5="x"),
        matched=[matched], summary={}, now=datetime(2026, 8, 17), header={},
    )

    assert "证据说明" in html
    assert "用户同意前已触发敏感信息收集" in html
