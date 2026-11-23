(() => {
	const api = "tongjianyun.weekly_menu_editor.";
	const doctype = "Meal Planning Week";
	const basicTab = "custom_tjy_week_basic_tab";
	const calendarTab = "custom_tjy_week_calendar_tab";
	const weekdays = ["周一", "周二", "周三", "周四", "周五"];
	const editable = (frm) => frm.doc.docstatus === 0 && !!frm.perm?.[0]?.write;
	let styles;
	let openedWeek;
	let requestedTab = window.location.hash.slice(1);
	frappe.router?.on?.("change", () => {
		const [view, type, name] = frappe.get_route();
		if (view !== "Form" || type !== doctype || name !== openedWeek) {
			openedWeek = undefined;
			requestedTab = window.location.hash.slice(1);
		}
	});
	function loadStyles() {
		styles ??= Promise.resolve(frappe.require("/assets/tongjianyun/css/weekly_menu_editor.css?v=meal-composer"))
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

	function renderCalendar(frm, $panel, data, tabbed) {
		const { days, slots, meals, initialized, categories } = data;
		const canEdit = editable(frm);
		const schedule = { days, slots, categories };
		const byMeal = new Map(meals.map((meal) => [`${meal.date}:${meal.slot}`, meal]));
		const total = days.length * slots.length;
		const stopped = meals.filter((meal) => meal.stopped).length;
		const scheduled = meals.filter((meal) => !meal.stopped && meal.menu).length;
		const pending = total - scheduled - stopped;
		const today = frappe.datetime?.get_today?.();
		$panel.empty();
		const $headBand = $("<div>", { class: "tgy-week-overview" }).appendTo($panel);
		const $heading = $("<div>").appendTo($headBand);
		const start = days[0];
		const end = days.at(-1);
		const period = `${dateLabel(start, true)} – ${dateLabel(end, start.slice(0, 4) !== end.slice(0, 4))}`;
		$("<h3>", { class: "tgy-week-title" }).text(tabbed ? period : "供餐周历").appendTo($heading);
		if (!tabbed) $("<div>", { class: "tgy-week-period" }).text(period).appendTo($heading);
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
		for (const [slotIndex, slot] of slots.entries()) {
			const $row = $("<tr>").appendTo($body);
			$("<th>", { scope: "row" }).text(slot).appendTo($row);
			for (const [dayIndex, day] of days.entries()) {
				const meal = byMeal.get(`${day}:${slot}`);
				const label = meal?.stopped ? "整餐停供" : meal?.menu || "未编排";
				const state = meal?.stopped ? "stopped" : meal?.menu ? "scheduled" : "pending";
				const $cell = $("<td>").appendTo($row);
				const cellClass = `tgy-meal-cell tgy-${state}`;
				let $card;
				if (canEdit && initialized) {
					$card = $("<button>", { type: "button", class: cellClass, "aria-label": `${day} ${slot} ${label}` })
						.on("click", () => openMeal(frm, schedule, dayIndex * slots.length + slotIndex)).appendTo($cell);
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
		const unsaved = Boolean(frm.is_new());
		const creating = unsaved && !frm.doc.amended_from;
		const name = frm.doc.name;
		const opening = openedWeek !== name;
		openedWeek = name;
		loadStyles();
		frm.layout.wrapper.toggleClass("tgy-week-create", creating);
		frm.fields_dict.company?.$wrapper?.closest(".form-section").toggleClass("tgy-week-settings", !creating);
		const $calendar = frm.fields_dict.custom_tjy_week_calendar?.$wrapper;
		const tab = frm.layout.tabs.find((entry) => entry.df.fieldname === calendarTab);
		const tabbed = Boolean($calendar?.length && tab);
		const $mealSection = tabbed ? $grid.closest(".form-section") : null;
		let $panel = tabbed ? $calendar.addClass("tgy-week-menu") : $grid.prev(".tgy-week-menu");
		$mealSection?.hide();
		if (creating) {
			if (tabbed) $panel.empty();
			else $panel.remove();
			frm.set_intro("保存后，在「供餐周历」选择空白编排或复制上周。", "blue");
			return;
		}
		if (!$panel.length) $panel = $("<div>", { class: "tgy-week-menu mb-3" }).insertBefore($grid);
		const $content = $("<div>").appendTo($panel.empty());
		if (unsaved) {
			$grid.show();
			message($content, "请先保存园所、供餐周、学期和原料仓库，再开始编排。");
			return;
		}
		if (tabbed) {
			const explicitTab = frm.layout.tabs.some((tab) => tab.df.fieldname === requestedTab && !tab.is_hidden());
			if (!tab.is_hidden() && (frm.__tgy_week_open_calendar || (opening && frm.doc.meals?.length && !explicitTab))) {
				frm.layout.select_tab(calendarTab);
			}
			frm.__tgy_week_open_calendar = false;
			frm.custom_buttons?.["采购需求预览"]?.off("click.tgyWeekTab")
				.on("click.tgyWeekTab", () => frm.layout.select_tab(basicTab));
		}
		message($content, "正在读取周食谱…");
		try {
			const data = await call("calendar", { week_name: name });
			if (frm.doc.name !== name || !$content.parent().length) return;
			renderCalendar(frm, $content, data, tabbed);
			frm.remove_custom_button("调整本餐菜品");
			frm.custom_buttons?.["从上一周编排"]?.text("从参考周编排");
			$grid.hide();
		} catch {
			if (frm.doc.name !== name || !$content.parent().length) return;
			message($content.empty(), "周食谱读取失败。");
			button($content, "重试", () => refresh(frm));
			$mealSection?.show();
			$grid.show();
		}
	}

	function isCurrentWeek(frm, name) {
		const route = frappe.get_route?.();
		return frm.doc.name === name && (!route || (route[0] === "Form" && route[1] === doctype && route[2] === name));
	}

	async function openMeal(frm, schedule, index, name = frm.doc.name) {
		if (!isCurrentWeek(frm, name) || !editable(frm) || frm.__meal_opening || !canAct(frm)) return;
		const { days, slots } = schedule;
		const dayIndex = Math.floor(index / slots.length);
		const args = { week_name: name, meal_date: days[dayIndex], meal_type: slots[index % slots.length] };
		frm.__meal_opening = true;
		try {
			const meal = await call("get_meal", args);
			if (isCurrentWeek(frm, name) && editable(frm) && canAct(frm)) {
				mealDialog(frm, schedule, index, args, weekdays[dayIndex], meal);
			}
		} catch {
			// Frappe displays the permission or validation error returned by the server.
		} finally {
			frm.__meal_opening = false;
		}
	}

	function mealDialog(frm, schedule, index, args, weekday, meal) {
		const { days, slots, categories } = schedule;
		const hasNext = index < days.length * slots.length - 1;
		const selected = [...meal.dishes];
		const previews = new Map();
		const base = Number(meal.base_headcount);
		let offset = 0;
		let request = 0;
		let $options, $chosen, $counts, $validation, $adjustments;
		let lastOptions = null;
		let expandedBom;
		let closed = false;
		let destination;
		const dialog = new frappe.ui.Dialog({
			title: `${dateLabel(args.meal_date, true)} · ${weekday} · ${args.meal_type}`,
			size: "large",
			no_submit_on_enter: true,
			fields: [
				{ fieldname: "composer", fieldtype: "Section Break" },
				{ fieldname: "catalog_column", fieldtype: "Column Break" },
				{ fieldname: "catalog_heading", fieldtype: "HTML" },
				{ fieldname: "search", fieldtype: "Data", label: "搜索菜品", placeholder: "菜名或编码" },
				{ fieldname: "category", fieldtype: "Select", label: "菜品分类",
					options: [{ label: "全部分类", value: "" }, ...categories], onchange: resetSearch },
				{ fieldname: "all_slots", fieldtype: "Check", label: "显示其他餐次的菜品", onchange: resetSearch },
				{ fieldname: "options", fieldtype: "HTML" },
				{ fieldname: "menu_column", fieldtype: "Column Break" },
				{ fieldname: "counts_summary", fieldtype: "HTML" },
				{ fieldname: "chosen", fieldtype: "HTML" },
				{ fieldname: "adjustments", fieldtype: "HTML" },
				{ fieldname: "excluded_count", fieldtype: "Int", label: "停餐调整人数", default: meal.excluded_count || 0, non_negative: 1,
					onchange: renderCounts },
				{ fieldname: "adjustment_reason", fieldtype: "Small Text", label: "停餐调整原因", default: meal.adjustment_reason },
				{ fieldname: "stopped", fieldtype: "Check", label: "整餐停供", default: Number(meal.stopped), onchange: renderCounts },
				{ fieldname: "reason", fieldtype: "Small Text", label: "整餐停供原因", default: meal.reason, depends_on: "eval:doc.stopped" },
			],
			onhide() { closed = true; },
			primary_action_label: hasNext ? "保存并编排下一餐" : "保存本餐",
			primary_action: (values) => save(values, hasNext),
			secondary_action_label: hasNext ? "保存本餐" : undefined,
			secondary_action: hasNext ? () => {
				const values = dialog.get_values();
				if (values) return save(values, false);
			} : undefined,
		});
		const fields = dialog.fields_dict;
		dialog.$wrapper.addClass("tgy-week-picker").one("hidden.bs.modal", () => {
			dialog.$wrapper.remove();
			if (destination !== undefined) return openMeal(frm, schedule, destination, args.week_name);
		});
		const $previous = button(dialog.header.find(".modal-actions"), "上一餐", () => {
			if (closed || !canAct(frm)) return;
			const leave = () => close(index - 1);
			const changed = selected.length !== meal.dishes.length
				|| selected.some((dish, position) => dish.bom !== meal.dishes[position]?.bom)
				|| ["excluded_count", "stopped"].some((key) => Number(dialog.get_value(key) || 0) !== Number(meal[key] || 0))
				|| ["adjustment_reason", "reason"].some((key) => (dialog.get_value(key) || "") !== (meal[key] || ""));
			if (changed) frappe.confirm("本餐有未保存的修改，是否返回上一餐？", leave);
			else leave();
		}).prop("disabled", index === 0);

		$("<h4>", { class: "tgy-picker-title" }).text("标准菜品库").appendTo(fields.catalog_heading.$wrapper);
		$options = fields.options.$wrapper;
		$chosen = fields.chosen.$wrapper;
		$counts = fields.counts_summary.$wrapper;
		$adjustments = $("<details>", { class: "tgy-picker-adjustments" }).appendTo(fields.adjustments.$wrapper);
		$("<summary>").text("供餐调整").appendTo($adjustments);
		const $adjustmentFields = $("<div>").appendTo($adjustments);
		for (const name of ["excluded_count", "adjustment_reason", "stopped", "reason"]) {
			fields[name].$wrapper.appendTo($adjustmentFields);
			fields[name].$input?.on("input.tgyMeal", () => $validation.text(""));
		}
		$validation = $("<p>", { class: "tgy-picker-validation text-danger", role: "alert" }).appendTo($adjustmentFields);
		fields.search.$input.on("input", frappe.utils.debounce(resetSearch, 250));
		dialog.show();
		renderChosen();
		loadOptions();

		function close(nextIndex) {
			if (closed || !isCurrentWeek(frm, args.week_name)) return;
			destination = nextIndex;
			dialog.hide();
		}

		async function save(values, advance) {
			if (closed || !isCurrentWeek(frm, args.week_name) || !canAct(frm)) return;
			const excluded = Number(values.excluded_count || 0);
			const adjustment = values.adjustment_reason?.trim() || "";
			const reason = values.reason?.trim() || "";
			const stopped = Number(values.stopped || 0);
			if (!Number.isInteger(excluded) || excluded < 0 || excluded >= base) {
				return adjustmentError("停餐调整人数须小于在园人数。", "excluded_count");
			}
			if (excluded && !adjustment) return adjustmentError("请填写停餐调整原因。", "adjustment_reason");
			if (stopped && !reason) return adjustmentError("请填写整餐停供原因。", "reason");

			const primary = dialog.get_primary_btn().prop("disabled", true);
			const secondary = dialog.get_secondary_btn().prop("disabled", true);
			$previous.prop("disabled", true);
			let saved = false;
			try {
				await mutate(frm, "save_meal", {
					...args, modified: meal.modified, boms: JSON.stringify(selected.map((dish) => dish.bom)),
					excluded_count: excluded, adjustment_reason: adjustment, stopped, reason,
				}, () => { saved = true; });
			} catch {
				// Keep the current meal open if Frappe rejected the save.
			} finally {
				primary.prop("disabled", false);
				secondary.prop("disabled", false);
				$previous.prop("disabled", index === 0);
			}
			if (saved && !closed) {
				frappe.show_alert({ message: "本餐草稿已保存", indicator: "green" });
				close(advance ? index + 1 : undefined);
			}
		}

		function adjustmentError(text, fieldname) {
			$adjustments.prop("open", true);
			$validation.text(text);
			fields[fieldname].$input?.trigger("focus");
		}

		function renderCounts() {
			if (!$counts) return;
			const $summary = $("<div>", { class: "tgy-picker-heading tgy-picker-counts" }).appendTo($counts.empty());
			$("<h4>", { class: "tgy-picker-title" }).text(`本餐菜单 · ${selected.length} 道`).appendTo($summary);
			const excluded = Number(dialog.get_value("excluded_count") || 0);
			const stopped = Number(dialog.get_value("stopped"));
			const planned = !Number.isInteger(excluded) || excluded < 0 || excluded >= base
				? "请核对停餐调整人数" : stopped ? "整餐停供" : `计划供餐 ${base - excluded} 人`;
			$("<strong>", { role: "status" }).text(planned).appendTo($summary);
		}

		function resetSearch() {
			if (!$options || closed) return;
			offset = 0;
			return loadOptions();
		}

		function renderChosen(focusBom, focusAction) {
			renderCounts();
			const $list = $("<div>", { class: "tgy-picker-list" }).appendTo($chosen.empty());
			if (!selected.length) message($list, "请从标准菜品库添加本餐菜品。");
			let $focus;
			selected.forEach((dish, position) => {
				const $entry = $("<div>").appendTo($list);
				const $row = $("<div>", { class: "tgy-picker-row" }).appendTo($entry);
				const $label = $("<div>", { class: "tgy-picker-name" }).appendTo($row);
				$("<span>").text(dish.name).appendTo($label);
				if (dish.category) $("<small>").text(dish.category).appendTo($label);
				const $actions = $("<div>", { class: "tgy-picker-row-actions" }).appendTo($row);
				const expanded = expandedBom === dish.bom;
				const $quantity = button($actions, "带量", () => {
					expandedBom = expanded ? undefined : dish.bom;
					renderChosen(dish.bom, "quantity");
				}).attr({ "aria-expanded": String(expanded), "aria-label": `查看${dish.name}的带量` });
				const $up = button($actions, "↑", () => move(-1, "up"))
					.attr({ "aria-label": `上移${dish.name}`, title: "上移" }).prop("disabled", position === 0);
				const $down = button($actions, "↓", () => move(1, "down"))
					.attr({ "aria-label": `下移${dish.name}`, title: "下移" }).prop("disabled", position === selected.length - 1);
				const $remove = button($actions, "×", () => {
					selected.splice(position, 1);
					if (expanded) expandedBom = undefined;
					renderChosen(selected[Math.min(position, selected.length - 1)]?.bom, "remove");
					renderOptions(lastOptions, $options.find(".tgy-picker-options").scrollTop());
					if (!selected.length) fields.search.$input.trigger("focus");
				}).attr({ "aria-label": `移除${dish.name}`, title: "移除" });
				if (expanded) renderIngredients($entry, dish);
				if (focusBom === dish.bom) {
					const actions = { quantity: $quantity, up: position > 0 ? $up : $down,
						down: position < selected.length - 1 ? $down : $up, remove: $remove };
					$focus = actions[focusAction];
				}

				function move(by, action) {
					const target = position + by;
					[selected[position], selected[target]] = [selected[target], selected[position]];
					renderChosen(dish.bom, action);
				}
			});
			$focus?.trigger("focus");
		}

		async function renderIngredients($entry, dish) {
			const $detail = $("<div>", { class: "tgy-picker-detail", role: "status" }).appendTo($entry);
			$detail.text("正在读取带量…");
			if (!previews.has(dish.bom)) {
				previews.set(dish.bom, call("ingredients", { week_name: args.week_name, bom_name: dish.bom }));
			}
			try {
				const ingredients = await previews.get(dish.bom);
				$detail.empty();
				$("<strong>").text("人均采购毛重").appendTo($detail);
				$("<div>").text(ingredients?.map((row) => `${row.name} ${row.gross ?? "—"} ${row.uom || ""}`).join("；")
					|| "暂无可查看的带量。").appendTo($detail);
			} catch {
				previews.delete(dish.bom);
				$detail.text("带量读取失败。可收起后重新打开。");
			}
		}

		async function loadOptions() {
			const sequence = ++request;
			lastOptions = null;
			message($options.empty(), "正在查找标准菜品…");
			try {
				const result = await call("dishes", {
					week_name: args.week_name, meal_type: args.meal_type, start: offset,
					search: dialog.get_value("search") || "", category: dialog.get_value("category") || "",
					all_slots: dialog.get_value("all_slots") || 0,
				});
				if (!closed && sequence === request) {
					lastOptions = result;
					renderOptions(result);
				}
			} catch {
				if (!closed && sequence === request) {
					message($options.empty(), "菜品读取失败。");
					button($options, "重试", loadOptions);
				}
			}
		}

		function renderOptions(result, scrollTop = 0, afterItem) {
			if (!result) return;
			const $list = $("<div>", { class: "tgy-picker-list tgy-picker-options" }).appendTo($options.empty());
			if (!result.rows.length) message($list, "暂无符合条件的标准菜品。");
			let passedItem = false;
			let $nextOption;
			for (const dish of result.rows) {
				const $entry = $("<div>").appendTo($list);
				const $row = $("<div>", { class: "tgy-picker-row" }).appendTo($entry);
				const $label = $("<div>", { class: "tgy-picker-name" }).appendTo($row);
				$("<span>").text(dish.name).appendTo($label);
				if (dish.category) $("<small>").text(dish.category).appendTo($label);
				if (!dish.bom) {
					$("<span>", { class: "text-muted" }).text(dish.status).appendTo($row);
					continue;
				}
				const picked = selected.some((item) => item.item === dish.item);
				const $add = button($row, picked ? "已选" : "添加", () => {
					if (closed || frm.__meal_action_running) return;
					if (selected.length >= 20) return frappe.msgprint("每餐最多选择 20 道菜。");
					selected.push(dish);
					renderChosen();
					renderOptions(result, $list.scrollTop(), dish.item);
				}).attr("aria-label", `${picked ? "已选" : "添加"}${dish.name}`).prop("disabled", picked);
				if (passedItem && !picked && !$nextOption) $nextOption = $add;
				if (afterItem === dish.item) passedItem = true;
			}
			if (offset || result.has_more) {
				const $pages = $("<div>", { class: "tgy-picker-pages" }).appendTo($options);
				if (offset) button($pages, "上一页", () => { offset -= result.page_size; return loadOptions(); });
				if (result.has_more) button($pages, "下一页", () => { offset += result.page_size; return loadOptions(); });
			}
			$list.scrollTop(scrollTop);
			if (afterItem) ($nextOption || fields.search.$input).trigger("focus");
		}
	}

	frappe.ui.form.on(doctype, {
		refresh,
		before_save(frm) {
			frm.__tgy_week_first_save = Boolean(frm.is_new());
		},
		after_save(frm) {
			frm.__tgy_week_open_calendar = frm.__tgy_week_first_save;
			frm.__tgy_week_first_save = false;
		},
	});
})();
