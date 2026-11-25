frappe.ui.form.on("I-ONE Flow Execution Policy", {
	refresh(frm) {
		set_tool_query(frm);
		set_policy_intro(frm);
	},

	execution_mode(frm) {
		set_policy_intro(frm);
	},
});

function set_tool_query(frm) {
	if (!frm.fields_dict.auto_approved_tools?.grid) {
		return;
	}

	frm.set_query("tool", "auto_approved_tools", () => ({
		filters: {
			enabled: 1,
			requires_confirmation: 1,
		},
	}));
}

function set_policy_intro(frm) {
	if (frm.doc.execution_mode === "全部自动执行") {
		frm.set_intro(
			__("该科室的 Flow 将不再逐项请求批准。请确保用户和 AI 员工仅拥有完成工作所需的最小权限。"),
			"orange",
		);
		return;
	}
	if (frm.doc.execution_mode === "指定工具自动执行") {
		frm.set_intro(__("仅所选工具自动执行，其他受控工具仍会请求批准。"), "blue");
		return;
	}
	frm.set_intro(__("所有需要确认的 Flow 工具都会等待用户批准。"), "gray");
}
