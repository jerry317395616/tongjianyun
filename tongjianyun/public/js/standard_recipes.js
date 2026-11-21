frappe.ui.form.on("BOM", {
	onload(frm) {
		const layout = new URLSearchParams(window.location.search).get("layout");
		if (frm.is_new() && (layout === "标准菜品" || frappe.router.doctype_layout === "标准菜品")) {
			return frm.set_value("custom_tjy_standard_recipe", 1);
		}
	},
	refresh(frm) {
		if (!frm.doc.custom_tjy_standard_recipe) {
			return;
		}
		frm.add_custom_button("返回菜品库", () => frappe.set_route("standard-dish-library"));
		frm.fields_dict.items?.grid.set_column_disp_in_list_view("custom_tjy_recipe_net_qty", true);
		if (frm.is_new() || frm.doc.docstatus !== 0) {
			return;
		}
		const pending = frm.doc.custom_tjy_recipe_state === "待审核";
		const label = pending ? __("撤回审核") : __("提交审核");
		if (frm.perm?.[0]?.write) {
			frm.add_custom_button(label, () => {
				if (frm.is_dirty()) {
					frappe.msgprint(__("请先保存配方。"));
					return;
				}
				frappe.call({
					method: "tongjianyun.standard_recipes.set_review_pending",
					args: { name: frm.doc.name, pending: pending ? 0 : 1 },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			});
		}
	},
});
