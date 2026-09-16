"""Idempotent, additive installation. Never enable cameras or payroll automation."""
import frappe

DEVICE = "Tongjianyun Video Device"
BATCH = "Tongjianyun Video Batch"
EVENT = "Tongjianyun Video Event"
PROFILE = "Tongjianyun Teacher Face"
PAGE = "teacher-video-attendance"


def field(name, kind="Data", **kw):
    return {"fieldname": name, "label": kw.pop("label", name), "fieldtype": kind, **kw}


def definitions():
    return {
        DEVICE: [field("camera_id", reqd=1, unique=1, label="设备编号"), field("title", label="点位名称"),
                 field("enabled", "Check", label="允许上传"), field("upload_user", "Link", options="User", reqd=1, label="专用上传账号"),
                 field("direction", "Select", options="IN\nOUT", reqd=1, label="专用通道方向"),
                 field("consent_scope_confirmed", "Check", label="点位及传输授权已核验"),
                 field("last_seen", "Datetime", read_only=1, label="最后心跳"),
                 field("health", "Data", read_only=1, label="采集状态"), field("pending", "Int", read_only=1, label="待传片段"),
                 field("disk_free_mb", "Int", read_only=1, label="剩余空间 MB")],
        BATCH: [field("camera", "Link", options=DEVICE, reqd=1), field("clip_id", reqd=1),
                field("manifest", "Long Text", read_only=1), field("sha256", read_only=1),
                field("size", "Int", read_only=1), field("received", "Int", read_only=1),
                field("started_at", "Datetime", read_only=1), field("ended_at", "Datetime", read_only=1),
                field("status", "Select", options="Uploading\nQueued\nProcessing\nNeeds Setup\nReview\nNo Match\nFailed\nExpired", read_only=1),
                field("detail", "Small Text", read_only=1), field("attempts", "Int", read_only=1),
                field("analysis_version", read_only=1), field("video_deleted", "Check", read_only=1)],
        EVENT: [field("batch", "Link", options=BATCH, reqd=1), field("employee", "Link", options="Employee", reqd=1),
                field("occurred_at", "Datetime", read_only=1), field("log_type", "Select", options="IN\nOUT", read_only=1),
                field("score", "Float", read_only=1), field("frames", "Int", read_only=1),
                field("status", "Select", options="Review\nApproved\nRejected", read_only=1),
                field("checkin", "Link", options="Employee Checkin", read_only=1),
                field("reviewer", "Link", options="User", read_only=1), field("reason", "Small Text", read_only=1)],
        PROFILE: [field("employee", "Link", options="Employee", reqd=1, unique=1, label="教师员工"),
                  field("consent", "Check", label="已取得识别及远端处理单独同意"),
                  field("consent_note", "Small Text", reqd=1, label="授权记录编号/日期及说明"),
                  field("active", "Check", label="启用识别"),
                  field("template_ciphertext", "Long Text", hidden=1, read_only=1),
                  field("model_version", read_only=1, label="模板模型版本")],
    }


def install():
    if frappe.session.user != "Administrator":
        raise frappe.PermissionError("Install requires Administrator")
    if "hrms" not in frappe.get_installed_apps():
        raise RuntimeError("HRMS must be installed first")
    for name, fields in definitions().items():
        if frappe.db.exists("DocType", name):
            continue
        configurable = name == DEVICE
        doc = frappe.get_doc({"doctype": "DocType", "name": name, "module": "Tongjianyun", "custom": 1,
            "autoname": "field:camera_id" if configurable else "hash", "track_changes": int(name != PROFILE),
            "fields": fields, "permissions": [{"role": "System Manager", "read": 1,
                "create": int(configurable), "write": int(configurable), "delete": 0,
                "export": 0, "share": 0, "print": 0}]})
        doc.insert(ignore_permissions=True)
    page_path = frappe.get_app_path("tongjianyun", "tongjianyun", "page", PAGE.replace("-", "_"), PAGE.replace("-", "_") + ".json")
    from frappe.modules.import_file import import_file_by_path
    import_file_by_path(page_path, force=True)
    method = "tongjianyun.video_attendance.jobs.tick"
    if not frappe.db.exists("Scheduled Job Type", {"method": method}):
        frappe.get_doc({"doctype": "Scheduled Job Type", "method": method, "frequency": "Cron", "cron_format": "*/2 * * * *"}).insert(ignore_permissions=True)
    frappe.clear_cache()
    return {"page": "/desk/" + PAGE, "mode": "review-only", "installed": list(definitions())}
