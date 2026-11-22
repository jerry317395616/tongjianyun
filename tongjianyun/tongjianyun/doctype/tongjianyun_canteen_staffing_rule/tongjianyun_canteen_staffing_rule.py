from frappe.model.document import Document

from tongjianyun.canteen_staffing import activate_rule, validate_rule


class TongjianyunCanteenStaffingRule(Document):
    def validate(self):
        validate_rule(self)

    def before_submit(self):
        activate_rule(self)
