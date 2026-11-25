from __future__ import annotations


def ensure_deal_video_field() -> bool:
	import frappe

	if not frappe.db.exists("DocType", "CRM Deal"):
		return False
	if not frappe.db.exists("DocType", "I-ONE Deal Video"):
		return False

	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"CRM Deal": [
				{
					"fieldname": "custom_customer_video",
					"label": "客户宣传视频",
					"fieldtype": "Link",
					"options": "I-ONE Deal Video",
					"read_only": 1,
					"no_copy": 1,
					"description": "由 I-ONE Agent 根据商机资料生成的客户宣传视频",
				}
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="CRM Deal")
	return True
