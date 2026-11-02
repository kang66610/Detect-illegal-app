"""Generate a concise editable Word report based on the manual-report format."""

from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt, RGBColor

from backend.app.config import PROJECT_ROOT, config


CONTENT_WIDTH_DXA = 8296
TABLE_INDENT_DXA = 0
BLACK = "000000"
GRAY = "666666"
LINE = "222222"

DETAIL_LABELS = {
    "data_type": "数据类型",
    "sdk": "相关 SDK",
    "host": "网络域名",
    "count": "发生次数",
    "permissions": "相关权限",
    "matched_by": "识别依据",
    "evidence_source": "证据来源",
    "pages_covered": "覆盖页面",
    "message": "提示文案",
    "permission_label": "权限名称",
    "page": "页面标识",
    "permission_rerequest_after_denial": "拒绝后重复申请",
    "privacy_hub_visited": "已访问隐私中心",
    "withdraw_ui_observed": "已观察到撤回入口",
    "policy_discloses_withdraw_path": "隐私政策披露撤回路径",
    "withdraw_consent_unavailable": "无法撤回同意",
    "probe_action": "探测动作",
    "business_action": "业务操作",
    "permission_message_matched": "权限文案匹配",
    "permission_denial_blocks_function": "拒绝权限后阻断功能",
    "missing_dimensions": "缺失披露维度",
    "policy_source": "隐私政策来源",
    "policy_length": "隐私政策文本长度",
    "linked_collection_list": "已关联收集清单",
    "itemized_disclosure": "逐项披露",
    "undisclosed_sdks": "未披露的 SDK",
    "purpose_not_disclosed": "未披露收集目的",
    "purpose_context": "权限使用说明",
    "purpose_explained_before_prompt": "授权前已说明用途",
    "purpose_context_verified": "用途说明已核验",
    "permission_purpose_not_informed": "申请权限前未告知目的",
    "sdk_known": "已识别 SDK",
    "policy_document_complete": "隐私政策文档完整",
    "sdk_collection_not_disclosed": "SDK 收集行为未披露",
    "no_complaint_channel": "未提供投诉举报渠道",
}

REFERENCES = (
    "《中华人民共和国网络安全法》",
    "《中华人民共和国个人信息保护法》",
    "《个人信息保护合规审计管理办法》（国家互联网信息办公室令第18号）",
    "《常见类型移动互联网应用程序必要个人信息范围规定》（国信办秘字〔2021〕14号）",
    "《App违法违规收集使用个人信息行为认定方法》（国信办秘字〔2019〕191号）",
    "《信息安全技术 移动互联网应用程序（App）收集个人信息基本要求》（GB/T 41391-2022）",
)

CN_NUMBERS = "一二三四五六七八九十"


def _set_run_font(run, *, size: float, bold: bool = False, color: str = BLACK) -> None:
    run.font.name = "Microsoft YaHei"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.rFonts
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for name in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{name}"), "Microsoft YaHei")


def _set_style_font(style, *, size: float, bold: bool = False) -> None:
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor.from_string(BLACK)
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.rFonts
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for name in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{name}"), "Microsoft YaHei")


def _configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    _set_style_font(normal, size=12.5)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.4

    heading1 = doc.styles["Heading 1"]
    _set_style_font(heading1, size=16, bold=True)
    heading1.paragraph_format.space_before = Pt(18)
    heading1.paragraph_format.space_after = Pt(8)
    heading1.paragraph_format.line_spacing = 1.2
    heading1.paragraph_format.keep_with_next = True

    heading2 = doc.styles["Heading 2"]
    _set_style_font(heading2, size=14, bold=True)
    heading2.paragraph_format.space_before = Pt(16)
    heading2.paragraph_format.space_after = Pt(8)
    heading2.paragraph_format.line_spacing = 1.2
    heading2.paragraph_format.keep_with_next = True

    for style_name in ("List Number", "List Paragraph"):
        style = doc.styles[style_name]
        _set_style_font(style, size=12.5)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.line_spacing = 1.45


def _configure_section(section) -> None:
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1.25)
    section.right_margin = Inches(1.25)
    section.header_distance = Inches(0.591)
    section.footer_distance = Inches(0.689)


def _set_cell_margins(cell, *, top: int = 110, start: int = 130,
                      bottom: int = 110, end: int = 130) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _set_cell_width(cell, width_dxa: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width_dxa))
    tc_w.set(qn("w:type"), "dxa")


