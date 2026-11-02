from pathlib import Path

from agent.rule_engine.report_generator import render_pdf


def test_render_pdf_creates_valid_pdf(tmp_path):
    html = tmp_path / "r.html"
    html.write_text("<html><head><meta charset='utf-8'></head><body><h1>检测报告</h1><p>测试</p></body></html>", encoding="utf-8")
    out = tmp_path / "r.pdf"
    render_pdf(html, out)
    assert out.exists() and out.stat().st_size > 500
    assert out.read_bytes()[:4] == b"%PDF"
