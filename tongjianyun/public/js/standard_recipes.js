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
		frm.add_custom_button("返回菜品库", () => {
			frappe.route_options = { layout: "标准菜品档案", custom_tjy_standard_dish: 1 };
			return frappe.set_route("List", "Item");
		});
		frm.fields_dict.items?.grid.set_column_disp_in_list_view("custom_tjy_recipe_net_qty", true);
		if (!frm.is_new() && frm.doc.docstatus < 2) {
			frm.add_custom_button("每份营养值", async () => {
				if (frm.is_dirty()) return frappe.msgprint("请先保存配方。");
				const recipe = frm.doc.name;
				const {message} = await frappe.call({
					method: "tongjianyun.recipe_nutrition.for_dish", type: "GET",
					args: {recipe}, freeze: true,
				});
				await frappe.require("/assets/tongjianyun/js/nutrition_profiles.js?v=source-reference.js");
				if (cur_frm === frm && frm.doc.name === recipe) frappe.tjy_food_nutrition.dish(message);
			});
		}
		if (frm.doc.docstatus === 1 && frm.doc.is_active && frappe.model.can_create("BOM")) {
			frm.add_custom_button("复制为新版", async () => {
				const { message } = await frappe.call({
					method: "tongjianyun.dish_library.copy_recipe",
					type: "POST",
					args: { dish: frm.doc.item, source: frm.doc.name },
					freeze: true,
				});
				frappe.route_options = { layout: "标准菜品" };
				return frappe.set_route("Form", "BOM", message.recipe);
			});
		}
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
