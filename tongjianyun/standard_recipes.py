"""Tongjianyun's approval rules for standard meal BOMs."""
import frappe
from frappe import _
from frappe.utils import cint, flt

MARKER = "custom_tjy_standard_recipe"
CATEGORY = "custom_tjy_recipe_category"
AGE = "custom_tjy_recipe_age"
ALLERGENS = "custom_tjy_recipe_allergens"
METHOD = "custom_tjy_recipe_method"
STATE = "custom_tjy_recipe_state"
NET_QTY = "custom_tjy_recipe_net_qty"

DRAFT, PENDING, PUBLISHED = "草稿", "待审核", "已发布"
APPROVERS = {"Manufacturing Manager", "System Manager", "膳食管理员"}


def validate_recipe(doc, method=None):
    if not doc.get(MARKER):
        return
    if flt(doc.quantity) != 1:
        frappe.throw(_("标准菜品的 BOM 产出数量必须是 1 份。"))
    dish = frappe.db.get_value("Item", doc.item, ["disabled", "is_purchase_item"], as_dict=True)
    if not dish or dish.disabled or dish.is_purchase_item:
        frappe.throw(_("请选择启用的自制菜品作为成品物料。"))
    for row in doc.items:
        net = flt(row.get(NET_QTY))
        if net < 0 or net > flt(row.qty):
            frappe.throw(_("第 {0} 行的可食净量必须在 0 与采购毛用量之间，且使用同一单位。").format(row.idx))


def save_draft(doc, method=None):
    previous = doc.get_doc_before_save()
    was_standard = previous and previous.get(MARKER)
    if not (doc.get(MARKER) or was_standard):
        return
    pending = was_standard and previous.get(STATE) == PENDING
    transition = doc.flags.get("tjy_recipe_review_transition")
    if pending and transition != DRAFT:
        frappe.throw(_("请先撤回审核，再编辑配方。"))
    doc.set(STATE, (transition or DRAFT) if doc.get(MARKER) else None)


@frappe.whitelist(methods=["POST"])
def set_review_pending(name, pending):
    doc = frappe.get_doc("BOM", name, for_update=True)
    doc.check_permission("write")
    if not doc.get(MARKER) or doc.docstatus != 0:
        frappe.throw(_("只能对草稿中的标准菜品执行送审或撤回。"))
    target = PENDING if cint(pending) else DRAFT
    if doc.get(STATE) != target:
        if target == PENDING and not doc.get(CATEGORY):
            frappe.throw(_("请先填写菜品分类。"))
        doc.flags.tjy_recipe_review_transition = target
        doc.save()
    return {"state": doc.get(STATE)}


def publish_recipe(doc, method=None):
    previous = doc.get_doc_before_save()
    previously_standard = previous and previous.get(MARKER)
    if not doc.get(MARKER) and not previously_standard:
        return
    if not (doc.get(MARKER) and previously_standard and previous.get(STATE) == PENDING):
        frappe.throw(_("标准菜品须先送审，再提交发布。"))
    if frappe.session.user != "Administrator" and APPROVERS.isdisjoint(frappe.get_roles()):
        frappe.throw(_("标准菜品须由有 BOM 提交权限的膳食管理员、制造经理或系统管理员发布。"),
                     frappe.PermissionError)
    if not doc.is_active:
        frappe.throw(_("请先启用此配方再发布。"))
    if _recipe_values(doc) != _recipe_values(previous):
        frappe.throw(_("送审后配方内容不能变更。请撤回审核、保存修改后重新送审。"))
    doc.set(STATE, PUBLISHED)


def _recipe_values(doc):
    fields = ("company", "item", "quantity", "uom", CATEGORY, AGE, ALLERGENS, METHOD)
    materials = tuple(
        (row.item_code, flt(row.qty), row.uom, flt(row.conversion_factor), row.bom_no or "", flt(row.get(NET_QTY)))
        for row in doc.items
    )
    return tuple(doc.get(field) or "" for field in fields), materials
