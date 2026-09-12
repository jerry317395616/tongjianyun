from frappe.model.document import Document
from tongjianyun.health_registration import access, record_name, validate

class TongjianyunStudentHealth(Document):
    def autoname(self):
        self.name = record_name(self.student, self.month)

    def validate(self):
        validate(self)

    def onload(self):
        access()
