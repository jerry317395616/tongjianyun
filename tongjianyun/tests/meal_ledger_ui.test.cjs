const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const reportDirectory = "../tongjianyun/report/tongjianyun_meal_ledger";
const script = readFileSync(path.join(__dirname, reportDirectory, "tongjianyun_meal_ledger.js"), "utf8");

function reportSettings() {
	const frappe = {
		query_reports: {},
		defaults: { get_user_default: () => "测试园所" },
		datetime: {
			get_today: () => "2026-11-21",
			add_days(value, days) {
				const date = new Date(value);
				date.setUTCDate(date.getUTCDate() + days);
				return date.toISOString().slice(0, 10);
			},
			str_to_user: String,
		},
		utils: {
			escape_html: (value) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;")
				.replaceAll(">", "&gt;").replaceAll('"', "&quot;"),
		},
	};
	vm.runInNewContext(script, { frappe, URLSearchParams, __: String });
	return frappe.query_reports["Tongjianyun Meal Ledger"];
}

test("the ledger opens the selected date and week with the meal detail filters", () => {
	const settings = reportSettings();
	assert.equal(settings.filters.find((field) => field.fieldname === "from_date").default, "2026-11-16");
	assert.equal(settings.filters.find((field) => field.fieldname === "to_date").default, "2026-11-20");
	const date = "2026-11-19";
	const html = settings.formatter(date, null, { fieldname: "meal_date" }, {
		company: "幼儿园 & 分园", meal_week: "WEEK-01", meal_date: date, day_status: "待日结",
	});
	const href = html.match(/href="([^"]+)"/)[1].replaceAll("&amp;", "&");
	const url = new URL(href, "https://example.test");
	assert.equal(decodeURIComponent(url.pathname), "/desk/query-report/Tongjianyun Meal Ledger");
	assert.deepEqual(Object.fromEntries(url.searchParams), {
		company: "幼儿园 & 分园", week_name: "WEEK-01", from_date: date, to_date: date, view: "餐次核对",
	});
});

test("the ledger separates missing and zero counts and treats report text as text", () => {
	const { formatter } = reportSettings();
	const actual = { fieldname: "actual", fieldtype: "Int" };
	assert.match(formatter(null, null, actual, {}), /待确认/);
	assert.equal(formatter(0, null, actual, {}, String), "0");
	assert.equal(formatter("<菜品>", null, { fieldtype: "Data" }, {}), "&lt;菜品&gt;");
	assert.equal(formatter("", null, { fieldname: "stock_entries" }, { stock_entry_names: ["STE-1/2"] }),
		'<a href="/desk/stock-entry/STE-1%2F2">STE-1/2</a>');
});
