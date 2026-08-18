from __future__ import annotations

import frappe
from frappe.model.document import Document


class TongjianyunDailyMealConfirmation(Document):
    def validate(self):
        self._calculate_totals()

    def _calculate_totals(self):
        fields = (
            "enrolled_count",
            "absent_count",
            "leave_count",
            "breakfast_count",
            "morning_snack_count",
            "lunch_count",
            "afternoon_snack_count",
            "dinner_count",
        )
        for fieldname in fields:
            value = sum(int(row.get(fieldname) or 0) for row in self.details)
            self.set(f"total_{fieldname}", value)

    def on_update(self):
        if self.has_value_changed("status") and self.status == "已确认":
            self.confirmed_by = frappe.session.user
            self.confirmed_at = frappe.utils.now_datetime()
            self.db_update()
