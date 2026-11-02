from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from backend.app.config import PROJECT_ROOT
from backend.app.services import report_docx, report_service, review_service

router = APIRouter(prefix="/api/reports", tags=["report"])


@router.get("/{task_id}")
def get_report(task_id: int):
    try:
        report, violations = report_service.get_report(task_id)
    except Exception:
        raise HTTPException(status_code=404, detail="报告不存在")
    return {
        "report_no": report.report_no, "app_name": report.task.apk.app_name or report.task.apk.filename, "score": report.score,
        "summary": report.summary, "weight_breakdown": report.weight_breakdown,
        "generated_at": report.generated_at,
        "violations": [
            {
                "id": v.id, "category": v.category, "category_name": v.category_name,
                "rule_id": v.rule_id,
                "description": v.description, "legal_basis": v.legal_basis,
                "risk_level": v.risk_level, "page": v.page,
                "suggestion": v.remediation_suggestion, "detail": v.detail,
                "evidence": [
                    {
                        "id": evidence.id,
                        "type": evidence.type,
                        "meta": evidence.meta or {},
                        "url": f"/api/reports/{task_id}/evidence/{evidence.id}",
                    }
                    for evidence in (v.evidences or [])
                ],
            }
            for v in violations
        ],
    }


@router.get("/{task_id}/pdf")
def download_pdf(task_id: int):
    try:
        report, _ = report_service.get_report(task_id)
    except Exception:
        raise HTTPException(status_code=404, detail="报告不存在")
    path = PROJECT_ROOT / report.pdf_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    return FileResponse(path, filename=f"{report.report_no}.pdf", media_type="application/pdf")


@router.get("/{task_id}/docx")
def download_docx(task_id: int):
    try:
        report, violations = report_service.get_report(task_id)
        reviews = review_service.list_reviews(task_id)
        server_events = review_service.list_server_events(task_id)
    except Exception:
        raise HTTPException(status_code=404, detail="报告不存在")
    evidence_by_violation = {
        int(violation.id): [
            {"type": evidence.type, "file_path": evidence.file_path, "meta": evidence.meta or {}}
            for evidence in (violation.evidences or [])
        ]
        for violation in violations
    }

    content = report_docx.build_report_docx(
        report, violations, reviews, server_events,
        evidence_by_violation=evidence_by_violation,
    )
    encoded_name = quote(f"{report.report_no}.docx")
    return StreamingResponse(
        content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": (
                'attachment; filename="privacy-compliance-report.docx"; '
                f"filename*=UTF-8''{encoded_name}"
            )
        },
    )


@router.get("/{task_id}/evidence/{evidence_id}")
def download_evidence(task_id: int, evidence_id: int):
    path = report_service.get_evidence_file(task_id, evidence_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="证据文件不存在")
    return FileResponse(path)
