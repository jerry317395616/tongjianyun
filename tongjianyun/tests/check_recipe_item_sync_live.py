"""Explicit rollback-only ORM acceptance; deterministic AI fixture, no model cost."""
import json
import uuid
from unittest.mock import patch
import frappe
from tongjianyun import recipe_item_sync as service
from tongjianyun import recipe_procurement
from tongjianyun.recipe_storage import _recipe_business_links


def run():
    frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
    frappe.connect()
    frappe.set_user("Administrator")
    prefix = "TJY-SYNC-" + uuid.uuid4().hex[:8]
    baseline = {dt: frappe.db.count(dt) for dt in ("Item", "Item Group", service.TRACE)}
    try:
        root = frappe.get_list("Item Group", filters={"is_group": 1}, pluck="name", limit_page_length=1)[0]
        existing_group = frappe.get_list("Item Group", filters={"is_group": 0}, pluck="name", limit_page_length=1)[0]
        recipe = frappe.get_doc({"doctype": "Tongjianyun Recipe", "recipe_id": prefix,
            "title": prefix, "workflow_status": "草稿", "week_start": "2099-01-05", "week_end": "2099-01-05"}).insert()
        dish = frappe.get_doc({"doctype": "Tongjianyun Recipe Dish", "dish_row_id": prefix + "-D",
            "recipe": recipe.name, "day_id": prefix, "meal_date": "2099-01-05", "meal_slot": "lunch", "dish_name": prefix}).insert()
        rows = []
        for index, (name, unit) in enumerate(((prefix + "-rice", "g"), (prefix + "-汤", "ml"), (prefix + "-bad", "不存在单位"))):
            rows.append(frappe.get_doc({"doctype": service.INGREDIENT, "ingredient_row_id": prefix + str(index),
                "recipe": recipe.name, "recipe_dish": dish.name, "ingredient_name": name,
                "amount": 10, "unit": unit}).insert())
        snapshot = service.source_snapshot(recipe.name)
        plan = {**snapshot, "groups": [{"name": root, "is_group": 1}, {"name": existing_group, "is_group": 0}],
            "classification_failed": False, "proposals": []}
        for row in snapshot["ingredients"]:
            action = "review" if "汤" in row["ingredient"] else "new"
            plan["proposals"].append({"key": row["key"], "action": action,
                "group": "" if action == "review" else prefix + "-group", "parent": "" if action == "review" else root,
                "reason": "Deterministic rollback test"})
        result = service.apply_plan(plan)
        assert result["status"] == "partial"
        assert len(result["created_items"]) == 1 and len(result["created_groups"]) == 1
        assert len(result["unresolved"]) == 2 and len(result["mappings"]) == 1
        item = frappe.get_doc("Item", result["created_items"][0])
        assert item.item_name == prefix + "-rice" and item.stock_uom == "g"
        assert not any(link["doctype"] == service.TRACE for link in _recipe_business_links(recipe))
        retry = service.apply_plan(plan)
        assert not retry["created_items"] and not retry["created_groups"]
        assert retry["mappings"] == result["mappings"]
        recipe.workflow_status = "已发布"
        recipe.save()
        company = frappe.get_list("Company", pluck="name", limit_page_length=1)[0]
        prepared = recipe_procurement.prepare(recipe.name, company)
        matched = next(row for row in prepared["ingredients"] if row["ingredient"] == item.item_name)
        assert matched["item_code"] == item.name and matched["basis"] == "自动匹配，需核对毛料系数"
        rows[0].ingredient_name = prefix + "-changed"
        rows[0].save()
        try:
            service.apply_plan(plan)
            raise AssertionError("stale accepted")
        except frappe.ValidationError:
            pass
        # Revoked create permission blocks new Items, even for a previously generated plan.
        fresh = service.source_snapshot(recipe.name)
        fresh_plan = {**plan, **fresh, "proposals": [{"key": row["key"], "action": "existing",
            "group": existing_group, "parent": "", "reason": "Test"} for row in fresh["ingredients"]]}
        original_permission = service._permission
        def deny_create(dt, action):
            if dt == "Item" and action == "create":
                raise frappe.PermissionError()
            return original_permission(dt, action)
        with patch.object(service, "_permission", side_effect=deny_create):
            denied = service.apply_plan(fresh_plan)
            assert not denied["created_items"]
        frappe.set_user("Guest")
        try:
            service.apply_plan(plan)
            raise AssertionError("guest accepted")
        except frappe.PermissionError:
            pass
        print(json.dumps({"passed": True, "checks": ["draft recipe", "standard Item Group and Item insert",
            "unit failure isolated", "soup blocked", "repeat idempotent", "auto mapping reused",
            "auto receipt not execution link", "stale rejected", "create permission rechecked", "guest denied"]}))
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")
        after = {dt: frappe.db.count(dt) for dt in baseline}
        assert after == baseline
        assert not frappe.db.exists("Tongjianyun Recipe", {"recipe_id": prefix})
        print(json.dumps({"rollback_verified": True, "counts": after}))
        frappe.destroy()


if __name__ == "__main__":
    run()
