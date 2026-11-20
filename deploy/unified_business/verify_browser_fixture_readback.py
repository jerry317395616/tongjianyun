"""Read-only new-connection evidence for the fixed synthetic browser fixture.

Imports the versioned QA guards, never reads credentials, never saves documents,
and records only the selected class/date. A MariaDB read-only transaction adds
an independent guard against an accidental business write in a read helper.
"""
from __future__ import annotations

import json
import uuid

import serve_isolated_browser as qa


DAY = "2026-09-18"
GROUP = "QA Teacher 9680e04d9f Assigned"
MANAGER = "browser-manager-02e16a31d7@example.invalid"
STUDENTS = ("EDU-STU-2026-00012", "EDU-STU-2026-00013")
REASON = "隔离浏览器验收：核对后补录本餐实际就餐"


def nested_lists(value):
    if isinstance(value, list):
        yield value
        for item in value:
            yield from nested_lists(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from nested_lists(item)


def main():
    qa.config_guard()
    fixture = json.loads(qa.safe_target(qa.STATE).read_text())
    assert fixture["owner"] == qa.TASK and fixture["site"] == qa.SITE
    assert (fixture["group"], fixture["day"], fixture["manager"], fixture["meal"]) == (GROUP, DAY, MANAGER, "lunch")
    frappe = qa.connect()
    checks = []
    result = {"site": qa.SITE, "group": GROUP, "day": DAY, "actor": MANAGER,
              "new_connection": True, "read_only_transaction": True,
              "production_writes": False, "business_writes": False,
              "codex_executed": False, "leave_guard_ui": "unverified",
              "leave_guard_note": "Native confirmation blocked CUA tab 13; a new tab completed other checks."
              }

    def check(label, condition):
        checks.append({"check": label, "passed": bool(condition)})

    try:
        frappe.db.sql("START TRANSACTION READ ONLY")
        frappe.set_user(MANAGER)
        from tongjianyun import classroom, daily_meals, student_meals
        group = classroom._scope(GROUP)
        roster = classroom._roster(group)
        check("exact_two_synthetic_students", [row["student"] for row in roster] == list(STUDENTS))
        attendance = classroom._attendance(group, classroom._day(DAY))
        statuses = {row["student"]: row["status"] for row in attendance["students"]}
        check("committed_attendance_present_unknown", statuses == dict(zip(STUDENTS, ("Present", "Unknown"))))
        native_attendance = frappe.get_list("Student Attendance",
            filters={"student_group": GROUP, "date": DAY, "docstatus": ["!=", 2]},
            fields=["name", "student", "status", "docstatus", "owner", "modified_by", "creation", "modified"],
            limit_page_length=0)
        check("only_first_student_has_native_attendance", len(native_attendance) == 1
              and native_attendance[0].student == STUDENTS[0] and native_attendance[0].status == "Present")
        check("attendance_native_actor_is_browser_manager", all(row.owner == MANAGER and row.modified_by == MANAGER
              for row in native_attendance))
        meals = classroom.get_meals(GROUP, DAY)
        record = meals["record"]
        rows = record["students"]
        check("exact_class_meal_record", record["name"] == student_meals.record_name(DAY, GROUP)
              and str(record["meal_date"]) == DAY and record["student_group"] == GROUP
              and {row["student"] for row in rows} == set(STUDENTS))
        check("lunch_saved_and_corrected_to_two_actual", all(row["lunch"] == "已就餐" for row in rows)
              and meals["actual"]["lunch_count"] == 2 and meals["meals"]["lunch"]["complete"])
        other_meals = [meal for meal in student_meals.MEALS if meal != "lunch"]
        check("other_four_meals_remain_unknown", all(row[meal] == "未确认" for row in rows for meal in other_meals)
              and all(meals["actual"][meal + "_count"] is None
                      and not meals["meals"][meal]["complete"] for meal in other_meals))
        check("class_day_not_falsely_confirmed", record["status"] == "待确认"
              and not record.get("confirmed_by") and not record.get("confirmed_at"))
        check("meal_native_actor_is_browser_manager", record["owner"] == MANAGER and record["modified_by"] == MANAGER)
        check("exact_browser_correction_reason_persisted", record.get("change_reason") == REASON)
        baseline = {row["student"]: row for row in daily_meals.calculate_student_details(DAY, GROUP)}
        check("expected_fields_match_original_planning_rule", all(
              row[meal + "_expected"] == baseline[row["student"]][meal]
              for row in rows for meal in student_meals.MEALS))
        check("both_lunch_expected_remain_true", all(row["lunch_expected"] == 1 for row in rows)
              and meals["expected"]["lunch_count"] == 2)
        daily = frappe.db.get_value(daily_meals.CONFIRMATION_DOCTYPE, {"meal_date": DAY},
              ["name", "meal_date", "status", "confirmed_by", "confirmed_at"], as_dict=True)
        check("daily_aggregate_remains_unconfirmed", daily and daily.status == "待确认"
              and not daily.confirmed_by and not daily.confirmed_at)
        versions = frappe.get_list("Version", filters={"ref_doctype": student_meals.DOCTYPE, "docname": record["name"]},
              fields=["name", "owner", "creation", "data"], order_by="creation asc", limit_page_length=0)
        version_evidence = [{"name": row.name, "owner": row.owner, "creation": row.creation,
                             "data": json.loads(row.data)} for row in versions]
        diffs = [entry for row in version_evidence for entry in nested_lists(row["data"])
                 if len(entry) >= 3 and isinstance(entry[0], str)]
        check("version_retains_lunch_not_eaten_to_eaten_correction", any(
              entry[:3] == ["lunch", "未就餐", "已就餐"] for entry in diffs))
        check("version_retains_exact_reason", any(entry[0] == "change_reason" and entry[-1] == REASON for entry in diffs))
        check("version_does_not_change_expected_fields", bool(version_evidence)
              and not any(entry[0] in {meal + "_expected" for meal in student_meals.MEALS} for entry in diffs))
        check("version_actor_is_browser_manager", bool(version_evidence) and all(row["owner"] == MANAGER for row in version_evidence))
        comments = frappe.get_list("Comment", filters={"reference_doctype": student_meals.DOCTYPE,
              "reference_name": record["name"], "comment_type": "Info"},
              fields=["name", "owner", "comment_email", "creation", "content"], order_by="creation asc", limit_page_length=0)
        markers = [dict(row) for row in comments if "午餐实际就餐已按班级名单核对" in (row.content or "")]
        check("two_native_meal_audit_markers_persisted", len(markers) == 2 and all(
              row["owner"] == MANAGER and row["comment_email"] == MANAGER for row in markers))
        result.update(attendance={"statuses": statuses, "revision": attendance["revision"], "native_records": native_attendance},
            meal={"name": record["name"], "status": record["status"], "revision": meals["revision"],
                  "change_reason": record.get("change_reason"), "expected": meals["expected"], "actual": meals["actual"],
                  "students": [{"student": row["student"], **{key: row[key] for meal in student_meals.MEALS
                              for key in (meal, meal + "_expected")}} for row in rows]},
            daily=daily, versions=version_evidence, audit_markers=markers,
            expected_evidence_limit="No independent pre-save DB snapshot; initial browser observed both expected=true. Current original rule and persisted Version diffs checked.")
    finally:
        frappe.db.rollback()
        frappe.destroy()
    result.update(checks=checks, passed=sum(row["passed"] for row in checks), total=len(checks),
                  status="passed" if checks and all(row["passed"] for row in checks) else "failed")
    output = qa.ROOT / ("browser-readback-" + uuid.uuid4().hex[:10] + ".json")
    qa.private_json(output, json.loads(json.dumps(result, ensure_ascii=False, default=str)))
    print(json.dumps({"evidence_file": str(output), "status": result["status"], "passed": result["passed"],
          "total": result["total"], "checks": checks, "production_writes": False,
          "codex_executed": False, "leave_guard_ui": "unverified"}, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
