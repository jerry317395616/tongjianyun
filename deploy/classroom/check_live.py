"""Read-only live smoke. Prints aggregate counts only; never student names or tokens.

Run: bench/env/bin/python apps/tongjianyun/deploy/classroom/check_live.py
from native-bench. Browser authentication is intentionally not handled here.
"""
import json
import os
from pathlib import Path
import frappe

site = os.environ.get("CLASSROOM_TEST_SITE", "child.myyr.top")
frappe.init(site=site, sites_path=str(Path.cwd() / "sites"))
frappe.connect()
try:
    frappe.set_user("Administrator")
    from tongjianyun.classroom import get_overview
    result = get_overview()
    print(json.dumps({"site":site,"groups":len(result["groups"]),"selected_group":bool(result["group"]),
        "roster_count":result.get("attendance",{}).get("counts",{}).get("total"),
        "attendance_counts":result.get("attendance",{}).get("counts",{}),
        "schedule_count":len(result.get("schedule",{}).get("rows",[])),
        "log_count":len(result.get("logs",{}).get("rows",[])),
        "health_access":result.get("health",{}).get("available"),
        "meal_access":result.get("meals",{}).get("available"),
        "capabilities":result.get("capabilities"),"scene":result["scene"]},ensure_ascii=False,default=str))
    if result["group"]:
        c=result["attendance"]["counts"]
        assert sum(c[k] for k in ["Present","Absent","Leave","Unknown"])==c["total"]
        assert result["scene"]["location_connected"] is False
        again=get_overview(result["group"]["name"],result["day"])
        assert again["attendance"]["revision"]==result["attendance"]["revision"]
        print("PASS: live model, roster partition, deterministic revision, no simulated telemetry")
finally:
    frappe.db.rollback()
    frappe.destroy()
