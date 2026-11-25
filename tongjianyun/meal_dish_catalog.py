"""Native Item meal applicability and safe adoption of existing standard dishes."""

import re
from collections import Counter
from unicodedata import normalize

import frappe

from tongjianyun.meal_planning import SLOT_FIELDS, SLOTS

SECTION = "custom_meal_slot_section"
INITIAL_CLASSIFICATION = "tongjianyun.meal_dish_catalog.initial_classification"
COMBINATION = re.compile(r"^(" + "|".join(SLOTS) + r")组合\s*[:\uFF1A]\s*(.+)$")


def install_meal_slot_fields(dish_marker, insert_after):
	frappe.only_for("System Manager")
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	fields = [{
		"fieldname": SECTION, "label": "适用餐次", "fieldtype": "Section Break",
		"insert_after": insert_after, "depends_on": f"eval:doc.{dish_marker}",
		"description": "可同时选择多个餐次。未设置时可用于所有餐次。",
	}]
	last = SECTION
	for slot, fieldname in SLOT_FIELDS.items():
		fields.append({"fieldname": fieldname, "label": slot, "fieldtype": "Check",
			"insert_after": last, "default": "0"})
		last = fieldname
	create_custom_fields({"Item": fields})


def _name_key(label):
	return " ".join(normalize("NFKC", label or "").casefold().split())


def catalog_changes(dishes, used_slots, all_names):
	"""Compute changes using Item codes, current display names and recorded meal slots."""
	updates = {}
	proposed = {}
	for dish in dishes:
		code = dish["name"]
		slots = used_slots.get(code, set())
		if slots and not any(dish.get(field) for field in SLOT_FIELDS.values()):
			updates[code] = {field: 1 for slot, field in SLOT_FIELDS.items() if slot in slots}
		name = dish.get("item_name") or ""
		match = COMBINATION.fullmatch(name.strip())
		if match and match.group(1) in slots:
			label = " ".join(match.group(2).split())
			if label:
				proposed[code] = label
	counts = Counter(_name_key(label) for label in proposed.values())
	occupied = {_name_key(label) for label in all_names}
	for code, label in proposed.items():
		key = _name_key(label)
		if counts[key] == 1 and key not in occupied:
			updates.setdefault(code, {})["item_name"] = label
	return updates


def _has_meal_history():
	return all(frappe.db.has_column("Production Plan", key) for key in ("custom_is_meal_plan", "custom_meal_type"))


def planned_catalog_changes(dish_marker):
	if not _has_meal_history():
		return {}
	fields = ["name", "item_name", *(
		field for field in SLOT_FIELDS.values() if frappe.db.has_column("Item", field)
	)]
	dishes = frappe.get_all("Item", filters={dish_marker: 1}, fields=fields)
	meal_uses = frappe.db.sql("""
		SELECT DISTINCT line.item_code, plan.custom_meal_type
		FROM `tabProduction Plan Item` AS line
		INNER JOIN `tabProduction Plan` AS plan ON plan.name = line.parent
		INNER JOIN `tabBOM` AS bom ON bom.name = line.bom_no AND bom.item = line.item_code
		WHERE plan.custom_is_meal_plan = 1 AND plan.docstatus < 2
	""")
	used_slots = {}
	for item, slot in meal_uses:
		if slot in SLOTS:
			used_slots.setdefault(item, set()).add(slot)
	return catalog_changes(dishes, used_slots, frappe.get_all("Item", pluck="item_name"))


def classify_existing_dishes(dish_marker):
	frappe.only_for("System Manager")
	if not _has_meal_history() or frappe.db.exists("Patch Log", {"patch": INITIAL_CLASSIFICATION, "skipped": 0}):
		return
	changes = planned_catalog_changes(dish_marker)
	for item, values in changes.items():
		frappe.db.set_value("Item", item, values, update_modified=False)
	from frappe.modules.patch_handler import update_patch_log

	update_patch_log(INITIAL_CLASSIFICATION)
