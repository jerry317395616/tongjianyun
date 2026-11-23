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
	refresh(frm) {
		if (frm.doctype_layout?.name !== "标准食材档案") return;

		const code = frm.fields_dict.item_code;
		code.df.reqd = 0;
		code.refresh();
		frm.fields_dict.custom_tjy_ingredient_aliases.$input?.attr("rows", 2).css("height", "auto");
		return frappe.require("/assets/tongjianyun/js/ingredient_nutrition.js?v=per-100g.js")
			.then(() => frappe.tjy_ingredient_nutrition(frm));
	},
	item_code(frm) {
		const { doc } = frm;
		if (frm.is_new() && doc.custom_tjy_standard_ingredient && doc.item_code && doc.item_name === doc.item_code) {
			return frm.set_value("item_name", "");
		}
	},
});
