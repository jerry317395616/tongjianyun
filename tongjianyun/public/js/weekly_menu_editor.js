(() => {
	const api = "tongjianyun.weekly_menu_editor.";
	const doctype = "Meal Planning Week";
	const basicTab = "custom_tjy_week_basic_tab";
	const calendarTab = "custom_tjy_week_calendar_tab";
	const weekdays = ["周一", "周二", "周三", "周四", "周五"];
	const editable = (frm) => frm.doc.docstatus === 0 && !!frm.perm?.[0]?.write;
	let styles;
	let openedWeek;
	let activeDrawer;
	let requestedTab = window.location.hash.slice(1);
	frappe.router?.on?.("change", () => {
		const [view, type, name] = frappe.get_route();
		if (activeDrawer && (view !== "Form" || type !== doctype || name !== activeDrawer.name)) {
			activeDrawer.dialog.hide();
		}
		if (view !== "Form" || type !== doctype || name !== openedWeek) {
			openedWeek = undefined;
			requestedTab = window.location.hash.slice(1);
		}
	});
	function loadStyles() {
		// The Frappe asset loader looks for the file extension after the version query.
		styles ??= Promise.resolve(frappe.require(window.tjyMealPortions.stylesheet))
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

	function weekEntries(data) {
		const meals = new Map(data.meals.map((meal) => [`${meal.date}:${meal.slot}`, meal]));
		return data.days.flatMap((day, dayIndex) => data.slots.map((slot) => {
			const meal = meals.get(`${day}:${slot}`);
			const state = meal?.stopped ? "stopped" : meal?.menu ? "scheduled" : "pending";
			return { day, dayIndex, slot, meal, state };
		}));
	}

	function focusMeal(frm, name, index) {
		if (!isCurrentWeek(frm, name)) return;
		const calendar = frm.__tgy_calendar;
		if (calendar?.name !== name || !calendar.cells[index]) {
			frm.__tgy_meal_focus = { name, index };
			return;
		}
		const cell = calendar.cells[index][0];
		cell?.focus({ preventScroll: true });
		cell?.scrollIntoView({ block: "nearest", inline: "nearest" });
	}

	function renderCalendar(frm, $panel, data, previousCalendar) {
		const { days, slots, initialized } = data;
		const canEdit = editable(frm);
		const entries = weekEntries(data);
		const total = entries.length;
		const stopped = entries.filter(({state}) => state === "stopped").length;
		const scheduled = entries.filter(({state}) => state === "scheduled").length;
		const pending = total - scheduled - stopped;
		const today = frappe.datetime?.get_today?.();
		const name = frm.doc.name;
		const cells = [];
		const scrollLeft = previousCalendar?.name === name ? previousCalendar.scroll.scrollLeft() : 0;
		$panel.empty();
		const $headBand = $("<div>", { class: "tgy-week-overview" }).appendTo($panel);
		const $heading = $("<div>").appendTo($headBand);
		const start = days[0];
		const end = days.at(-1);
		const period = `${dateLabel(start, true)} – ${dateLabel(end, start.slice(0, 4) !== end.slice(0, 4))}`;
		$("<div>", { class: "tgy-week-period" }).text(frm.doc.company || "供餐周历").appendTo($heading);
		$("<h3>", { class: "tgy-week-title" }).text(period).appendTo($heading);
		if (canEdit && !initialized) {
			const $actions = $("<div>", { class: "tgy-week-actions" }).appendTo($headBand);
			button($actions, "空白编排", () => startWeek(frm, false), true);
			button($actions, "复制上周", () => startWeek(frm, true));
		}
		if (initialized) {
			const $progress = $("<div>", { class: "tgy-week-progress" }).appendTo($headBand);
			const $summary = $("<div>", { class: "tgy-week-summary", role: "status" }).appendTo($progress);
			for (const [label, count, state] of [["已编排", scheduled, "scheduled"], ["停餐", stopped, "stopped"], ["待编排", pending, "pending"]]) {
				const $stat = $("<span>", { class: `tgy-week-stat tgy-${state}` }).appendTo($summary);
				$("<strong>").text(count).appendTo($stat);
				$("<span>").text(label).appendTo($stat);
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
			const $slot = $("<th>", { scope: "row" }).appendTo($row);
			$("<span>", { class: `tgy-week-slot tgy-slot-${slotIndex}` }).text(slot).appendTo($slot);
			for (const [dayIndex, day] of days.entries()) {
				const index = dayIndex * slots.length + slotIndex;
				const { meal, state } = entries[index];
				const label = meal?.stopped ? "整餐停供" : meal?.menu || "未编排";
				const $cell = $("<td>").appendTo($row);
				const cellClass = `tgy-meal-cell tgy-${state}`;
				let $card;
				if (canEdit && initialized) {
					$card = $("<button>", { type: "button", class: cellClass, "aria-label": `${day} ${slot} ${label}`,
						"aria-haspopup": "dialog" }).on("click", () => openMeal(frm, data, index)).appendTo($cell);
				} else {
					$card = $("<div>", { class: cellClass }).appendTo($cell);
				}
				cells[index] = $card;
				if (state === "scheduled") {
					const names = meal.menu.split("、");
					if (names.length > 3) $card.attr("title", meal.menu);
					for (const dish of names.slice(0, 3)) {
						$("<span>", { class: "tgy-meal-name" }).text(dish).appendTo($card);
					}
					const rest = names.length > 3 ? `另有 ${names.length - 3} 道 · ` : "";
					$("<span>", { class: "tgy-meal-note" }).text(`${rest}${meal.headcount} 人`).appendTo($card);
				} else {
					const text = state === "pending" && canEdit && initialized ? "+ 添加菜品" : label;
					$("<span>", { class: "tgy-meal-name" }).text(text).appendTo($card);
					if (meal?.stopped && meal.reason) $("<span>", { class: "tgy-meal-note" }).text(meal.reason).appendTo($card);
				}
			}
		}
		frm.__tgy_calendar = { name, data, cells, scroll: $scroll };
		$scroll.scrollLeft(scrollLeft);
		if (frm.__tgy_meal_focus?.name === name) {
			focusMeal(frm, name, frm.__tgy_meal_focus.index);
			delete frm.__tgy_meal_focus;
		}
		if (canEdit && pending) {
			frm.remove_custom_button("采购需求预览");
			frm.remove_custom_button("核对账面库存");
			frm.remove_custom_button("确认采购毛重口径", "采购操作");
		}
	}

	function openReview(frm) {
		if (!canSubmit(frm) || !canAct(frm) || activeDrawer || frm.__meal_opening) return;
		const name = frm.doc.name;
		const dialog = new frappe.ui.Dialog({
			title: "提交前核对",
			animate: true,
			no_submit_on_enter: true,
			fields: [{ fieldtype: "HTML", fieldname: "review" }],
			primary_action_label: "确认提交",
			primary_action() {
				if (!ready || !canSubmit(frm) || !isCurrentWeek(frm, name) || !canAct(frm)) return;
				close(() => frm.savesubmit());
			},
		});
		let ready = false;
		let afterClose;
		activeDrawer = { dialog, name };
		dialog.$wrapper.addClass("tgy-week-drawer tgy-week-review").one("hidden.bs.modal", () => {
			activeDrawer = undefined;
			dialog.$wrapper.remove();
			if (isCurrentWeek(frm, name)) return afterClose?.();
		});
		const $body = dialog.fields_dict.review.$wrapper;
		dialog.get_primary_btn().prop("disabled", true);
		dialog.show();
		load();

		function close(action) {
			afterClose = action;
			return dialog.hide();
		}

		async function load() {
			message($body.empty(), "正在核对本周餐次…");
			try {
				const data = await call("calendar", { week_name: name });
				if (activeDrawer?.dialog !== dialog || !isCurrentWeek(frm, name)) return;
				render(data);
			} catch {
				message($body.empty(), "核对清单读取失败。");
				button($body, "重试", load);
			}
		}

		function render(data) {
			$body.empty();
			const entries = weekEntries(data);
			const pending = entries.filter(({state}) => state === "pending").length;
			const $progress = $("<div>", { class: "tgy-review-progress" }).appendTo($body);
			$("<span>").text("已处理餐次（含停餐）").appendTo($progress);
			$("<strong>").text(`${entries.length - pending} / ${entries.length}`).appendTo($progress);
			$("<progress>", { value: entries.length - pending, max: entries.length,
				"aria-label": "已处理餐次" }).appendTo($progress);

			for (const [state, title] of [["pending", "待编排"], ["stopped", "已停餐"]]) {
				const list = entries.filter((entry) => entry.state === state);
				const $group = $("<section>", { class: `tgy-review-group tgy-${state}` }).appendTo($body);
				$("<h4>").text(`${title} · ${list.length} 餐`).appendTo($group);
				if (!data.initialized && state === "pending") {
					button($group, "返回周历开始编排", () => close(() => frm.layout.select_tab(calendarTab)));
					continue;
				}
				const $list = $("<div>", { class: "tgy-review-list" }).appendTo($group);
				for (const entry of list) {
					const index = entry.dayIndex * data.slots.length + data.slots.indexOf(entry.slot);
					const label = `${weekdays[entry.dayIndex]} · ${entry.slot}`;
					const $row = $("<div>", { class: "tgy-review-row" }).appendTo($list);
					const $label = $("<div>").appendTo($row);
					$("<strong>").text(label).appendTo($label);
					const detail = state === "stopped" ? entry.meal.reason : dateLabel(entry.day);
					if (detail) $("<small>").text(detail).appendTo($label);
					if (editable(frm)) button($row, state === "pending" ? "去编排" : "查看", () => close(() => {
						frm.layout.select_tab(calendarTab);
						focusMeal(frm, name, index);
						return openMeal(frm, data, index);
					})).attr("aria-label", `${label} ${state === "pending" ? "去编排" : "查看停餐"}`);
				}
			}
			const stockReviewed = Boolean(Number(frm.doc.stock_reviewed));
			const weightConfirmed = frm.doc.requirement_weight_basis === "采购毛重";
			const sameReviewer = frm.doc.owner && frm.doc.owner === frappe.session?.user;
			const stale = data.modified && frm.doc.modified && data.modified !== frm.doc.modified;
			const $checks = $("<section>", { class: "tgy-review-group" }).appendTo($body);
			$("<h4>").text("采购与审核").appendTo($checks);
			$("<p>").text(weightConfirmed ? "采购毛重口径已确认" : "待确认采购毛重口径").appendTo($checks);
			$("<p>").text(stockReviewed ? "账面库存已核对" : "待核对采购需求与账面库存").appendTo($checks);
			const preview = frm.custom_buttons?.["采购需求预览"];
			if (!pending && preview) button($checks, "采购需求预览", () => close(() => {
				frm.layout.select_tab(basicTab);
				preview.trigger("click");
			}));
			if (sameReviewer) $("<p>").text("请由另一位有权限的审核人提交。").appendTo($checks);
			if (stale) button($checks, "食谱已有更新，刷新后核对", () => close(() => frm.reload_doc()));
			ready = data.initialized && !pending && stockReviewed && weightConfirmed && !sameReviewer && !stale;
			dialog.get_primary_btn().prop("disabled", !ready);
		}
	}

	function canSubmit(frm) {
		return frm.doc.docstatus === 0 && !frm.is_new() && frm.perm?.[0]?.submit
			&& !frappe.model?.has_workflow(doctype) && frm.toolbar?.get_action_status() === "Submit";
	}

	function openTaskDestination(frm) {
		const target = frappe.tjy_week_task_destination;
		if (!target || target.name !== frm.doc.name || !isCurrentWeek(frm, target.name)) return;
		delete frappe.tjy_week_task_destination;
		frm.layout.select_tab(basicTab);
		const procurement = target.section === "procurement";
		if (procurement) frm.custom_buttons?.[__("采购需求预览")]?.trigger("click");
		const field = procurement ? "procurement_html" : "kitchen_reconciled";
		const section = frm.fields_dict[field]?.$wrapper?.closest(".form-section");
		section?.[0]?.scrollIntoView({ block: "center" });
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
		if (tabbed) $calendar.closest(".form-section").addClass("tgy-week-calendar-section");
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
		const previousCalendar = frm.__tgy_calendar;
		delete frm.__tgy_calendar;
		if (unsaved) {
			$grid.show();
			message($content, "请先保存园所、供餐周、学期和原料仓库，再开始编排。");
			return;
		}
		if (canSubmit(frm)) frm.page.set_primary_action(__("Submit"), () => openReview(frm), "check");
		if (tabbed) {
			const explicitTab = frm.layout.tabs.some((tab) => tab.df.fieldname === requestedTab && !tab.is_hidden());
			if (!tab.is_hidden() && (frm.__tgy_week_open_calendar || (opening && !explicitTab))) {
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
			renderCalendar(frm, $content, data, previousCalendar);
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
		openTaskDestination(frm);
	}

	function isCurrentWeek(frm, name) {
		const route = frappe.get_route?.();
		return frm.doc.name === name && (!route || (route[0] === "Form" && route[1] === doctype && route[2] === name));
	}

	async function openMeal(frm, schedule, index, name = frm.doc.name) {
		if (!isCurrentWeek(frm, name) || !editable(frm) || frm.__meal_opening || activeDrawer || !canAct(frm)) return;
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
		const dayStart = index - (index % slots.length);
		const dayEntries = weekEntries(schedule).slice(dayStart, dayStart + slots.length);
		const hasNext = index < days.length * slots.length - 1;
		const selected = [...meal.dishes];
		const portions = new Map();
		const previews = new Map();
		const base = Number(meal.base_headcount);
		let offset = 0;
		let request = 0;
		let $options, $chosen, $counts, $validation, $adjustments;
		let lastOptions = null;
		let expandedBom;
		let updatePortionTotals;
		let portionView = 0;
		let closed = false;
		let destination;
		const dialog = new frappe.ui.Dialog({
			title: `${dateLabel(args.meal_date, true)} · ${weekday} · ${args.meal_type}`,
			size: "large",
			static: true,
			animate: true,
			no_submit_on_enter: true,
			fields: [
				{ fieldname: "day_meals", fieldtype: "HTML" },
				{ fieldname: "composer", fieldtype: "Section Break" },
				{ fieldname: "catalog_column", fieldtype: "Column Break" },
				{ fieldname: "catalog_heading", fieldtype: "HTML" },
				{ fieldname: "search", fieldtype: "Data", label: "搜索菜品", placeholder: "菜名或编码" },
				{ fieldname: "catalog_slot", fieldtype: "Select", label: "餐次", default: args.meal_type,
					options: [{ label: `当前餐次 · ${args.meal_type}`, value: args.meal_type },
						...slots.filter((slot) => slot !== args.meal_type), { label: "全部餐次", value: "all" }],
					onchange: resetSearch },
				{ fieldname: "category", fieldtype: "Select", label: "菜品分类",
					options: [{ label: "全部分类", value: "" }, ...categories, "未分类"], onchange: resetSearch },
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
			primary_action_label: "保存本餐",
			primary_action: (values) => save(values, false),
			secondary_action_label: hasNext ? "保存并编排下一餐" : undefined,
			secondary_action: hasNext ? () => {
				const values = dialog.get_values();
				if (values) return save(values, true);
			} : undefined,
		});
		const fields = dialog.fields_dict;
		dialog.$wrapper.addClass("tgy-week-drawer tgy-week-picker").one("hidden.bs.modal", () => {
			activeDrawer = undefined;
			dialog.$wrapper.remove();
			focusMeal(frm, args.week_name, destination ?? index);
			if (destination !== undefined) return openMeal(frm,
				frm.__tgy_calendar?.data || schedule, destination, args.week_name);
		});
		activeDrawer = { dialog, name: args.week_name };
		const $actions = dialog.header.find(".modal-actions");
		const $previous = button($actions, "上一餐", () => leave(index - 1)).prop("disabled", index === 0);
		const $return = button($actions, "返回周历", () => leave());
		dialog.$wrapper.on("keydown.tgyMeal", (event) => {
			if (event.key === "Escape") {
				event.preventDefault();
				leave();
			}
		});
		const $day = $("<div>", { class: "tgy-picker-day", role: "group", "aria-label": "当天餐次" })
			.appendTo(fields.day_meals.$wrapper);
		for (const [offset, entry] of dayEntries.entries()) {
			const target = dayStart + offset;
			const active = target === index;
			const status = {scheduled: "已编排", stopped: "停餐", pending: "待编排"}[entry.state];
			const $slot = button($day, entry.slot, () => leave(target))
				.attr({ "aria-current": active ? "true" : undefined, "aria-label": `${entry.slot} ${status}` })
				.prop("disabled", active);
			$("<small>", { class: `tgy-${entry.state}` }).text(status).appendTo($slot);
		}

		function leave(nextIndex) {
			if (closed || !canAct(frm)) return;
			const changed = portions.size || selected.length !== meal.dishes.length
				|| selected.some((dish, position) => dish.bom !== meal.dishes[position]?.bom)
				|| ["excluded_count", "stopped"].some((key) => Number(dialog.get_value(key) || 0) !== Number(meal[key] || 0))
				|| ["adjustment_reason", "reason"].some((key) => (dialog.get_value(key) || "") !== (meal[key] || ""));
			if (changed) frappe.confirm("本餐有未保存的修改，是否离开本餐？", () => close(nextIndex));
			else close(nextIndex);
		}

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
			if (!Number.isInteger(excluded) || excluded < 0 || (excluded >= base && (!stopped || excluded))) {
				return adjustmentError("停餐调整人数须小于在园人数。", "excluded_count");
			}
			if (excluded && !adjustment) return adjustmentError("请填写停餐调整原因。", "adjustment_reason");
			if (stopped && !reason) return adjustmentError("请填写整餐停供原因。", "reason");

			const primary = dialog.get_primary_btn().prop("disabled", true);
			const secondary = dialog.get_secondary_btn().prop("disabled", true);
			$previous.prop("disabled", true);
			$return.prop("disabled", true);
			let saved = false;
			try {
				await mutate(frm, "save_meal", {
					...args, modified: meal.modified, boms: JSON.stringify(selected.map((dish) => dish.bom)),
					excluded_count: excluded, adjustment_reason: adjustment, stopped, reason,
					portions: JSON.stringify(Object.fromEntries(portions)),
				}, () => { saved = true; });
			} catch {
				// Keep the current meal open if Frappe rejected the save.
			} finally {
				primary.prop("disabled", false);
				secondary.prop("disabled", false);
				$previous.prop("disabled", index === 0);
				$return.prop("disabled", false);
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
			const planned = !Number.isInteger(excluded) || excluded < 0 || (excluded >= base && (!stopped || excluded))
				? "请核对停餐调整人数" : stopped ? "整餐停供" : `计划供餐 ${base - excluded} 人`;
			$("<strong>", { role: "status" }).text(planned).appendTo($summary);
			updatePortionTotals?.();
		}

		function servingCount() {
			if (Number(dialog.get_value("stopped"))) return 0;
			const count = base - Number(dialog.get_value("excluded_count") || 0);
			return Number.isInteger(count) && count > 0 && count <= base ? count : null;
		}

		function resetSearch() {
			if (!$options || closed) return;
			offset = 0;
			return loadOptions();
		}

		function renderChosen(focusBom, focusAction) {
			portionView += 1;
			updatePortionTotals = undefined;
			renderCounts();
			const $list = $("<div>", { class: "tgy-picker-list" }).appendTo($chosen.empty());
			if (!selected.length) message($list, "请从标准菜品库添加本餐菜品。");
			let $focus;
			selected.forEach((dish, position) => {
				const $entry = $("<div>").appendTo($list);
				const $row = $("<div>", { class: "tgy-picker-row" }).appendTo($entry);
				const $label = $("<div>", { class: "tgy-picker-name" }).appendTo($row);
				const sameName = selected.some((other) => other !== dish && other.name === dish.name);
				const label = sameName ? `${dish.name}（${dish.item}）` : dish.name;
				$("<span>").text(dish.name).appendTo($label);
				$("<small>").text(sameName ? `${dish.category || "未分类"} · ${dish.item}` : dish.category || "未分类").appendTo($label);
				const $actions = $("<div>", { class: "tgy-picker-row-actions" }).appendTo($row);
				button($actions, "配餐提示", async () => {
					const {message: notes} = await frappe.call({method:"tongjianyun.canteen_ops.meal_operations.dish_notes",
						type:"GET", args:{week_name:frm.doc.name, bom_name:dish.bom, service_date:args.meal_date}});
					const d=new frappe.ui.Dialog({title:"配餐提示",fields:[{fieldname:"notes",fieldtype:"HTML"}]});
					const panel=d.fields_dict.notes.$wrapper;
					$("<p>").text("配方标注过敏原："+(notes.allergens||"未标注")).appendTo(panel);
					$("<p>").text("特殊餐匹配："+(notes.conflicts?.join("、")||"请核对已确认的饮食安排")).appendTo(panel);
					if (notes.latest) $("<p>").text("最近观察 · "+notes.latest.date+" · "+(notes.latest.reason||notes.latest.acceptance)).appendTo(panel);
					for(const row of notes.feedback) $("<p>").text(row.acceptance+" · "+row.observations+" 次班级观察").appendTo(panel);
					d.show();
				});
				const expanded = expandedBom === dish.bom;
				const $quantity = button($actions, "食材用量", () => {
					expandedBom = expanded ? undefined : dish.bom;
					renderChosen(dish.bom, "quantity");
				}).attr({ "aria-expanded": String(expanded), "aria-label": `查看${label}的食材用量` });
				const $up = button($actions, "↑", () => move(-1, "up"))
					.attr({ "aria-label": `上移${label}`, title: "上移" }).prop("disabled", position === 0);
				const $down = button($actions, "↓", () => move(1, "down"))
					.attr({ "aria-label": `下移${label}`, title: "下移" }).prop("disabled", position === selected.length - 1);
				const $remove = button($actions, "×", () => {
					selected.splice(position, 1);
					portions.delete(dish.bom);
					if (expanded) expandedBom = undefined;
					renderChosen(selected[Math.min(position, selected.length - 1)]?.bom, "remove");
					renderOptions(lastOptions, $options.find(".tgy-picker-options").scrollTop());
					if (!selected.length) fields.search.$input.trigger("focus");
				}).attr({ "aria-label": `移除${label}`, title: "移除" });
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
			const view = portionView;
			const $detail = $("<div>", { class: "tgy-picker-detail" }).appendTo($entry);
			$detail.text("正在读取食材用量…");
			if (!previews.has(dish.bom)) {
				previews.set(dish.bom, window.tjyMealPortions.load({ ...args, bom_name: dish.bom }));
			}
			try {
				const data = await previews.get(dish.bom);
				if (closed || view !== portionView) return;
				updatePortionTotals = window.tjyMealPortions.render($detail, data, portions.get(dish.bom), servingCount,
					(changes) => { portions.set(dish.bom, changes); });
			} catch {
				previews.delete(dish.bom);
				$detail.text("食材用量读取失败。可收起后重新打开。");
			}
		}

		async function loadOptions() {
			const sequence = ++request;
			lastOptions = null;
			message($options.empty(), "正在查找标准菜品…");
			try {
				const slot = dialog.get_value("catalog_slot") || args.meal_type;
				const result = await call("dishes", {
					week_name: args.week_name, meal_type: slot === "all" ? args.meal_type : slot, start: offset,
					search: dialog.get_value("search") || "", category: dialog.get_value("category") || "",
					all_slots: Number(slot === "all"),
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
			const $list = $("<div>", { class: "tgy-picker-options" }).appendTo($options.empty());
			const $table = $("<table>", { class: "tgy-picker-table", "aria-label": "标准菜品列表" }).appendTo($list);
			const $head = $("<tr>").appendTo($("<thead>").appendTo($table));
			for (const label of ["菜品名称", "适用餐次", "菜品分类", "操作"]) {
				$("<th>", { scope: "col" }).text(label).appendTo($head);
			}
			const $body = $("<tbody>").appendTo($table);
			if (!result.rows.length) message($list, "暂无符合条件的标准菜品。");
			let passedItem = false;
			let $nextOption;
			for (const dish of result.rows) {
				const $row = $("<tr>").appendTo($body);
				const $label = $("<th>", { scope: "row", class: "tgy-picker-name" }).appendTo($row);
				const $identity = $("<div>", { class: "tgy-picker-identity" }).appendTo($label);
				if (typeof dish.image === "string" && /^\/(?:files|private\/files)\/[^/]/.test(dish.image)) {
					$("<img>", { src: dish.image, alt: "", loading: "lazy", class: "tgy-picker-thumb" })
						.on("error", function () { $(this).remove(); }).appendTo($identity);
				}
				const $names = $("<div>").appendTo($identity);
				$("<span>").text(dish.name).appendTo($names);
				$("<small>").text(dish.item).appendTo($names);
				const $slots = $("<div>", { class: "tgy-picker-slots" }).appendTo($("<td>").appendTo($row));
				for (const slot of dish.meal_slots || []) {
					$(slot === args.meal_type ? "<strong>" : "<span>").text(slot).appendTo($slots);
				}
				if (!dish.meal_slots?.length) $slots.text("未限定");
				$("<td>").text(dish.category || "未分类").appendTo($row);
				const $actions = $("<td>", { class: "tgy-picker-option-action" }).appendTo($row);
				if (!dish.bom) {
					$("<span>", { class: "text-muted" }).text(dish.status).appendTo($actions);
					continue;
				}
				const picked = selected.some((item) => item.item === dish.item);
				const $add = button($actions, picked ? "已选" : "添加", () => {
					if (closed || frm.__meal_action_running) return;
					if (selected.length >= 20) return frappe.msgprint("每餐最多选择 20 道菜。");
					selected.push(dish);
					renderChosen();
					renderOptions(result, $list.scrollTop(), dish.item);
				}).attr("aria-label", `${picked ? "已选" : "添加"}${dish.name}（${dish.item}）`).prop("disabled", picked);
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
		setup(frm) {
			frm.set_query("custom_tjy_canteen", () => ({ filters: { company: frm.doc.company, disabled: 0 } }));
		},
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
