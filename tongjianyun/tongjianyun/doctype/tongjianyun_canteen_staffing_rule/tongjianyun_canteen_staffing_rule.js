frappe.ui.form.on("Tongjianyun Canteen Staffing Rule", {
	setup(frm) {
		frm.set_query("department", () => ({
			filters: { company: frm.doc.company || "", disabled: 0 },
		}));
		frm.set_query("kitchen_warehouse", () => ({
			filters: { company: frm.doc.company || "", disabled: 0, is_group: 0 },
		}));
	},
});
