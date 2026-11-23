from frappe.model.document import Document


class TongjianyunFoodNutritionProfile(Document):
    def validate(self):
        from tongjianyun.food_nutrition import validate_profile

        validate_profile(self)

    def before_submit(self):
        import frappe
        from frappe.utils import now_datetime

        self.approved_at = now_datetime()
        self.approved_by = frappe.session.user

    def on_update(self):
        from tongjianyun.food_nutrition import sync_status

        sync_status(self.item_code)

    def on_trash(self):
        from tongjianyun.food_nutrition import sync_status

        sync_status(self.item_code, exclude=self.name)

    def before_cancel(self):
        import frappe

        frappe.throw("已审核的营养档案供历史食谱追溯。请新建版本进行更正。")
