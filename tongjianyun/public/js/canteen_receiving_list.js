(() => {
	const type = "Tongjianyun Canteen Receiving";
	const method = "tongjianyun.canteen_ops.purchasing.receiving_from_code";
	frappe.listview_settings[type] = {
		onload(list) {
			if (!(frappe.boot.user.can_create || []).includes(type)) return;
			const receive = async (code) => {
				const { message } = await frappe.call({ method, args: { code }, type: "POST", freeze: true });
				frappe.set_route("Form", type, message);
			};
			list.page.add_inner_button("扫码验收", () => {
				new frappe.ui.Scanner({
					dialog: true, multiple: false, allow_keep_open: false,
					on_scan(data) {
						if (data?.decodedText) receive(data.decodedText);
					}
				});
			});
			list.page.add_inner_button("录入随货码", () =>
				frappe.prompt([{ fieldname: "code", label: "随货二维码内容", fieldtype: "Data", reqd: 1 }],
					({ code }) => receive(code), "录入随货码", "打开验收"));
		}
	};
})();
