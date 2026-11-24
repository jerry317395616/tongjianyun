"""Install the native, module-scoped Desk home block without disturbing other blocks."""
import json
from pathlib import Path

import frappe


MODULE = "膳食与食堂"
BLOCK = "童健云食堂工作台"


def install():
    assets = Path(__file__).resolve().parents[1] / "public"
    values = {
        "private": 0,
        "html": '<main class="tjy-food-home" aria-label="食堂工作台"><p role="status">正在加载供餐安排…</p></main>',
        "style": (assets / "css/meal_home.css").read_text(encoding="utf-8"),
        "script": (assets / "js/meal_home.js").read_text(encoding="utf-8"),
    }
    block = frappe.get_doc("Custom HTML Block", BLOCK) if frappe.db.exists("Custom HTML Block", BLOCK) else None
    if not block:
        frappe.get_doc({"doctype": "Custom HTML Block", **values}).insert(set_name=BLOCK)
    elif any(block.get(k) != value for k, value in values.items()):
        block.update(values).save()
    workspace = frappe.get_doc("Workspace", MODULE) if frappe.db.exists("Workspace", MODULE) else frappe.get_doc(
        {"doctype": "Workspace", "label": MODULE, "title": MODULE, "module": MODULE, "public": 1, "content": "[]"})
    content = json.loads(workspace.content or "[]")
    original = list(content)
    if len(content) == 2 and content[0].get("data", {}).get("text") == f"Welcome to the {MODULE} workspace" and (
            content[1].get("data", {}).get("text") in ("Click on the ⋯ menu to edit", "Click on the ⋮ menu to edit")):
        content = []
    if not any(b.get("type") == "custom_block" and b.get("data", {}).get("custom_block_name") == BLOCK for b in content):
        content.insert(0, {"id": "tjymealhome", "type": "custom_block", "data": {"custom_block_name": BLOCK, "col": 12}})
    missing = not any(b.custom_block_name == BLOCK for b in workspace.custom_blocks)
    if missing:
        workspace.append("custom_blocks", {"custom_block_name": BLOCK, "label": BLOCK})
    if missing or content != original:
        workspace.content = json.dumps(content, ensure_ascii=False)
        workspace.save()
    frappe.clear_document_cache("Workspace", MODULE)
    frappe.clear_document_cache("Custom HTML Block", BLOCK)
