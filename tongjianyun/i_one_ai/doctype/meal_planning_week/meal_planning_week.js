(() => {
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
	const hasRole = (...roles) => roles.some((role) => frappe.user.has_role(role));
	const canReviewStock = () => hasRole("System Manager", "Purchase Manager", "Stock Manager");
	const canCreateRequest = () => hasRole("System Manager", "Purchase Manager", "膳食业务经办员");
	const canDraftPurchase = () => hasRole("System Manager", "Purchase Manager", "膳食业务经办员");
	const canUseKitchen = () => hasRole("System Manager", "Stock Manager", "Stock User", "膳食业务经办员");
	const editable = (frm) => frm.doc.docstatus === 0 && !!frm.perm?.[0]?.write;
	const reportName = "Tongjianyun Weekly Menu";
	const previewMethod = "tongjianyun.meal_procurement.get_procurement_preview";
	let previewAssets;

	function ensureSaved(frm) {
		if (frm.is_new() || frm.is_dirty()) {
			frappe.throw(__("请先保存本周编排，再执行此操作。"));
		}
	}

	async function runAction(frm, button, method, args, onSuccess) {
		if (frm.__meal_action_running) return;
		try {
			ensureSaved(frm);
			frm.__meal_action_running = true;
			button?.prop("disabled", true);
			const response = await frappe.call({
				method,
				args,
				freeze: true,
				freeze_message: __("正在处理周食谱…"),
			});
			if (response.exc) throw new Error(__("操作未完成，请查看服务器提示。"));
			await onSuccess?.(response.message);
		} catch (error) {
			// Frappe displays detailed server validation messages; this covers network failures too.
			if (!error?._server_messages && !error?.responseJSON?._server_messages) {
				frappe.msgprint({
					title: __("操作未完成"),
					indicator: "red",
					message: escape(error?.message || __("请求失败，请检查连接并重试。")),
				});
			}
		} finally {
			frm.__meal_action_running = false;
			button?.prop("disabled", false);
		}
	}

	function actionButton(frm, label, method, args, onSuccess) {
		const button = frm.add_custom_button(__(label), () =>
			runAction(frm, button, method, args(), onSuccess)
		);
		return button;
	}

	async function openProcurementPreview(frm, preview) {
		if (!preview || preview.week_name !== frm.doc.name) return;
		const wrapper = frm.fields_dict.procurement_html?.$wrapper;
		if (!wrapper?.length) return;
		const assets = "/assets/tongjianyun";
		previewAssets ??= Promise.resolve(frappe.require([
			`${assets}/css/meal_procurement_preview.css?v=procurement-inline-3.css`,
			`${assets}/js/meal_procurement_preview.js?v=procurement-inline-2.js`,
		])).catch((error) => {
			previewAssets = undefined;
			throw error;
		});
		await previewAssets;
		if (window.cur_frm !== frm || frm.doc.name !== preview.week_name || frm.is_dirty()) return;
		if (frm.layout.tabs?.some(({ df }) => df.fieldname === "custom_tjy_week_basic_tab")) {
			frm.layout.select_tab("custom_tjy_week_basic_tab");
		}
		const canReview = canReviewStock() && frm.doc.docstatus === 0 && frm.doc.meals?.length;
		window.tjyProcurementPreview.render(wrapper, preview, canReview ? (button) => reviewStock(frm, button) : null);
		const card = wrapper.closest(".tgy-basic-procurement")[0] || wrapper.find(".tjy-proc-shell")[0];
		card?.scrollIntoView({ block: "start" });
	}

	function reviewStock(frm, button) {
		if (frm.__meal_action_running) return;
		const name = frm.doc.name;
		const previewVisible = frm.fields_dict.procurement_html?.$wrapper.find(".tjy-proc-shell").is(":visible");
		frappe.confirm(
			__("请确认已核对采购预览中的账面库存、待到货及采购分类。此操作只记录账面核对，不表示完成实物盘点。"),
			() => {
				if (window.cur_frm !== frm || frm.doc.name !== name) return;
				return runAction(frm, button, "tongjianyun.meal_planning.confirm_stock_review", { name }, async () => {
					await frm.reload_doc();
					if (!previewVisible || window.cur_frm !== frm || frm.doc.name !== name) return;
					const response = await frappe.call({ method: previewMethod, args: { week_name: name } });
					if (!response.exc) await openProcurementPreview(frm, response.message);
				});
			},
			null,
			__("确认核对"),
			__("返回检查")
		);
	}

	function resetPreview(frm, message) {
		frm.fields_dict.procurement_html?.$wrapper.html(
			message ? `<p class="text-muted">${escape(message)}</p>` : `
				<p class="text-muted tgy-basic-preview-prompt">点击「采购需求预览」核对食材、库存、到货和采购分类。</p>
				<p class="text-muted tgy-basic-preview-wait" hidden>完成本周餐次编排后可预览采购需求。</p>
				<p class="text-muted tgy-basic-preview-cancelled" hidden>本周食谱已取消。</p>`
		);
	}

	function editMealDishes(frm, button) {
		try {
			ensureSaved(frm);
		} catch (error) {
			return;
		}
		const meals = (frm.doc.meals || []).filter((row) => row.production_plan);
		if (!meals.length || frm.__meal_action_running) return;
		const label = (row) => `${row.meal_date}｜${row.meal_type}`;
		let loading = false;
		const dialog = new frappe.ui.Dialog({
			title: __("调整本餐菜品"),
			size: "large",
			fields: [
				{ fieldname: "meal", fieldtype: "Select", label: __("选择餐次"), reqd: 1,
					options: meals.map(label).join("\n"), default: label(meals[0]),
					onchange() { loadCurrentDishes(); } },
				{ fieldname: "notice", fieldtype: "HTML", options: `<p class="text-muted">${escape(
					"下表为本餐完整菜品配方列表。调整后将替换本餐菜品；生产数量由计划人数确定。"
				)}</p>` },
				{ fieldname: "show_all_dishes", fieldtype: "Check", label: __("显示全部餐次的菜品") },
				{ fieldname: "boms", fieldtype: "Table", label: __("菜品配方"), reqd: 1,
					in_place_edit: true, fields: [
						{ fieldname: "bom", fieldtype: "Link", label: __("菜品配方"), options: "BOM",
							reqd: 1, in_list_view: 1, get_query: () => {
								const meal = meals.find((row) => label(row) === dialog.get_value("meal"));
								return {
									query: "tongjianyun.meal_planning.search_meal_recipes",
									filters: { week_name: frm.doc.name, meal_type: meal?.meal_type,
										include_all: dialog.get_value("show_all_dishes") || 0 },
								};
							} },
					] },
			],
			primary_action_label: __("保存本餐菜品"),
			primary_action(values) {
				if (loading || frm.__meal_action_running) return;
				const row = meals.find((meal) => label(meal) === values.meal);
				const boms = (values.boms || []).map((entry) => entry.bom).filter(Boolean);
				if (!row || !boms.length) return frappe.msgprint(__("请至少选择一个有效菜品配方。"));
				dialog.get_primary_btn().prop("disabled", true);
				runAction(frm, button, "tongjianyun.meal_planning.update_meal_dishes", {
					week_name: frm.doc.name, meal_date: row.meal_date, meal_type: row.meal_type, boms,
				}, async () => {
					dialog.hide();
					await frm.reload_doc();
				}).finally(() => dialog.get_primary_btn().prop("disabled", false));
			},
		});
		async function loadCurrentDishes() {
			const selectedMeal = dialog.get_value("meal");
			const row = meals.find((meal) => label(meal) === selectedMeal);
			if (!row) return;
			loading = true;
			dialog.get_primary_btn().prop("disabled", true);
			try {
				const plan = await frappe.db.get_doc("Production Plan", row.production_plan);
				if (dialog.get_value("meal") !== selectedMeal) return;
				dialog.fields_dict.boms.df.data = (plan.po_items || []).map((item) => ({ bom: item.bom_no }));
				dialog.fields_dict.boms.grid.refresh();
			} catch (error) {
				if (dialog.get_value("meal") !== selectedMeal) return;
				dialog.fields_dict.boms.df.data = [];
				dialog.fields_dict.boms.grid.refresh();
				frappe.msgprint({ title: __("读取菜品失败"), indicator: "red",
					message: escape(error?.message || "无法读取本餐生产计划，请核对读取权限后重试。") });
			} finally {
				if (dialog.get_value("meal") === selectedMeal) {
					loading = false;
					dialog.get_primary_btn().prop("disabled", false);
				}
			}
		}
		dialog.show();
		loadCurrentDishes();
	}

	function configureKitchen(frm, button) {
		frappe.prompt([{ fieldname: "kitchen_warehouse", fieldtype: "Link", options: "Warehouse",
			label: __("厨房仓库"), reqd: 1, default: frm.doc.kitchen_warehouse,
			get_query: () => ({ filters: { company: frm.doc.company, is_group: 0,
				name: ["!=", frm.doc.raw_material_warehouse] } }) }], (values) =>
			runAction(frm, button, "tongjianyun.meal_kitchen.configure_kitchen_warehouse", {
				week_name: frm.doc.name, kitchen_warehouse: values.kitchen_warehouse,
			}, async () => { await frm.reload_doc(); }), __("配置厨房仓库"), __("保存配置"));
	}

	function openKitchenDay(frm, button) {
		const today = frappe.datetime.get_today();
		const defaultDate = today >= frm.doc.week_start && today <= frm.doc.week_end ? today : frm.doc.week_start;
		frappe.prompt([{ fieldname: "meal_date", fieldtype: "Date", label: __("供餐日期"),
			reqd: 1, default: defaultDate }], (values) => runAction(frm, button,
			"tongjianyun.meal_kitchen.get_kitchen_day", { week_name: frm.doc.name, meal_date: values.meal_date }, (result) => {
				if (!result?.name) throw new Error(__("未返回厨房执行记录编号，请刷新列表核对。"));
				frappe.set_route("Form", "Meal Kitchen Day", result.name);
			}), __("打开厨房每日执行"), __("打开执行记录"));
	}

	function requestAdjustment(frm, button) {
		const meals = (frm.doc.meals || []).filter((row) => row.meal_date >= frappe.datetime.get_today());
		if (!meals.length) return frappe.msgprint(__("本周没有可申请变更的未来餐次。"));
		const label = (row) => `${row.meal_date}｜${row.meal_type}`;
		frappe.prompt([{ fieldname: "meal", fieldtype: "Select", label: __("申请变更的餐次"), reqd: 1,
			options: meals.map(label).join("\n"), default: label(meals[0]) }], (values) => {
			const meal = meals.find((row) => label(row) === values.meal);
			if (!meal) return;
			runAction(frm, button, "tongjianyun.meal_adjustments.create_adjustment", {
				week_name: frm.doc.name, meal_date: meal.meal_date, meal_type: meal.meal_type,
			}, (result) => {
				const name = typeof result === "string" ? result : result?.name;
				if (!name) throw new Error(__("未返回变更申请编号，请刷新列表核对。"));
				frappe.set_route("Form", "Meal Plan Adjustment", name);
			});
		}, __("申请单餐变更"), __("创建变更草稿"));
	}

	async function draftPurchase(frm, button) {
		try {
			ensureSaved(frm);
			if (frm.__meal_action_running) return;
			const week = frm.doc.name;
			const { message: rows } = await frappe.call({
				method: "tongjianyun.meal_purchasing.purchase_order_candidates",
				type: "GET", args: { week_name: week },
			});
			if (window.cur_frm !== frm || frm.doc.name !== week) return;
			if (!rows?.length) return frappe.msgprint(__("没有可加入新订单的采购明细，请查看已有采购订单。"));
			const dialog = new frappe.ui.Dialog({
				title: __("按采购申请生成订单草稿"), size: "extra-large",
				fields: [
					{ fieldname: "supplier", fieldtype: "Link", options: "Supplier", label: __("实际供应商"), reqd: 1,
						get_query: () => ({ filters: { disabled: 0 } }) },
					{ fieldname: "notice", fieldtype: "HTML", options: `<p>${escape("待采购明细默认全选。请用左侧复选框取消本供应商不承接的明细。生成后需要有效的供应商报价，并由另一位授权人员确认及提交订单。")}</p>` },
					{ fieldname: "items", fieldtype: "Table", label: __("采购申请明细"), cannot_add_rows: true, cannot_delete_rows: true,
						in_place_edit: true, data: rows,
						fields: [
							{ fieldname: "source_row", fieldtype: "Data", hidden: 1, read_only: 1 },
							{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("食材"), read_only: 1, in_list_view: 1 },
							{ fieldname: "item_name", fieldtype: "Data", label: __("名称"), read_only: 1, in_list_view: 1 },
							{ fieldname: "qty", fieldtype: "Float", label: __("待采购数量"), read_only: 1, in_list_view: 1 },
							{ fieldname: "uom", fieldtype: "Data", label: __("采购单位"), read_only: 1, in_list_view: 1 },
							{ fieldname: "schedule_date", fieldtype: "Date", label: __("需要日期"), read_only: 1, in_list_view: 1 },
						] },
				],
				primary_action_label: __("生成订单草稿"),
				primary_action(values) {
					const selected = (values.items || []).filter((row) => row.__checked).map((row) => row.source_row);
					if (!selected.length) return frappe.msgprint(__("请勾选本供应商承接的申请明细。"));
					dialog.get_primary_btn().prop("disabled", true);
					runAction(frm, button, "tongjianyun.meal_purchasing.create_purchase_order_draft", {
						week_name: week, supplier: values.supplier, material_request_items: selected,
					}, (result) => {
						if (!result?.purchase_order) throw new Error(__("未返回采购订单编号，请刷新列表核对。"));
						dialog.hide();
						frappe.set_route("Form", "Purchase Order", result.purchase_order);
					}).finally(() => dialog.get_primary_btn().prop("disabled", false));
				},
			});
			dialog.show();
			dialog.fields_dict.items.check_all_rows();
		} catch (error) {
			if (!error?._server_messages && !error?.responseJSON?._server_messages) frappe.msgprint({ title: __("读取采购申请失败"), indicator: "red", message: escape(error?.message || "请检查读取权限后重试。") });
		}
	}

	frappe.ui.form.on("Meal Planning Week", {
		setup(frm) {
			frm.set_query("raw_material_warehouse", () => ({
				filters: { company: frm.doc.company, is_group: 0 },
			}));
		},
		refresh(frm) {
			const grid = frm.fields_dict.meals?.grid;
			if (grid) {
				grid.cannot_add_rows = true;
				grid.cannot_delete_rows = true;
			}
			resetPreview(frm);
			frm.set_intro(__("供餐人数来自教育管理的在园学生名册，属于计划人数。请核对各餐停餐调整，再预览采购需求并核对账面库存。"), "blue");
			frm.$intro_message?.addClass("tgy-basic-intro");
			if (frm.is_new()) return;
			if (editable(frm) && !(frm.doc.meals || []).length) {
				actionButton(frm, "从上一周编排", "tongjianyun.meal_planning.initialize_week",
					() => ({ name: frm.doc.name }), async () => { await frm.reload_doc(); });
			}
			if (editable(frm) && (frm.doc.meals || []).length) {
				actionButton(frm, "刷新教育人数", "tongjianyun.meal_planning.refresh_population",
					() => ({ name: frm.doc.name }), async () => { await frm.reload_doc(); });
				const button = frm.add_custom_button(__("调整本餐菜品"), () => editMealDishes(frm, button));
			}
			frm.add_custom_button(__("周食谱表"), () => {
				frappe.set_route("query-report", reportName, { week_name: frm.doc.name });
			});
			if (frm.doc.docstatus === 2) return;
			if (frm.doc.docstatus === 1 && hasRole("System Manager", "Stock Manager")) {
				const button = frm.add_custom_button(__("配置厨房仓库"), () => configureKitchen(frm, button), __("厨房执行"));
			}
			if ((frm.doc.meals || []).length === 25 && frm.doc.requirement_weight_basis !== "采购毛重" && hasRole("System Manager", "Purchase Manager")) {
				const button = frm.add_custom_button(__("确认采购毛重口径"), () => {
					frappe.confirm(__("仅当原食谱带量已确认是清洗、去皮前的采购毛重时确认。确认后按原表用量计算，不另加损耗系数。"), () => runAction(frm, button,
						"tongjianyun.meal_weights.confirm_requirement_weight_basis", { week_name: frm.doc.name, basis: "采购毛重" }, async () => { await frm.reload_doc(); }));
				}, __("采购操作"));
			}
			actionButton(frm, "采购需求预览", previewMethod,
				() => ({ week_name: frm.doc.name }), (preview) => openProcurementPreview(frm, preview));
			if (canReviewStock() && frm.doc.docstatus === 0 && frm.doc.meals?.length) {
				const button = frm.add_custom_button(__("核对账面库存"), () => reviewStock(frm, button));
			}
			if (frm.doc.docstatus === 1) {
				if (canUseKitchen()) {
					const dayButton = frm.add_custom_button(__("打开每日执行"), () => openKitchenDay(frm, dayButton), __("厨房执行"));
					frm.add_custom_button(__("查看本周执行记录"), () => frappe.set_route("List", "Meal Kitchen Day", { meal_week: frm.doc.name }), __("厨房执行"));
				}
				if (hasRole("System Manager", "Stock Manager") && !frm.doc.kitchen_reconciled) {
					const button = frm.add_custom_button(__("审核厨房周核销"), () => {
						frappe.confirm(__("请核对五日实际供餐、领退耗损流水、厨房余料清点及采购未结单据。核销保留真实留存及其来源，不自动退料或清空库存。"), () => runAction(frm, button,
							"tongjianyun.meal_kitchen.reconcile_kitchen_week", { week_name: frm.doc.name }, async () => { await frm.reload_doc(); }));
					}, __("厨房执行"));
				}
				if (hasRole("System Manager", "食谱编排员", "膳食业务经办员")) {
					const button = frm.add_custom_button(__("申请单餐变更"), () => requestAdjustment(frm, button));
				}
				if (frm.doc.material_request && canDraftPurchase()) {
					const button = frm.add_custom_button(__("生成采购订单草稿"), () => draftPurchase(frm, button), __("采购操作"));
					const reissue = frm.add_custom_button(__("由经办人重制申请草稿"), () => {
						frappe.confirm(__("仅用于原草稿由管理员创建、尚无后续订单的情况。原申请将保留替代关系，新申请由当前经办人创建，随后交另一位授权人员审核。"), () => runAction(frm, reissue,
							"tongjianyun.meal_purchasing.reissue_material_request_draft", { week_name: frm.doc.name }, async (result) => {
								await frm.reload_doc();
								const name = result?.material_request || result?.name || frm.doc.material_request;
								if (!name) throw new Error(__("未返回替代采购申请编号，请刷新列表核对。"));
								frappe.set_route("Form", "Material Request", name);
							}));
					}, __("采购操作"));
				}
				if (!frm.doc.material_request && canCreateRequest()) {
					actionButton(frm, "生成采购申请草稿", "tongjianyun.meal_procurement.create_material_request",
						() => ({ week_name: frm.doc.name }), async (result) => {
							await frm.reload_doc();
							const name = result?.material_request || frm.doc.material_request;
							if (name) frappe.set_route("Form", "Material Request", name);
						});
				}
				if (hasRole("System Manager", "食谱编排员")) {
					const button = frm.add_custom_button(__("复制到下一周"), () => {
						if (frm.__meal_action_running) return;
						frappe.prompt([
							{ fieldname: "target_week_start", fieldtype: "Date", label: __("新一周开始日期"),
								reqd: 1, default: frappe.datetime.add_days(frm.doc.week_start, 7) },
						], (values) => runAction(frm, button, "tongjianyun.meal_planning.copy_next_week",
							{ name: frm.doc.name, target_week_start: values.target_week_start }, (result) => {
								const name = typeof result === "string" ? result : result?.name;
								if (!name) throw new Error(__("服务器未返回新一周的编号，请刷新列表核对。"));
								frappe.set_route("Form", "Meal Planning Week", name);
							}), __("复制周食谱"), __("创建新周草稿"));
					});
				}
			}
		},
		before_submit(frm) {
			if (!frm.doc.stock_reviewed) frappe.throw(__("请先预览采购需求，并由授权人员核对账面库存。"));
		},
		week_start(frm) {
			if (frm.doc.week_start) frm.set_value("week_end", frappe.datetime.add_days(frm.doc.week_start, 4));
			resetPreview(frm, "日期已调整，请保存后重新核对人数和采购需求。");
		},
	});

	frappe.ui.form.on("Meal Plan Meal", {
		excluded_count(frm) {
			resetPreview(frm, "停餐人数已调整，请保存后重新预览采购需求。人数由服务器重新核算。");
		},
		adjustment_reason(frm) {
			resetPreview(frm, "停餐调整说明已修改，请保存后重新预览采购需求。");
		},
		service_suspended(frm) {
			resetPreview(frm, "整餐供餐安排已修改，请保存后重新核对人数与采购需求。");
		},
		suspension_reason(frm) {
			resetPreview(frm, "整餐停供原因已修改，请保存后重新预览采购需求。");
		},
	});
})();
