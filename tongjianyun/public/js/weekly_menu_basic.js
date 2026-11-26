(() => {
	const basicTab = "custom_tjy_week_basic_tab";
	const calendarTab = "custom_tjy_week_calendar_tab";
	const icons = {
		calendar: "calendar-days",
		settings: "utensils",
		people: "users",
		record: "notepad-text",
		procurement: "shopping-basket",
		kitchen: "chef-hat",
		notes: "sticky-note",
	};
	const setupFields = ["company", "custom_tjy_canteen", "academic_year", "academic_term",
		"raw_material_warehouse", "kitchen_warehouse", "week_start", "week_end"];
	const details = ["title", "template_week_start", "source_week", "revision", "status", "amended_from"];
	const weekday = new Intl.DateTimeFormat("zh-CN", { weekday: "short", timeZone: "UTC" });
	const date = new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", timeZone: "UTC" });
	const year = new Intl.DateTimeFormat("zh-CN", { year: "numeric", timeZone: "UTC" });

	function displayPeriod(doc) {
		const start = new Date(`${doc.week_start}T00:00:00Z`);
		const end = new Date(`${doc.week_end}T00:00:00Z`);
		if (!Number.isFinite(start.getTime())) return ["设置供餐周", ""];
		if (!Number.isFinite(end.getTime())) return [date.format(start), year.format(start)];
		if (year.format(start) !== year.format(end)) {
			return [`${year.format(start)}${date.format(start)} — ${year.format(end)}${date.format(end)}`, ""];
		}
		return [`${date.format(start)} — ${date.format(end)}`,
			`${year.format(start)} · ${weekday.format(start)}至${weekday.format(end)}`];
	}

	function mark($parent, key) {
		return $("<span>", { class: "tgy-basic-mark", "aria-hidden": "true" })
			.html(frappe.utils.icon(icons[key], "sm")).appendTo($parent);
	}

	function heading(section, label, key) {
		const $head = $("<div>", { class: "tgy-basic-head" }).prependTo(section.wrapper);
		mark($head, key);
		$("<h3>").text(label).appendTo($head);
		return $head;
	}

	function action($head, label, handler) {
		const $button = $("<button>", { type: "button", class: "tgy-basic-action" }).appendTo($head);
		$("<span>").text(label).appendTo($button);
		$("<span>", { "aria-hidden": "true" }).text("→").appendTo($button);
		return $button.on("click", handler);
	}

	function fold(section, label, key) {
		const $button = $("<button>", {
			type: "button", class: "tgy-basic-fold", "aria-expanded": "false",
		}).prependTo(section.wrapper);
		mark($button, key);
		$("<span>", { class: "tgy-basic-fold-title" }).text(label).appendTo($button);
		const $status = $("<span>", { class: "tgy-basic-fold-status" }).appendTo($button);
		$("<span>", { class: "tgy-basic-chevron", "aria-hidden": "true" }).appendTo($button);
		section.collapse(true);
		$button.on("click", () => {
			const open = section.is_collapsed();
			section.collapse(!open);
			$button.attr("aria-expanded", String(open));
		});
		return $status;
	}

	function install(frm, $pane, { planning, population, procurement, kitchen, notes }) {
		const $hero = $("<div>", { class: "tgy-basic-hero" }).insertBefore(planning.wrapper);
		const $school = $("<div>", { class: "tgy-basic-school" }).appendTo($hero);
		mark($school, "calendar");
		const $company = $("<span>").appendTo($school);
		const $dates = $("<h2>").appendTo($hero);
		const $period = $("<p>").appendTo($hero);

		const $setup = $("<div>", { class: "tgy-basic-setup" }).insertBefore(planning.wrapper);
		$setup.append(planning.wrapper, population.wrapper);
		planning.wrapper.removeClass("tgy-week-settings").addClass("tgy-basic-planning");
		population.wrapper.addClass("tgy-basic-population");
		heading(planning, "供餐设置", "settings");
		const $setupFields = planning.columns[0].form.addClass("tgy-basic-setup-fields");
		for (const field of setupFields) frm.fields_dict[field]?.$wrapper?.appendTo($setupFields);
		const $calendar = action(heading(population, "供餐人数依据", "people"), "查看供餐周历", () => {
			frm.layout.select_tab(calendarTab);
			frm.fields_dict.custom_tjy_week_calendar?.$wrapper[0]?.scrollIntoView({ block: "start" });
		});

		const $record = $("<details>", { class: "tgy-basic-record" }).insertAfter($setup);
		const $summary = $("<summary>").appendTo($record);
		mark($summary, "record");
		$("<span>", { class: "tgy-basic-fold-title" }).text("编排记录").appendTo($summary);
		const $version = $("<span>", { class: "tgy-basic-version" }).appendTo($summary);
		$("<span>", { class: "tgy-basic-chevron", "aria-hidden": "true" }).appendTo($summary);
		const $fields = $("<form>", { class: "tgy-basic-record-fields" }).appendTo($record).on("submit", () => false);
		for (const field of details) frm.fields_dict[field]?.$wrapper?.appendTo($fields);

		procurement.wrapper.addClass("tgy-basic-procurement");
		const $preview = action(heading(procurement, "采购需求", "procurement"), "采购需求预览", () =>
			frm.custom_buttons?.[__("采购需求预览")]?.trigger("click"));
		const $checkpoints = $("<div>", { class: "tgy-basic-checkpoints" }).insertBefore(procurement.body);
		const $weight = $("<span>").text("食材带量口径").appendTo($checkpoints);
		const $basis = $("<b>").appendTo($weight);
		const $stock = $("<span>").text("账面库存").appendTo($checkpoints);
		const $review = $("<b>", { class: "tgy-basic-pill" }).appendTo($stock);

		const $kitchen = fold(kitchen, "厨房执行与周核销", "kitchen");
		notes.wrapper.addClass("tgy-basic-notes");
		fold(notes, "备注", "notes");
		$("<p>", { class: "tgy-basic-notes-empty text-muted" }).text("暂无备注。").appendTo(notes.body);
		$pane.addClass("tgy-basic").data("tgy-basic", {
			$company, $dates, $period, $record, $version, $calendar, $preview, $basis, $review, $kitchen,
		});
		return $pane.data("tgy-basic");
	}

	function render(frm) {
		const $pane = frm.layout.tabs.find((tab) => tab.df.fieldname === basicTab)?.wrapper;
		if (!$pane?.length || !$pane.closest(".form-layout").length) return;
		const sections = {};
		for (const key of ["planning", "population", "procurement", "kitchen", "notes"]) {
			const section = frm.layout.sections.find((entry) => entry.df.fieldname === `${key}_section`);
			if (!section?.wrapper?.length) return;
			sections[key] = section;
		}
		if (!sections.planning.columns[0]?.form?.length) return;
		const ui = $pane.data("tgy-basic") || install(frm, $pane, sections);
		const { doc } = frm;
		const isNew = Boolean(frm.is_new());
		$pane.toggleClass("tgy-basic-readonly", doc.docstatus !== 0 || !frm.perm?.[0]?.write);
		const [dates, period] = displayPeriod(doc);
		ui.$company.text(doc.company || "周食谱编排");
		ui.$dates.text(dates);
		ui.$period.text(period).prop("hidden", !period);
		ui.$record.prop("hidden", isNew);
		const reference = doc.template_week_start || doc.source_week;
		ui.$version.text([`版本 ${doc.revision || 1}`, reference ? `参考周 ${reference}` : ""].filter(Boolean).join(" · "));
		ui.$calendar.prop("hidden", isNew || frm.layout.tabs.find((tab) => tab.df.fieldname === calendarTab)?.is_hidden() !== false);
		const preview = frm.custom_buttons?.[__("采购需求预览")]?.[0];
		const canPreview = Boolean(preview?.isConnected);
		ui.$preview.prop("hidden", !canPreview);
		sections.procurement.wrapper.toggleClass("tgy-basic-preview-available", canPreview);
		sections.procurement.wrapper.toggleClass("tgy-basic-procurement-cancelled", doc.docstatus === 2);
		frm.fields_dict.material_request?.$wrapper.toggleClass("tgy-basic-empty", !doc.material_request);
		ui.$basis.text(doc.requirement_weight_basis || "待确认");
		const reviewed = Boolean(Number(doc.stock_reviewed));
		ui.$review.text(reviewed ? "已核对" : "待核对").attr("data-state", reviewed ? "complete" : "pending");
		const reconciled = Boolean(Number(doc.kitchen_reconciled));
		ui.$kitchen.text(reconciled ? "已核销" : "待核销").attr("data-state", reconciled ? "complete" : "pending");
	}

	window.tjyWeeklyMenuBasic = { render };
})();
