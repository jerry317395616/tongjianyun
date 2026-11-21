(() => {
	const route = "standard-dish-library";
	const layout = "标准菜品";

	function api(method, args, type = "GET") {
		return frappe.call({ method: `tongjianyun.dish_library.${method}`, args, type }).then((r) => r.message);
	}

	function button(label, action) {
		return $("<button>", { type: "button", class: "btn btn-default btn-xs" }).text(label).on("click", action);
	}

	function table(parent, headings) {
		const container = $("<div>", { class: "table-responsive" }).appendTo(parent);
		const result = $("<table>", { class: "table table-hover" }).appendTo(container);
		const head = $("<tr>").appendTo($("<thead>").appendTo(result));
		headings.forEach((text) => $("<th>", { scope: "col" }).text(text).appendTo(head));
		return $("<tbody>").appendTo(result);
	}

	function cells(row, values) {
		values.forEach((text) => $("<td>").text(text || "—").appendTo(row));
	}

	function openRecipe(name) {
		frappe.route_options = { layout };
		return frappe.set_route("Form", "BOM", name);
	}

	function newRecipe(dish) {
		return frappe.model.with_doctype("BOM", () => {
			const doc = frappe.model.get_new_doc("BOM", null, null, true);
			doc.item = dish.name;
			doc.custom_tjy_standard_recipe = 1;
			doc.custom_tjy_recipe_category = dish.category || "";
			doc.quantity = 1;
			return openRecipe(doc.name);
		});
	}

	async function showDish(name) {
		const info = await api("detail", { dish: name });
		const dish = info.dish;
		const dialog = new frappe.ui.Dialog({
			title: frappe.utils.escape_html(dish.label || dish.name),
			size: "extra-large",
			fields: [{ fieldtype: "HTML", fieldname: "versions" }],
		});
		const content = dialog.fields_dict.versions.$wrapper;
		$("<p>", { class: "text-muted" }).text([dish.category, dish.unit, dish.state].filter(Boolean).join(" · ")).appendTo(content);
		if (info.recipes.length) {
			const body = table(content, ["配方版本", "所属机构", "状态", "来源配方", "操作"]);
			for (const recipe of info.recipes) {
				const row = $("<tr>").appendTo(body);
				let state = recipe.state === "已发布" && !recipe.active ? "已停用" : recipe.state;
				if (recipe.name === dish.current) state += " · 当前";
				cells(row, [recipe.name, recipe.company, state, recipe.from_recipe]);
				const actions = $("<td>").appendTo(row);
				actions.append(button("查看配方", () => {
					dialog.hide();
					openRecipe(recipe.name);
				}));
				if (info.can_create_recipe && recipe.can_copy) {
					const copy = button("复制为新版", async () => {
						copy.prop("disabled", true);
						try {
							const result = await api("copy_recipe", { dish: dish.name, source: recipe.name }, "POST");
							dialog.hide();
							openRecipe(result.recipe);
						} finally {
							copy.prop("disabled", false);
						}
					}).addClass("ml-2");
					actions.append(copy);
				}
			}
		} else {
			$("<p>").text("待配置配方").appendTo(content);
		}
		if (info.can_create_recipe) {
			dialog.set_primary_action("添加配方", () => {
				dialog.hide();
				newRecipe(dish);
			});
		}
		dialog.show();
	}

	function createDish(info, onSaved) {
		const dialog = new frappe.ui.Dialog({
			title: "新建菜品",
			fields: [
				{ fieldname: "label", label: "菜名", fieldtype: "Data", reqd: 1 },
				{ fieldname: "category", label: "菜品分类", fieldtype: "Select", options: ["", ...info.categories], reqd: 1 },
				{ fieldname: "unit", label: "默认单位", fieldtype: "Link", options: "UOM", default: info.default_unit },
				{ fieldname: "item_group", label: "物料组", fieldtype: "Link", options: "Item Group", get_query: () => ({ filters: { is_group: 0 } }) },
				{ fieldname: "matches", fieldtype: "HTML" },
			],
		});
		let saving = false;
		async function save(values) {
			if (saving) return;
			saving = true;
			dialog.get_primary_btn().prop("disabled", true);
			const matches = dialog.fields_dict.matches.$wrapper.empty();
			try {
				const result = await api("save_dish", values, "POST");
				if (result.dish) {
					dialog.hide();
					onSaved();
					await showDish(result.dish);
					return;
				}
				$("<p>").text("发现同名自制菜品，请核对后选择。").appendTo(matches);
				for (const item of result.matches) {
					const line = $("<p>").appendTo(matches);
					$("<span>").text(`${item.item_name} · ${item.name} · ${item.stock_uom} · ${item.item_group} `).appendTo(line);
					line.append(button("使用此菜品", () => {
						const current = dialog.get_values();
						if (current) save({ ...current, existing: item.name });
					}));
				}
			} finally {
				saving = false;
				dialog.get_primary_btn().prop("disabled", false);
			}
		}
		dialog.set_primary_action("保存菜品", save);
		dialog.show();
	}

	frappe.pages[route].on_page_load = (wrapper) => {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: "标准菜品库", single_column: true });
		const root = $("<div>", { class: "frappe-card" }).appendTo(page.main);
		const results = $("<div>").appendTo(root);
		const pagination = $("<div>", { class: "d-flex justify-content-end pb-2 pr-3" }).appendTo(root);
		let start = 0;
		let revision = 0;
		const search = page.add_field({
			fieldname: "search", label: "菜名或物料号", fieldtype: "Data",
			change: () => {
				start = 0;
				refresh();
			},
		});

		async function refresh() {
			const request = ++revision;
			const info = await api("dishes", { search: search.get_value() || "", start });
			if (request !== revision) return;
			if (info.can_create_dish) page.set_primary_action("新建菜品", () => createDish(info, refresh));
			else page.clear_primary_action();
			results.empty();
			pagination.empty();
			if (!info.rows.length) {
				$("<p>", { class: "text-muted p-3" }).text("没有符合条件的菜品").appendTo(results);
			} else {
				const body = table(results, ["菜品", "分类", "单位", "配方状态", "操作"]);
				for (const dish of info.rows) {
					const row = $("<tr>").appendTo(body);
					const name = $("<td>").appendTo(row);
					$("<button>", { type: "button", class: "btn btn-link btn-xs px-0" })
						.text(dish.label || dish.name).on("click", () => showDish(dish.name)).appendTo(name);
					cells(row, [dish.category, dish.unit, [dish.state, dish.draft_state].filter(Boolean).join(" · ")]);
					const actions = $("<td>").appendTo(row);
					if (info.can_create_recipe && dish.can_make_recipe && !dish.recipes) {
						actions.append(button("添加配方", () => newRecipe(dish)));
					} else {
						actions.append(button("查看配方", () => showDish(dish.name)));
					}
				}
			}
			if (start) pagination.append(button("上一页", () => {
				start -= info.page_size;
				refresh();
			}));
			if (info.has_more) pagination.append(button("下一页", () => {
				start += info.page_size;
				refresh();
			}).addClass("ml-2"));
		}
		wrapper.refresh_dishes = refresh;
	};

	frappe.pages[route].on_page_show = (wrapper) => wrapper.refresh_dishes();
})();
