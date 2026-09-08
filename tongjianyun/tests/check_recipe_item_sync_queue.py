"""No-write queue acceptance and current account permission preview."""
import json
import time
import uuid
import frappe


def probe(expected_user):
    return {"actor_preserved": frappe.session.user == expected_user,
            "source_available": callable(__import__("tongjianyun.recipe_item_sync", fromlist=["run_sync"]).run_sync)}


def run():
    frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
    frappe.connect()
    job = None
    try:
        preview = {}
        for user in ("Administrator", "317395616@qq.com"):
            if not frappe.db.exists("User", user):
                continue
            frappe.set_user(user)
            preview[user] = {dt + ":" + action: bool(frappe.has_permission(dt, ptype=action))
                for dt, action in (("Item", "read"), ("Item", "create"), ("Item Group", "create"),
                    ("Tongjianyun Food Purchase", "read"), ("Tongjianyun Food Purchase", "create"))}
        frappe.set_user("Administrator")
        job = frappe.enqueue("tongjianyun.tests.check_recipe_item_sync_queue.probe", queue="long", timeout=30,
            expected_user="Administrator", job_id="tjy-sync-probe-" + uuid.uuid4().hex)
        for _ in range(30):
            job.refresh()
            if job.is_finished or job.is_failed:
                break
            time.sleep(1)
        assert job.is_finished
        result = job.return_value()
        assert result == {"actor_preserved": True, "source_available": True}
        print(json.dumps({"passed": True, "queue": "long", "permissions": preview,
                          "worker": result, "business_writes": 0}))
    finally:
        if job and (job.is_finished or job.is_failed):
            job.delete()
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    run()
