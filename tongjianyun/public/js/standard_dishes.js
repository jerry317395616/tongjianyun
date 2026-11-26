(() => {
	const dishLayout = "标准菜品档案";
	const recipeLayout = "标准菜品";
	const reuseLabel = "使用同名菜品";
	const previewField = "custom_tjy_dish_recipe_preview";
	const assetPath = "/assets/tongjianyun";
	const ingredientColumns = [
		{ id: "item_code", name: "食材", width: 30, link: "Item" },
		{ id: "gross", name: "每份采购毛用量", width: 22, align: "right" },
		{ id: "net", name: "每份可食净量", width: 22, align: "right" },
		{ id: "uom", name: "单位", width: 17, link: "UOM" },
	];
	let activeRecipePanel;

	function closeRecipePanel() {
		activeRecipePanel?.dispose?.();
		activeRecipePanel = null;
	}

	frappe.router?.on?.("change", closeRecipePanel);

	function showNewDishSidebar(frm) {
		// Frappe builds the sidebar for a new document but hides it until the first save.
		const $sidebar = frm.sidebar?.sidebar;
		if (!$sidebar?.length || $sidebar.hasClass("tjy-dish-sidebar-pending")) return;
		$sidebar.addClass("tjy-dish-sidebar-pending");
		$sidebar.children(".sidebar-section").prop("inert", true);
		$("<p>", { class: "tjy-dish-sidebar-note" }).text("保存后可用").appendTo($sidebar);
	}

	function renderDishLayout(frm, $preview) {
		const $details = frm.layout.tabs.find((tab) => tab.df.fieldname === "details")?.wrapper;
		if (!$details?.length) return;
		let $steps = $details.data("tjy-dish-steps");
		if (!$steps) {
			const sections = ["section_break_zlmj", "custom_meal_slot_section", "custom_tjy_dish_recipe_section", "section_break_11"]
				.map((fieldname) => frm.layout.sections.find((section) => section.df.fieldname === fieldname));
			if (sections.some((section) => !section?.wrapper?.length)) return;
			const [information, meals, recipe, advanced] = sections;
			const $grid = $("<div>", { class: "tjy-dish-grid" }).insertBefore(information.wrapper);
			const $profile = $("<div>", { class: "tjy-dish-profile" }).appendTo($grid);
			information.wrapper.addClass("tjy-dish-information").appendTo($profile);
			meals.wrapper.addClass("tjy-dish-meals").appendTo($profile);
			recipe.wrapper.addClass("tjy-dish-recipe").appendTo($grid);
			advanced.wrapper.addClass("tjy-dish-advanced");
			$preview.addClass("tjy-dish-recipe-content");
			$("<span>", { class: "tjy-dish-recipe-lock", "aria-hidden": "true" })
				.html(frappe.utils.icon("lock", "sm")).appendTo(recipe.head);

			$steps = $("<ol>", { class: "tjy-dish-steps", "aria-label": "菜品维护步骤" })
				.insertBefore(frm.layout.page.children(".form-tabs-list"));
			$("<li>", { class: "tjy-dish-step tjy-dish-step-profile" })
				.append($("<span>", { class: "tjy-dish-step-icon", "aria-hidden": "true" }).text("1"))
				.append(document.createTextNode("菜品建档")).appendTo($steps);
			$("<li>", { class: "tjy-dish-step tjy-dish-step-recipe" })
				.append($("<span>", { class: "tjy-dish-step-icon", "aria-hidden": "true" }))
				.append(document.createTextNode("配置配方")).appendTo($steps);
			$details.addClass("tjy-dish-layout").data("tjy-dish-steps", $steps);
		}
		const isNew = Boolean(frm.is_new());
		$details.toggleClass("tjy-dish-new", isNew);
		$steps.toggleClass("tjy-dish-steps-new", isNew);
		$steps.find(".tjy-dish-step-profile").attr("aria-current", isNew ? "step" : null);
		$steps.find(".tjy-dish-step-recipe").attr("aria-current", isNew ? null : "step")
			.find(".tjy-dish-step-icon").html(isNew ? frappe.utils.icon("lock", "xs") : "2");

		if (isNew) {
			showNewDishSidebar(frm);
			const $empty = $("<div>", { class: "tjy-dish-recipe-empty" }).appendTo($preview.empty());
			$("<img>", { src: `${assetPath}/images/dish-recipe-bowl.webp`, alt: "", width: 176, height: 150 })
				.appendTo($empty);
			$("<p>").text("保存菜品后即可添加配方和食材。").appendTo($empty);
		}
	}

	function openRecipe(name) {
		frappe.route_options = { layout: recipeLayout };
		return frappe.set_route("Form", "BOM", name);
	}

	function viewRecipes(dish, company) {
		frappe.route_options = { layout: recipeLayout, item: dish, custom_tjy_standard_recipe: 1 };
		if (company) frappe.route_options.company = company;
		return frappe.set_route("List", "BOM");
	}

	function addRecipe(dish, company) {
		return frappe.model.with_doctype("BOM", () => {
			const doc = frappe.model.get_new_doc("BOM", null, null, true);
			doc.item = dish.name;
			if (company) doc.company = company;
			doc.quantity = 1;
			doc.custom_tjy_standard_recipe = 1;
			doc.custom_tjy_recipe_category = dish.custom_tjy_dish_category || "";
			return openRecipe(doc.name);
		});
	}

	async function copyRecipe(dish, source) {
		const { message } = await frappe.call({
			method: "tongjianyun.dish_library.copy_recipe", type: "POST", freeze: true, args: { dish, source },
		});
		return openRecipe(message.recipe);
	}

	function recipeAction($container, label, action, primary = false) {
		return $("<button>", { type: "button", class: `btn btn-xs mr-2 mb-2 ${primary ? "btn-primary" : "btn-default"}` })
			.text(label).on("click", action).appendTo($container);
	}

	function escapeCell(value) {
		return frappe.utils.escape_html(String(value ?? ""));
	}

	function mountIngredientTable($container, label, columns, data, options = {}) {
		const $grid = $("<div>", { "aria-label": label, class: "tjy-dish-ingredient-grid" })
			.appendTo($("<div>", { class: "table-responsive mb-2" }).appendTo($container));
		const table = new frappe.DataTable($grid[0], {
			columns: columns.map((column) => ({ sortable: false, dropdown: false, ...column })),
			data, layout: "ratio", serialNoColumn: false, disableReorderColumn: true,
			clusterize: false, noDataMessage: "暂无食材明细", ...options,
		});
		return { $grid, table };
	}

	function positionLinkOptions(control) {
		const bounds = control.$input[0].getBoundingClientRect();
		const width = Math.min(Math.max(230, bounds.width), window.innerWidth - 16);
		const spaceBelow = window.innerHeight - bounds.bottom - 8;
		const showAbove = spaceBelow < 150 && bounds.top > spaceBelow;
		Object.assign(control.awesomplete.ul.style, {
			position: "fixed", left: `${Math.max(8, Math.min(bounds.left, window.innerWidth - width - 8))}px`, right: "auto",
			top: showAbove ? "auto" : `${bounds.bottom + 4}px`,
			bottom: showAbove ? `${window.innerHeight - bounds.top + 4}px` : "auto",
			minWidth: "0", width: `${width}px`, maxHeight: `${Math.max(64, Math.min(240, showAbove ? bounds.top - 8 : spaceBelow))}px`,
			zIndex: "1051", overflowY: "auto",
		});
	}

	function recipeLinkEditor(parent, column, getQuery, save, acceptSelection) {
		const control = frappe.ui.form.make_control({
			parent, render_input: true, only_input: true,
			df: {
				fieldtype: "Link", fieldname: column.id, label: column.name, options: column.link,
				get_query: getQuery, only_select: 1,
			},
		});
		const $input = control.$input;
		if (column.id === "item_code") {
			control.get_filter_description = () => "";
			const renderOption = control.awesomplete.item;
			control.awesomplete.item = function (item) {
				const option = renderOption.call(this, item);
				const suggestion = this.get_item(item.value);
				const label = option.querySelector("p");
				if (label && !suggestion.action) {
					// Link treats the name as a description on sites that show the code as the title.
					const name = suggestion.label !== suggestion.value
						? suggestion.label : suggestion.description || suggestion.label;
					label.textContent = name;
					label.title = name;
				}
				return option;
			};
		}
		let selected;
		$input.on("awesomplete-open", () => positionLinkOptions(control));
		$input.on("awesomplete-selectcomplete", (event) => {
			const value = event.originalEvent?.text?.value;
			if (typeof value !== "string" || !value || value.includes("__link_option")) return;
			selected = value;
			acceptSelection();
		});
		$input.on("keydown", (event) => {
			// Let the Link dropdown handle keys it consumes before the grid receives them.
			if (event.isDefaultPrevented() || (control.awesomplete?.opened && ["ArrowUp", "ArrowDown", "Escape"].includes(event.key))) {
				event.stopPropagation();
			}
		});
		return {
			initValue(value) { $input.val(value ?? ""); $input[0].focus(); },
			getValue() { return (selected ?? control.get_input_value() ?? "").trim(); },
			setValue: save,
		};
	}

	function recipeQuantityEditor(parent, label, save) {
		const $input = $("<input>", {
			type: "number", min: 0, step: "any", "aria-label": label, class: "dt-input",
		}).appendTo($(parent));
		return {
			initValue(value) { $input.val(value ?? ""); $input[0].focus(); },
			getValue() { return String($input.val() ?? ""); },
			setValue: save,
		};
	}

	function renderIngredientEditor($editor, dish, company, source, onClose, onSaved) {
		const rows = source.ingredients.map((ingredient) => ({ ...ingredient }));
		if (!rows.length) rows.push({});
		const names = new Map(rows.filter((row) => row.name).map((row) => [row.item_code, row.name]));
		const defaults = new Set();
		let disposed = false;
		let changingRows = false;
		$("<p>", { class: "text-muted small mb-2" }).text("双击单元格或按 Enter 编辑，按 Tab 切换。").appendTo($editor);
		const columns = [
			...ingredientColumns.map((column) => ({
				...column, format: column.id === "item_code" ? (code) => escapeCell(names.get(code) || code) : escapeCell,
			})),
			{ id: "remove", name: "操作", width: 9, editable: false, focusable: false,
				format: (index) => `<button type="button" class="btn btn-xs btn-default text-nowrap" data-remove-ingredient="${Number(index)}">删除</button>` },
		];
		const gridData = () => rows.map((row, index) => [
			{ content: row.item_code || "", editable: !row.row }, String(row.gross ?? ""), String(row.net ?? ""),
			row.uom || "", index,
		]);
		const { $grid, table } = mountIngredientTable($editor, "编辑食材明细", columns, gridData(), {
			getEditor(_column, index, _value, parent, column) {
				const row = rows[index];
				const acceptSelection = () => cells.deactivateEditing();
				if (column.id === "item_code") {
					return recipeLinkEditor(parent, column, () => ({
						query: "tongjianyun.dish_recipe_editor.ingredient_query",
						filters: { name: ["!=", dish], disabled: 0, is_fixed_asset: 0, include_item_in_manufacturing: 1 },
					}), (code) => selectIngredient(row, index, code), acceptSelection);
				}
				if (column.id === "uom") {
					return recipeLinkEditor(parent, column, () => ({
						query: "erpnext.controllers.queries.get_item_uom_query", filters: { item_code: row.item_code || "" },
					}), (unit) => { row.uom = unit; }, acceptSelection);
				}
				return recipeQuantityEditor(parent, column.name, (value) => { row[column.id] = value; });
			},
		});
		const cells = table.cellmanager;
		const unitColumn = columns.findIndex((column) => column.id === "uom");

		function refreshUnit(index, value) {
			const cell = cells.getCell$(unitColumn, index);
			if (cell === cells.$editingCell && cell) {
				// The lookup may finish after the user opened this unit editor.
				// Refresh its display without replacing the live Link control.
				table.datamanager.updateCell(unitColumn, index, { content: value });
				cell.querySelector(".dt-cell__content").textContent = value;
				const input = cell.querySelector(".dt-cell__edit input");
				if (input && !input.value) input.value = value;
			} else if (cell) {
				cells.updateCell(unitColumn, index, value);
			}
		}

		function selectIngredient(row, index, code) {
			row.item_code = code;
			row.uom = "";
			refreshUnit(index, "");
			if (!code) return;
			const lookup = frappe.db.get_value("Item", code, ["item_name", "stock_uom"]).then(({ message }) => {
				if (disposed || row.item_code !== code || !message) return;
				if (message.item_name) names.set(code, message.item_name);
				const itemCell = cells.getCell$(0, index);
				if (itemCell && itemCell !== cells.$editingCell) cells.updateCell(0, index, code, true);
				if (!row.uom && message.stock_uom) {
					row.uom = message.stock_uom;
					refreshUnit(index, row.uom);
				}
			}).catch(() => {
				// Keep the typed item and allow the user to select its unit if lookup fails.
			}).finally(() => defaults.delete(lookup));
			defaults.add(lookup);
			return lookup;
		}

		async function commitCell() {
			// DataTable has no public API to commit the cell still being edited on an outside click.
			const committed = cells.submitEditing();
			cells.deactivateEditing(false);
			$grid.prop("inert", true);
			await committed;
			await Promise.all(defaults);
		}

		const $status = $("<span>", { class: "text-muted", role: "status" });
		async function changeRows(update) {
			if (changingRows || disposed) return;
			changingRows = true;
			try {
				await commitCell();
				if (disposed) return;
				update();
				table.refresh(gridData());
			} catch {
				$status.text("请核对正在编辑的食材明细。");
			} finally {
				$grid.prop("inert", false);
				changingRows = false;
			}
		}
		$grid.on("click", "[data-remove-ingredient]", (event) =>
			changeRows(() => rows.splice(Number(event.currentTarget.dataset.removeIngredient), 1)));
		recipeAction($editor, "添加食材", () => changeRows(() => rows.push({})));
		recipeAction($editor, "取消", onClose);
		const $save = recipeAction($editor, "保存配方草稿", async () => {
			if (changingRows || disposed) return;
			changingRows = true;
			$status.empty();
			$save.prop("disabled", true);
			try {
				await commitCell();
				if (disposed) return;
				const ingredients = JSON.stringify(rows.map(({ row, item_code, gross, net, uom }) =>
					({ row, item_code, gross: String(gross ?? ""), net: String(net ?? ""), uom })));
				await frappe.call({
					method: "tongjianyun.dish_recipe_editor.save_ingredients", type: "POST", freeze: true,
					args: { dish, company, recipe: source.recipe, modified: source.modified, ingredients },
				});
				if (disposed) return;
				frappe.show_alert({ message: "配方草稿已保存", indicator: "green" });
				return onSaved();
			} catch {
				$status.text("保存失败，当前修改仍可继续编辑。");
			} finally {
				$grid.prop("inert", false);
				changingRows = false;
				$save.prop("disabled", false);
			}
		}, true);
		$status.appendTo($editor);
		return () => {
			disposed = true;
			table.destroy();
		};
	}

	function renderPreview($content, $wrapper, dish, preview, panel) {
		const { current, draft, company, companies, can_create_recipe } = preview;
		const draftLabel = draft?.state === "待审核" ? "待审核配方" : "配方草稿";
		let selected = draft || current;
		let submittingReview = false;
		const $header = $("<div>", { class: "d-flex flex-wrap align-items-center justify-content-between" }).appendTo($content);
		const $context = $("<div>", { class: "d-flex flex-wrap align-items-center" }).appendTo($header);
		if (companies.length > 1) {
			const $label = $("<label>", { class: "d-flex align-items-center text-muted mb-2 mr-2" }).text("机构").appendTo($context);
			const $select = $("<select>", { class: "form-control input-xs ml-2" }).appendTo($label);
			if (!company) $("<option>", { value: "", disabled: true }).text("请选择").appendTo($select);
			for (const name of companies) $("<option>", { value: name }).text(name).appendTo($select);
			$select.val(company || "").on("change", () => loadPreview($wrapper, dish, $select.val()));
		} else if (company) {
			$("<span>", { class: "text-muted mb-2 mr-2" }).text(company).appendTo($context);
		}
		const $version = $("<div>", { class: "mb-2 mr-2" }).appendTo($context);
		const $actions = $("<div>", { class: "ml-auto" }).appendTo($header);
		const $body = $("<div>").appendTo($content);

		function clearGrid() {
			panel.dispose?.();
			panel.dispose = null;
			$body.empty();
		}

		async function startEditor(selectedCompany) {
			if (activeRecipePanel !== panel) return;
			clearGrid();
			$actions.empty();
			$version.text("配方草稿");
			$context.find("select").prop("disabled", true);
			$body.text("正在加载配方草稿…");
			try {
				const { message } = await frappe.call({
					method: "tongjianyun.dish_recipe_editor.load_editor", type: "GET",
					args: { dish: dish.name, company: selectedCompany },
				});
				if (activeRecipePanel !== panel) return;
				$version.text(message.mode === "revision" ? "新版配方草稿" : "配方草稿");
				panel.dispose = renderIngredientEditor($body.empty(), dish.name, selectedCompany, message, renderVersion,
					() => loadPreview($wrapper, dish, selectedCompany));
			} catch {
				if (activeRecipePanel !== panel) return;
				renderVersion();
				frappe.show_alert({ message: "无法加载配方草稿，请重试。", indicator: "red" });
			}
		}

		function openEditor() {
			if (company) return startEditor(company);
			return frappe.prompt([{ fieldname: "company", fieldtype: "Link", label: "机构", options: "Company", reqd: 1 }],
				({ company: selectedCompany }) => startEditor(selectedCompany), "选择机构", "继续");
		}

		async function submitReview() {
			if (submittingReview || activeRecipePanel !== panel) return;
			submittingReview = true;
			const controls = $header.find("button, select");
			controls.prop("disabled", true);
			try {
				await frappe.call({
					method: "tongjianyun.standard_recipes.set_review_pending", type: "POST", freeze: true,
					args: { name: draft.name, pending: 1 },
				});
				if (activeRecipePanel !== panel) return;
				frappe.show_alert({ message: "配方已提交审核", indicator: "green" });
				await loadPreview($wrapper, dish, company);
			} catch {
				if (activeRecipePanel === panel) {
					frappe.show_alert({ message: "提交审核失败，请重试。", indicator: "red" });
				}
			} finally {
				submittingReview = false;
				controls.prop("disabled", false);
			}
		}

		function renderVersion() {
			clearGrid();
			$actions.empty();
			$version.empty();
			$context.find("select").prop("disabled", false);
			if (current && draft) {
				const $select = $("<select>", { class: "form-control input-xs", "aria-label": "配方版本" }).appendTo($version);
				$("<option>", { value: current.name }).text("在用配方").appendTo($select);
				$("<option>", { value: draft.name }).text(draftLabel).appendTo($select);
				$select.val(selected.name).on("change", () => {
					selected = $select.val() === current.name ? current : draft;
					renderVersion();
					$version.find("select")[0]?.focus();
				});
			} else if (selected) {
				const isDraft = selected === draft;
				$("<span>", { class: `indicator-pill ${isDraft ? "orange" : "green"}` })
					.text(isDraft ? draftLabel : "在用配方").appendTo($version);
			}

			if (draft && selected === draft) {
				if (draft.state === "待审核") {
					recipeAction($actions, "审核配方", () => openRecipe(draft.name));
				} else if (draft.can_edit) {
					const edit = draft.inline_edit === false ? () => openRecipe(draft.name) : openEditor;
					recipeAction($actions, "继续编辑", edit);
					recipeAction($actions, "提交审核", submitReview, true);
				}
			} else {
				if (!draft && can_create_recipe && (company || !companies.length)) {
					if (current?.inline_edit === false) {
						recipeAction($actions, "复制为新版", () => copyRecipe(dish.name, current.name));
					} else {
						recipeAction($actions, current ? "编辑配方" : "添加食材", openEditor, true);
					}
				}
				if (current) recipeAction($actions, "打开在用配方", () => openRecipe(current.name));
			}

			if (!selected || !selected.ingredients) {
				const hint = selected ? "当前账号无权查看食材明细。" :
					!company && companies.length ? "请选择机构查看配方。" : "暂无配方。";
				$("<div>", { class: "text-muted" }).text(hint).appendTo($body);
				return;
			}
			const columns = ingredientColumns.map((column) => ({ ...column, editable: false, format: escapeCell }));
			const rows = selected.ingredients.map(({ name, gross, net, uom }) => [name, gross ?? "—", net ?? "—", uom ?? "—"]);
			const { table } = mountIngredientTable($body, "配方食材明细", columns, rows);
			panel.dispose = () => table.destroy();
		}

		renderVersion();
	}

	async function loadPreview($wrapper, dish, company) {
		closeRecipePanel();
		const panel = {};
		activeRecipePanel = panel;
		const $content = $("<div>").appendTo($wrapper.empty());
		$("<div>", { class: "text-muted", role: "status" }).text("正在加载配方…").appendTo($content);
		try {
			const [{ message }] = await Promise.all([
				frappe.call({ method: "tongjianyun.dish_library.recipe_preview", type: "GET", args: { dish: dish.name, company } }),
				frappe.require("report.bundle.css"),
			]);
			if (activeRecipePanel === panel) renderPreview($content.empty(), $wrapper, dish, message, panel);
		} catch {
			if (activeRecipePanel !== panel) return;
			$("<span>", { class: "text-muted mr-2" }).text("无法加载配方。").appendTo($content.empty());
			recipeAction($content, "重试", () => loadPreview($wrapper, dish, company));
		}
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
		async refresh(frm) {
			if (!frm.doc.custom_tjy_standard_dish) return;
			frm.set_df_property("item_name", "description", "填写菜品本名，例如小米粥。供餐时段在「适用餐次」设置。");
			const $preview = frm.fields_dict?.[previewField]?.$wrapper;
			if (frm.doctype_layout?.name === dishLayout && $preview) {
				const { doc, layout } = frm;
				await frappe.require(`${assetPath}/css/standard_dish_profile.css?v=1.css`);
				const [view, doctype] = frappe.get_route();
				if (frm.doc !== doc || frm.layout !== layout || view !== "Form" || doctype !== "Item") return;
				renderDishLayout(frm, $preview);
				if (frm.is_new()) return;
				if (frappe.model.can_read("BOM")) return loadPreview($preview, frm.doc);
				$preview.text("当前账号无权查看配方。");
				if (!frm.doc.disabled && !frm.doc.is_purchase_item && frappe.model.can_create("BOM")) {
					recipeAction($preview, "添加配方", () => addRecipe(frm.doc), true);
				}
				return;
			}
			if (frm.is_new()) return;
			if (frappe.model.can_read("BOM")) {
				frm.add_custom_button("查看配方", () => viewRecipes(frm.doc.name));
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
