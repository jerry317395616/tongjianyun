(() => {
	const esc = (value) => frappe.utils.escape_html(String(value ?? ""));
	const canPurchase = () => ["System Manager", "Purchase Manager", "膳食业务经办员"].some((role) => frappe.user.has_role(role));

	async function draftAdjustmentOrder(frm, button) {
		if (frm.__meal_adjustment_order_busy) return;
		try {
			if (frm.is_new() || frm.is_dirty()) frappe.throw(__("请先保存变更申请。"));
			frm.__meal_adjustment_order_busy = true;
			button?.prop("disabled", true);
			const request = await frappe.db.get_doc("Material Request", frm.doc.material_request);
			if (request.docstatus !== 1) return frappe.msgprint(__("请先由另一位授权人员审核并提交补采申请，再生成采购订单草稿。"));
			const dialog = new frappe.ui.Dialog({
				title: __("为单餐补采生成订单草稿"), size: "extra-large",
				fields: [
					{ fieldname: "supplier", fieldtype: "Link", options: "Supplier", label: __("实际供应商"), reqd: 1,
						get_query: () => ({ filters: { disabled: 0 } }) },
					{ fieldname: "notice", fieldtype: "HTML", options: `<p>${esc("勾选本供应商承接的补采明细。原申请、订单和收货保留；本订单须应用有效供应商报价，并由另一位授权人员确认及提交。")}</p>` },
					{ fieldname: "items", fieldtype: "Table", label: __("补采申请明细"), cannot_add_rows: true, cannot_delete_rows: true,
						in_place_edit: true, data: (request.items || []).map((row) => ({ selected: 0, source_row: row.name,
							item_code: row.item_code, item_name: row.item_name, qty: row.qty, uom: row.uom, schedule_date: row.schedule_date })),
						fields: [
							{ fieldname: "selected", fieldtype: "Check", label: __("采购本项"), in_list_view: 1 },
							{ fieldname: "source_row", fieldtype: "Data", hidden: 1, read_only: 1 },
							{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("食材"), read_only: 1, in_list_view: 1 },
							{ fieldname: "item_name", fieldtype: "Data", label: __("名称"), read_only: 1, in_list_view: 1 },
							{ fieldname: "qty", fieldtype: "Float", label: __("申请数量"), read_only: 1, in_list_view: 1 },
							{ fieldname: "uom", fieldtype: "Data", label: __("采购单位"), read_only: 1, in_list_view: 1 },
							{ fieldname: "schedule_date", fieldtype: "Date", label: __("需要日期"), read_only: 1, in_list_view: 1 },
						] },
				],
				primary_action_label: __("生成订单草稿"),
				async primary_action(values) {
					if (frm.__meal_adjustment_order_busy) return;
					const selected = (values.items || []).filter((row) => row.selected).map((row) => row.source_row);
					if (!selected.length) return frappe.msgprint(__("请勾选本供应商承接的补采明细。"));
					try {
						frm.__meal_adjustment_order_busy = true;
						dialog.get_primary_btn().prop("disabled", true);
						const response = await frappe.call({ method: "tongjianyun.meal_purchasing.create_purchase_order_draft", freeze: true,
							args: { week_name: frm.doc.meal_week, supplier: values.supplier,
								material_request: request.name, material_request_items: selected } });
						if (response.exc || !response.message?.purchase_order) throw new Error(__("未返回采购订单编号，请刷新列表核对。"));
						dialog.hide();
						frappe.set_route(frappe.tjyMealDesk.purchaseOrderLink(response.message.purchase_order));
					} catch (error) {
						if (!error?._server_messages && !error?.responseJSON?._server_messages) frappe.msgprint({ title: __("创建补采订单失败"), indicator: "red", message: esc(error?.message || "请求失败，请重试。") });
					} finally {
						frm.__meal_adjustment_order_busy = false;
						dialog.get_primary_btn().prop("disabled", false);
					}
				},
			});
			dialog.show();
		} catch (error) {
			if (!error?._server_messages && !error?.responseJSON?._server_messages) frappe.msgprint({ title: __("读取补采申请失败"), indicator: "red", message: esc(error?.message || "请检查读取权限后重试。") });
		} finally {
			frm.__meal_adjustment_order_busy = false;
			button?.prop("disabled", false);
		}
	}

	frappe.ui.form.on("Meal Plan Adjustment", {
		setup(frm) {
			frm.set_query("bom_no", "dishes", () => ({ filters: { docstatus: 1, is_active: 1 } }));
		},
		refresh(frm) {
			frm.set_intro(__("本申请调整已审核周的未来单餐。请填写完整目标人数与菜品；整餐停供须明确勾选并说明原因。提交审核须由另一位授权审核人完成，申请人不能审核自己的申请。"), "blue");
			if (frm.doc.docstatus === 1) frm.set_intro(__("本次变更已生效并保留应用依据。后续更正请从原周食谱创建下一张单餐变更申请，不能取消已生效的采购和库存事实。"), "green");
			if (frm.doc.meal_week) frm.add_custom_button(__("原周食谱"), () => frappe.set_route("Form", "Meal Planning Week", frm.doc.meal_week));
			if (frm.doc.replacement_plan) frm.add_custom_button(__("替代生产计划"), () => frappe.set_route("Form", "Production Plan", frm.doc.replacement_plan));
			if (frm.doc.material_request) frm.add_custom_button(__("采购调整申请"), () => frappe.set_route("Form", "Material Request", frm.doc.material_request));
			if (frm.doc.docstatus === 1 && frm.doc.material_request && canPurchase()) {
				const button = frm.add_custom_button(__("生成补采订单草稿"), () => draftAdjustmentOrder(frm, button));
			}
		},
		service_suspended(frm) {
			if (frm.doc.service_suspended) frm.set_value("target_headcount", 0);
		},
		before_submit(frm) {
			if (frm.doc.owner === frappe.session.user) frappe.throw(__("申请人不能审核自己的变更，请交由另一位授权审核人提交。"));
			if (frm.doc.service_suspended && Number(frm.doc.target_headcount) !== 0) frappe.throw(__("整餐停供时目标人数必须为零。"));
			if (!frm.doc.service_suspended && (!(Number(frm.doc.target_headcount) > 0) || !(frm.doc.dishes || []).length)) frappe.throw(__("正常供餐需要正数目标人数和至少一个菜品配方。"));
		},
	});
})();
