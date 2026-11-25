"""DingTalk attendance integration for child.myyr.top.

The service pulls DingTalk's attendance detail API into HRMS Employee Checkin.
Credentials may be read from site_config.json (dingtalk_app_key and
dingtalk_app_secret) or the matching environment variables. When app
credentials are absent, the official dws CLI authorization for the service user
is used. No credentials are stored in this module.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import get_datetime, get_time, getdate, now_datetime


_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
_DEFAULT_RECORD_URL = "https://api.dingtalk.com/v1.0/attendance/listRecord"
_ALLOWED_ROLES = {
    "System Manager",
    "I-ONE Manager",
    "I-ONE AI Operator",
    "HR Manager",
}


def _conf(name, default=None):
    value = frappe.conf.get(name)
    if value is None or value == "":
        value = os.environ.get(name.upper())
    return value if value not in (None, "") else default


def _require_manager():
    if frappe.session.user == "Guest":
        frappe.throw(_("请先登录"), frappe.AuthenticationError)
    if not _ALLOWED_ROLES.intersection(set(frappe.get_roles(frappe.session.user))):
        frappe.throw(_("您没有教师考勤同步权限。"), frappe.PermissionError)
    return frappe.session.user


def _app_configured():
    return bool(str(_conf("dingtalk_app_key", "")).strip() and str(_conf("dingtalk_app_secret", "")).strip())


def _dingtalk_cli_path():
    configured = str(_conf("dingtalk_cli_path", "")).strip()
    if configured:
        return configured
    for candidate in (
        os.environ.get("DINGTALK_CLI_PATH"),
        "/home/zyd/.local/bin/dws",
        "/root/.local/bin/dws",
    ):
        if candidate and shutil.which(candidate):
            return candidate
    return None


def _dws_configured():
    return bool(_dingtalk_cli_path())


def _configured():
    return _app_configured() or _dws_configured()


def _notification_recipients():
    """Return the Frappe users that should receive attendance summaries."""
    raw = _conf("dingtalk_attendance_notify_users", [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return []
    recipients = []
    for value in raw:
        user = str(value or "").strip()
        if user and frappe.db.exists("User", user):
            recipients.append(user)
    return list(dict.fromkeys(recipients))


def _notify_sync(result):
    """Create one idempotent server notification for each configured mobile user."""
    result.setdefault("notification_recipients", [])
    result.setdefault("notifications_created", 0)
    result.setdefault("notification_errors", [])
    if result.get("dry_run") or not result.get("mapped") or result.get("errors"):
        return
    recipients = _notification_recipients()
    result["notification_recipients"] = recipients
    if not recipients:
        return
    day = str(result.get("date"))
    subject = f"钉钉教师考勤已同步：{day}"
    document_name = f"dingtalk-attendance:{day}"
    body = (
        f"{day} 已从钉钉同步 {result.get('mapped', 0)} 条教师考勤记录，"
        f"新增 {result.get('created', 0)} 条，已存在 {result.get('skipped', 0)} 条。"
    )
    # The mobile client only needs the first morning IN for each teacher/day.
    # Keep the complete filtered set here so the phone table is not truncated
    # to the first twenty raw IN/OUT events.
    first_morning_in = {}
    for item in result.get("items", []):
        if str(item.get("log_type") or "").upper() != "IN":
            continue
        raw_time = str(item.get("time") or "").replace("T", " ")
        try:
            timestamp = datetime.fromisoformat(raw_time)
        except ValueError:
            continue
        if timestamp.hour >= 12:
            continue
        label = item.get("employee_name") or item.get("employee") or item.get("userid")
        label = str(label or "").strip()
        if not label:
            continue
        key = (timestamp.date().isoformat(), label)
        previous = first_morning_in.get(key)
        if previous is None or timestamp < previous[0]:
            first_morning_in[key] = (timestamp, label)

    details = [
        f"{timestamp.date().isoformat()} {label}：{timestamp.strftime('%H:%M:%S')}（IN）"
        for timestamp, label in sorted(
            first_morning_in.values(),
            key=lambda value: (value[0], value[1]),
        )
    ]
    if details:
        body += "\n早上班打卡（每位教师每天最早一条）：\n" + "\n".join(details)
    else:
        body += "\n早上班打卡：暂无记录。"
    for user in recipients:
        if frappe.db.exists(
            "Notification Log",
            {
                "for_user": user,
                "document_name": document_name,
                "subject": subject,
            },
        ):
            continue
        try:
            frappe.get_doc(
                {
                    "doctype": "Notification Log",
                    "type": "Alert",
                    "title": subject,
                    "description": body,
                    "for_user": user,
                    "subject": subject,
                    "email_content": body,
                    "document_type": "Employee Checkin",
                    "document_name": document_name,
                    "link": "/app/employee-checkin",
                    "read": 0,
                }
            ).insert(ignore_permissions=True)
            result["notifications_created"] += 1
        except Exception:
            result["notification_errors"].append(
                {"user": user, "error": frappe.get_traceback()[-500:]}
            )


def _http_json(url, payload=None, headers=None, timeout=30):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        frappe.throw(_("钉钉接口请求失败：{0}").format(raw[:500]), frappe.ValidationError)
    except urllib.error.URLError as exc:
        frappe.throw(_("钉钉接口网络错误：{0}").format(exc.reason), frappe.ValidationError)
    try:
        result = json.loads(raw or "{}")
    except ValueError:
        frappe.throw(_("钉钉接口返回了无法解析的内容。"), frappe.ValidationError)
    if isinstance(result, dict) and result.get("errcode") not in (None, 0, "0"):
        frappe.throw(
            _("钉钉接口返回错误 {0}：{1}").format(result.get("errcode"), result.get("errmsg") or ""),
            frappe.ValidationError,
        )
    return result


def _access_token():
    if not _configured():
        frappe.throw(
            _("尚未配置钉钉应用，请设置 dingtalk_app_key 和 dingtalk_app_secret。"),
            frappe.ValidationError,
        )
    result = _http_json(
        _TOKEN_URL,
        {
            "appKey": str(_conf("dingtalk_app_key")).strip(),
            "appSecret": str(_conf("dingtalk_app_secret")).strip(),
        },
    )
    token = result.get("accessToken") or result.get("access_token")
    if not token:
        frappe.throw(_("钉钉未返回 accessToken。"), frappe.ValidationError)
    return str(token)


def _employee_mapping_field():
    if frappe.db.exists("DocType", "Employee") and frappe.get_meta("Employee").get_field("dingtalk_userid"):
        return "dingtalk_userid"
    return "user_id"


def _configured_employee_map():
    raw = _conf("dingtalk_employee_map", {})
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    if not isinstance(raw, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in raw.items() if str(k).strip() and str(v).strip()}


def _employee_mappings(employee=None):
    if not frappe.db.exists("DocType", "Employee"):
        return [], "Employee DocType 不存在"
    field = _employee_mapping_field()
    filters = {"status": "Active"}
    if employee:
        filters["name"] = employee
    fields = ["name", "employee_name", field]
    rows = frappe.get_all("Employee", filters=filters, fields=fields, limit_page_length=500)
    mapping = []
    seen = set()
    for row in rows:
        user_id = str(row.get(field) or "").strip()
        if user_id:
            mapping.append({"employee": row["name"], "employee_name": row.get("employee_name"), "userid": user_id})
            seen.add(row["name"])
    for userid, employee_name in _configured_employee_map().items():
        target = employee_name
        if target in seen:
            continue
        if frappe.db.exists("Employee", target):
            row = frappe.db.get_value("Employee", target, ["name", "employee_name"], as_dict=True)
            if not employee or row["name"] == employee:
                mapping.append({"employee": row["name"], "employee_name": row.get("employee_name"), "userid": userid})
    return mapping, field


def _as_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        number = int(value)
        if number > 10**11:
            number //= 1000
        return datetime.fromtimestamp(number)
    text = str(value).strip().replace("T", " ")
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        text = text.split(".", 1)[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _records_from_response(result):
    candidates = []
    if isinstance(result, dict):
        for key in ("recordresult", "recordResult", "records", "data", "result"):
            value = result.get(key)
            if isinstance(value, list):
                candidates.extend(value)
            elif isinstance(value, dict):
                candidates.extend(value.get("recordresult") or value.get("records") or value.get("list") or [])
    return [item for item in candidates if isinstance(item, dict)]


def _fetch_records(token, user_ids, start, end):
    endpoint = str(_conf("dingtalk_attendance_url", _DEFAULT_RECORD_URL)).strip() or _DEFAULT_RECORD_URL
    all_records = []
    for offset in range(0, len(user_ids), 50):
        batch = user_ids[offset : offset + 50]
        payload = {
            "userIds": batch,
            "checkDateFrom": start.strftime("%Y-%m-%d %H:%M:%S"),
            "checkDateTo": end.strftime("%Y-%m-%d %H:%M:%S"),
            "isI18n": False,
        }
        result = _http_json(endpoint, payload, {"x-acs-dingtalk-access-token": token})
        all_records.extend(_records_from_response(result))
    return all_records


def _fetch_records_dws(user_ids, day):
    cli = _dingtalk_cli_path()
    if not cli:
        frappe.throw(_("未找到钉钉 dws CLI。"), frappe.ValidationError)
    # Pin every batch and retry to the configured organization/account instead
    # of following changes to the service user's interactive current profile.
    # Unconfigured sites retain the existing DWS profile-selection behavior.
    profile = str(_conf("dingtalk_attendance_profile", "")).strip()
    requested = [str(value).strip() for value in user_ids]
    if any(not value or "," in value for value in requested) or len(set(requested)) != len(requested):
        frappe.throw(_("钉钉考勤查询人员范围无效，已停止同步。"), frappe.ValidationError)
    target, start, end = _window(day)
    all_records = []
    seen_ids = set()
    for offset in range(0, len(requested), 50):
        batch = requested[offset : offset + 50]
        command = [
            cli, "attendance", "+check-record", "--users", ",".join(batch),
            "--start", target.isoformat(), "--end", end.date().isoformat(),
            "-f", "json",
        ]
        if profile:
            command.extend(["--profile", profile])
        payload = None
        for attempt in range(3):
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
                if completed.returncode == 0:
                    parsed = json.loads(completed.stdout)
                    if isinstance(parsed, dict) and not parsed.get("error") and parsed.get("ok") is True:
                        payload = parsed
                        break
            except (OSError, subprocess.TimeoutExpired, ValueError):
                pass
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
        if payload is None:
            frappe.throw(_("钉钉考勤流水查询失败，请检查服务连接和权限后重试。"), frappe.ValidationError)

        # The strict shortcut preserves the source userId; never infer ownership
        # from the requested employee or reinterpret a missing collection as empty.
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        records = data.get("records")
        meta = payload.get("meta") or {}
        pagination = meta.get("pagination") if isinstance(meta, dict) else None
        if (
            not isinstance(records, list)
            or any(not isinstance(row, dict) for row in records)
            or data.get("count") != len(records)
            or data.get("complete") is False
            or (isinstance(pagination, dict) and (pagination.get("has_more") or pagination.get("hasMore") or pagination.get("next_token") or pagination.get("nextToken")))
        ):
            frappe.throw(_("钉钉考勤流水返回格式无效或未完整返回，已停止同步。"), frappe.ValidationError)
        for record in records:
            owner = str(record.get("userId") or "").strip()
            if owner not in batch:
                frappe.throw(_("钉钉考勤流水人员归属与查询范围不一致，已停止同步。"), frappe.ValidationError)
            try:
                actual = _as_datetime(record.get("userCheckTime"))
            except (OSError, OverflowError, TypeError, ValueError):
                actual = None
            if actual is None or not start <= actual < end:
                frappe.throw(_("钉钉考勤流水缺少实际时间或超出查询日期，已停止同步。"), frappe.ValidationError)
            identity = str(record.get("id") or record.get("recordId") or "").strip()
            if not identity or identity in seen_ids:
                frappe.throw(_("钉钉考勤流水标识缺失或重复，已停止同步。"), frappe.ValidationError)
            seen_ids.add(identity)
            all_records.append(dict(record))
    return all_records


def _normalise_record(record):
    userid = str(
        record.get("userId")
        or record.get("userid")
        or record.get("user_id")
        or ""
    ).strip()
    # userCheckTime is the actual event. baseCheckTime and planCheckTime are
    # scheduled timestamps and cannot establish that an employee checked in.
    stamp = (
        record.get("userCheckTime")
        or record.get("checkinTime")
        or record.get("checkInTime")
        or record.get("checkTime")
        or record.get("time")
    )
    when = _as_datetime(stamp)
    known_types = set()
    for field in ("checkType", "check_type", "checkTypeDesc", "logType", "log_type"):
        value = str(record.get(field) or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")
        if value in ("onduty", "in", "checkin", "上班", "上班打卡"):
            known_types.add("IN")
        elif value in ("offduty", "out", "checkout", "下班", "下班打卡"):
            known_types.add("OUT")
    log_type = next(iter(known_types)) if len(known_types) == 1 else ""
    external_id = str(
        record.get("recordId")
        or record.get("id")
        or f"{userid}:{when.isoformat() if when else stamp}:{log_type}"
    )
    return {
        "userid": userid,
        "time": when,
        "log_type": log_type,
        "external_id": external_id,
        "source_type": str(record.get("sourceType") or record.get("source") or "DingTalk"),
        "raw": record,
    }


def _window(day):
    target = getdate(day) if day else getdate(now_datetime())
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)
    return target, start, end


def _runtime_status(**changes):
    """Operational timestamps and counts only; never cache employee identities."""
    key = f"dingtalk-attendance-runtime:{frappe.local.site}"
    previous = frappe.cache.get_value(key)
    value = dict(previous) if isinstance(previous, dict) else {}
    value.update(changes)
    frappe.cache.set_value(key, value)


def _late_checkin_review(doc, target):
    """Protect submitted attendance and closed shift-days from delayed logs.

    The native hourly processor does not take our ingestion lock. Checking the
    released shift-day as well as Attendance closes the race where that native
    processor has read its logs but has not yet committed Attendance. A later
    shift on the same employee/day remains eligible until its own day is sealed.
    """
    submitted = frappe.get_all(
        "Attendance", filters={"employee": doc.employee, "attendance_date": target, "docstatus": 1},
        fields=["name", "shift"],
    )
    matching = [row for row in submitted if not row.get("shift") or not doc.shift or row.get("shift") == doc.shift]
    watermark = frappe.db.get_value("Shift Type", doc.shift, "last_sync_of_checkin") if doc.shift else None
    day_end = datetime.combine(target + timedelta(days=1), datetime.min.time())
    released = bool(watermark and get_datetime(watermark) >= day_end)
    if not matching and not released:
        return None
    doc.db_set("skip_auto_attendance", 1, update_modified=False)
    reason = "submitted_attendance" if matching else "released_shift_day"
    frappe.log_error(
        title="钉钉补到打卡需复核",
        message=f"{target} 打卡 {doc.name} 员工 {doc.employee} 班次 {doc.shift or '未匹配'}：{reason}；已保留打卡并暂停自动考勤，请人工复核。",
    )
    return reason


def _sync(day=None, dry_run=True, employee=None, notify=True):
    target, start, end = _window(day)
    mappings, mapping_field = _employee_mappings(employee)
    if not mappings:
        return {
            "date": str(target),
            "dry_run": bool(dry_run),
            "configured": _configured(),
            "mapping_field": mapping_field,
            "employee_count": 0,
            "full_employee_scope": employee is None,
            "fetched": 0,
            "mapped": 0,
            "created": 0,
            "skipped": 0,
            "skipped_no_actual_time": 0,
            "unmapped": [],
            "message": "没有找到带钉钉 userid 的 Active Employee。",
        }
    user_ids = [item["userid"] for item in mappings]
    if _app_configured():
        token = _access_token()
        records = _fetch_records(token, user_ids, start, end)
    else:
        records = _fetch_records_dws(user_ids, target)
    by_user = {item["userid"]: item for item in mappings}
    result = {
        "date": str(target),
        "dry_run": bool(dry_run),
        "configured": True,
        "mapping_field": mapping_field,
        "employee_count": len(mappings),
        "full_employee_scope": employee is None,
        "fetched": len(records),
        "mapped": 0,
        "created": 0,
        "skipped": 0,
        "skipped_no_actual_time": 0,
        "unmapped": [],
        "errors": [],
        "review_required": 0,
        "items": [],
    }
    seen_unmapped = set()
    for raw in records:
        item = _normalise_record(raw)
        mapping = by_user.get(item["userid"])
        if not mapping:
            if item["userid"] and item["userid"] not in seen_unmapped:
                result["unmapped"].append(item["userid"])
                seen_unmapped.add(item["userid"])
            continue
        if not item["time"]:
            result["skipped_no_actual_time"] += 1
            continue
        result["mapped"] += 1
        time_value = item["time"].strftime("%Y-%m-%d %H:%M:%S")
        existing = frappe.db.exists(
            "Employee Checkin",
            {
                "employee": mapping["employee"],
                "time": time_value,
                "log_type": item["log_type"],
            },
        )
        created = False
        review_reason = None
        if not existing and not dry_run:
            frappe.db.savepoint("dingtalk_checkin_insert")
            try:
                doc = frappe.get_doc(
                    {
                        "doctype": "Employee Checkin",
                        "employee": mapping["employee"],
                        "employee_name": mapping.get("employee_name"),
                        "time": time_value,
                        "log_type": item["log_type"],
                        "device_id": "dingtalk",
                        "skip_auto_attendance": 0 if item["log_type"] in ("IN", "OUT") else 1,
                    }
                )
                doc.insert(ignore_permissions=True)
                review_reason = _late_checkin_review(doc, target)
                if review_reason:
                    result["review_required"] += 1
                created = True
            except Exception:
                # A failed review guard must not leave an unprotected late log
                # visible to the independent native hourly attendance worker.
                frappe.db.rollback(save_point="dingtalk_checkin_insert")
                result["errors"].append({"userid": item["userid"], "error": frappe.get_traceback()[-500:]})
        if existing:
            result["skipped"] += 1
        elif created or dry_run:
            result["created"] += 1
        result["items"].append(
            {
                "userid": item["userid"],
                "employee": mapping["employee"],
                "employee_name": mapping.get("employee_name"),
                "time": time_value,
                "log_type": item["log_type"],
                "existing": bool(existing),
                "would_create": not bool(existing),
                "review_reason": review_reason,
            }
        )
    if not dry_run:
        # Commit check-ins first so a notification validation error cannot roll them back.
        frappe.db.commit()
        if notify:
            _notify_sync(result)
        frappe.db.commit()
    return result


@frappe.whitelist()
def get_dingtalk_attendance_status():
    _require_manager()
    mappings, field = _employee_mappings()
    return {
        "configured": _configured(),
        "mapping_field": field,
        "mapped_employees": mappings,
        "mode": "app" if _app_configured() else ("dws" if _dws_configured() else None),
        "endpoint": str(_conf("dingtalk_attendance_url", _DEFAULT_RECORD_URL)),
    }


@frappe.whitelist(methods=["POST"])
def sync_dingtalk_attendance(day=None, dry_run=1, employee=None):
    _require_manager()
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() not in ("0", "false", "no")
    return _sync(day=day, dry_run=bool(dry_run), employee=employee)


def _attendance_shift_names():
    raw = _conf("dingtalk_attendance_shift_types", [])
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list) or any(not isinstance(name, str) or not name.strip() for name in raw):
        frappe.throw(_("钉钉自动考勤班次配置无效。"), frappe.ValidationError)
    return list(dict.fromkeys(raw))


def _attendance_shifts():
    shifts = [frappe.get_doc("Shift Type", name) for name in _attendance_shift_names()]
    for shift in shifts:
        if (not shift.enable_auto_attendance or shift.auto_update_last_sync
                or not shift.process_attendance_after or (shift.absent_buffer_days or 0) < 1):
            frappe.throw(_("钉钉班次 {0} 必须启用自动考勤、关闭时钟推进并设置考勤起日和缺勤缓冲。").format(shift.name), frappe.ValidationError)
        # The daily midnight watermark is only valid for shifts whose full
        # check-in window is contained within the same local calendar date.
        begin = datetime.combine(getdate(shift.process_attendance_after), get_time(shift.start_time))
        finish = datetime.combine(begin.date(), get_time(shift.end_time))
        if (begin >= finish
                or (begin - timedelta(minutes=shift.begin_check_in_before_shift_start_time or 0)).date() != begin.date()
                or (finish + timedelta(minutes=shift.allow_check_out_after_shift_end_time or 0)).date() != begin.date()):
            frappe.throw(_("钉钉按日考勤暂不支持跨午夜打卡窗口：{0}").format(shift.name), frappe.ValidationError)
    return shifts


def _validate_complete_sync(result, require_full_scope=True):
    """Only a complete, full-employee import may release HRMS attendance."""
    if (result.get("dry_run") or not result.get("configured")
            or (require_full_scope and not result.get("full_employee_scope")) or not result.get("employee_count")
            or result.get("errors") or result.get("unmapped") or result.get("skipped_no_actual_time")
            or result.get("mapped") != result.get("fetched")
            or result.get("mapped") != result.get("created", 0) + result.get("skipped", 0)
            or len(result.get("items", [])) != result.get("mapped")
            or any(item.get("log_type") not in ("IN", "OUT") for item in result.get("items", []))):
        frappe.throw(_("钉钉打卡未完整导入，已停止推进自动考勤，请处理同步错误后重试。"), frappe.ValidationError)


def _validate_attendance_mapping(day, shifts):
    mappings, _field = _employee_mappings()
    employees = {row["employee"] for row in mappings}
    userids = [row["userid"] for row in mappings]
    if not employees or len(userids) != len(set(userids)):
        frappe.throw(_("钉钉员工映射缺失或重复，已停止自动考勤。"), frappe.ValidationError)
    scheduled = frappe.db.sql(
        """select distinct e.name from `tabEmployee` e
        where e.status = 'Active' and (
            e.default_shift in %(shifts)s or exists (
                select 1 from `tabShift Assignment` a
                where a.employee=e.name and a.docstatus=1 and a.status='Active'
                and a.shift_type in %(shifts)s and a.start_date<=%(day)s
                and (a.end_date is null or a.end_date>=%(day)s)
            )
        )""", {"shifts": tuple(shift.name for shift in shifts), "day": day}, as_dict=True,
    )
    missing = [row.name for row in scheduled if row.name not in employees]
    if missing:
        frappe.throw(_("有 {0} 名已排班员工缺少钉钉映射，已停止自动考勤。").format(len(missing)), frappe.ValidationError)


def _latest_attendance_date(current=None):
    current = current or now_datetime()
    cutoff = datetime.combine(current.date(), datetime.min.time()) + timedelta(hours=18)
    return current.date() if current >= cutoff else current.date() - timedelta(days=1)


def _sync_attendance_day(day, shifts, *, notify=True, imported_result=None):
    target, start, end = _window(day)
    current = now_datetime()
    if target > _latest_attendance_date(current):
        frappe.throw(_("当天自动考勤须在站点时间 18:00 后执行。"), frappe.ValidationError)
    applicable = [shift for shift in shifts if getdate(shift.process_attendance_after) <= target]
    eligible, deferred = [], []
    for shift in applicable:
        window_end = datetime.combine(target, get_time(shift.end_time)) + timedelta(minutes=shift.allow_check_out_after_shift_end_time or 0)
        # A timestamp exactly on the boundary is still a valid checkout. Wait
        # until the complete window is strictly in the past before sealing it.
        (eligible if window_end < current else deferred).append(shift)
    for shift in eligible:
        watermark = get_datetime(shift.last_sync_of_checkin) if shift.last_sync_of_checkin else datetime.combine(getdate(shift.process_attendance_after), datetime.min.time())
        if watermark < start:
            frappe.throw(_("仍有更早日期未同步，不能跳日推进自动考勤。"), frappe.ValidationError)
    if eligible:
        # DWS validates complete collections and source ownership. The legacy
        # app API path has no verified pagination contract and must not release
        # absence processing until it gains an equally strict completeness check.
        if _app_configured():
            frappe.throw(_("当前自动考勤要求已验证完整性校验的 DWS 数据源。"), frappe.ValidationError)
        _validate_attendance_mapping(target, eligible)
    if imported_result is not None and imported_result.get("date") != str(target):
        frappe.throw(_("补漏数据日期与考勤日期不一致。"), frappe.ValidationError)
    result = imported_result if imported_result is not None else _sync(day=target, dry_run=False, notify=notify)
    _validate_complete_sync(result)
    for shift in eligible:
        previous = get_datetime(shift.last_sync_of_checkin) if shift.last_sync_of_checkin else None
        if previous is None or previous < end:
            frappe.db.set_value("Shift Type", shift.name, "last_sync_of_checkin", end)
            shift.last_sync_of_checkin = end
    # Native attendance commits internally. The midnight boundary releases D's
    # attendance with absent_buffer_days=1. Each eligible shift's complete
    # check-in window has ended. Deferred shifts retain their prior watermark;
    # the next periodic reconciliation can close them after their own window.
    frappe.db.commit()
    for shift in eligible:
        frappe.get_doc("Shift Type", shift.name).process_auto_attendance()
    result["attendance_shifts_processed"] = len(eligible)
    result["attendance_shifts_deferred"] = len(deferred)
    result["attendance_deferred_shifts"] = [shift.name for shift in deferred]
    result["attendance_complete_through"] = str(target) if eligible and not deferred else None
    return result


def _sync_attendance_pending_days(shifts, *, notify=True, imported_results=None):
    latest = _latest_attendance_date()
    imported_results = imported_results or {}
    if not shifts:
        return {"configured": True, "days": [], "pending_days": 0}
    first_day = min(
        max(getdate(shift.process_attendance_after), getdate(shift.last_sync_of_checkin or shift.process_attendance_after))
        for shift in shifts
    )
    # A completed day is represented by the following midnight. Retry the
    # latest date even when all cursors are current, so an interrupted native
    # attendance call can finish without skipping a date or reopening a cursor.
    first_day = min(first_day, latest)
    days = []
    for offset in range(min((latest - first_day).days + 1, 7)):
        day = first_day + timedelta(days=offset)
        result = _sync_attendance_day(day, shifts, notify=notify, imported_result=imported_results.get(str(day)))
        days.append({key: value for key, value in result.items() if key not in ("items", "notification_recipients")})
    return {"configured": True, "days": days, "pending_days": max((latest - first_day).days + 1 - len(days), 0)}


def _record_settlement_status(result):
    days = result.get("days", [])
    processed = sum(day.get("attendance_shifts_processed", 0) for day in days)
    values = {
        "last_settlement_deferred_count": sum(day.get("attendance_shifts_deferred", 0) for day in days),
        "last_settlement_error": None,
    }
    if processed:
        values["last_settlement_success"] = now_datetime().isoformat()
    _runtime_status(**values)


def sync_dingtalk_attendance_job():
    """At 18:00 site time, reconcile everyone and close only ended shifts."""
    if not _configured():
        frappe.throw(_("钉钉数据源尚未配置，无法同步考勤。"), frappe.ValidationError)
    try:
        with frappe.cache.lock(f"dingtalk-attendance:{frappe.local.site}", timeout=3600, blocking_timeout=0):
            shifts = _attendance_shifts()
            if not shifts:
                return _sync(day=_latest_attendance_date(), dry_run=False)
            result = _sync_attendance_pending_days(shifts)
            _record_settlement_status(result)
            return result
    except Exception:
        _runtime_status(last_settlement_error=now_datetime().isoformat())
        frappe.log_error(title="DingTalk 同步及原生考勤失败", message=frappe.get_traceback())
        # Do not silently mark a failed scheduler job as successful.
        raise


def sync_dingtalk_attendance_catchup_job():
    """Ten-minute safety net; Stream remains the primary, per-event importer.

    Pull today and yesterday for missed events. The same lock protects Stream,
    daily reconciliation and this job. Before 18:00 only historical days can
    settle; after 18:00 unfinished late shifts are retried after their windows.
    Recent results are reused under that lock, avoiding duplicate API requests.
    """
    if not _configured():
        frappe.throw(_("钉钉数据源尚未配置，无法同步考勤。"), frappe.ValidationError)
    lock = frappe.cache.lock(f"dingtalk-attendance:{frappe.local.site}", timeout=3600, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return {"ok": True, "skipped": "sync_busy"}
    try:
        shifts = _attendance_shifts()
        today = getdate(now_datetime())
        start = min((getdate(shift.process_attendance_after) for shift in shifts), default=today)
        recent = {}
        for day in (today - timedelta(days=1), today):
            if day < start:
                continue
            result = _sync(day=day, dry_run=False, notify=False)
            _validate_complete_sync(result)
            recent[str(day)] = result
        _runtime_status(
            last_reconcile_success=now_datetime().isoformat(), last_reconcile_error=None,
            last_reconcile_created=sum(result.get("created", 0) for result in recent.values()),
            last_reconcile_review_count=sum(result.get("review_required", 0) for result in recent.values()),
        )
        result = _sync_attendance_pending_days(shifts, notify=False, imported_results=recent)
        _record_settlement_status(result)
        result["recent_dates"] = list(recent)
        return result
    except Exception:
        _runtime_status(last_reconcile_error=now_datetime().isoformat(), last_settlement_error=now_datetime().isoformat())
        frappe.log_error(title="DingTalk 定时补漏及考勤失败", message=frappe.get_traceback())
        raise
    finally:
        lock.release()


def _unmapped_stream_employee(userid, target):
    digest = hashlib.sha256(userid.encode()).hexdigest()
    key = f"dingtalk-unmapped-stream:{frappe.local.site}:{target}:{digest}"
    if not frappe.cache.get_value(key):
        frappe.log_error(title="钉钉实时打卡员工待匹配", message=f"{target} 钉钉 userid {userid} 尚未匹配唯一有效员工；事件保持待处理，请核对人员映射。")
        frappe.db.commit()
        frappe.cache.set_value(key, True, expires_in_sec=86400)
    frappe.throw(_("钉钉打卡人员尚未匹配，事件已保留等待处理。"), frappe.ValidationError)


def sync_stream_trigger(employee_userid, day, check_time=None, check_times=None):
    """Import a verified employee/day from the API; never release attendance.

    Called by the local durable Stream worker, not exposed over HTTP. Stream
    events carry no reliable IN/OUT type, so they are only lookup triggers.
    """
    userid = str(employee_userid or "").strip()
    target = getdate(day)
    starts = [getdate(shift.process_attendance_after) for shift in _attendance_shifts()]
    if target > getdate(now_datetime()):
        frappe.throw(_("钉钉事件日期尚未到达。"), frappe.ValidationError)
    if starts and target < min(starts):
        return {"ok": True, "ignored": "before_attendance_start"}
    mappings, _field = _employee_mappings()
    matched = [row for row in mappings if row["userid"] == userid]
    if not matched:
        _unmapped_stream_employee(userid, target)
    if len(matched) != 1:
        frappe.throw(_("钉钉用户映射不唯一，已停止实时导入。"), frappe.ValidationError)
    if check_times is not None and (
        not isinstance(check_times, list) or not 1 <= len(check_times) <= 256
        or any(isinstance(value, bool) or not isinstance(value, int) or not 946684800000 <= value <= 4102444800000 for value in check_times)
    ):
        frappe.throw(_("钉钉事件时间列表无效。"), frappe.ValidationError)
    stamps = list(check_times) if check_times is not None else []
    if check_time is not None:
        stamps.append(check_time)
    expected = []
    for stamp in stamps:
        value = _as_datetime(stamp)
        if value is None or value.date() != target:
            frappe.throw(_("钉钉事件时间与日期不一致。"), frappe.ValidationError)
        if value not in expected:
            expected.append(value)
    with frappe.cache.lock(f"dingtalk-attendance:{frappe.local.site}", timeout=3600, blocking_timeout=0):
        result = _sync(day=target, dry_run=False, employee=matched[0]["employee"], notify=False)
        _validate_complete_sync(result, require_full_scope=False)
        visible = {get_datetime(item["time"]) for item in result["items"]}
        if any(stamp not in visible for stamp in expected):
            # Event delivery can precede API visibility. The durable worker
            # retries without losing the event or inventing a check-in record.
            frappe.throw(_("事件对应的实际打卡尚未在查询接口中可见，请稍后重试。"), frappe.ValidationError)
        return {"ok": True, "date": str(target), "fetched": result["fetched"], "created": result["created"], "skipped": result["skipped"]}


def ensure_dingtalk_employee_field():
    """Add a visible Employee field for the DingTalk userid when HRMS is installed."""
    if not frappe.db.exists("DocType", "Employee"):
        return
    if frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "dingtalk_userid"}):
        return
    frappe.get_doc(
        {
            "doctype": "Custom Field",
            "dt": "Employee",
            "label": "钉钉用户 ID",
            "fieldname": "dingtalk_userid",
            "fieldtype": "Data",
            "insert_after": "user_id",
            "description": "用于将钉钉企业通讯录 userid 映射到本系统教师。",
        }
    ).insert(ignore_permissions=True)
    frappe.clear_cache(doctype="Employee")
