frappe.ui.form.on("Tongjianyun Nutrition Improvement Plan", {
	setup(frm) {
		frm.set_query("student_batch", "batches", () => ({
			filters: { company: frm.doc.company || "", disabled: 0 },
		}));
		frm.set_query("item_code", "ingredients", () => ({
			filters: { disabled: 0, is_purchase_item: 1 },
		}));
	},
	student_scope(frm) {
		if (frm.doc.student_scope === "全校在册学生") {
			frm.clear_table("batches");
			frm.refresh_field("batches");
		}
	},
});
