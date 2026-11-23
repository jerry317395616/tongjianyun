frappe.ui.form.on("Item", {
	async onload(frm) {
		const doc = frm.doc;
		if (!frm.is_new() || !doc.custom_tjy_standard_ingredient || doc.item_code?.trim()) return;
		const { message: code } = await frappe.call({
			method: "tongjianyun.ingredient_library.new_ingredient_code",
			type: "GET",
		});
		if (frm.doc === doc && !doc.item_code?.trim()) {
			// The native Item Code change event uses the code as a default Item Name.
			doc.item_code = code;
			frm.refresh_field("item_code");
		}
	},
	item_code(frm) {
		const { doc } = frm;
		if (frm.is_new() && doc.custom_tjy_standard_ingredient && doc.item_code && doc.item_name === doc.item_code) {
			return frm.set_value("item_name", "");
		}
	},
});
