frappe.ui.form.on("Item", {
	async onload(frm) {
		const doc = frm.doc;
		if (!frm.is_new() || !doc.custom_tjy_standard_ingredient || doc.item_code?.trim()) return;
		const { message: code } = await frappe.call({
			method: "tongjianyun.ingredient_library.new_ingredient_code",
			type: "GET",
		});
		if (frm.doc === doc && !doc.item_code?.trim()) {
			return frm.set_value("item_code", code);
		}
	},
});
