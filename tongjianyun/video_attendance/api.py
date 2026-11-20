"""Authenticated, device-scoped uploads. Video paths never come from requests."""
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import frappe
from frappe.utils import now_datetime, get_datetime, getdate

from .domain import CHUNK_BYTES, batch_id, validate_manifest
from .setup import BATCH, DEVICE, EVENT, PROFILE


def require_manager():
    if frappe.session.user == "Guest" or not (frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()):
        raise frappe.PermissionError("仅系统管理员可管理视频及人脸资料")


def device_for_upload(camera_id):
    if frappe.session.user == "Guest":
        raise frappe.AuthenticationError("Device authentication required")
    doc = frappe.get_doc(DEVICE, camera_id)
    if not doc.enabled or not doc.consent_scope_confirmed or doc.upload_user != frappe.session.user:
        raise frappe.PermissionError("Device is disabled or not assigned to this uploader")
    return doc


def storage():
    root = Path(frappe.get_site_path("private", "video_attendance")).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def video_path(name, partial=False):
    if not re.fullmatch(r"TVB-[0-9a-f]{40}", str(name)):
        raise ValueError("invalid_batch_id")
    return storage() / (name + (".part" if partial else ".mp4"))


def local_time(iso):
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(iso).astimezone(ZoneInfo(frappe.utils.get_system_timezone())).replace(tzinfo=None)


@frappe.whitelist(methods=["POST"])
def heartbeat(camera_id, health="ok", pending=0, disk_free_mb=0):
    device = device_for_upload(camera_id)
    if health not in ("ok", "recording", "camera_offline", "disk_full", "clock_error", "upload_error", "outside_schedule"):
        health = "upload_error"
    device.db_set({"last_seen": now_datetime(), "health": health,
                   "pending": max(0, min(int(pending), 100000)), "disk_free_mb": max(0, min(int(disk_free_mb), 2000000000))})
    return {"server_time": datetime.now(timezone.utc).isoformat(), "mode": "review-only"}


@frappe.whitelist(methods=["POST"])
def begin_upload(manifest):
    value = frappe.parse_json(manifest)
    device_for_upload(value.get("camera_id") if isinstance(value, dict) else "")
    # An already acknowledged old clip may query its receipt after a long outage.
    candidate = batch_id(value) if isinstance(value, dict) and all(value.get(k) for k in ("camera_id", "clip_id")) else ""
    existing = frappe.db.exists(BATCH, candidate) if candidate else None
    if existing:
        doc = frappe.get_doc(BATCH, existing)
        stored = json.loads(doc.manifest)
        if any(value.get(k) != stored[k] for k in stored):
            raise frappe.ValidationError("clip_id_conflict")
        if doc.status != "Uploading":
            return {"batch": doc.name, "offset": doc.size, "sealed": True, "sha256": doc.sha256}
    try:
        value = validate_manifest(value)
    except (ValueError, TypeError):
        raise frappe.ValidationError("视频元信息或采集时间不可验证") from None
    name = batch_id(value)
    with frappe.cache.lock("video-upload:" + name, timeout=90):
        if not frappe.db.exists(BATCH, name):
            count = frappe.db.count(BATCH, {"camera": value["camera_id"], "status": "Uploading"})
            if count >= 250:
                raise frappe.ValidationError("too_many_incomplete_uploads")
            # Bound total retained storage; never silently overwrite old evidence.
            if sum(p.stat().st_size for p in storage().iterdir() if p.is_file()) + value["size"] > 32 * 1024**3:
                raise frappe.ValidationError("server_video_quota_reached")
            doc = frappe.get_doc({"doctype": BATCH, "camera": value["camera_id"], "clip_id": value["clip_id"],
                "manifest": json.dumps(value, sort_keys=True), "sha256": value["sha256"], "size": value["size"],
                "started_at": local_time(value["started_at"]), "ended_at": local_time(value["ended_at"]),
                "received": 0, "status": "Uploading", "detail": "等待上传完成"})
            doc.insert(ignore_permissions=True, set_name=name)
        doc = frappe.get_doc(BATCH, name)
        if json.loads(doc.manifest) != value:
            raise frappe.ValidationError("clip_id_conflict")
        path = video_path(name, partial=True)
        return {"batch": name, "offset": path.stat().st_size if path.exists() else 0,
                "sealed": doc.status != "Uploading", "sha256": doc.sha256}


