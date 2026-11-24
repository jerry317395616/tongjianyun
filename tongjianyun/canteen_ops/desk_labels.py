"""Permission-aware display names for the meal desk. All document references stay unchanged."""
import frappe
from frappe.model import get_permitted_fields

TITLE_FIELDS = {
    "Tongjianyun Canteen": "canteen_name",
    "Tongjianyun Meal Term Project": "project_title",
    "Meal Planning Week": "title",
    "Item": "item_name",
    "BOM": "item_name",
    "Employee": "employee_name",
    "Student": "student_name",
    "Student Batch Name": "batch_name",
    "Supplier": "supplier_name",
    "Warehouse": "warehouse_name",
    "Account": "account_name",
    "Project": "project_name",
    "User": "full_name",
    "Task": "subject",
}


def lookup_labels(references):
    labels = {}
    for doctype, names in references.items():
        field = TITLE_FIELDS.get(doctype)
        if not field or not names or not frappe.has_permission(doctype, "read"):
            continue
        if field not in get_permitted_fields(doctype, ignore_virtual=True):
            continue
        keys = sorted(set(names))
        found = {}
        for offset in range(0, len(keys), 250):
            batch = keys[offset:offset + 250]
            for row in frappe.get_list(doctype, filters={"name": ["in", batch]},
                                       fields=["name", field], limit_page_length=len(batch)):
                title = row.get(field)
                if title and title != row.name:
                    found[row.name] = title
        if found:
            labels[doctype] = found
    return labels


@frappe.whitelist(methods=["POST"])
def link_labels(references):
    references = frappe.parse_json(references)
    if (not isinstance(references, dict) or set(references) - TITLE_FIELDS.keys()
            or any(not isinstance(names, list) or any(not isinstance(key, str) or len(key) > 140 for key in names)
                   for names in references.values())
            or sum(map(len, references.values())) > 500):
        frappe.throw("关联名称查询参数无效。")
    return lookup_labels(references)


def report_labels(result):
    """Attach labels to rows of the current result without changing amounts, links, filters or exports."""
    columns, rows = result[:2]
    links = [c for c in columns if isinstance(c, dict) and not c.get("hidden")
             and c.get("fieldtype") in ("Link", "Dynamic Link")]
    refs = {}
    for row in rows:
        for col in links:
            field = col["fieldname"]
            target = row.get(col.get("options")) if col["fieldtype"] == "Dynamic Link" else col.get("options")
            value = row.get(field)
            if target in TITLE_FIELDS and value:
                refs.setdefault(target, set()).add(value)
    names = lookup_labels(refs)
    for row in rows:
        for col in links:
            field = col["fieldname"]
            target = row.get(col.get("options")) if col["fieldtype"] == "Dynamic Link" else col.get("options")
            label = names.get(target, {}).get(row.get(field))
            if label:
                row.setdefault("_meal_labels", {})[field] = label
    return result
