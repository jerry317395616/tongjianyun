(() => {
	const esc = (value) => frappe.utils.escape_html(String(value ?? ""));
	const canPurchase = () => ["System Manager", "Purchase Manager", "膳食业务经办员"].some((role) => frappe.user.has_role(role));
	const canConfirm = () => ["System Manager", "Purchase Manager"].some((role) => frappe.user.has_role(role));

	async function action(frm, button, method, args) {
		if (frm.__meal_quote_busy) return;
		try {
			if (frm.is_new() || frm.is_dirty()) frappe.throw(__("请先保存采购订单，再应用或确认供应商报价。"));
			frm.__meal_quote_busy = true;
			button?.prop("disabled", true);
			const response = await frappe.call({ method, args, freeze: true, freeze_message: __("正在核对本单供应商报价…") });
			if (response.exc) throw new Error(__("操作未完成，请查看服务器提示。"));
			await frm.reload_doc();
		} catch (error) {
			if (!error?._server_messages && !error?.responseJSON?._server_messages) frappe.msgprint({ title: __("报价操作未完成"), indicator: "red", message: esc(error?.message || "请求失败，请重试。") });
		} finally {
			frm.__meal_quote_busy = false;
			button?.prop("disabled", false);
		}
	}

	function quoteState(frm) {
		try { return JSON.parse(frm.doc.custom_meal_quote_snapshot || "{}"); } catch (error) { return {}; }
	}

	frappe.ui.form.on("Purchase Order", {
		refresh(frm) {
			if (!frm.doc.custom_meal_week) return;
			const snapshot = quoteState(frm);
			const confirmed = snapshot.confirmed === true;
			const quotations = Array.isArray(snapshot.quotation_names) ? snapshot.quotation_names.join("、") : "";
			frm.set_intro(confirmed
				? `${esc("本单报价已确认")}：${esc(snapshot.confirmed_by)} · ${esc(snapshot.confirmed_at)}${quotations ? ` · ${esc(quotations)}` : ""}`
				: __("本单来自周食谱采购需求。请应用已提交且在有效期内的供应商报价，报价须覆盖本单全部食材及采购单位；由另一位授权采购审核人确认后提交订单。"), confirmed ? "green" : "orange");
			frm.add_custom_button(__("来源周食谱"), () => frappe.set_route("Form", "Meal Planning Week", frm.doc.custom_meal_week));
			if (frm.doc.docstatus !== 0 || !canPurchase() || frm.is_new()) return;
			const apply = frm.add_custom_button(__("应用供应商报价"), () => {
				if (frm.__meal_quote_busy) return;
				frappe.prompt([{ fieldname: "quotation_name", fieldtype: "Link", options: "Supplier Quotation", label: __("已提交的供应商报价"), reqd: 1,
					get_query: () => ({ filters: { docstatus: 1, supplier: frm.doc.supplier, company: frm.doc.company, currency: frm.doc.currency,
						valid_till: [">=", frappe.datetime.get_today()] } }) }], (values) => action(frm, apply,
					"tongjianyun.meal_purchasing.apply_supplier_quotation", { po_name: frm.doc.name, quotation_name: values.quotation_name }), __("应用本单供应商报价"), __("应用报价"));
			});
			if (!canConfirm()) return;
			const confirm = frm.add_custom_button(__("确认本单报价"), () => {
				if (frm.doc.owner === frappe.session.user) return frappe.msgprint(__("采购订单创建人不能确认自己的订单报价，请由另一位授权采购审核人操作。"));
				frappe.confirm(__("请确认本单品种、采购单位、单价及送货日期与供应商已提交报价一致。确认后仍需按原生流程提交采购订单。"), () => action(frm, confirm,
					"tongjianyun.meal_purchasing.confirm_purchase_order_quote", { po_name: frm.doc.name }));
			});
		},
		before_submit(frm) {
			if (frm.doc.custom_meal_week && quoteState(frm).confirmed !== true) frappe.throw(__("请先应用供应商报价，并由另一位授权采购审核人确认本单报价。"));
		},
	});
})();
