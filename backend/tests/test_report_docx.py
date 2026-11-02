from io import BytesIO
from types import SimpleNamespace

from docx import Document
from PIL import Image

from backend.app.services.report_docx import build_report_docx


def test_build_report_docx_is_editable_and_contains_report_sections():
    apk = SimpleNamespace(
        app_name="测试应用", filename="sample.apk", package_name="com.example.sample", version_name="1.2.3",
        md5="0123456789ABCDEF0123456789ABCDEF",
    )
    task = SimpleNamespace(apk=apk)
    report = SimpleNamespace(
        task=task,
        report_no="测试应用-RPT-20260826-0001",
        score=72,
        generated_at=None,
        summary={
            "total": 1,
            "by_risk": {"高": 1, "中": 0, "低": 0},
            "coverage_gaps": ["未覆盖登录后功能"],
            "adjudication_counts": {"violation": 1, "no_violation_evidence": 2, "not_covered": 28},
        },
    )
    violation = SimpleNamespace(
        id=1, category=3, category_name="违规收集个人信息", rule_id="RULE_3_1",
        description="同意隐私政策前收集个人信息", legal_basis="《个人信息保护法》",
        risk_level="高", page="启动页", remediation_suggestion="将数据收集延后至用户同意后。",
        detail={"data_type": "设备标识符"},
    )
    reviews = [{
        "legal_key": "3.1", "evidence_scope": "device", "title": "同意前收集个人信息",
        "tri_state": "violation", "status": "violation",
    }]

    output = build_report_docx(report, [violation], reviews, [])

    assert output.getvalue()[:2] == b"PK"
    document = Document(BytesIO(output.getvalue()))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    table_text = "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    assert "测试应用" in text
    assert "测试应用”个人信息合规检测报告" in text
    assert "二、评估结果" in text
    assert "（一）同意隐私政策前收集个人信息" in text
    assert "证据：" in text
    assert "规则编号：RULE_3_1" in text
    assert "三、评估参考范围" in text
    assert "MD5 值" in table_text
    assert len(document.sections) == 2


def test_build_report_docx_places_screenshot_evidence_before_text_fallback(tmp_path):
    screenshot = tmp_path / "proof.png"
    Image.new("RGB", (80, 80), "white").save(screenshot)
    apk = SimpleNamespace(
        app_name="截图应用", filename="sample.apk", package_name="com.example.sample", version_name="1.0", md5="x",
    )
    report = SimpleNamespace(
        task=SimpleNamespace(apk=apk), report_no="截图-RPT-1", score=80, generated_at=None,
        summary={"total": 1, "by_risk": {"高": 0, "中": 1, "低": 0}, "coverage_gaps": []},
    )
    violation = SimpleNamespace(
        id=42, category=4, category_name="必要性", rule_id="RULE_4_2", description="拒绝权限后功能受阻",
        legal_basis="第四条", risk_level="中", page="首页", remediation_suggestion="按需申请",
        detail={"message": "页面提示权限不足"},
    )

    output = build_report_docx(
        report,
        [violation],
        evidence_by_violation={42: [
            {"type": "timeline", "file_path": "timeline.json", "meta": {"event_type": "result"}},
            {"type": "screenshot", "file_path": str(screenshot), "meta": {}},
        ]},
    )

    document = Document(BytesIO(output.getvalue()))
    assert len(document.inline_shapes) == 1
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    assert paragraphs.index("证据：") < paragraphs.index("截图证据：")
