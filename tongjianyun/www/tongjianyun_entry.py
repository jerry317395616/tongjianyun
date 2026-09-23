"""Application-icon gateway. Server decisions, no client actor/role parameters."""
from urllib.parse import urlencode

import frappe
from tongjianyun import workspace_entry as entry

no_cache = 1
sitemap = 0


def get_context(context):
    entry.mark_private_response()
    if frappe.session.user == "Guest":
        entry.temporary_redirect("/login?" + urlencode({"redirect-to": entry.ENTRY}))
    model = entry.entry_model()
    args = frappe.form_dict
    # Forced chooser has precedence only when no explicit identity was selected.
    choose = str(args.get("choose") or "") == "1"
    profile = args.get("profile")
    result = entry.resolve_entry(model, profile, args.get("class"), choose)
    if choose and not profile and not args.get("class") and len(model["profiles"]) > 1:
        result = {"destination": None, "view": "profiles", "profile": None}
    if result["destination"]:
        entry.temporary_redirect(result["destination"])
    context.no_cache = 1
    context.title = "我的工作空间 · 童健云"
    context.entry = {**model, **result}
    for row in context.entry["profiles"]:
        row["url"] = entry.ENTRY + "?" + urlencode({"profile": row["id"]})
    for row in context.entry["groups"]:
        row["url"] = entry.ENTRY + "?" + urlencode({"profile": "teacher", "class": row["name"]})
