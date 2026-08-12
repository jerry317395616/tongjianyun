from __future__ import annotations

import frappe
from frappe.model.document import Document


class TongjianyunGrowthMeasurement(Document):
    def validate(self):
        if self.height_cm and self.weight_kg:
            height_m = float(self.height_cm) / 100
            self.bmi = round(float(self.weight_kg) / (height_m * height_m), 2)
        elif self.bmi:
            self.bmi = None

        if self.bmi_percentile and not 0 <= float(self.bmi_percentile) <= 100:
            frappe.throw("BMI 百分位必须在 0 到 100 之间")
