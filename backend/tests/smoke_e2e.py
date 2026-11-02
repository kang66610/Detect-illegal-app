"""端到端冒烟：不走网络，直接跑服务层 + 管线，打印测试摘要。

用法：.venv/Scripts/python backend/tests/smoke_e2e.py
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 仓库根，保证 agent/backend 可导入

from agent.agent_core.workflow import run_task
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask, Evidence, Report, Violation


def smoke() -> dict:
    init_db()
    with SessionLocal() as s:
        apk = APKFile(
            filename="demo-tool.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=4096, parse_status="success",
            storage_path="data/apks/x.enc", app_name="演示工具App", package_name="com.demo.tool",
            version_name="1.0.0",
            permissions=["android.permission.READ_CONTACTS", "android.permission.ACCESS_FINE_LOCATION"],
            sdk_list=[{"name": "友盟", "collected": ["设备标识"]}],
            policy_raw=None,  # 无隐私政策 → 触发第 1 类违规
        )
        s.add(apk)
        s.commit()
        task = DetectionTask(apk_id=apk.id, industry="工具", mode="deep")
        s.add(task)
        s.commit()
        task_id = task.id

    run_task(task_id)

    with SessionLocal() as s:
        t = s.query(DetectionTask).filter_by(id=task_id).one()
        violations = s.query(Violation).filter_by(task_id=task_id).all()
        report = s.query(Report).filter_by(task_id=task_id).one()
        evidence_count = sum(s.query(Evidence).filter_by(violation_id=v.id).count() for v in violations)
        result = {
            "task_status": t.status,
            "pages_covered": t.pages_covered,
            "scenarios_triggered": t.scenarios_triggered,
            "violation_count": len(violations),
            "evidence_count": evidence_count,
            "score": report.score,
            "report_no": report.report_no,
            "pdf_exists": bool(report.pdf_path and (__import__('pathlib').Path(__file__).resolve().parents[2] / report.pdf_path).exists()),
        }
    return result


if __name__ == "__main__":
    r = smoke()
    print("=" * 50)
    print("端到端冒烟测试结果")
    print("=" * 50)
    for k, v in r.items():
        print(f"  {k}: {v}")
    ok = r["task_status"] == "completed" and r["violation_count"] >= 3 and r["pdf_exists"]
    print(f"结论: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)
