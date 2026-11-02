import os
import tempfile
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError

from agent.common.exceptions import ApkParseError, ApkValidationError
from agent.common.utils import decrypt_to_temp, encrypt_bytes, get_or_create_fernet_key, sha256_of_file
from agent.detection_engines.static_analyzer import analyze_apk
from backend.app.config import PROJECT_ROOT, config
from backend.app.db import SessionLocal
from backend.app.models import APKFile, DetectionTask, Evidence, Report, Violation
from backend.app.models.review import ReviewItem, ServerAuditEvent
from backend.app.services.artifact_cleanup import delete_stored_apk, delete_task_artifacts

MAX_APK_BYTES = 500 * 1024 * 1024  # 500MB（PRD 4.2.1.1）


def validate_apk_upload(tmp_path: Path, filename: str, max_bytes: int = MAX_APK_BYTES) -> None:
    if not filename.lower().endswith(".apk"):
        raise ApkValidationError("文件格式无效：仅支持 .apk 文件")
    size = tmp_path.stat().st_size
    if size > max_bytes:
        raise ApkValidationError(f"文件超过大小限制（{max_bytes // 1024 // 1024}MB）")
    if size < 1024:
        raise ApkValidationError("文件格式无效：文件过小")
    # APK 是 zip 容器，且必须含 AndroidManifest.xml 或 META-INF
    import zipfile
    try:
        with zipfile.ZipFile(tmp_path) as z:
            names = set(z.namelist())
            if "AndroidManifest.xml" not in names and not any(n.startswith("META-INF/") for n in names):
                raise ApkValidationError("文件格式无效：不是有效的 APK（zip 容器内无清单文件）")
            if z.testzip() is not None:
                raise ApkValidationError("文件格式无效：zip 容器损坏")
    except zipfile.BadZipFile as e:
        raise ApkValidationError("文件格式无效：不是有效的 APK") from e


def save_apk(file: UploadFile) -> APKFile:
    """上传流程：幂等查重 → 校验 → 落盘加密 → 真实解析 → 入库。校验失败也入库（invalid 状态，界面可见原因）。"""
    cfg = config
    apk_dir = PROJECT_ROOT / cfg["storage"]["apk_dir"]
    apk_dir.mkdir(parents=True, exist_ok=True)
    # 临时文件由 mkstemp 在 apk 目录内安全创建：随机文件名、无符号链接、
    # 与客户端文件名完全脱钩，杜绝路径逃逸与同名上传互踩
    fd, tmp_name = tempfile.mkstemp(dir=apk_dir, prefix=".tmp_", suffix=".apk")
    tmp_path = Path(tmp_name)
    with os.fdopen(fd, "wb") as f:
        f.write(file.file.read())
    try:
        sha256 = sha256_of_file(tmp_path)  # 唯一键：任何路径都用真实哈希
        # 幂等上传：同 sha256 已有成功/parsing 行，直接返回该行，不重复写盘
        with SessionLocal() as s:
            existing = s.query(APKFile).filter_by(sha256=sha256).first()
        if existing is not None and existing.parse_status in ("success", "parsing"):
            # 相同内容的 APK 默认不重复落盘，但历史记录可能是在静态画像
            # 字段/分析器升级前生成的。没有任何检测任务时，重新上传应当
            # 触发一次原文件的静态画像刷新；已有任务的样本保持不可变，
            # 避免修改报告所依赖的历史分析结果。
            if existing.parse_status == "success":
                existing = _refresh_existing_profile_if_unreferenced(existing.id)
            return existing
        validate_apk_upload(tmp_path, file.filename)
        key = get_or_create_fernet_key(cfg)
        enc_path = apk_dir / f"{sha256}.apk.enc"
        enc_path.write_bytes(encrypt_bytes(tmp_path.read_bytes(), key))
        row = APKFile(
            filename=file.filename, sha256=sha256, size_bytes=tmp_path.stat().st_size,
            parse_status="parsing", storage_path=str(enc_path.relative_to(PROJECT_ROOT)),
        )
        with SessionLocal() as s:
            s.add(row)
            try:
                s.commit()
            except IntegrityError:  # 并发上传同内容兜底：返回已存在行
                s.rollback()
                return s.query(APKFile).filter_by(sha256=sha256).one()
            s.refresh(row)
            parse_apk(row.id)
            s.refresh(row)  # parse_apk 在独立会话回写，刷新取回解析结果
            s.commit()
            return s.query(APKFile).filter_by(id=row.id).one()
    except ApkValidationError as e:
        with SessionLocal() as s:
            existing = s.query(APKFile).filter_by(sha256=sha256).first()
            if existing is not None:  # 幂等：同内容已有行（含 invalid）直接返回
                return existing
            row = APKFile(filename=file.filename, sha256=sha256, size_bytes=tmp_path.stat().st_size,
                          parse_status="invalid", parse_message=str(e),
                          storage_path=str(tmp_path.relative_to(PROJECT_ROOT)))
            s.add(row)
            try:
                s.commit()
            except IntegrityError:  # 并发上传同内容兜底
                s.rollback()
                return s.query(APKFile).filter_by(sha256=sha256).one()
            return s.query(APKFile).filter_by(id=row.id).one()
    finally:
        tmp_path.unlink(missing_ok=True)


