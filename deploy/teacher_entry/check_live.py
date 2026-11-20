"""Actual hook registration and teacher scope checks, with rollback-only reads."""
import json
import os
from pathlib import Path
import sys
import frappe

if os.environ.get("TEACHER_ENTRY_SOURCE"):
    sys.path.insert(0, os.environ["TEACHER_ENTRY_SOURCE"])
frappe.init(site=os.environ.get("CLASSROOM_TEST_SITE", "child.myyr.top"), sites_path=str(Path.cwd()/"sites"))
frappe.connect()
try:
    frappe.set_user("Administrator")
    from frappe.apps import get_apps
    from tongjianyun import workspace_entry as entry, classroom
    registered = [a for a in get_apps() if a["name"] == "tongjianyun"]
    assert len(registered) == 1 and registered[0]["route"] == entry.ENTRY
    from frappe.website.page_renderers.template_page import TemplatePage
    renderer = TemplatePage("tongjianyun-entry")
    renderer.set_pymodule()
    assert renderer.pymodule_name == "tongjianyun.www.tongjianyun_entry"
    users = frappe.get_all("User", filters={"enabled":1,"user_type":"System User","name":["not in",["Guest","Administrator"]]}, pluck="name")
    checked, rejected = 0, 0
    for user in users:
        frappe.set_user(user)
        model = entry.entry_model()
        teacher = next((p for p in model["profiles"] if p["id"] == "teacher"), None)
        if not teacher or not teacher["enabled"]:
            continue
        names = {g["name"] for g in model["groups"]}
        result = classroom.get_overview(workspace="teacher")
        assert result["workspace"] == "teacher" and {g["name"] for g in result["groups"]} == names
        assert result["group"]["name"] in names
        counts = result["attendance"]["counts"]
        assert sum(counts[s] for s in ("Present","Absent","Leave","Unknown")) == counts["total"]
        try:
            classroom.get_overview("ENTRY-NON-ASSIGNED-CHECK",workspace="teacher")
        except frappe.PermissionError:
            rejected += 1
        else:
            raise AssertionError("Non-assigned group accepted")
        checked += 1
    print(json.dumps({"native_app_icon_route":registered[0]["route"],"native_template_controller":renderer.pymodule_name,
        "assigned_teacher_accounts_checked":checked,"nonassigned_group_rejections":rejected,"business_rows_written":0},ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
