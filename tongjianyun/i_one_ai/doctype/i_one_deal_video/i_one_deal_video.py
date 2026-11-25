from __future__ import annotations

import json

import frappe
from frappe.model.document import Document

from tongjianyun.mcp.video import manifest_from_video_document


class IONEDealVideo(Document):
	def validate(self):
		if not self.scenes:
			return
		manifest = manifest_from_video_document(self)
		self.duration_seconds = manifest["duration_seconds"]
		self.manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)

	@frappe.whitelist()
	def submit_render(self):
		from tongjianyun.deal_video import queue_deal_video_render

		return queue_deal_video_render(self.name, self.quality or "正式")
