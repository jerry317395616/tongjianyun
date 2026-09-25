"""Real attendance / per-meal ORM acceptance, fixed isolated site ONLY.

Creates synthetic prerequisites and retains successful evidence. Never imports
production data and never starts HTTP, workers or a scheduler.
"""
import json
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse


SITE = "unified-business-acceptance.localhost"
ROOT = Path("/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925").resolve()
sites = Path(os.environ["UNIFIED_BUSINESS_SITES"]).resolve(strict=True)
source = Path(os.environ["UNIFIED_BUSINESS_SOURCE"]).resolve(strict=True)
assert sites == ROOT / "sites", "Only the dedicated acceptance sites path is permitted"
config = {**json.loads((sites / "common_site_config.json").read_text()),
          **json.loads((sites / SITE / "site_config.json").read_text())}


def guard(conf):
    assert conf.get("unified_business_acceptance") == 1
    assert conf.get("db_host") == "127.0.0.1" and int(conf.get("db_port", 0)) == 23316
    assert conf.get("db_name") == "tgy_blueprint_qa"
    assert conf.get("db_user", conf.get("db_name")) == "tgy_blueprint_qa"
    assert not conf.get("db_socket") and not conf.get("developer_mode")
    assert conf.get("pause_scheduler") == 1 and conf.get("disable_scheduler") == 1
    for key in ("redis_cache", "redis_queue", "redis_socketio"):
        url = urlparse(conf.get(key) or "")
        assert url.scheme == "redis" and url.hostname == "127.0.0.1" and url.port == 23379


guard(config)
for key in list(os.environ):
    if key.startswith(("FRAPPE_DB_", "FRAPPE_REDIS_")):
        os.environ.pop(key)