@frappe.whitelist(methods=["POST"])
def upload_chunk(batch, offset, data):
    doc = frappe.get_doc(BATCH, batch)
    device_for_upload(doc.camera)
    if not isinstance(data, str) or len(data) > (CHUNK_BYTES * 4 // 3 + 8):
        raise frappe.ValidationError("chunk_too_large")
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        raise frappe.ValidationError("invalid_chunk") from None
    if not 0 < len(raw) <= CHUNK_BYTES:
        raise frappe.ValidationError("invalid_chunk_size")
    offset = int(offset)
    with frappe.cache.lock("video-upload:" + batch, timeout=90):
        doc.reload()
        if doc.status != "Uploading":
            raise frappe.ValidationError("upload_already_sealed")
        path = video_path(batch, partial=True)
        size = path.stat().st_size if path.exists() else 0
        if offset != size:
            return {"offset": size, "retry": True}
        if offset + len(raw) > doc.size:
            raise frappe.ValidationError("size_exceeded")
        with path.open("ab") as stream:
            path.chmod(0o600)
            stream.write(raw)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        doc.db_set("received", offset + len(raw))
        return {"offset": offset + len(raw)}


@frappe.whitelist(methods=["POST"])
def seal_upload(batch):
    doc = frappe.get_doc(BATCH, batch)
    device_for_upload(doc.camera)
    with frappe.cache.lock("video-upload:" + batch, timeout=120):
        doc.reload()
        if doc.status != "Uploading":
            return {"batch": batch, "sealed": True, "sha256": doc.sha256}
        path = video_path(batch, partial=True)
        # Recover a crash between atomic rename and transaction commit.
        if not path.exists() and video_path(batch).exists():
            path = video_path(batch)
        if not path.exists() or path.stat().st_size != doc.size:
            raise frappe.ValidationError("upload_incomplete")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != doc.sha256:
            raise frappe.ValidationError("checksum_mismatch")
        if path.suffix == ".part":
            path.replace(video_path(batch))
        doc.db_set({"received": doc.size, "status": "Queued", "detail": "校验完成，等待分析"})
        frappe.enqueue("tongjianyun.video_attendance.jobs.process_batch", queue="long", timeout=600,
                       batch=batch, enqueue_after_commit=True)
        return {"batch": batch, "sealed": True, "sha256": digest}


@frappe.whitelist()
def overview(day=None):
    require_manager()
    day = getdate(day)
    start, end = str(day) + " 00:00:00", str(day) + " 23:59:59.999999"
    batches = frappe.get_all(BATCH, filters={"started_at": ["between", [start, end]]},
        fields=["name", "camera", "started_at", "status", "detail", "size", "received", "video_deleted"],
        order_by="started_at desc", limit_page_length=100)
    events = frappe.get_all(EVENT, filters={"occurred_at": ["between", [start, end]]},
        fields=["name", "batch", "employee", "occurred_at", "log_type", "score", "status", "checkin"],
        order_by="occurred_at desc", limit_page_length=200)
    devices = frappe.get_all(DEVICE, fields=["name", "title", "enabled", "direction", "last_seen", "health", "pending", "disk_free_mb"])
    for d in devices:
        d["online"] = bool(d.last_seen and (now_datetime() - get_datetime(d.last_seen)).total_seconds() < 180)
    profiles = frappe.get_all(PROFILE, fields=["name", "employee", "active", "consent", "model_version"])
    return {"mode": "review-only", "day": str(day), "devices": devices, "batches": batches, "events": events,
            "profiles": profiles, "batch_total": frappe.db.count(BATCH, {"started_at": ["between", [start, end]]}),
            "event_total": frappe.db.count(EVENT, {"occurred_at": ["between", [start, end]]})}


@frappe.whitelist(methods=["POST"])
def retry_batch(batch):
    require_manager()
    doc = frappe.get_doc(BATCH, batch)
    if doc.status not in ("Failed", "Needs Setup") or doc.video_deleted:
        raise frappe.ValidationError("该任务不可重试")
    doc.db_set({"status": "Queued", "detail": "管理员请求重新分析", "attempts": 0})
    frappe.enqueue("tongjianyun.video_attendance.jobs.process_batch", queue="long", timeout=600,
                   batch=batch, enqueue_after_commit=True)
    return {"status": "Queued"}


@frappe.whitelist(methods=["POST"])
def review_event(event, action, reason, confirmed=False):
    require_manager()
    if action not in ("approve", "reject") or not isinstance(reason, str) or not reason.strip():
        raise frappe.ValidationError("请填写核实说明")
    if action == "approve" and str(confirmed).lower() not in ("1", "true"):
        raise frappe.ValidationError("请核实本人、日期及进出方向")
    with frappe.cache.lock("video-review:" + event, timeout=60):
        doc = frappe.get_doc(EVENT, event)
        if doc.status != "Review":
            return {"status": doc.status, "checkin": doc.checkin}
        if action == "reject":
            doc.db_set({"status": "Rejected", "reviewer": frappe.session.user, "reason": reason[:1000]})
            return {"status": "Rejected"}
        profile = frappe.db.get_value(PROFILE, {"employee": doc.employee}, ["active", "consent"], as_dict=True)
        if not profile or not profile.active or not profile.consent:
            raise frappe.ValidationError("教师授权已停用")
        if not frappe.has_permission("Employee Checkin", "create") or not frappe.has_permission("Employee", "read", doc=doc.employee):
            raise frappe.PermissionError("Employee Checkin create permission required")
        # Serialize cross-clip/cross-camera approvals and preserve HRMS validation.
        employee = frappe.db.get_value("Employee", doc.employee, ["name", "status"], as_dict=True, for_update=True)
        if not employee or employee.status != "Active":
            raise frappe.ValidationError("员工已停用")
        if frappe.db.exists("Attendance", {"employee": doc.employee, "attendance_date": getdate(doc.occurred_at), "docstatus": 1}):
            raise frappe.ValidationError("该日考勤已确认，请走正式更正流程")
        from datetime import timedelta
        moment = get_datetime(doc.occurred_at)
        existing = frappe.db.get_value("Employee Checkin", {"employee": doc.employee, "log_type": doc.log_type,
            "time": ["between", [moment - timedelta(seconds=60), moment + timedelta(seconds=60)]]}, "name")
        if not existing:
            checkin = frappe.get_doc({"doctype": "Employee Checkin", "employee": doc.employee,
                "time": moment, "log_type": doc.log_type, "device_id": "video-review:" + doc.batch,
                "skip_auto_attendance": 1})
            checkin.insert(set_name="TJV-" + hashlib.sha256(doc.name.encode()).hexdigest()[:40])
            existing = checkin.name
        doc.db_set({"status": "Approved", "checkin": existing, "reviewer": frappe.session.user, "reason": reason[:1000]})
        return {"status": "Approved", "checkin": existing, "skip_auto_attendance": 1}


@frappe.whitelist(methods=["POST"])
def enroll(employee, image_base64, consent_note, confirmed=False):
    require_manager()
    if not frappe.has_permission("Employee", "read", doc=employee):
        raise frappe.PermissionError("Employee read permission required")
    if str(confirmed).lower() not in ("1", "true") or not str(consent_note).strip():
        raise frappe.ValidationError("请先取得授权并填写授权记录")
    if frappe.db.get_value("Employee", employee, "status") != "Active":
        raise frappe.ValidationError("请选择在职员工")
    if not isinstance(image_base64, str) or len(image_base64) > 6 * 1024**2:
        raise frappe.ValidationError("照片过大")
    try:
        raw = base64.b64decode(image_base64, validate=True)
    except Exception:
        raise frappe.ValidationError("照片编码不可识别") from None
    if len(raw) > 4 * 1024**2:
        raise frappe.ValidationError("照片须小于 4 MB")
    import tempfile
    from .jobs import run_engine
    from frappe.utils.password import encrypt
    with tempfile.TemporaryDirectory(prefix="enroll-", dir=storage()) as temp:
        path = Path(temp) / "enrollment.jpg"
        path.write_bytes(raw)
        path.chmod(0o600)
        try:
            result = run_engine({"mode": "enroll", "input": str(path)})
        except (RuntimeError, ValueError, TimeoutError):
            raise frappe.ValidationError("识别服务未就绪或照片处理失败，请检查环境后重试") from None
    if not result.get("feature"):
        raise frappe.ValidationError("照片需要包含一张清晰正脸，请重新采集")
    name = frappe.db.get_value(PROFILE, {"employee": employee}, "name")
    doc = frappe.get_doc(PROFILE, name) if name else frappe.new_doc(PROFILE)
    doc.update({"employee": employee, "consent": 1, "active": 1, "consent_note": str(consent_note)[:1000],
                "template_ciphertext": encrypt(json.dumps(result["feature"])), "model_version": result["model_version"]})
    doc.save(ignore_permissions=True)
    doc.add_comment("Comment", "管理员核验授权并更新识别模板；注册原图不保留。")
    return {"profile": doc.name, "employee": employee, "mode": "review-only"}


@frappe.whitelist(methods=["POST"])
def revoke_profile(profile):
    require_manager()
    doc = frappe.get_doc(PROFILE, profile)
    doc.db_set({"active": 0, "consent": 0, "template_ciphertext": ""})
    doc.add_comment("Comment", "停止识别并删除当前人脸模板；备份副本按备份保留策略到期清理。")
    return {"status": "revoked"}


@frappe.whitelist()
def download_video(batch):
    require_manager()
    doc = frappe.get_doc(BATCH, batch)
    path = video_path(batch)
    if doc.video_deleted or not path.exists() or doc.status == "Uploading":
        raise frappe.DoesNotExistError("视频已过期或尚未上传完成")
    frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": BATCH,
                    "reference_name": batch, "content": "管理员下载核实视频"}).insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.local.response.update({"type": "download", "filename": batch + ".mp4",
                                 "filecontent": path.read_bytes(), "content_type": "video/mp4"})


@frappe.whitelist()
def my_checkins(day=None):
    if frappe.session.user == "Guest":
        raise frappe.AuthenticationError("Login required")
    employees = frappe.get_all("Employee", filters={"user_id": frappe.session.user, "status": "Active"}, pluck="name")
    if not employees:
        return []
    day = str(getdate(day))
    return frappe.get_all("Employee Checkin", filters={"employee": ["in", employees],
        "time": ["between", [day + " 00:00:00", day + " 23:59:59"]]},
        fields=["name", "time", "log_type", "skip_auto_attendance"], order_by="time", limit_page_length=100)