def _set_table_geometry(table, widths_dxa: list[int]) -> None:
    if sum(widths_dxa) != CONTENT_WIDTH_DXA:
        raise ValueError(f"table widths must total {CONTENT_WIDTH_DXA} DXA")
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(CONTENT_WIDTH_DXA))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(TABLE_INDENT_DXA))
    tbl_ind.set(qn("w:type"), "dxa")
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    for grid_col, width in zip(table._tbl.tblGrid.gridCol_lst, widths_dxa):
        grid_col.set(qn("w:w"), str(width))
    for row in table.rows:
        for cell, width in zip(row.cells, widths_dxa):
            _set_cell_width(cell, width)
            _set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _set_table_borders(table, *, value: str = "single", size: int = 6,
                       color: str = LINE) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), value)
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)


def _set_cell_bottom_border(cell, *, size: int = 6) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "0")
    bottom.set(qn("w:color"), LINE)
    borders.append(bottom)


def _prevent_row_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    marker = OxmlElement("w:cantSplit")
    marker.set(qn("w:val"), "true")
    tr_pr.append(marker)


def _create_decimal_numbering(doc: Document) -> int:
    numbering = doc.part.numbering_part.element
    abstract_ids = [int(item.get(qn("w:abstractNumId"))) for item in numbering.findall(qn("w:abstractNum"))]
    num_ids = [int(item.get(qn("w:numId"))) for item in numbering.findall(qn("w:num"))]
    abstract_id = max(abstract_ids, default=-1) + 1
    num_id = max(num_ids, default=0) + 1

    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi_level = OxmlElement("w:multiLevelType")
    multi_level.set(qn("w:val"), "singleLevel")
    abstract.append(multi_level)
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    level.append(start)
    number_format = OxmlElement("w:numFmt")
    number_format.set(qn("w:val"), "decimal")
    level.append(number_format)
    level_text = OxmlElement("w:lvlText")
    level_text.set(qn("w:val"), "%1.")
    level.append(level_text)
    suffix = OxmlElement("w:suff")
    suffix.set(qn("w:val"), "space")
    level.append(suffix)
    ppr = OxmlElement("w:pPr")
    indent = OxmlElement("w:ind")
    indent.set(qn("w:left"), "560")
    indent.set(qn("w:hanging"), "320")
    ppr.append(indent)
    level.append(ppr)
    abstract.append(level)
    numbering.append(abstract)

    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abstract_ref = OxmlElement("w:abstractNumId")
    abstract_ref.set(qn("w:val"), str(abstract_id))
    num.append(abstract_ref)
    numbering.append(num)
    return num_id


def _add_numbered_item(doc: Document, text: str, num_id: int, *, size: float = 12.5) -> None:
    paragraph = doc.add_paragraph(style="List Paragraph")
    ppr = paragraph._p.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    number = OxmlElement("w:numId")
    number.set(qn("w:val"), str(num_id))
    num_pr.extend((ilvl, number))
    ppr.append(num_pr)
    _set_run_font(paragraph.add_run(text), size=size)


def _plain(value) -> str:
    if value in (None, "", [], {}):
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple, set)):
        return "、".join(_plain(item) for item in value) or "—"
    if isinstance(value, dict):
        return "；".join(f"{_detail_label(key)}：{_plain(item)}" for key, item in value.items()) or "—"
    return str(value)


def _set_cell_text(cell, value, *, size: float = 11.5, bold: bool = False,
                   alignment=WD_ALIGN_PARAGRAPH.CENTER, line_spacing: float = 1.2) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = alignment
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = line_spacing
    _set_run_font(paragraph.add_run(_plain(value)), size=size, bold=bold)


def _detail_label(key) -> str:
    normalized = str(key).strip().lower().replace(" ", "_")
    return DETAIL_LABELS.get(normalized, str(key).replace("_", " "))


def _format_local_date(value: datetime | None) -> str:
    if value is None:
        return datetime.now().strftime("%Y-%m-%d")
    local = value + timedelta(hours=8) if value.tzinfo is None else value.astimezone()
    return local.strftime("%Y-%m-%d")


