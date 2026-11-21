(() => {
	const dishLayout = "标准菜品档案";
	const recipeLayout = "标准菜品";
	const reuseLabel = "使用同名菜品";

	function addRecipe(dish) {
		return frappe.model.with_doctype("BOM", () => {
			const doc = frappe.model.get_new_doc("BOM", null, null, true);
			doc.item = dish.name;
			doc.quantity = 1;
			doc.custom_tjy_standard_recipe = 1;
			doc.custom_tjy_recipe_category = dish.custom_tjy_dish_category || "";
			frappe.route_options = { layout: recipeLayout };
			return frappe.set_route("Form", "BOM", doc.name);
		});
	}

	async function reuseDish(frm, label, existing) {
		const category = frm.doc.custom_tjy_dish_category;
		if (!category) {
			frappe.msgprint("请先填写菜品分类。");
			return;
		}
		const { message } = await frappe.call({
			method: "tongjianyun.dish_library.save_dish",
			type: "POST",
			args: { label, category, existing },
		});
		frm.doc.__unsaved = 0;
		frappe.route_options = { layout: dishLayout };
		return frappe.set_route("Form", "Item", message.dish);
	}

	frappe.ui.form.on("Item", {
		refresh(frm) {
			if (!frm.doc.custom_tjy_standard_dish) return;
			frm.set_df_property("item_name", "description", "填写菜品本名，例如小米粥。供餐时段在「适用餐次」设置。");
			if (frm.is_new()) return;
			if (frappe.model.can_read("BOM")) {
				frm.add_custom_button("查看配方", () => {
					frappe.route_options = {
						layout: recipeLayout, item: frm.doc.name, custom_tjy_standard_recipe: 1,
					};
					return frappe.set_route("List", "BOM");
				});
			}
			if (!frm.doc.disabled && !frm.doc.is_purchase_item && frappe.model.can_create("BOM")) {
				frm.add_custom_button("添加配方", () => addRecipe(frm.doc));
			}
		},
		async item_name(frm) {
			if (!frm.is_new() || !frm.doc.custom_tjy_standard_dish) return;
			const label = (frm.doc.item_name || "").trim();
			frm.remove_custom_button(reuseLabel);
			frm.set_intro("");
			if (!label) return;
			const { message } = await frappe.call({
				method: "tongjianyun.dish_library.dish_options",
				type: "GET",
				args: { label },
			});
			if (!frm.is_new() || (frm.doc.item_name || "").trim() !== label || !message.matches?.length) return;
			const names = message.matches.map((match) => match.name);
			frm.set_intro("发现同名自制菜品，请核对后使用。", "orange");
			frm.add_custom_button(reuseLabel, () => frappe.prompt({
				fieldname: "item", fieldtype: "Link", options: "Item", label: "菜品", reqd: 1,
				default: names.length === 1 ? names[0] : undefined,
				get_query: () => ({ filters: { name: ["in", names] } }),
			}, ({ item }) => reuseDish(frm, label, item), reuseLabel));
		},
	});
})();