def _refresh_existing_profile_if_unreferenced(apk_id: int) -> APKFile:
    """Refresh a deduplicated APK only when no task references it.

    Upload deduplication intentionally keeps one encrypted artifact per SHA-256.
    That must not imply stale static metadata: a repeated upload is an explicit
    request to parse the same sample again after the analyzer or schema changes.
    Once a task exists, the APK row is treated as historical evidence and is
    left untouched for report reproducibility.
    """
    with SessionLocal() as s:
        row = s.query(APKFile).filter_by(id=apk_id).first()
        if row is None:
            return row
        if s.query(DetectionTask.id).filter_by(apk_id=apk_id).first() is not None:
            return row
        # Another concurrent upload may already be refreshing this row.
        if row.parse_status != "success":
            return row
        row.parse_status = "parsing"
        row.parse_message = "重复上传同一 APK，正在刷新静态画像"
        s.commit()

    try:
        parse_apk(apk_id)
    except Exception as exc:
        # Do not leave an indefinitely parsing row if decryption or a future
        # analyzer failure happens outside parse_apk's guarded section.
        with SessionLocal() as s:
            row = s.query(APKFile).filter_by(id=apk_id).first()
            if row is not None:
                row.parse_status = "failed"
                row.parse_message = f"静态画像刷新失败：{type(exc).__name__}: {exc}"
                s.commit()

    with SessionLocal() as s:
        return s.query(APKFile).filter_by(id=apk_id).one()


def parse_apk(apk_id: int) -> APKFile:
    """解析 APK 并回写解析结果（真实 Androguard；加密存储先解密到临时文件）。"""
    with SessionLocal() as s:
        row = s.query(APKFile).filter_by(id=apk_id).one()
        if row.parse_status in ("invalid",):
            return row
        tmp_dir = PROJECT_ROOT / config["storage"]["apk_dir"] / "tmp"
        tmp = decrypt_to_temp(PROJECT_ROOT / row.storage_path, get_or_create_fernet_key(), tmp_dir)
        try:
            result = analyze_apk(tmp)
        except ApkParseError as e:
            row.parse_status = "failed"
            row.parse_message = str(e)
            s.commit()
            return row
        except Exception as e:  # 兜底：未知异常同样落 failed，避免行滞留 parsing
            row.parse_status = "failed"
            row.parse_message = f"解析失败（未知错误）：{type(e).__name__}: {e}"
            s.commit()
            return row
        finally:
            tmp.unlink(missing_ok=True)
        row.parse_status = "success"
        row.parse_message = None
        row.app_name = result["app_name"]
        row.package_name = result["package_name"]
        row.version_name = result["version_name"]
        row.md5 = result["md5"]
        row.permissions = result["permissions"]
        row.policy_raw = result["policy_raw"]
        row.sdk_list = result["sdk_list"]
        row.static_summary = result.get("static_summary")
        s.commit()
        return row


def list_apks() -> list[APKFile]:
    with SessionLocal() as s:
        return s.query(APKFile).order_by(APKFile.uploaded_at.desc()).all()


def delete_apk(apk_id: int) -> None:
    """删除 APK 及其关联任务/违规/证据/报告（PRD 4.2.3.2 确认后执行）。"""
    with SessionLocal() as s:
        tasks = s.query(DetectionTask).filter_by(apk_id=apk_id).all()
        active_tasks = [task.id for task in tasks if task.status not in {"completed", "failed", "canceled"}]
        if active_tasks:
            raise ApkValidationError("该 APK 仍有运行中的检测任务，请先取消任务后再删除")
        artifacts: list[tuple[int, list[str | None]]] = []
        for t in tasks:
            report_paths = [report.pdf_path for report in s.query(Report).filter_by(task_id=t.id).all()]
            artifacts.append((t.id, report_paths))
            violation_ids = s.query(Violation.id).filter_by(task_id=t.id).subquery()
            s.query(Evidence).filter(Evidence.violation_id.in_(violation_ids)).delete(synchronize_session=False)
            s.query(Violation).filter_by(task_id=t.id).delete(synchronize_session=False)
            s.query(Report).filter_by(task_id=t.id).delete(synchronize_session=False)
            s.query(ReviewItem).filter_by(task_id=t.id).delete(synchronize_session=False)
            s.query(ServerAuditEvent).filter_by(task_id=t.id).delete(synchronize_session=False)
            s.flush()
            for v in s.query(Violation).filter_by(task_id=t.id):
                s.delete(v)  # 证据随 violation 级联删除
            s.query(Report).filter_by(task_id=t.id).delete()
            s.delete(t)
        apk = s.query(APKFile).filter_by(id=apk_id).one()
        storage_path = apk.storage_path
        s.delete(apk)
        s.commit()

    for task_id, report_paths in artifacts:
        delete_task_artifacts(task_id, report_paths)
    delete_stored_apk(storage_path)
