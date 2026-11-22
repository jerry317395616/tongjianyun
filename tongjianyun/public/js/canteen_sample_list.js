frappe.listview_settings["Tongjianyun Food Sample"] = {
	onload(list) {
		list.page.add_inner_button("打印选中留样标签", () => {
			const selected = list.get_checked_items().filter((row) => Number(row.docstatus) === 1);
			if (!selected.length) return frappe.msgprint("请选择已提交的留样记录。");
			if (selected.length > 50) return frappe.msgprint("每次最多打印 50 张标签。");
			if (!frappe.tgyCanteenPrintLabels) {
				frappe.require("/assets/tongjianyun/js/canteen_forms.js", () =>
					frappe.tgyCanteenPrintLabels("Tongjianyun Food Sample", selected.map((row) => row.name)));
				return;
			}
			frappe.tgyCanteenPrintLabels("Tongjianyun Food Sample", selected.map((row) => row.name));
		});
	}
};
