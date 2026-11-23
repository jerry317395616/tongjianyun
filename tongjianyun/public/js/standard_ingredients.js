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
		const active = frm.doctype_layout?.name === "标准食材档案";
		frm.layout.wrapper.toggleClass("tjy-ingredient-layout", active);
		if (!active) return;

		const fields = frm.fields_dict;
		fields.item_name.$input?.attr("placeholder", "例如番茄");
		fields.custom_tjy_ingredient_aliases.$input?.attr("placeholder", "例如西红柿");
		fields.item_group.$input?.attr("placeholder", "请选择分类");
		fields.stock_uom.$input?.attr("placeholder", "请选择库存单位");
		fields.purchase_uom.$input?.attr("placeholder", "与库存单位一致");
		fields.item_code.$wrapper.toggleClass("tjy-generated-code", /^TJY-AUTO-/.test(frm.doc.item_code || ""));

		for (const [name, icon] of [["profile", "leaf"], ["units", "scale"]]) {
			const heading = fields["custom_tjy_ing_" + name]?.$wrapper.find("h4");
			if (heading?.length && !heading.find("svg").length) {
				heading.prepend(frappe.utils.icon(icon, "sm"));
			}
		}
		return frappe.require("/assets/tongjianyun/css/standard_ingredients.css");
	},
	item_code(frm) {
		const { doc } = frm;
		if (frm.is_new() && doc.custom_tjy_standard_ingredient && doc.item_code && doc.item_name === doc.item_code) {
			return frm.set_value("item_name", "");
		}
	},
});
