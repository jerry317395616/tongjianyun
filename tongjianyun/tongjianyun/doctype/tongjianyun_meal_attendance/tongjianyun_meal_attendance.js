const TJY_MEAL_FIELDS = ["breakfast_count", "lunch_count", "dinner_count"];

function tjy_meal_number(value) {
	const parsed = Number.parseInt(value, 10);
	return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function tjy_meal_totals(frm) {
	const totals = {
		breakfast_total: 0,
		lunch_total: 0,
		dinner_total: 0,
	};
	(frm.doc.details || []).forEach((row) => {
		totals.breakfast_total += tjy_meal_number(row.breakfast_count);
		totals.lunch_total += tjy_meal_number(row.lunch_count);
		totals.dinner_total += tjy_meal_number(row.dinner_count);
	});
	totals.total_meal_times = totals.breakfast_total + totals.lunch_total + totals.dinner_total;
	totals.total_person_days = Math.round(totals.total_meal_times / 3);
	return totals;
}

function tjy_update_meal_summary(frm) {
	const totals = tjy_meal_totals(frm);
	Object.entries(totals).forEach(([fieldname, value]) => {
		if (tjy_meal_number(frm.doc[fieldname]) !== value) {
			frm.set_value(fieldname, value);
		}
	});
	const wrapper = frm.fields_dict.attendance_table?.$wrapper;
	if (!wrapper) return;
	wrapper.find("[data-total-field]").each(function () {
		const fieldname = this.dataset.totalField;
		this.textContent = totals[fieldname] ?? 0;
	});
}

function tjy_month_label(month) {
	if (!month) return "请选择统计月份";
	const [year, monthNumber] = String(month).slice(0, 7).split("-");
	return `${year}年${Number(monthNumber)}月`;
}

function tjy_escape(value) {
	return frappe.utils.escape_html(String(value ?? ""));
}

function tjy_render_meal_table(frm) {
	const wrapper = frm.fields_dict.attendance_table?.$wrapper;
	if (!wrapper) return;
	const rows = frm.doc.details || [];
	const totals = tjy_meal_totals(frm);
	const disabled = frm.doc.status === "已确认" ? "disabled" : "";
	const rowHtml = rows.map((row, index) => `
		<tr>
			<td class="tjy-class-cell">${tjy_escape(row.class_name)}</td>
			${TJY_MEAL_FIELDS.map((fieldname) => `
				<td>
					<input
						class="tjy-attendance-input"
						type="number"
						min="0"
						step="1"
						inputmode="numeric"
						data-row-index="${index}"
						data-fieldname="${fieldname}"
						value="${tjy_meal_number(row[fieldname])}"
						${disabled}
					>
				</td>
			`).join("")}
		</tr>
	`).join("");

	wrapper.html(`
		<style>
			.tjy-attendance-sheet { max-width: 940px; margin: 8px auto 18px; padding: 26px 30px 30px; color: #1f2933; background: #fff; border: 1px solid #dfe5e2; border-radius: 12px; box-shadow: 0 8px 26px rgba(31, 61, 46, .06); }
			.tjy-attendance-sheet-header { display: grid; grid-template-columns: 1fr 2fr 1fr; align-items: start; margin-bottom: 16px; }
			.tjy-attendance-sheet-kicker { font-size: 14px; line-height: 1.8; }
			.tjy-attendance-sheet-title { margin: 12px 0 0; text-align: center; font-family: "Noto Serif SC", "Songti SC", serif; font-size: 26px; font-weight: 700; letter-spacing: 4px; }
			.tjy-attendance-table-wrap { overflow-x: auto; }
			.tjy-attendance-table { width: 100%; min-width: 640px; table-layout: fixed; border-collapse: collapse; border: 2px solid #26342d; }
			.tjy-attendance-table th, .tjy-attendance-table td { height: 48px; padding: 6px 10px; text-align: center; vertical-align: middle; border: 1px solid #3d4a43; }
			.tjy-attendance-table th { background: #f4f7f5; font-size: 15px; font-weight: 700; }
			.tjy-attendance-table .tjy-class-cell { width: 28%; font-size: 15px; font-weight: 600; }
			.tjy-attendance-input { width: 100%; height: 36px; padding: 3px 8px; text-align: center; font-size: 16px; font-variant-numeric: tabular-nums; background: #fbfdfc; border: 1px solid #c8d4cd; border-radius: 6px; outline: none; transition: border-color .15s, box-shadow .15s; }
			.tjy-attendance-input:hover { border-color: #6ca988; }
			.tjy-attendance-input:focus { border-color: #27845a; box-shadow: 0 0 0 3px rgba(39, 132, 90, .12); }
			.tjy-attendance-input:disabled { color: #26342d; background: transparent; border-color: transparent; opacity: 1; }
			.tjy-summary-row td { height: 44px; background: #f7faf8; font-weight: 700; }
			.tjy-grand-total td { background: #edf6f1; font-size: 16px; }
			.tjy-total-value { font-variant-numeric: tabular-nums; }
			.tjy-attendance-help { margin-top: 12px; color: #718078; font-size: 12px; text-align: right; }
			@media (max-width: 767px) { .tjy-attendance-sheet { padding: 18px 14px 22px; } .tjy-attendance-sheet-header { grid-template-columns: 1fr; } .tjy-attendance-sheet-title { grid-row: 1; margin: 0 0 12px; font-size: 22px; } }
		</style>
		<div class="tjy-attendance-sheet">
			<div class="tjy-attendance-sheet-header">
				<div class="tjy-attendance-sheet-kicker">
					<div>儿童营养表3</div>
					<div>${tjy_escape(tjy_month_label(frm.doc.month))}</div>
				</div>
				<h2 class="tjy-attendance-sheet-title">就餐人数记录表</h2>
				<div></div>
			</div>
			<div class="tjy-attendance-table-wrap">
				<table class="tjy-attendance-table">
					<thead><tr><th>班级</th><th>早餐</th><th>午餐</th><th>晚餐</th></tr></thead>
					<tbody>
						${rowHtml || '<tr><td colspan="4">正在载入班级……</td></tr>'}
						<tr class="tjy-summary-row"><td>合计</td><td data-total-field="breakfast_total">${totals.breakfast_total}</td><td data-total-field="lunch_total">${totals.lunch_total}</td><td data-total-field="dinner_total">${totals.dinner_total}</td></tr>
						<tr class="tjy-summary-row tjy-grand-total"><td>总人次数</td><td colspan="3" class="tjy-total-value" data-total-field="total_meal_times">${totals.total_meal_times}</td></tr>
						<tr class="tjy-summary-row tjy-grand-total"><td>总人日数</td><td colspan="3" class="tjy-total-value" data-total-field="total_person_days">${totals.total_person_days}</td></tr>
					</tbody>
				</table>
			</div>
			<div class="tjy-attendance-help">直接点击数字单元格填写；总人日数按总人次数 ÷ 3 四舍五入。</div>
		</div>
	`);

	wrapper.off("input.tjy-meal-attendance").on("input.tjy-meal-attendance", ".tjy-attendance-input", function () {
		const row = frm.doc.details?.[Number(this.dataset.rowIndex)];
		const fieldname = this.dataset.fieldname;
		if (!row || !TJY_MEAL_FIELDS.includes(fieldname)) return;
		const value = tjy_meal_number(this.value);
		this.value = value;
		frappe.model.set_value(row.doctype, row.name, fieldname, value);
		tjy_update_meal_summary(frm);
	});
}

async function tjy_load_active_classes(frm, keepExisting = true) {
	if (frm.__tjy_loading_classes) return;
	frm.__tjy_loading_classes = true;
	try {
		const response = await frappe.call({
			method: "tongjianyun.tongjianyun.doctype.tongjianyun_meal_attendance.tongjianyun_meal_attendance.get_active_classes",
		});
		const existing = new Map((frm.doc.details || []).map((row) => [row.class_id || row.class_name, row]));
		frm.clear_table("details");
		(response.message || []).forEach((item) => {
			const previous = keepExisting ? existing.get(item.class_id || item.class_name) : null;
			const row = frm.add_child("details");
			row.class_id = item.class_id;
			row.class_name = item.class_name;
			row.sort_order = item.sort_order || 10;
			TJY_MEAL_FIELDS.forEach((fieldname) => {
				row[fieldname] = tjy_meal_number(previous?.[fieldname]);
			});
		});
		frm.dirty();
		tjy_update_meal_summary(frm);
		tjy_render_meal_table(frm);
	} finally {
		frm.__tjy_loading_classes = false;
	}
}

frappe.ui.form.on("Tongjianyun Meal Attendance", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.month) {
			frm.set_value("month", `${frappe.datetime.get_today().slice(0, 7)}-01`);
		}
	},

	refresh(frm) {
		if (!frm.doc.details?.length) {
			tjy_load_active_classes(frm, false);
		} else {
			tjy_render_meal_table(frm);
		}
		frm.add_custom_button(__("同步当前班级"), () => {
			frappe.confirm(__("将按当前启用班级刷新表格，并保留同名班级已填写的人数。是否继续？"), () => tjy_load_active_classes(frm, true));
		});
		if (!frm.is_new()) {
			frm.add_custom_button(__("打印表格"), () => {
				const query = new URLSearchParams({
					doctype: frm.doctype,
					name: frm.doc.name,
					format: "就餐人数记录表",
					no_letterhead: "1",
					trigger_print: "0",
				});
				window.open(`/printview?${query.toString()}`, "_blank");
			});
		}
	},

	month(frm) {
		tjy_render_meal_table(frm);
	},

	status(frm) {
		tjy_render_meal_table(frm);
	},

	before_save(frm) {
		tjy_update_meal_summary(frm);
	},
});
