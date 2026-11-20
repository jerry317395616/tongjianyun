"""Read-only linkage audit. Prints aggregate counts, never identity or pupils."""
import json
import os
from pathlib import Path
import sys
import frappe

source = os.environ.get("TEACHER_ENTRY_SOURCE")
if source:
    sys.path.insert(0, source)
frappe.init(site=os.environ.get("CLASSROOM_TEST_SITE", "child.myyr.top"), sites_path=str(Path.cwd()/"sites"))
frappe.connect()
try:
    frappe.set_user("Administrator")
    from tongjianyun.workspace_entry import entry_model
    users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User", "name": ["not in", ["Guest", "Administrator"]]}, pluck="name")
    # No promotion/assignment; audit current internal accounts only.
    totals = {"enabled_internal_accounts": len(users), "teacher_with_one_class": 0,
              "teacher_with_multiple_classes": 0, "teacher_needs_setup": 0,
              "multiple_work_entries": 0, "business_only": 0, "no_entry": 0}
    for user in users:
        frappe.set_user(user)
        result = entry_model()
        teacher = next((p for p in result["profiles"] if p["id"] == "teacher"), None)
        if teacher:
            n = teacher["class_count"]
            totals["teacher_with_one_class" if n == 1 else "teacher_with_multiple_classes" if n > 1 else "teacher_needs_setup"] += 1
        elif result["profiles"]:
            totals["business_only"] += 1
        else:
            totals["no_entry"] += 1
        totals["multiple_work_entries"] += int(len(result["profiles"]) > 1)
    print(json.dumps(totals, ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
