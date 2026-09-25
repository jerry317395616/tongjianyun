"""Real assigned-teacher attendance/meal lifecycle: fixed isolated site ONLY.

The Administrator creates synthetic identity/roster prerequisites; every positive
business read/write runs as an enabled Instructor, never as a management role.
Retained historical fixtures and the locked 2026-09-25 aggregate are not edited.
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
assert source.is_relative_to(ROOT.parent) and source != ROOT.parent, "Use an isolated candidate checkout"
config = {**json.loads((sites / "common_site_config.json").read_text()),
          **json.loads((sites / SITE / "site_config.json").read_text())}


def guard(conf):
    assert conf.get("unified_business_acceptance") == 1
    assert conf.get("db_host") == "127.0.0.1" and int(conf.get("db_port", 0)) == 23316
    assert conf.get("db_name") == "tgy_blueprint_qa"
    assert conf.get("db_user", conf.get("db_name")) == "tgy_blueprint_qa"
    assert not conf.get("db_socket") and not conf.get("developer_mode")
    assert conf.get("pause_scheduler") == 1 and conf.get("disable_scheduler") == 1
    for key, db in (("redis_cache", "0"), ("redis_queue", "1"), ("redis_socketio", "2")):
        url = urlparse(conf.get(key) or "")
        assert url.scheme == "redis" and url.hostname == "127.0.0.1" and url.port == 23379
        assert url.path == "/" + db


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
from frappe.api import v1 as resource_api
from frappe.utils import getdate, nowdate
from tongjianyun import attendance_scope, classroom, daily_meals, student_meals, teacher_permissions
from tongjianyun.meal_view_tool import use_site_os_identity

for module in (attendance_scope, classroom, daily_meals, student_meals, teacher_permissions):
    assert Path(module.__file__).resolve().is_relative_to(source), "Wrong candidate source"
use_site_os_identity(sites / SITE)
os.umask(0o077)
run_id = uuid.uuid4().hex[:10]
checks, setup_actions, retained, gaps = [], [], {}, []
committed = False


def check(label, condition):
    assert condition, label
    checks.append(label)
    print(json.dumps({"passed": label}), flush=True)


def denied(label, action, exception=frappe.PermissionError):
    point = "reject_" + uuid.uuid4().hex[:8]
    frappe.db.savepoint(point)
    try:
        action()
    except exception:
        frappe.db.rollback(save_point=point)
        check(label, True)
        return
    raise AssertionError(label + ": action unexpectedly accepted")


def connect(user="Administrator"):
    frappe.init(site=SITE, sites_path=str(sites))
    guard(frappe.conf)  # Recheck the effective configuration BEFORE connecting.
    frappe.connect()
    frappe.set_user(user)


def report(error=None):
    result = {"isolated_site": SITE, "run_id": run_id, "checks": checks, "passed": len(checks),
        "setup_actions": setup_actions, "retained_synthetic_records": retained,
        "production_writes": False, "browser_ui_tested": False, "native_resource_handlers_tested": True,
        "fixtures_committed": committed, "gaps": gaps,
        "status": "failed" if error or gaps else "passed"}
    if error:
        result["failure"] = {"type": type(error).__name__, "message": str(error)}
    (ROOT / ("teacher-scope-lifecycle-" + run_id + ".json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if "--unit-tests-only" in sys.argv:
    import unittest
    connect()
    try:
        modules = ["test_attendance_scope", "test_teacher_permissions", "test_classroom",
                   "test_student_meals", "test_workspace_entry"]
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(
            ["tongjianyun.tests." + name for name in modules]))
    finally:
        frappe.db.rollback()
        frappe.destroy()
    raise SystemExit(0 if result.wasSuccessful() else 1)


connect()
try:
    # Reuse only explicitly named synthetic prerequisites, never production data.
    prior = json.loads((ROOT / "attendance-meal-lifecycle-0afbba8af3.json").read_text())
    fixture = prior["retained_synthetic_records"]
    assert prior["isolated_site"] == SITE and not prior["production_writes"]
    company_name, year_name = fixture["company"], fixture["academic_year"]
    assert company_name.startswith("QA Meal ") and year_name.startswith("QA Meal ")
    year = frappe.get_doc("Academic Year", year_name)
    today = getdate(nowdate())
    # Daily recomputation legitimately includes every existing active class. Use
    # a previously unused past date; never recalculate a retained fixture's day.
    day = min(today - timedelta(days=2), getdate(year.year_end_date))
    while day >= getdate(year.year_start_date):
        if not frappe.db.exists(daily_meals.CONFIRMATION_DOCTYPE, {"meal_date": str(day)}):
            break
        day -= timedelta(days=1)
    assert day >= getdate(year.year_start_date), "No untouched past date in the synthetic academic year"
    day, future_day = str(day), str(today + timedelta(days=2))
    assert day != fixture["day"]
    old_daily = frappe.get_doc(daily_meals.CONFIRMATION_DOCTYPE, fixture["daily_meal"]).as_json()
    old_group = frappe.get_doc("Student Group", fixture["student_group"]).as_json()
    old_meals = frappe.get_doc(student_meals.DOCTYPE, fixture["class_meal"]).as_json()

    # Optional only for a newly installed test DB lacking the original migration.
    # No ad-hoc grants, user elevation or broad app migrations are allowed here.
    if os.environ.get("UNIFIED_BUSINESS_INSTALL_ATTENDANCE_ROLES") == "1":
        from tongjianyun import meal_attendance_roles
        assert Path(meal_attendance_roles.__file__).resolve().is_relative_to(source)
        meal_attendance_roles.install()
        setup_actions.append("isolated existing meal_attendance_roles.install hook")
        frappe.db.commit()

    email = "teacher-scope-" + run_id + "@example.invalid"
    user = frappe.get_doc({"doctype": "User", "email": email, "first_name": "Synthetic Teacher " + run_id,
        "enabled": 1, "user_type": "System User", "send_welcome_email": 0,
        "roles": [{"role": "Instructor"}, {"role": "Academics User"}]}).insert()
    gender = frappe.get_doc({"doctype": "Gender", "gender": "Synthetic QA " + run_id}).insert()
    employee = frappe.get_doc({"doctype": "Employee", "first_name": "Synthetic Teacher " + run_id,
        "company": company_name, "gender": gender.name, "date_of_birth": "1990-01-01",
        "date_of_joining": str(year.year_start_date), "status": "Active", "user_id": email,
        "create_user_permission": 0, "naming_series": "HR-EMP-"}).insert()
    instructor = frappe.get_doc({"doctype": "Instructor", "instructor_name": "Synthetic Teacher " + run_id,
        "employee": employee.name, "status": "Active", "naming_series": "EDU-INS-.YYYY.-"}).insert()
    children = [frappe.get_doc({"doctype": "Student", "first_name": "QA Teacher " + run_id + " " + str(n),
        "enabled": 1, "joining_date": str(year.year_start_date), "date_of_birth": "2021-01-01"}).insert()
        for n in range(4)]

    def make_group(label, roster, assigned=False):
        return frappe.get_doc({"doctype": "Student Group", "student_group_name": "QA Teacher " + run_id + " " + label,
            "group_based_on": "Activity", "academic_year": year_name,
            "instructors": [{"instructor": instructor.name}] if assigned else [],
            "students": [{"student": child.name, "student_name": child.student_name,
                          "group_roll_number": n + 1, "active": 1} for n, child in enumerate(roster)]}).insert()

    own, other = make_group("Assigned", children[:2], True), make_group("Other", children[2:])
    retained.update(teacher=email, employee=employee.name, instructor=instructor.name, assigned_group=own.name,
        other_group=other.name, students=[child.name for child in children], day=day, future_day=future_day)
    # Capture a legitimate cross-class revision as admin so denial is not merely
    # a bad revision. No business save occurs under admin for the new fixtures.
    other_attendance = classroom.get_overview(other.name, day)["attendance"]
    other_meals = classroom.get_meals(other.name, day)
    frappe.set_user(email)
    check("positive_actor_is_assigned_teacher_not_manager", email != "Administrator"
        and "Instructor" in frappe.get_roles() and not set(frappe.get_roles()) & attendance_scope.MANAGERS
        and teacher_permissions.is_scoped_teacher(email))
    check("scope_is_exact_assigned_class", set(attendance_scope.allowed_groups()) == {own.name})
    check("permission_filtered_lists_hide_other_class_and_students",
        set(frappe.get_list("Student Group", pluck="name", limit_page_length=0)) == {own.name}
        and set(frappe.get_list("Student", pluck="name", limit_page_length=0)) == {c.name for c in children[:2]})

    def overview(which_day=day):
        return classroom.get_overview(own.name, which_day, workspace="teacher")

    def attendance(which_day=day):
        return overview(which_day)["attendance"]

    def meals(which_day=day):
        return classroom.get_meals(own.name, which_day, workspace="teacher")

    def payload(values, roster=children[:2]):
        return [{"student": child.name, "value": value} for child, value in zip(roster, values)]

    initial = overview()
    check("teacher_reads_two_unknown_students", initial["attendance"]["counts"]["Unknown"] == 2
        and {g["name"] for g in initial["groups"]} == {own.name})
    attendance_enabled = bool(initial["capabilities"]["attendance_write"])
    if not attendance_enabled:
        gaps.append({"code": "teacher_attendance_write_unavailable", "capabilities": initial["capabilities"],
            "daily_create": bool(frappe.has_permission(daily_meals.CONFIRMATION_DOCTYPE, "create")),
            "daily_write": bool(frappe.has_permission(daily_meals.CONFIRMATION_DOCTYPE, "write")),
            "message": "Real Instructor cannot save attendance; do not replace with manager role to pass"})
    else:
        check("teacher_has_real_attendance_write_capability", True)
    check("teacher_has_real_meal_write_capability", initial["capabilities"]["meals_write"])
    denied("cross_class_overview_exact_id_denied", lambda: classroom.get_overview(other.name, day))
    denied("cross_class_meal_read_exact_id_denied", lambda: classroom.get_meals(other.name, day))
    denied("cross_class_attendance_write_exact_revision_denied", lambda: classroom.save_attendance(other.name, day,
        [{"student": children[2].name, "status": "Present"}], other_attendance["revision"]))
    denied("cross_class_meal_write_exact_revision_denied", lambda: classroom.save_meal(other.name, day,
        "breakfast", payload(["就餐", "就餐"], children[2:]), other_meals["revision"], 1))
    if attendance_enabled:
        denied("other_student_cannot_be_injected_into_assigned_attendance", lambda: classroom.save_attendance(own.name, day,
            [{"student": children[2].name, "status": "Present"}], attendance()["revision"]), frappe.ValidationError)
    denied("other_student_cannot_be_injected_into_assigned_meal", lambda: classroom.save_meal(own.name, day,
        "breakfast", payload(["就餐", "就餐"], children[2:]), meals()["revision"], 1), frappe.ValidationError)
    first_revision = attendance()["revision"]
    if attendance_enabled:
        classroom.save_attendance(own.name, day, [{"student": children[0].name, "status": "Present"}], first_revision)
        check("teacher_saved_attendance_reads_present_and_unknown", attendance()["counts"]["Present"] == 1
            and attendance()["counts"]["Unknown"] == 1)
        denied("teacher_stale_attendance_revision_denied", lambda: classroom.save_attendance(own.name, day,
            [{"student": children[0].name, "status": "Absent"}], first_revision), frappe.ValidationError)
        classroom.save_attendance(own.name, day, [{"student": children[0].name, "status": "Absent"}], attendance()["revision"])
        check("teacher_corrects_native_submitted_attendance", attendance()["counts"]["Absent"] == 1
            and attendance()["counts"]["Unknown"] == 1)
        # Direct domain-service calls must independently authorize the batch,
        # not depend on the classroom wrapper or a caller-selected internal flag.
        denied("direct_attendance_service_cross_class_denied", lambda: daily_meals.save_student_meal_attendance(day,
            [{"student_group": other.name, "student": children[2].name, "status": "Present"}]))
        denied("direct_attendance_service_foreign_student_denied", lambda: daily_meals.save_student_meal_attendance(day,
            [{"student_group": own.name, "student": children[2].name, "status": "Present"}]), frappe.ValidationError)
        denied("direct_attendance_service_whole_batch_validated_before_write", lambda: daily_meals.save_student_meal_attendance(day,
            [{"student_group": own.name, "student": children[0].name, "status": "Present"},
             {"student_group": other.name, "student": children[2].name, "status": "Absent"}]))
        check("rejected_mixed_batch_kept_first_student_unchanged", attendance()["counts"]["Absent"] == 1)
        direct = daily_meals.save_student_meal_attendance(day,
            [{"student_group": own.name, "student": children[0].name, "status": "Present"}])
        check("teacher_daily_response_contains_only_assigned_class_no_school_totals",
            {row["student_group"] for row in direct["confirmation"]["details"]} == {own.name}
            and {row["student_group"] for row in direct["details"]} == {own.name}
            and not any(key.startswith("total_") for key in direct["confirmation"]))
        check("direct_teacher_service_saves_and_classroom_reads_back", attendance()["counts"]["Present"] == 1)
        classroom.save_attendance(own.name, day, [{"student": children[0].name, "status": "Absent"}], attendance()["revision"])
        daily_name = direct["confirmation"]["name"]
        denied("legacy_daily_read_remains_permission_denied", lambda: daily_meals.get_daily_meal_confirmation(day))
        check("teacher_has_no_whole_school_daily_read_create_write_permission",
            not any(frappe.has_permission(daily_meals.CONFIRMATION_DOCTYPE, action) for action in ("read", "create", "write")))

        def native_resource(action, data=None):
            original = frappe.local.form_dict
            frappe.local.form_dict = frappe._dict(data=json.dumps(data or {}))
            try:
                return action()
            finally:
                frappe.local.form_dict = original

        denied("native_resource_read_of_whole_school_daily_denied", lambda: native_resource(
            lambda: resource_api.read_doc(daily_meals.CONFIRMATION_DOCTYPE, daily_name)))
        denied("native_resource_list_of_whole_school_daily_denied", lambda: native_resource(
            lambda: resource_api.document_list(daily_meals.CONFIRMATION_DOCTYPE)))
        denied("native_resource_write_of_whole_school_daily_denied", lambda: native_resource(
            lambda: resource_api.update_doc(daily_meals.CONFIRMATION_DOCTYPE, daily_name), {"remark": "Forbidden teacher write"}))
        denied("native_resource_create_of_whole_school_daily_denied", lambda: native_resource(
            lambda: resource_api.create_doc(daily_meals.CONFIRMATION_DOCTYPE), {"meal_date": future_day, "status": "待确认"}))
        denied("private_confirmation_helper_not_remote_whitelisted",
            lambda: frappe.is_whitelisted(daily_meals._get_confirmation_for_edit))
        denied("direct_attendance_service_future_denied", lambda: daily_meals.save_student_meal_attendance(future_day,
            [{"student_group": own.name, "student": children[0].name, "status": "Present"}]))
        # Exercise both locks on only this new synthetic day; roll them back.
        for state in ("已确认", "已锁定"):
            point = "synthetic_lock_" + uuid.uuid4().hex[:8]
            frappe.db.savepoint(point)
            frappe.set_user("Administrator")
            test_daily = frappe.get_doc(daily_meals.CONFIRMATION_DOCTYPE, daily_name)
            test_daily.status = state
            test_daily.save()
            frappe.set_user(email)
            check("teacher_capability_denied_for_" + state, not overview()["capabilities"]["attendance_write"])
            denied("classroom_attendance_denied_for_" + state, lambda: classroom.save_attendance(own.name, day,
                [{"student": children[0].name, "status": "Present"}], attendance()["revision"]))
            denied("direct_attendance_denied_for_" + state, lambda: daily_meals.save_student_meal_attendance(day,
                [{"student_group": own.name, "student": children[0].name, "status": "Present"}]),
                frappe.ValidationError if state == "已确认" else frappe.PermissionError)
            frappe.db.rollback(save_point=point)
    else:
        denied("diagnostic_teacher_attendance_denial_reproduced", lambda: classroom.save_attendance(own.name, day,
            [{"student": children[0].name, "status": "Present"}], first_revision))
    denied("teacher_cannot_confirm_whole_school", lambda: daily_meals.confirm_daily_meal(day))
    denied("teacher_future_attendance_denied", lambda: classroom.save_attendance(own.name, future_day,
        [{"student": children[0].name, "status": "Present"}], attendance(future_day)["revision"]))

    start_meals = meals()
    check("teacher_meals_start_unknown_not_expected_actual", start_meals["actual"]["breakfast_count"] is None)
    classroom.save_meal(own.name, day, "breakfast", payload(["就餐", "不就餐"]), start_meals["revision"], 1)
    saved = meals()
    check("teacher_confirms_only_selected_meal", saved["actual"]["breakfast_count"] == 1
        and saved["actual"]["lunch_count"] is None and saved["record"]["status"] == "待确认")
    denied("teacher_stale_meal_revision_denied", lambda: classroom.save_meal(own.name, day, "lunch",
        payload(["就餐", "就餐"]), start_meals["revision"], 1), frappe.ValidationError)
    denied("teacher_meal_correction_without_reason_denied", lambda: classroom.save_meal(own.name, day, "breakfast",
        payload(["就餐", "就餐"]), meals()["revision"], 1), frappe.ValidationError)
    classroom.save_meal(own.name, day, "breakfast", payload(["就餐", "就餐"]), meals()["revision"], 1,
        "Synthetic teacher recount")
    check("teacher_meal_correction_with_reason_reads_back", meals()["actual"]["breakfast_count"] == 2
        and meals()["record"]["change_reason"] == "Synthetic teacher recount")
    denied("teacher_future_actual_meal_denied", lambda: classroom.save_meal(own.name, future_day, "breakfast",
        payload(["就餐", "就餐"]), meals(future_day)["revision"], 1), frappe.ValidationError)
    check("meal_save_did_not_fake_unregistered_attendance", attendance()["counts"]["Unknown"] == (1 if attendance_enabled else 2))
    retained.update(class_meal=meals()["record"]["name"],
        daily_meal=frappe.db.get_value(daily_meals.CONFIRMATION_DOCTYPE, {"meal_date": day}, "name"))

    # Simulate an already established session whose account is then disabled.
    frappe.set_user("Administrator")
    frappe.db.set_value("User", email, "enabled", 0)
    frappe.clear_cache(user=email)
    frappe.set_user(email)
    denied("disabled_teacher_cannot_read_attendance", lambda: overview())
    denied("disabled_teacher_cannot_read_meals", lambda: meals())
    denied("disabled_teacher_cannot_save_attendance", lambda: classroom.save_attendance(own.name, day,
        [{"student": children[0].name, "status": "Present"}], first_revision))
    denied("disabled_teacher_cannot_save_meal", lambda: classroom.save_meal(own.name, day, "lunch",
        payload(["就餐", "就餐"]), saved["revision"], 1))
    denied("disabled_teacher_cannot_call_direct_attendance_service", lambda: daily_meals.save_student_meal_attendance(day,
        [{"student_group": own.name, "student": children[0].name, "status": "Present"}]))
    denied("disabled_teacher_cannot_call_direct_meal_save", lambda: student_meals.save_class_meal(day, own.name,
        "lunch", payload(["就餐", "就餐"]), saved["revision"], 1))
    frappe.set_user("Administrator")
    frappe.db.set_value("User", email, "enabled", 1)
    frappe.clear_cache(user=email)
    check("cross_class_and_future_denials_created_no_business_rows",
        not frappe.db.exists("Student Attendance", {"student_group": other.name})
        and not frappe.db.exists(student_meals.DOCTYPE, {"student_group": other.name})
        and not frappe.db.exists("Student Attendance", {"student_group": own.name, "date": future_day})
        and not frappe.db.exists(student_meals.DOCTYPE, {"student_group": own.name, "meal_date": future_day}))
    check("earlier_locked_fixture_and_roster_are_unchanged",
        frappe.get_doc(daily_meals.CONFIRMATION_DOCTYPE, fixture["daily_meal"]).as_json() == old_daily
        and frappe.get_doc("Student Group", fixture["student_group"]).as_json() == old_group
        and frappe.get_doc(student_meals.DOCTYPE, fixture["class_meal"]).as_json() == old_meals)
    frappe.db.commit()
    committed = True
    frappe.destroy()
    connect(email)
    check("new_connection_as_teacher_reads_committed_attendance_and_meals",
        attendance()["counts"]["Absent"] == (1 if attendance_enabled else 0)
        and attendance()["counts"]["Unknown"] == (1 if attendance_enabled else 2)
        and meals()["actual"]["breakfast_count"] == 2 and meals()["actual"]["lunch_count"] is None)
    check("new_connection_remains_teacher_scoped", set(attendance_scope.allowed_groups()) == {own.name}
        and not attendance_scope.is_manager())
    report()
    if gaps:
        raise SystemExit("Teacher lifecycle has reported gaps; this is not a complete acceptance pass")
except Exception as exc:
    report(exc)
    raise
finally:
    if getattr(frappe.local, "db", None):
        frappe.db.rollback()
    frappe.destroy()