os.environ["FRAPPE_BENCH_ROOT"] = str(ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
sys.path.insert(0, str(source))
os.chdir(sites)

import frappe
from frappe.utils import getdate, nowdate
from tongjianyun import classroom, daily_meals, student_meals
from tongjianyun.meal_view_tool import use_site_os_identity

for module in (classroom, daily_meals, student_meals):
    assert Path(module.__file__).resolve().is_relative_to(source), "Wrong candidate source"
use_site_os_identity(sites / SITE)
os.umask(0o077)
run_id = uuid.uuid4().hex[:10]
checks = []
retained = {}


def check(label, condition):
    assert condition, label
    checks.append(label)
    print(json.dumps({"passed": label}, ensure_ascii=False), flush=True)


def denied(label, action, exception=frappe.ValidationError):
    point = "reject_" + uuid.uuid4().hex[:8]
    frappe.db.savepoint(point)
    try:
        action()
    except exception:
        frappe.db.rollback(save_point=point)
        checks.append(label)
        print(json.dumps({"passed": label}, ensure_ascii=False), flush=True)
        return
    raise AssertionError(label + ": action unexpectedly accepted")


def connect():
    frappe.init(site=SITE, sites_path=str(sites))
    guard(frappe.conf)  # Guard effective config BEFORE connecting.
    frappe.connect()
    frappe.set_user("Administrator")


connect()
try:
    day = getdate(nowdate())
    # Retain a successful run as evidence rather than silently reopening its
    # locked day or folding earlier synthetic classes into a fresh aggregate.
    assert not frappe.db.exists(daily_meals.CONFIRMATION_DOCTYPE, {"meal_date": str(day)}), \
        "This isolated date already has retained evidence; do not reset it to rerun"
    assert not frappe.db.exists("Student Group", {"disabled": 0}), \
        "Use a fresh isolated attendance fixture; do not modify retained classes"
    # Fresh app installation does not run Tongjianyun's after_migrate hooks.
    # Install only the original Student prerequisites; do not invoke unrelated
    # setup hooks that remove legacy DocTypes or seed operational content.
    from tongjianyun import education_integration, student_identity
    education_integration._configure_student_master()
    student_identity.install()
    frappe.db.commit()
    tomorrow = str(day + timedelta(days=1))
    year_start, year_end = str(day.replace(month=1, day=1)), str(day.replace(month=12, day=31))
    # A real attendance controller needs a Company with a Holiday List. This
    # prerequisite also uses normal ORM validation/hooks on the isolated DB.
    holiday = frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": "QA Meal " + run_id,
        "from_date": year_start, "to_date": year_end, "holidays": []}).insert()
    if not frappe.db.exists("Warehouse Type", "Transit"):
        frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert()
    company = frappe.get_doc({"doctype": "Company", "company_name": "QA Meal " + run_id,
        "abbr": "QM" + run_id[:5].upper(), "default_currency": "CNY", "country": "China",
        "chart_of_accounts": "Standard", "default_holiday_list": holiday.name}).insert()
    frappe.defaults.set_global_default("company", company.name)
    academic_year = frappe.get_doc({"doctype": "Academic Year", "academic_year_name": "QA Meal " + run_id,
        "year_start_date": year_start, "year_end_date": year_end}).insert()
    children = [frappe.get_doc({"doctype": "Student", "first_name": "QA Meal " + run_id + " " + str(n),
        "enabled": 1, "joining_date": year_start, "date_of_birth": "2021-01-01"}).insert() for n in range(3)]
    group = frappe.get_doc({"doctype": "Student Group", "student_group_name": "QA Meal " + run_id,
        "group_based_on": "Activity", "academic_year": academic_year.name,
        "students": [{"student": child.name, "student_name": child.student_name,
                      "group_roll_number": n + 1, "active": 1} for n, child in enumerate(children)]}).insert()
    retained.update(company=company.name, academic_year=academic_year.name, student_group=group.name,
                    students=[child.name for child in children], day=str(day))
    check("synthetic_fixture_has_three_active_students", len(classroom._roster(group)) == 3)

    def attendance(which_day=str(day)):
        return classroom.get_overview(group.name, which_day)["attendance"]

    initial = attendance()
    check("missing_attendance_is_unknown_not_present", initial["counts"]["Unknown"] == 3
          and initial["counts"]["Present"] == 0)
    classroom.save_attendance(group.name, str(day), [
        {"student": children[0].name, "status": "Present"},
        {"student": children[1].name, "status": "Leave", "leave_reason": "Synthetic lifecycle QA only"},
    ], initial["revision"])
    current = attendance()
    check("native_present_leave_and_unknown_saved", current["counts"]["Present"] == 1
          and current["counts"]["Leave"] == 1 and current["counts"]["Unknown"] == 1)
    denied("stale_attendance_revision_rejected", lambda: classroom.save_attendance(group.name, str(day),
        [{"student": children[0].name, "status": "Absent"}], initial["revision"]))
    classroom.save_attendance(group.name, str(day), [{"student": children[0].name, "status": "Absent"}], current["revision"])
    current = attendance()
    check("submitted_attendance_can_be_corrected", current["counts"]["Absent"] == 1 and current["counts"]["Present"] == 0)
    denied("active_leave_cannot_be_silently_overwritten", lambda: classroom.save_attendance(group.name, str(day),
        [{"student": children[1].name, "status": "Present"}], current["revision"]))
    leave_name = next(row["leave_record"] for row in current["students"] if row["student"] == children[1].name)
    frappe.get_doc("Student Leave Application", leave_name).cancel()
    classroom.save_attendance(group.name, str(day), [
        {"student": children[0].name, "status": "Present"},
        {"student": children[1].name, "status": "Present"},
    ], attendance()["revision"])
    current = attendance()
    check("cancelled_leave_returns_through_native_attendance", current["counts"]["Present"] == 2
          and current["counts"]["Unknown"] == 1 and current["counts"]["Leave"] == 0)
    denied("future_attendance_rejected", lambda: classroom.save_attendance(group.name, tomorrow,
        [{"student": children[0].name, "status": "Present"}], attendance(tomorrow)["revision"]), frappe.PermissionError)
    check("future_attendance_rejection_writes_no_record", not frappe.db.exists("Student Attendance", {"student_group": group.name, "date": tomorrow}))

    def meals(which_day=str(day)):
        return classroom.get_meals(group.name, which_day)

    def payload(values):
        return [{"student": child.name, "value": value} for child, value in zip(children, values)]

    def save(meal, values, confirm=1, reason="", which_day=str(day)):
        classroom.save_meal(group.name, which_day, meal, payload(values), meals(which_day)["revision"], confirm, reason)
        return meals(which_day)

    initial_meals = meals()
    check("unknown_meal_actual_is_null", initial_meals["actual"]["breakfast_count"] is None
          and initial_meals["actual"]["lunch_count"] is None)
    plan = save("breakfast", ["就餐"] * 3, confirm=0)
    check("planning_does_not_confirm_actual", plan["expected"]["breakfast_count"] == 3
          and plan["actual"]["breakfast_count"] is None)
    breakfast = save("breakfast", ["就餐", "就餐", "不就餐"])
    check("breakfast_actual_preserves_original_expected", breakfast["expected"]["breakfast_count"] == 3
          and breakfast["actual"]["breakfast_count"] == 2)
    check("breakfast_does_not_confirm_other_meals", breakfast["actual"]["lunch_count"] is None
          and breakfast["actual"]["morning_snack_count"] is None and breakfast["record"]["status"] == "待确认")
    check("meal_does_not_fake_unknown_attendance", attendance()["counts"]["Unknown"] == 1)
    denied("stale_meal_revision_rejected", lambda: classroom.save_meal(group.name, str(day), "lunch",
        payload(["就餐"] * 3), plan["revision"], 1))
    denied("correcting_actual_requires_reason", lambda: save("breakfast", ["就餐"] * 3))
    corrected = save("breakfast", ["就餐"] * 3, reason="Synthetic QA correction after recount")
    check("correction_with_reason_is_retained", corrected["actual"]["breakfast_count"] == 3
          and corrected["record"]["change_reason"] == "Synthetic QA correction after recount")
    unchanged = save("breakfast", ["就餐"] * 3, confirm=0, reason="Synthetic QA save estimate")
    check("saving_estimate_preserves_confirmed_actual", unchanged["actual"]["breakfast_count"] == 3)
    lunch = save("lunch", ["就餐", "就餐", "不就餐"])
    check("lunch_confirmed_independently", lunch["actual"]["lunch_count"] == 2
          and lunch["expected"]["lunch_count"] == 3 and lunch["actual"]["afternoon_snack_count"] is None)
    daily_name = frappe.db.get_value(daily_meals.CONFIRMATION_DOCTYPE, {"meal_date": str(day)}, "name")
    daily = frappe.get_doc(daily_meals.CONFIRMATION_DOCTYPE, daily_name)
    daily_row = next(row for row in daily.details if row.student_group == group.name)
    check("partial_daily_aggregate_uses_actual_and_explicit_estimates", daily.status == "待确认"
          and daily_row.breakfast_count == 3 and daily_row.lunch_count == 2
          and daily_row.afternoon_snack_count == 3 and "不是全日实际" in daily.source)
    future = save("breakfast", ["就餐"] * 3, confirm=0, which_day=tomorrow)
    denied("future_actual_meal_rejected", lambda: save("breakfast", ["就餐"] * 3, which_day=tomorrow))
    check("future_estimate_remains_unconfirmed", meals(tomorrow)["actual"]["breakfast_count"] is None
          and meals(tomorrow)["revision"] == future["revision"])

    save("morning_snack", ["就餐", "就餐", "不就餐"])
    pending_dinner = save("afternoon_snack", ["就餐", "就餐", "不就餐"])
    check("zero_dinner_estimate_does_not_mean_no_service", pending_dinner["record"]["status"] == "待确认"
          and pending_dinner["meals"]["dinner"]["actual"] is None
          and pending_dinner["meals"]["dinner"]["expected"] == 0)
    complete = save("dinner", ["不供餐"] * 3)
    daily.reload()
    check("last_served_meal_auto_confirms_class_day", complete["record"]["status"] == "已确认"
          and complete["meals"]["dinner"]["status"] == "不供餐")
    check("daily_auto_confirms_without_second_daily_action", daily.status == "已确认"
          and "自动汇总" in daily.source and bool(daily.confirmed_at))
    check("one_daily_aggregate_per_date", frappe.db.count(daily_meals.CONFIRMATION_DOCTYPE, {"meal_date": str(day)}) == 1)
    name = complete["record"]["name"]
    check("native_meal_version_history_retained", frappe.db.count("Version", {"ref_doctype": student_meals.DOCTYPE, "docname": name}) >= 1)
    check("per_meal_confirmation_audit_comments_retained", frappe.db.count("Comment", {"reference_doctype": student_meals.DOCTYPE,
          "reference_name": name, "comment_type": "Info"}) >= 4)
    daily.status = "已锁定"
    daily.save()
    denied("locked_day_rejects_meal_changes", lambda: save("lunch", ["就餐"] * 3, reason="QA locked check"), frappe.PermissionError)
    denied("locked_day_rejects_attendance_changes", lambda: classroom.save_attendance(group.name, str(day),
        [{"student": children[0].name, "status": "Absent"}], attendance()["revision"]), frappe.PermissionError)
    daily_meals.confirm_daily_meal(str(day))
    daily.reload()
    check("legacy_daily_confirm_cannot_unlock_day", daily.status == "已锁定")

    viewer = "meal-qa-viewer-" + run_id + "@example.invalid"
    frappe.get_doc({"doctype": "User", "email": viewer, "first_name": "Synthetic Meal QA",
        "enabled": 1, "user_type": "System User", "send_welcome_email": 0, "roles": []}).insert()
    frappe.set_user(viewer)
    denied("unauthorised_user_cannot_read_meal_roster", lambda: classroom.get_meals(group.name, str(day)), frappe.PermissionError)
    denied("unauthorised_user_cannot_write_meals", lambda: classroom.save_meal(group.name, tomorrow,
        "breakfast", payload(["就餐"] * 3), future["revision"], 0), frappe.PermissionError)
    frappe.set_user("Administrator")
    frappe.db.commit()
    retained.update(class_meal=name, daily_meal=daily.name, cancelled_leave=leave_name, viewer=viewer)
    frappe.destroy()
    connect()
    saved = meals()
    check("new_connection_reads_actual_expected_and_locked_daily", saved["actual"]["lunch_count"] == 2
          and saved["expected"]["lunch_count"] == 3
          and frappe.db.get_value(daily_meals.CONFIRMATION_DOCTYPE, daily_name, "status") == "已锁定")
    report = {"isolated_site": SITE, "run_id": run_id, "checks": checks, "passed": len(checks),
        "retained_synthetic_records": retained, "production_writes": False, "browser_ui_tested": False}
    (ROOT / ("attendance-meal-lifecycle-" + run_id + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
finally:
    if getattr(frappe.local, "db", None):
        frappe.db.rollback()
    frappe.destroy()
