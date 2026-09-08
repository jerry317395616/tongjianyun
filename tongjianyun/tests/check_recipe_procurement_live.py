"""Explicit opt-in rollback-only integration check on the configured site."""
import json
import uuid

import frappe
from frappe.utils import add_days, nowdate
from tongjianyun import recipe_procurement as service
from tongjianyun import ingredient_resolution as resolution


def run():
    prefix = "T-JY-ERP-" + uuid.uuid4().hex[:12]
    frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
    frappe.connect()
    frappe.set_user("Administrator")
    names = []
    try:
        company = frappe.get_list("Company", pluck="name", limit_page_length=1)[0]
        warehouse = frappe.get_list("Warehouse", filters={"company": company, "is_group": 0, "disabled": 0}, pluck="name", limit_page_length=1)[0]
        group = frappe.get_list("Item Group", filters={"is_group": 0}, pluck="name", limit_page_length=1)[0]
        item = frappe.get_doc({"doctype": "Item", "item_code": prefix + "-ITEM", "item_name": prefix + "-ITEM",
            "item_group": group, "stock_uom": "Gram", "is_stock_item": 1, "is_purchase_item": 1, "is_sales_item": 0}).insert()
        names.append(("Item", item.name))
        date = add_days(nowdate(), 7)
        recipe = frappe.get_doc({"doctype": service.RECIPE, "recipe_id": prefix, "title": "ROLLBACK ONLY ERP integration check",
            "workflow_status": "已发布", "week_start": date, "week_end": date}).insert()
        names.append((service.RECIPE, recipe.name))
        dish = frappe.get_doc({"doctype": "Tongjianyun Recipe Dish", "dish_row_id": prefix + "-D", "recipe": recipe.name,
            "day_id": prefix + "-DAY", "meal_date": date, "meal_slot": "lunch", "dish_name": "ROLLBACK ONLY"}).insert()
        names.append((dish.doctype, dish.name))
        ingredient = frappe.get_doc({"doctype": "Tongjianyun Recipe Ingredient", "ingredient_row_id": prefix + "-I",
            "recipe": recipe.name, "recipe_dish": dish.name, "ingredient_name": item.item_name, "amount": 50, "unit": item.stock_uom}).insert()
        names.append((ingredient.doctype, ingredient.name))
        prepared = service.prepare(recipe.name, company)
        key = prepared["ingredients"][0]["key"]
        args = dict(recipe=recipe.name, company=company, warehouse=warehouse,
                    mappings={key: {"item_code": item.name, "uom": item.stock_uom, "factor": 1}},
                    meals={str(date) + ":lunch": 10})
        plan = service.preview(**args)
        assert plan["lines"][0]["qty"] == 500
        result = service.create_request(**args, token=plan["token"], confirmed=1)
        names.append(("Material Request", result["name"]))
        trace_key = service.KIND + "::" + service.digest([recipe.name, company])[:32]
        names.append((service.TRACE, trace_key))
        mr = frappe.get_doc("Material Request", result["name"])
        assert mr.docstatus == 0 and mr.material_request_type == "Purchase"
        assert mr.items[0].qty == 500
        assert service.create_request(**args, token=plan["token"], confirmed=1)["existing"]
        try:
            service.create_request(**args, token="stale", confirmed=1)
            raise AssertionError("stale preview accepted")
        except frappe.ValidationError:
            pass
        remembered = service.prepare(recipe.name, company)
        assert remembered["ingredients"][0]["basis"] == "历史确认"
        extra = frappe.get_doc({"doctype": "Tongjianyun Recipe Ingredient", "ingredient_row_id": prefix + "-I2",
            "recipe": recipe.name, "recipe_dish": dish.name, "ingredient_name": prefix + "-NEW", "amount": 10, "unit": "g"}).insert()
        names.append((extra.doctype, extra.name))
        extra_key = service.digest([extra.ingredient_name, "g"])[:24]
        decisions = [{"key": extra_key, "action": "新建物料", "uom": "g", "factor": 1}]
        resolve_args = dict(recipe=recipe.name, company=company, decisions=decisions, default_group=group)
        resolution_plan = resolution.preview_resolution(**resolve_args)
        assert not frappe.db.exists("Item", resolution_plan["rows"][0]["item_code"])
        for confirmed, token in ((0, resolution_plan["token"]), (1, "stale")):
            try:
                resolution.apply_resolution(**resolve_args, token=token, confirmed=confirmed)
                raise AssertionError("invalid confirmation accepted")
            except frappe.ValidationError:
                pass
        resolved = resolution.apply_resolution(**resolve_args, token=resolution_plan["token"], confirmed=1)
        assert len(resolved["created"]) == 1
        names.append(("Item", resolved["created"][0]))
        receipt_key = resolution.MAPPING_KIND + "::" + service.digest([recipe.name, company, resolution_plan["token"]])[:32]
        names.append((service.TRACE, receipt_key))
        assert resolution.apply_resolution(**resolve_args, token=resolution_plan["token"], confirmed=1)["existing"]
        assert next(r for r in service.prepare(recipe.name, company)["ingredients"] if r["key"] == extra_key)["item_code"] == resolved["created"][0]
        try:
            resolution.preview_resolution(**resolve_args)
            raise AssertionError("duplicate name accepted")
        except frappe.ValidationError:
            pass
        extra.ingredient_name = prefix + "-汤"
        extra.save()
        soup_key = service.digest([extra.ingredient_name, "g"])[:24]
        try:
            resolution.preview_resolution(recipe.name, company,
                [{"key": soup_key, "action": "新建物料", "uom": "g", "factor": 1}], group)
            raise AssertionError("self-made soup accepted without review")
        except frappe.ValidationError:
            pass
        frappe.set_user("Guest")
        try:
            resolution.preview_resolution(**resolve_args)
            raise AssertionError("Guest resolution accepted")
        except frappe.PermissionError:
            pass
        try:
            service.preview(**args)
            raise AssertionError("Guest accepted")
        except frappe.PermissionError:
            pass
        print(json.dumps({"passed": ["live source matching", "demand preview", "standard ERP draft insert",
            "idempotent retry", "stale preview rejection", "mapping reuse", "Guest denied",
            "resolution preview read-only", "resolution confirmation required", "batch Item creation",
            "resolution retry", "resolution mapping reuse", "duplicate name rejection", "self-made soup guard",
            "Guest resolution denied"], "draft_submitted": False}))
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")
        remaining = [(dt, name) for dt, name in names if frappe.db.exists(dt, name)]
        print(json.dumps({"rollback_verified": not remaining, "temporary_records": len(names)}))
        frappe.destroy()
        if remaining:
            raise AssertionError("Rollback left records")


if __name__ == "__main__":
    run()