def _add_cover(doc: Document, app_name: str, version: str, generated_at: datetime | None) -> None:
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(70)
    title.paragraph_format.space_after = Pt(70)
    _set_run_font(title.add_run("检测报告"), size=26)

    header = (config.get("report") or {}).get("header") or {}
    rows = [
        ("软件名称：", app_name),
        ("软件版本：", version),
        ("受检单位：", header.get("subject_org") or "—"),
        ("检测单位：", header.get("test_org") or "—"),
        ("委托单位：", header.get("entrust_org") or "—"),
        ("检测时间：", _format_local_date(generated_at)),
    ]
    table = doc.add_table(rows=len(rows), cols=2)
    _set_table_geometry(table, [1900, CONTENT_WIDTH_DXA - 1900])
    _set_table_borders(table, value="nil", size=0)
    for index, (label, value) in enumerate(rows):
        _set_cell_text(table.cell(index, 0), label, size=14.5, alignment=WD_ALIGN_PARAGRAPH.LEFT, line_spacing=1.0)
        _set_cell_text(table.cell(index, 1), value, size=14.5, line_spacing=1.0)
        _set_cell_bottom_border(table.cell(index, 1))
        _set_cell_margins(table.cell(index, 0), top=70, start=0, bottom=70, end=0)
        _set_cell_margins(table.cell(index, 1), top=70, start=80, bottom=70, end=80)
        _prevent_row_split(table.rows[index])


def _add_basic_info_table(doc: Document, app, app_name: str) -> None:
    table = doc.add_table(rows=6, cols=4)
    widths = [1891, 2782, 1407, 2216]
    _set_table_geometry(table, widths)
    _set_table_borders(table)

    first_row = (("App 名称", True), (app_name, False), ("版本", True), (getattr(app, "version_name", None), False))
    for index, (value, bold) in enumerate(first_row):
        _set_cell_text(table.cell(0, index), value, bold=bold)

    remaining = (
        ("包名", getattr(app, "package_name", None)),
        ("MD5 值", getattr(app, "md5", None)),
        ("下载渠道", "用户上传 APK"),
        ("下载地址", getattr(app, "filename", None)),
        ("运营者名称", ((config.get("report") or {}).get("header") or {}).get("subject_org") or "—"),
    )
    for row_index, (label, value) in enumerate(remaining, 1):
        _set_cell_text(table.cell(row_index, 0), label, bold=True)
        merged = table.cell(row_index, 1).merge(table.cell(row_index, 3))
        _set_cell_text(merged, value)
        _set_cell_width(merged, sum(widths[1:]))
    for row in table.rows:
        _prevent_row_split(row)


def _add_summary(doc: Document, app_name: str, violations: list) -> None:
    doc.add_heading("二、评估结果", level=1)
    lead = doc.add_paragraph()
    lead.paragraph_format.first_line_indent = Inches(0.33)
    lead.paragraph_format.keep_with_next = True
    if violations:
        _set_run_font(
            lead.add_run(f"经过评估，“{app_name}”App 在处理个人信息以及个人信息保护活动中，存在以下问题："),
            size=14,
            bold=True,
        )
        list_numbering = _create_decimal_numbering(doc)
        for violation in violations:
            _add_numbered_item(doc, violation.description or violation.category_name, list_numbering)
    else:
        _set_run_font(
            lead.add_run("本次自动检测未形成可支撑违规认定的完整证据；该结果不代表 App 合规。"),
            size=14,
            bold=True,
        )

def _evidence_text(violation) -> str:
    parts = []
    if getattr(violation, "rule_id", None):
        parts.append(f"规则编号：{violation.rule_id}")
    if getattr(violation, "page", None):
        parts.append(f"发生页面：{violation.page}")

    detail = getattr(violation, "detail", None) or {}
    preferred = (
        "evidence_source", "data_type", "sdk", "undisclosed_sdks", "permissions",
        "permission_label", "message", "probe_action", "business_action", "host",
        "missing_dimensions", "policy_source", "pages_covered", "count",
    )
    selected = 0
    for key in preferred:
        value = detail.get(key)
        if value in (None, "", [], {}):
            continue
        rendered = _plain(value)
        if len(rendered) > 180:
            rendered = rendered[:177] + "…"
        parts.append(f"{_detail_label(key)}：{rendered}")
        selected += 1
        if selected >= 5:
            break
    if not parts:
        return "系统根据已采集的页面、权限及动态行为记录形成该项认定。"
    return "；".join(parts) + "。"


def _cn_index(index: int) -> str:
    if 1 <= index <= 10:
        return CN_NUMBERS[index - 1]
    if 11 <= index <= 19:
        return "十" + CN_NUMBERS[index - 11]
    return str(index)


