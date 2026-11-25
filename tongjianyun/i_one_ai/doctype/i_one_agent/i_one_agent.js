frappe.ui.form.on("I-ONE Agent", {
	refresh(frm) {
		const colors = {
			草稿: "gray",
			试用: "orange",
			在职: "green",
			暂停: "yellow",
			离职: "red",
		};
		frm.page.set_indicator(frm.doc.status || "草稿", colors[frm.doc.status] || "gray");

		if (frm.is_new()) {
			frm.dashboard.set_headline_alert("先完成员工档案并保存，再发布运行资源。", "blue");
			return;
		}

		if (frappe.user.has_role(["System Manager", "I-ONE Manager"])) {
			frm.add_custom_button(__("发布 AI 员工"), () => publish_employee(frm)).addClass("btn-primary");
			if (frm.doc.flow_agent && ["试用", "在职"].includes(frm.doc.status)) {
				frm.add_custom_button(__("试运行"), () => trial_employee(frm), __("运行"));
			}
		}

		if (frm.doc.flow_agent) {
			frm.add_custom_button(
				__("打开 Flow Agent"),
				() => frappe.set_route("Form", "Flow Agent", frm.doc.flow_agent),
				__("运行"),
			);
		}
		if (frm.doc.service_user) {
			frm.add_custom_button(
				__("查看服务用户"),
				() => frappe.set_route("Form", "User", frm.doc.service_user),
				__("运行"),
			);
		}
	},

	flow_model(frm) {
		if (frm.doc.flow_model && !frm.doc.max_iterations) {
			frm.set_value("max_iterations", 20);
		}
	},
});

function publish_employee(frm) {
	frappe.call({
		method: "tongjianyun.i_one_ai.doctype.i_one_agent.i_one_agent.publish_ai_employee",
		args: { name: frm.doc.name },
		freeze: true,
		freeze_message: __("正在创建服务用户并同步 Flow 配置..."),
		callback() {
			frm.reload_doc();
			frappe.show_alert({ message: __("AI 员工已发布"), indicator: "green" });
		},
	});
}

function trial_employee(frm) {
	frappe.prompt(
		[
			{
				fieldname: "prompt",
				fieldtype: "Long Text",
				label: __("试运行任务"),
				reqd: 1,
				default: "请介绍你的岗位职责、工作边界，以及遇到高风险操作时会如何处理。",
			},
		],
		(values) => {
			frappe.call({
				method: "tongjianyun.i_one_ai.doctype.i_one_agent.i_one_agent.queue_trial_task",
				args: { name: frm.doc.name, prompt: values.prompt },
				freeze: true,
				callback(r) {
					if (r.message?.name) {
						frappe.set_route("Form", "I-ONE AI Task", r.message.name);
					}
				},
			});
		},
		__("试运行 AI 员工"),
		__("开始"),
	);
}
