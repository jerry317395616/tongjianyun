import frappe
from frappe.model.document import Document


class TongjianyunSpecialIngredientBasis(Document):
    def validate(self):
        previous = self.get_doc_before_save()
        if not self.flags.special_ingredients_service or (previous and previous.approved):
            frappe.throw("专项归属依据由供餐审核流程维护。", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("专项归属依据须保留用于历史追溯。", frappe.PermissionError)