def _add_issue(doc: Document, violation, index: int, evidence: list[dict] | None = None) -> None:
    heading = doc.add_heading(
        f"（{_cn_index(index)}）{violation.description or violation.category_name}",
        level=2,
    )
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    label = doc.add_paragraph()
    label.paragraph_format.keep_with_next = True
    _set_run_font(label.add_run("问题描述："), size=13, bold=True)

    description = doc.add_paragraph()
    description.paragraph_format.first_line_indent = Inches(0.33)
    basis = str(getattr(violation, "legal_basis", "") or "").strip()
    text = str(violation.description or violation.category_name)
    if basis:
        text = f"App 存在“{text}”的情形，违反{basis}。"
    else:
        text = f"App 存在“{text}”的情形。"
    _set_run_font(description.add_run(text), size=12.5)

    evidence_label = doc.add_paragraph()
    evidence_label.paragraph_format.keep_with_next = True
    _set_run_font(evidence_label.add_run("证据："), size=13, bold=True)
    evidence_rows = sorted(
        list(evidence or []),
        key=lambda item: 0 if str(item.get("type") or "") == "screenshot" else 1,
    )
    screenshots = [item for item in evidence_rows if item.get("type") == "screenshot"]
    text_rows = [item for item in evidence_rows if item.get("type") != "screenshot"]
    embedded_screenshots = 0
    if screenshots:
        screenshot_label = doc.add_paragraph()
        screenshot_label.paragraph_format.keep_with_next = True
        _set_run_font(screenshot_label.add_run("截图证据："), size=12.5, bold=True)
        for item in screenshots:
            raw_path = Path(str(item.get("file_path") or ""))
            path = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
            if not path.exists():
                continue
            try:
                paragraph = doc.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.paragraph_format.keep_with_next = True
                paragraph.add_run().add_picture(str(path), width=Inches(5.8))
                embedded_screenshots += 1
            except Exception:
                # A corrupt/missing image must fall back to textual evidence.
                pass
    if text_rows or not embedded_screenshots:
        text_evidence = doc.add_paragraph()
        text_evidence.paragraph_format.first_line_indent = Inches(0.33)
        if text_rows:
            details = []
            for item in text_rows:
                meta = item.get("meta") or {}
                event_type = str(meta.get("event_type") or item.get("type") or "文字证据")
                detail = "；".join(
                    f"{key}={value}" for key, value in meta.items()
                    if key not in {"event_type", "finding_kind", "finding_kinds"}
                    and value not in (None, "", [], {})
                )
                details.append(f"{event_type}{('：' + detail) if detail else ''}")
            value = "；".join(details)
        else:
            value = _evidence_text(violation)
        _set_run_font(text_evidence.add_run(value), size=12)

    suggestion = doc.add_paragraph()
    suggestion.paragraph_format.space_before = Pt(4)
    suggestion.paragraph_format.keep_together = True
    _set_run_font(suggestion.add_run("修改建议："), size=13, bold=True)
    remediation = getattr(violation, "remediation_suggestion", None) or "请依据对应法规要求补充说明，并完善用户授权和控制能力。"
    _set_run_font(suggestion.add_run(str(remediation)), size=12.5)


def _add_references(doc: Document, report_no: str) -> None:
    doc.add_page_break()
    doc.add_heading("三、评估参考范围", level=1)
    list_numbering = _create_decimal_numbering(doc)
    for item in REFERENCES:
        _add_numbered_item(doc, item, list_numbering, size=12.5)
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.paragraph_format.space_before = Pt(20)
    _set_run_font(footer.add_run(f"报告编号：{report_no}　由 App 隐私合规自动化检测平台生成"), size=9, color=GRAY)


def build_report_docx(report, violations: Iterable, reviews: list[dict] | None = None,
                      server_events: list[dict] | None = None,
                      evidence_by_violation: dict[int, list[dict]] | None = None) -> BytesIO:
    """Return a concise, fully editable ``.docx`` report in memory."""
    del reviews, server_events
    violations = list(violations)
    risk_order = {"高": 0, "中": 1, "低": 2}
    violations.sort(key=lambda item: (risk_order.get(item.risk_level, 9), item.category, item.id))

    app = report.task.apk
    app_name = app.app_name or app.filename or "未命名应用"
    version = getattr(app, "version_name", None) or "—"

    doc = Document()
    _configure_section(doc.sections[0])
    _configure_styles(doc)
    _add_cover(doc, app_name, version, report.generated_at)

    body_section = doc.add_section(WD_SECTION.NEW_PAGE)
    _configure_section(body_section)
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(14)
    title.paragraph_format.keep_with_next = True
    _set_run_font(title.add_run(f"“{app_name}”个人信息合规检测报告"), size=22)

    doc.add_heading("一、评估对象基本信息", level=1)
    _add_basic_info_table(doc, app, app_name)
    _add_summary(doc, app_name, violations)

    if violations:
        doc.add_page_break()
        for index, violation in enumerate(violations, 1):
            _add_issue(doc, violation, index, (evidence_by_violation or {}).get(int(violation.id), []))

    _add_references(doc, report.report_no)

    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return output
