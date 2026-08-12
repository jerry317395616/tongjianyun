import frappe
from frappe import _
from frappe.model.document import Document


class TongjianyunRecipe(Document):
    def validate(self):
        if self.week_start and self.week_end and self.week_start > self.week_end:
            frappe.throw(_("结束日期不能早于开始日期。"))
        if self.all_student_groups:
            self.set("applicable_student_groups", [])
        elif not self.applicable_student_groups:
            frappe.throw(_("请选择至少一个适用班级。"))
