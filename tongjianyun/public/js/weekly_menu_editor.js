(() => {
	const api = "tongjianyun.weekly_menu_editor.";
	const weekdays = ["周一", "周二", "周三", "周四", "周五"];
	const editable = (frm) => frm.doc.docstatus === 0 && !!frm.perm?.[0]?.write;
	let styles;
	function loadStyles() {
		styles ??= Promise.resolve(frappe.require("/assets/tongjianyun/css/weekly_menu_editor.css?v=week-create.css"))
			.catch(() => { styles = undefined; });
	}
	function dateLabel(value, year = false) {
		const [y, m, d] = value.split("-").map(Number);
		return `${year ? `${y}年` : ""}${m}月${d}日`;
	}

	const call = async (method, args, write = false) => {
		const response = await frappe.call({ method: api + method, args, type: write ? "POST" : "GET", freeze: write });
		if (response.exc) throw new Error("周食谱操作未完成。");
		return response.message;
	};

	function button($parent, label, action, primary = false) {
		return $("<button>", { type: "button", class: `btn btn-xs mr-2 mb-1 ${primary ? "btn-primary" : "btn-default"}` })
			.text(label).on("click", action).appendTo($parent);
	}

	function message($parent, text) {
		return $("<div>", { class: "text-muted mb-2", role: "status" }).text(text).appendTo($parent);
	}

	function canAct(frm) {
		if (frm.__meal_action_running) return false;
		if (frm.is_dirty()) {
			frappe.msgprint("请先保存周计划表单上的修改。");
			return false;
		}
		return true;
	}

	async function mutate(frm, method, args, onSuccess) {
		if (!canAct(frm)) return;
		frm.__meal_action_running = true;
		try {
			const result = await call(method, { week_name: frm.doc.name, ...args }, true);
			onSuccess?.(result);
			await frm.reload_doc();
		} finally {
			frm.__meal_action_running = false;
		}
	}

	function startWeek(frm, previous) {
		return mutate(frm, "initialize", { copy_previous: Number(previous) }, (result) => {
			if (result.skipped_recipes) frappe.msgprint(`上周有 ${result.skipped_recipes} 个配方已不可用，请重新核对对应餐次。`);
		}).catch(() => {});
	}

	function renderCalendar(frm, $panel, data) {
		const { days, slots, meals, initialized, categories } = data;
		const canEdit = editable(frm);
		const byMeal = new Map(meals.map((meal) => [`${meal.date}:${meal.slot}`, meal]));
		const total = days.length * slots.length;
		const stopped = meals.filter((meal) => meal.stopped).length;
		const scheduled = meals.filter((meal) => !meal.stopped && meal.menu).length;
		const pending = total - scheduled - stopped;
		const today = frappe.datetime?.get_today?.();
		$panel.empty();
		const $headBand = $("<div>", { class: "tgy-week-overview" }).appendTo($panel);
		const $heading = $("<div>").appendTo($headBand);
		$("<h3>", { class: "tgy-week-title" }).text("供餐周历").appendTo($heading);
		const start = days[0];
		const end = days.at(-1);
		$("<div>", { class: "tgy-week-period" }).text(`${dateLabel(start, true)} – ${dateLabel(end, start.slice(0, 4) !== end.slice(0, 4))}`).appendTo($heading);
		if (canEdit && !initialized) {
			const $actions = $("<div>", { class: "tgy-week-actions" }).appendTo($headBand);
			button($actions, "空白编排", () => startWeek(frm, false), true);
			button($actions, "复制上周", () => startWeek(frm, true));
		}
		if (initialized) {
			const $progress = $("<div>", { class: "tgy-week-progress" }).appendTo($headBand);
			const $summary = $("<div>", { class: "tgy-week-summary", role: "status" }).appendTo($progress);
			for (const [label, count, state] of [["已选菜", scheduled, "scheduled"], ["停供", stopped, "stopped"], ["待编排", pending, "pending"]]) {
				$("<span>", { class: `tgy-week-stat tgy-${state}` }).text(`${label} ${count} 餐`).appendTo($summary);
			}
			$("<progress>", { value: total - pending, max: total, "aria-label": "餐次编排进度" }).appendTo($progress);
		}
		const $scroll = $("<div>", { class: "tgy-week-scroll table-responsive", role: "region", tabindex: 0, "aria-label": "供餐周历" }).appendTo($panel);
		const $table = $("<table>", { class: "tgy-week-table", "aria-label": "五天五餐周食谱" }).appendTo($scroll);
		const $head = $("<tr>").appendTo($("<thead>").appendTo($table));
		$("<th>", { scope: "col" }).text("餐次").appendTo($head);
		for (const [index, day] of days.entries()) {
			const $day = $("<th>", { scope: "col", "aria-current": day === today ? "date" : undefined }).appendTo($head);
			$("<strong>").text(weekdays[index]).appendTo($day);
			$("<time>", { datetime: day }).text(dateLabel(day)).appendTo($day);
		}
		const $body = $("<tbody>").appendTo($table);
		for (const slot of slots) {
			const $row = $("<tr>").appendTo($body);
			$("<th>", { scope: "row" }).text(slot).appendTo($row);
			for (const day of days) {
				const meal = byMeal.get(`${day}:${slot}`);
				const label = meal?.stopped ? "整餐停供" : meal?.menu || "未编排";
				const state = meal?.stopped ? "stopped" : meal?.menu ? "scheduled" : "pending";
				const $cell = $("<td>").appendTo($row);
				const cellClass = `tgy-meal-cell tgy-${state}`;
				let $card;
				if (canEdit && initialized) {
					$card = $("<button>", { type: "button", class: cellClass, "aria-label": `${day} ${slot} ${label}` })
						.on("click", () => openMeal(frm, day, slot, categories)).appendTo($cell);
				} else {
					$card = $("<div>", { class: cellClass }).appendTo($cell);
				}
				$("<span>", { class: "tgy-meal-name" }).text(label).appendTo($card);
				if (meal?.stopped) $("<span>", { class: "tgy-meal-note" }).text(meal.reason).appendTo($card);
				else if (meal?.menu) $("<span>", { class: "tgy-meal-note" }).text(`计划 ${meal.headcount} 人`).appendTo($card);
			}
		}
		if (canEdit && pending) {
			frm.remove_custom_button("采购需求预览");
			frm.remove_custom_button("核对账面库存");
			frm.remove_custom_button("确认采购毛重口径", "采购操作");
		} else if (canEdit) {
			message($panel, "编排完成后，核对采购毛重口径和账面库存，再由授权审核员提交发布。");
		}
	}

	async function refresh(frm) {
		const $grid = frm.fields_dict.meals?.$wrapper;
		if (!$grid?.length) return;
		const creating = Boolean(frm.is_new() && !frm.doc.amended_from);
		loadStyles();
		frm.layout.wrapper.toggleClass("tgy-week-create", creating);
		frm.fields_dict.company?.$wrapper?.closest(".form-section").toggleClass("tgy-week-settings", !creating);
		let $panel = $grid.prev(".tgy-week-menu");
		if (creating) {
			$panel.remove();
			frm.set_intro("保存后，可选择空白编排或复制上周。", "blue");
			return;
		}
		if (!$panel.length) $panel = $("<div>", { class: "tgy-week-menu mb-3" }).insertBefore($grid);
		const $content = $("<div>").appendTo($panel.empty());
		if (frm.is_new()) {
			$grid.show();
			message($content, "请先保存园所、供餐周、学期和原料仓库，再开始编排。");
			return;
		}
		const name = frm.doc.name;
		message($content, "正在读取周食谱…");
		try {
			const data = await call("calendar", { week_name: name });
			if (frm.doc.name !== name || !$content.parent().length) return;
			renderCalendar(frm, $content, data);
			frm.remove_custom_button("调整本餐菜品");
			frm.custom_buttons?.["从上一周编排"]?.text("从参考周编排");
			$grid.hide();
		} catch {
			message($content.empty(), "周食谱读取失败。");
			button($content, "重试", () => refresh(frm));
			$grid.show();
		}
	}

	async function openMeal(frm, date, slot, categories) {
		if (!canAct(frm)) return;
		const args = { week_name: frm.doc.name, meal_date: date, meal_type: slot };
		try {
			const meal = await call("get_meal", args);
			if (frm.doc.name === args.week_name && canAct(frm)) mealDialog(frm, args, meal, categories);
		} catch {
			// Frappe displays the permission or validation error returned by the server.
		}
	}

	function mealDialog(frm, args, meal, categories) {
		const selected = [...meal.dishes];
		let offset = 0;
		let request = 0;
		let $options, $chosen, $counts;
		let lastOptions = null;
		const dialog = new frappe.ui.Dialog({
			title: `${dateLabel(args.meal_date, true)} · ${args.meal_type}`,
			size: "large",
			fields: [
				{ fieldname: "search", fieldtype: "Data", label: "搜索菜品", placeholder: "菜名或编码" },
				{ fieldname: "category_column", fieldtype: "Column Break" },
				{ fieldname: "category", fieldtype: "Select", label: "菜品分类", options: ["", ...categories], onchange: resetSearch },
				{ fieldname: "options_section", fieldtype: "Section Break" },
				{ fieldname: "all_slots", fieldtype: "Check", label: "显示其他餐次的菜品", onchange: resetSearch },
				{ fieldname: "options", fieldtype: "HTML" },
				{ fieldname: "chosen", fieldtype: "HTML" },
				{ fieldname: "counts_section", fieldtype: "Section Break", label: "供餐安排" },
				{ fieldname: "counts_summary", fieldtype: "HTML" },
				{ fieldname: "excluded_count", fieldtype: "Int", label: "停餐调整人数", default: meal.excluded_count || 0, non_negative: 1,
					onchange: renderCounts },
				{ fieldname: "adjustment_reason", fieldtype: "Small Text", label: "停餐调整原因", default: meal.adjustment_reason },
				{ fieldname: "stopped", fieldtype: "Check", label: "整餐停供", default: Number(meal.stopped), onchange: renderCounts },
				{ fieldname: "reason", fieldtype: "Small Text", label: "整餐停供原因", default: meal.reason, depends_on: "eval:doc.stopped" },
			],
			primary_action_label: "保存本餐草稿",
			async primary_action(values) {
				if (frm.doc.name !== args.week_name || !canAct(frm)) return;
				const primary = dialog.get_primary_btn().prop("disabled", true);
				try {
					await mutate(frm, "save_meal", {
						...args, modified: meal.modified, boms: JSON.stringify(selected.map((dish) => dish.bom)),
						excluded_count: values.excluded_count || 0, adjustment_reason: values.adjustment_reason || "",
						stopped: values.stopped || 0, reason: values.reason || "",
					}, () => dialog.hide());
				} catch {
					// Keep the meal open so quantities and selections can be checked.
				} finally {
					primary.prop("disabled", false);
				}
			},
		});
		dialog.$wrapper.addClass("tgy-week-picker");
		dialog.show();
		$options = dialog.fields_dict.options.$wrapper;
		$chosen = dialog.fields_dict.chosen.$wrapper;
		$counts = dialog.fields_dict.counts_summary.$wrapper;
		dialog.fields_dict.search.$input.on("input", frappe.utils.debounce(resetSearch, 250));
		renderCounts();
		renderChosen();
		loadOptions();

		function renderCounts() {
			if (!$counts) return;
			const $summary = $("<div>", { class: "tgy-picker-counts", role: "status" }).appendTo($counts.empty());
			const base = Number(meal.base_headcount);
			const excluded = Number(dialog.get_value("excluded_count") || 0);
			const stopped = Number(dialog.get_value("stopped"));
			$("<span>").text(`在园学生 ${base} 人`).appendTo($summary);
			const planned = !Number.isInteger(excluded) || excluded < 0 || excluded >= base
				? "请核对停餐调整人数" : `计划供餐 ${stopped ? 0 : base - excluded} 人`;
			$("<strong>").text(planned).appendTo($summary);
		}

		function resetSearch() {
			if (!$options) return;
			offset = 0;
			return loadOptions();
		}

		function renderChosen() {
			const $card = $("<div>", { class: "tgy-picker-card tgy-picker-chosen" }).appendTo($chosen.empty());
			$("<h4>", { class: "tgy-picker-title" }).text(`已选菜品（${selected.length}）`).appendTo($card);
			if (!selected.length) message($card, "从上方添加本餐菜品。");
			const $detail = $("<div>", { class: "tgy-picker-detail", role: "status" });
			selected.forEach((dish, index) => {
				const $row = $("<div>", { class: "tgy-picker-row" }).appendTo($card);
				$("<span>", { class: "tgy-picker-name" }).text(dish.name).appendTo($row);
				const $actions = $("<div>", { class: "tgy-picker-row-actions" }).appendTo($row);
				button($actions, "带量", async () => {
					try {
						const ingredients = await call("ingredients", { week_name: args.week_name, bom_name: dish.bom });
						$detail.empty();
						$("<strong>").text(`${dish.name} · 人均采购毛重`).appendTo($detail);
						$("<div>").text(ingredients?.map((row) => `${row.name} ${row.gross ?? "—"} ${row.uom || ""}`).join("；") || "暂无可查看的带量。").appendTo($detail);
					} catch { $detail.text("带量读取失败。"); }
				});
				if (index > 0) button($actions, "上移", () => {
					[selected[index - 1], selected[index]] = [selected[index], selected[index - 1]];
					renderChosen();
				});
				button($actions, "移除", () => { selected.splice(index, 1); renderChosen(); renderOptions(lastOptions); });
			});
			$detail.appendTo($card);
		}

		async function loadOptions() {
			const sequence = ++request;
			message($options.empty(), "正在查找标准菜品…");
			try {
				const result = await call("dishes", {
					week_name: args.week_name, meal_type: args.meal_type, start: offset,
					search: dialog.get_value("search") || "", category: dialog.get_value("category") || "",
					all_slots: dialog.get_value("all_slots") || 0,
				});
				if (sequence === request) {
					lastOptions = result;
					renderOptions(result);
				}
			} catch {
				if (sequence === request) message($options.empty(), "菜品读取失败，请重新搜索。");
			}
		}

		function renderOptions(result) {
			if (!result) return;
			const $card = $("<div>", { class: "tgy-picker-card" }).appendTo($options.empty());
			$("<h4>", { class: "tgy-picker-title" }).text("标准菜品").appendTo($card);
			const $list = $("<div>", { class: "tgy-picker-options" }).appendTo($card);
			if (!result.rows.length) message($list, "暂无符合条件的标准菜品。");
			for (const dish of result.rows) {
				const $row = $("<div>", { class: "tgy-picker-row" }).appendTo($list);
				const $label = $("<span>", { class: "tgy-picker-name" }).text(dish.name).appendTo($row);
				if (dish.category) $("<span>", { class: "tgy-picker-category" }).text(dish.category).appendTo($label);
				if (!dish.bom) { message($row, dish.status); continue; }
				const picked = selected.some((item) => item.item === dish.item);
				button($row, picked ? "已选" : "添加", () => {
					if (selected.length >= 20) return frappe.msgprint("每餐最多选择 20 道菜。");
					selected.push(dish);
					renderChosen();
					renderOptions(result);
				}).prop("disabled", picked);
			}
			if (offset || result.has_more) {
				const $pages = $("<div>", { class: "tgy-picker-pages" }).appendTo($card);
				if (offset) button($pages, "上一页", () => { offset -= result.page_size; loadOptions(); });
				if (result.has_more) button($pages, "下一页", () => { offset += result.page_size; loadOptions(); });
			}
		}
	}

	frappe.ui.form.on("Meal Planning Week", { refresh });
})();
