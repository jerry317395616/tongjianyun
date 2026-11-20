"""Operator-only activation; change two non-secret settings, no business writes."""
import frappe
import json
from pathlib import Path
from frappe.installer import update_site_config

frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
try:
    users = frappe.conf.get("tongjianyun_shared_harness_users")
    if users is None:
        # The deployed site still uses IONE Core's direct handoff. Seed only
        # accounts already admitted by the private shared authority, not roles.
        authority = json.loads(Path("/home/zyd/frappe/config/harness/authority.json").read_text())
        users = [json.loads(Path(source).read_text())["user"] for source in authority["identity_configs"]]
    assert isinstance(users, list) and users and all(isinstance(user, str) for user in users)
    assert len(set(users)) == len(users)
    assert frappe.conf.get("tongjianyun_shared_harness_enabled") in (None, 1)
    if "Administrator" not in users:
        update_site_config("tongjianyun_shared_harness_users", users + ["Administrator"])
    update_site_config("tongjianyun_harness_administrator_enabled", 1)
    update_site_config("tongjianyun_shared_harness_enabled", 1)
    print("Administrator admission enabled; existing employee list preserved")
finally:
    frappe.destroy()
