"""Bounded background jobs. Preview candidates are never automatic attendance."""
import hashlib
import json
import subprocess
from datetime import timedelta
from pathlib import Path

import frappe
from frappe.utils import now_datetime, get_datetime

from .setup import BATCH, DEVICE, EVENT, PROFILE


def run_engine(payload):
    config = frappe.conf.get("tongjianyun_video_attendance") or {}
    executable, models = config.get("python"), config.get("models_dir")
    if not executable or not models or not Path(executable).is_file():
        raise RuntimeError("vision_engine_not_configured")
    payload["models_dir"] = models
    payload["threshold"] = float(config.get("preview_threshold", 0.5))
    payload["margin"] = float(config.get("preview_margin", 0.12))
    command = [executable, frappe.get_app_path("tongjianyun", "video_attendance", "recognition.py")]
    result = subprocess.run(command, input=json.dumps(payload), capture_output=True, text=True, timeout=420,
                            env={"PATH": "/usr/bin:/bin", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"})
    if result.returncode or len(result.stdout) > 2 * 1024**2:
        # Never include image paths, template data or third-party decoder output in UI.
        raise RuntimeError("vision_analysis_failed")
    return json.loads(result.stdout)


def process_batch(batch):
    from .api import video_path
    from frappe.utils.password import decrypt
    with frappe.cache.lock("video-analysis:" + batch, timeout=580, blocking_timeout=1):
        doc = frappe.get_doc(BATCH, batch)
        if doc.status != "Queued":
            return
        doc.db_set({"status": "Processing", "detail": "正在分析视频（仅生成待核实候选）", "attempts": (doc.attempts or 0) + 1})
        frappe.db.commit()
        try:
            device = frappe.get_doc(DEVICE, doc.camera)
            if not device.enabled or not device.consent_scope_confirmed:
                raise RuntimeError("device_authorization_disabled")
            config = frappe.conf.get("tongjianyun_video_attendance") or {}
            if not config.get("processing_enabled"):
                doc.db_set({"status": "Needs Setup", "detail": "尚未配置识别服务；视频已安全接收"})
                frappe.db.commit()
                return
            profiles = frappe.get_all(PROFILE, filters={"active": 1, "consent": 1},
                fields=["employee", "template_ciphertext", "model_version"])
            gallery = [{"employee": p.employee, "feature": json.loads(decrypt(p.template_ciphertext)), "model_version": p.model_version}
                       for p in profiles if p.template_ciphertext and frappe.db.get_value("Employee", p.employee, "status") == "Active"]
            if not gallery:
                doc.db_set({"status": "Needs Setup", "detail": "尚无已授权的教师识别档案，请先注册教师"})
                frappe.db.commit()
                return
            result = run_engine({"mode": "video", "input": str(video_path(batch)), "gallery": gallery})
            expected = (get_datetime(doc.ended_at) - get_datetime(doc.started_at)).total_seconds()
            if abs(float(result["duration"]) - expected) > max(3, expected * 0.08):
                raise RuntimeError("capture_duration_mismatch")
            count = 0
            for idx, candidate in enumerate(result.get("candidates", [])):
                if not 0 <= candidate["offset"] < expected:
                    continue
                profile = frappe.db.get_value(PROFILE, {"employee": candidate["employee"], "active": 1, "consent": 1}, "name")
                if not profile or frappe.db.get_value("Employee", candidate["employee"], "status") != "Active":
                    continue
                name = "TVE-" + hashlib.sha256((batch + ":" + str(idx)).encode()).hexdigest()[:40]
                if not frappe.db.exists(EVENT, name):
                    frappe.get_doc({"doctype": EVENT, "batch": batch, "employee": candidate["employee"],
                        "occurred_at": get_datetime(doc.started_at) + timedelta(seconds=candidate["offset"]),
                        "log_type": device.direction, "score": candidate["score"], "frames": candidate["frames"],
                        "status": "Review", "reason": "视频候选：未验证活体及进出方向，须人工核实"}).insert(ignore_permissions=True, set_name=name)
                count += 1
            doc.db_set({"status": "Review" if count else "No Match", "analysis_version": result["model_version"],
                        "detail": f"生成 {count} 条待核实候选；未写正式考勤" if count else "未找到可靠教师匹配，不代表无人到岗或缺勤"})
            frappe.db.commit()
        except Exception as exc:
            frappe.db.rollback()
            codes = {"vision_engine_not_configured": "识别运行环境未配置", "device_authorization_disabled": "设备或点位授权已停用",
                     "capture_duration_mismatch": "视频时长与采集时间不一致，请核查电脑时钟及录像完整性"}
            message = codes.get(str(exc), "视频分析失败，请检查模型、视频格式或处理超时；可重试")
            frappe.db.set_value(BATCH, batch, {"status": "Failed", "detail": message})
            frappe.db.commit()


def tick():
    """Recover interrupted workers; retention is bounded and explicit."""
    if not frappe.db.exists("DocType", BATCH):
        return
    stale = now_datetime() - timedelta(minutes=12)
    for row in frappe.get_all(BATCH, filters={"status": "Processing", "modified": ["<", stale]}, fields=["name", "attempts"]):
        frappe.db.set_value(BATCH, row.name, {"status": "Queued" if row.attempts < 3 else "Failed", "detail": "处理任务中断，已恢复队列"})
    for name in frappe.get_all(BATCH, filters={"status": "Queued"}, pluck="name", order_by="started_at", limit_page_length=4):
        frappe.enqueue("tongjianyun.video_attendance.jobs.process_batch", batch=name, queue="long", timeout=600, enqueue_after_commit=True)
    # Seven days is an initial operational maximum, not a legal minimum.
    # Retention follows capture time, so late uploads cannot extend it indefinitely.
    from .api import video_path
    config = frappe.conf.get("tongjianyun_video_attendance") or {}
    days = max(1, min(int(config.get("retention_days", 3)), 7))
    cutoff = now_datetime() - timedelta(days=days)
    for row in frappe.get_all(BATCH, filters={"video_deleted": 0, "ended_at": ["<", cutoff], "status": ["!=", "Processing"]},
                              fields=["name", "status"], limit_page_length=100):
        with frappe.cache.lock("video-analysis:" + row.name, timeout=30, blocking_timeout=1), frappe.cache.lock("video-upload:" + row.name, timeout=30):
            if frappe.db.get_value(BATCH, row.name, "status") == "Processing":
                continue
            for partial in (False, True):
                video_path(row.name, partial).unlink(missing_ok=True)
            values = {"video_deleted": 1, "detail": "视频已按保留期限清理，未核实记录不能据此自动打卡"}
            if row.status in ("Uploading", "Queued", "Needs Setup", "Failed"):
                values["status"] = "Expired"
            frappe.db.set_value(BATCH, row.name, values)
