frappe.ui.form.on("I-ONE Deal Video", {
	refresh(frm) {
		if (!frm.is_new() && !["已排队", "渲染中"].includes(frm.doc.status)) {
			frm.add_custom_button(__("提交渲染"), () => {
				frm.call("submit_render").then(() => frm.reload_doc());
			}, __("视频"));
		}
	},
});
