"""Read-only classification acceptance; prints no source records or credentials."""
import json
import frappe
from tongjianyun.ingredient_classification import preview_recipe

frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
frappe.connect()
try:
    frappe.set_user("Administrator")
    before = {dt: frappe.db.count(dt) for dt in ("Item", "Item Group")}
    recipe = frappe.get_list("Tongjianyun Recipe", filters={"is_deleted": 0},
        pluck="name", order_by="modified desc", limit_page_length=1)[0]
    result = preview_recipe(recipe)
    assert result["read_only"]
    summary = {action: sum(row["action"] == action for row in result["rows"])
               for action in ("existing", "new", "review")}
    after = {dt: frappe.db.count(dt) for dt in before}
    assert before == after
    frappe.set_user("Guest")
    try:
        preview_recipe(recipe)
        raise AssertionError("Guest was not rejected")
    except frappe.PermissionError:
        pass
    print(json.dumps({"passed": True, "ingredients": len(result["rows"]),
        "actions": summary, "guest_denied": True, "business_writes": 0, "counts": after}))
except Exception as error:
    print(json.dumps({"passed": False, "error_type": type(error).__name__}))
    raise SystemExit(1)
finally:
    frappe.db.rollback()
    frappe.destroy()
