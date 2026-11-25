frappe.ui.form.on("I-ONE AI Task", {
	refresh(frm) {
		const colors = {
			草稿: "gray",
			待审批: "orange",
			已排队: "blue",
			执行中: "blue",
			等待确认: "orange",
			已完成: "green",
			执行失败: "red",
			已取消: "gray",
		};
		frm.page.set_indicator(frm.doc.status || "草稿", colors[frm.doc.status] || "gray");

		if (!frm.is_new() && ["草稿", "执行失败"].includes(frm.doc.status)) {
			frm.add_custom_button(__("开始执行"), () => queue_task(frm)).addClass("btn-primary");
		}
		if (frm.doc.flow_run) {
			frm.add_custom_button(
				__("打开 Flow 运行记录"),
				() => frappe.set_route("Form", "Flow Run", frm.doc.flow_run),
				__("Flow"),
			);
		}
		if (frm.doc.flow_session) {
			frm.add_custom_button(
				__("打开 Flow 会话"),
				() => frappe.set_route("Form", "Flow Session", frm.doc.flow_session),
				__("Flow"),
			);
		}
	},
});

function queue_task(frm) {
	frappe.call({
		method: "tongjianyun.ai.queue_existing_task",
		args: { task_name: frm.doc.name },
		freeze: true,
		callback() {
			frm.reload_doc();
			frappe.show_alert({ message: __("工作单已进入执行队列"), indicator: "blue" });
		},
	});
}
