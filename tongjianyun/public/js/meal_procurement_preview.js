(() => {
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
	const icons = {
		buying: '<path d="M3 9h18l-2.5 9.5a2 2 0 0 1-2 1.5h-9a2 2 0 0 1-2-1.5ZM7 9l3-5a2.3 2.3 0 0 1 4 0l3 5"/>',
		stock: '<path d="m3 7 9-4 9 4v10l-9 4-9-4Zm0 0 9 4 9-4m-9 4v10"/>',
		info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>',
	};
	const icon = (name) => `<svg class="tjy-proc-icon" viewBox="0 0 24 24" fill="none"
		stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"
		aria-hidden="true" focusable="false">${icons[name]}</svg>`;
	const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 6 });
	const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
	const columns = ["食材", "需求量", "分配库存", "分配待到货", "已申请量", "本次申请量"];
	const statuses = {
		kitchen_water: "厨房用水 · 无需采购",
		needs_recipe: "待补配方",
		needs_policy: "待确认采购分类",
		needs_conversion: "待确认单位换算",
	};
	const ingredientPhotos = [
		[/^(大米|粳米|白米|籼米|强化长粒白米)(?:$|[（( ])/u, "rice"],
		[/^鲜?(胡萝卜|红萝卜)(?:$|[（( ])/u, "carrot"],
		[/^(鸡蛋|鲜鸡蛋)(?:$|[（( ])/u, "egg"],
		[/^(鲜南瓜|南瓜|贝贝南瓜)(?:$|[（( ])/u, "pumpkin"],
	];
	const isNumber = (value) => value != null && value !== "" && Number.isFinite(Number(value));
	const quantity = (value, unit) => isNumber(value)
		? `${number.format(Number(value))}${unit ? ` ${unit}` : ""}` : "—";
	const isoDay = (date) => new Date(`${date}T00:00:00Z`);
	const weekday = (date) => weekdays[isoDay(date).getUTCDay()] || "";
	const shortDate = (date, slash) => {
		const value = isoDay(date);
		return Number.isFinite(value.getTime())
			? `${value.getUTCMonth() + 1}${slash ? "/" : "月"}${value.getUTCDate()}${slash ? "" : "日"}` : "";
	};
	const mealLabel = (row) => [weekday(row.meal_date), row.meal_type].filter(Boolean).join(" · ");
	const displayName = (row) => row.item_name || row.item_code;
	const hasPurchase = (row) => row.status === "purchase" && Number(row.purchase_qty) > 0;
	const amount = (row) => row.status === "purchase" ? quantity(row.purchase_qty, row.purchase_uom) : "—";

	function weekDates(start, end) {
		const startDay = isoDay(start);
		const lastDay = isoDay(end);
		const dates = [];
		for (const day = new Date(startDay); day <= lastDay && dates.length < 7; day.setUTCDate(day.getUTCDate() + 1)) {
			dates.push(day.toISOString().slice(0, 10));
		}
		if (!dates.length) return { dates, period: "" };
		const year = startDay.getUTCFullYear();
		const endYear = lastDay.getUTCFullYear();
		return { dates, period: `${year}年${shortDate(start)}—${endYear === year ? "" : `${endYear}年`}${shortDate(end)}` };
	}

	function photoClass(row) {
		return ingredientPhotos.find(([pattern]) => pattern.test(displayName(row)))?.[1] || "";
	}

	function photoUrl(preview, row) {
		const path = preview.item_images?.[row.item_code];
		if (typeof path !== "string" || !path.startsWith("/")) return "";
		try {
			const url = new URL(path, window.location.origin);
			return url.origin === window.location.origin && /^\/(files|assets)\//.test(url.pathname) ? url.href : "";
		} catch {
			return "";
		}
	}

	function thumbnail(preview, row) {
		const url = photoUrl(preview, row);
		const photo = photoClass(row);
		return `<span class="tjy-proc-thumb" data-photo="${photo}" aria-hidden="true">
			${photo ? "" : icon("stock")}
			${url ? `<img alt="" loading="lazy" src="${escape(url)}">` : ""}
		</span>`;
	}

	function notice(label, messages, tone) {
		if (!messages.length) return "";
		return `<details class="tjy-proc-notice" data-tone="${tone}" ${tone === "danger" ? "open" : ""}>
			<summary>${label} · ${messages.length} 项</summary>
			<ul>${messages.map((message) => `<li>${escape(message)}</li>`).join("")}</ul>
		</details>`;
	}

	function detailLine(label, value, emphasis = false) {
		return `<div${emphasis ? ' class="is-total"' : ""}><dt>${label}</dt><dd>${escape(value)}</dd></div>`;
	}

	function inventoryDetails(preview, row) {
		const claims = (preview.stock_claims || []).filter((claim) =>
			claim.item_code === row.item_code && claim.warehouse === row.warehouse);
		const lines = [
			["现货实存", "physical_qty"], ["本周已安排", "own_claim_qty"],
			["其他周已安排", "other_week_claim_qty"], ["尚无归属", "free_qty"],
			["本次可用无归属", "available_free_qty"],
		];
		return `<details class="tjy-proc-inventory">
			<summary>原料仓库存安排</summary>
			<div>
				${row.warehouse ? `<p>${escape(row.warehouse)}</p>` : ""}
				${isNumber(row.allocated_owned_stock_qty) ? `<dl class="tjy-proc-lines">
					${detailLine("本周已有归属", quantity(row.allocated_owned_stock_qty, row.stock_uom))}
					${detailLine("本次认领现货", quantity(row.new_physical_claim_qty, row.stock_uom))}
				</dl>` : ""}
				${claims.map((claim) => `<dl class="tjy-proc-lines">
					${lines.map(([label, key]) => detailLine(label, quantity(claim[key], row.stock_uom))).join("")}
				</dl>`).join("")}
				${claims.length ? "" : "<p>暂无原料仓现货安排。</p>"}
			</div>
		</details>`;
	}

	function renderDetail(preview, row) {
		const purchase = row.status === "purchase";
		const quote = purchase && row.price_status !== "available";
		const art = photoClass(row);
		const photo = photoUrl(preview, row);
		const formatStock = (value) => quantity(value, row.stock_uom);
		const subtract = (value) => isNumber(value) ? formatStock(Number(value) ? -Number(value) : 0) : "—";
		const offsets = [row.allocated_stock_qty, row.expected_receipt_qty, row.already_requested_qty, row.planned_surplus_used_qty];
		const remainder = Math.max(0, offsets.reduce((total, value) => total - Number(value || 0), Number(row.required_qty)));
		const conversion = purchase && row.stock_uom && row.purchase_uom && row.stock_uom !== row.purchase_uom
			&& Number(row.conversion_factor) > 0;
		const converted = quantity(row.purchase_stock_qty, row.stock_uom);

		return `<div class="tjy-proc-inspector-head"><h3 id="tjy-proc-detail">食材核对明细</h3>
			<button type="button" data-action="close-detail" aria-label="关闭食材核对明细">×</button></div>
			<div class="tjy-proc-detail-content">
				<div class="tjy-proc-ingredient">
					<h3>${escape(displayName(row))}</h3>
					${quote || !purchase ? `<span class="tjy-proc-badge">${escape(quote ? "待询价" : (statuses[row.status] || "待确认"))}</span>` : ""}
				</div>
				<p class="tjy-proc-context">${escape([shortDate(row.meal_date), mealLabel(row)].filter(Boolean).join(" · "))}</p>
				<div class="tjy-proc-hero" data-photo="${photo ? "" : art}">
					<div><strong>本次申请量</strong><b>${escape(amount(row))}</b></div>
					${conversion ? `<div class="tjy-proc-conversion"><span>${escape(converted)}</span>
						<small>${escape(`1 ${row.purchase_uom} = ${formatStock(row.conversion_factor)}`)}</small></div>` : ""}
					${photo ? `<img alt="" src="${escape(photo)}">` : ""}
				</div>
				<h4>需求计算明细</h4>
				<dl class="tjy-proc-lines">
					${detailLine("需求量", formatStock(row.required_qty))}
					${detailLine("分配库存", subtract(row.allocated_stock_qty))}
					${detailLine("分配待到货", subtract(row.expected_receipt_qty))}
					${detailLine("已申请量", subtract(row.already_requested_qty))}
					${Number(row.planned_surplus_used_qty) > 0 ? detailLine("前餐采购余量抵扣", subtract(row.planned_surplus_used_qty)) : ""}
					${detailLine("还需采购", purchase ? formatStock(remainder) : "—", true)}
				</dl>
				${isNumber(row.purchase_stock_qty) && Number(row.purchase_stock_qty) - remainder > 0.0000005 && purchase
					? '<p class="tjy-proc-meta">本次申请量已按采购单位进位。</p>' : ""}
				${inventoryDetails(preview, row)}
				${row.production_plan ? `<button type="button" class="tjy-proc-link" data-action="plan">查看对应生产计划</button>` : ""}
			</div>`;
	}

	function render(wrapper, preview, review) {
		const rows = preview.rows || [];
		const totals = preview.totals || {};
		const blockers = preview.blockers || [];
		const warnings = preview.warnings || [];
		const { dates, period } = weekDates(preview.week_start, preview.week_end);
		const $view = $("<div>", { class: "tjy-proc-view" }).appendTo(wrapper.empty());
		let selectedDate = "";
		let purchaseOnly = false;
		let selectedIndex = null;
		const reviewed = Boolean(Number(preview.stock_reviewed));
		const advance = preview.advance_purchase_mode ? [preview.advance_purchase_note || "提前采购不预支旧周余量。"] : [];
		$view.html(`<section class="tjy-proc-shell" aria-label="采购需求预览">
			<div class="tjy-proc-main">
				<div class="tjy-proc-content">
					<header class="tjy-proc-heading">
						<h2>本周采购需求预览</h2>
						<span>${escape(period)}</span>
					</header>
					<div class="tjy-proc-summary" aria-label="全周汇总">
						${icon("buying")}<span><b>${escape(totals.ingredient_count ?? "—")}</b> 种食材</span>
						<span><b>${escape(totals.purchase_row_count ?? "—")}</b> 行需采购</span>
						<span><b>${escape(totals.need_quote_count ?? "—")}</b> 项待询价</span>
					</div>
					<div class="tjy-proc-dates" role="group" aria-label="使用日期">
						<button type="button" data-day="" aria-pressed="true">全周</button>
						${dates.map((day) => `<button type="button" data-day="${day}" aria-pressed="false">${weekday(day)} ${shortDate(day, true)}</button>`).join("")}
					</div>
					${notice("待处理", blockers, "danger")}${notice("采购提示", [...advance, ...warnings], "warning")}
					<div class="tjy-proc-table-title">
						<h2>食材需求明细</h2>
						<label><input type="checkbox" data-filter="purchase"> 仅看需采购</label>
					</div>
					<div class="tjy-proc-table-scroll">
						<table aria-label="食材需求明细">
							<thead><tr>${columns.map((name) => `<th scope="col">${name}</th>`).join("")}</tr></thead>
							<tbody></tbody>
						</table>
					</div>
				</div>
				<div class="tjy-proc-footer">
					<strong role="status">${icon("info")} <span>${reviewed ? "账面库存已核对" : "账面库存待核对"}</span></strong>
					${review ? `<button type="button" class="is-primary" data-action="review" ${blockers.length ? "disabled" : ""}>${reviewed ? "重新核对账面库存" : "核对账面库存"}</button>` : ""}
				</div>
			</div>
			<aside class="tjy-proc-inspector" aria-labelledby="tjy-proc-detail" hidden></aside>
		</section>`);
		const $body = $view.find("tbody");
		const $inspector = $view.find(".tjy-proc-inspector");
		const $shell = $view.find(".tjy-proc-shell");

		function showDetail(index, focus) {
			const row = rows[index];
			selectedIndex = row ? index : null;
			$body.find("[data-row]").each((_, button) => {
				const selected = Number(button.dataset.row) === selectedIndex;
				button.setAttribute("aria-expanded", String(selected));
				button.closest("tr").classList.toggle("is-selected", selected);
			});
			$inspector.prop("hidden", !row).html(row ? renderDetail(preview, row) : "");
			$shell.toggleClass("has-detail", Boolean(row));
			watchImages($inspector);
			if (row && focus) $inspector.find("[data-action='close-detail']").trigger("focus");
		}

		function renderRows() {
			const visible = rows.flatMap((row, index) =>
				(!selectedDate || row.meal_date === selectedDate) && (!purchaseOnly || hasPurchase(row)) ? [[row, index]] : []);
			if (selectedIndex !== null && !visible.some(([, index]) => index === selectedIndex)) showDetail(null);
			$body.html(visible.map(([row, index]) => `
				<tr data-entry="${index}" class="${index === selectedIndex ? "is-selected" : ""}">
					<th scope="row"><button type="button" data-row="${index}" aria-expanded="${index === selectedIndex}">
						${thumbnail(preview, row)}
						<span><b>${escape(displayName(row))}</b><small>${escape(mealLabel(row))}</small>
						${row.status === "purchase" ? "" : `<small class="tjy-proc-row-status">${escape(statuses[row.status] || "待确认")}</small>`}</span>
					</button></th>
					${[row.required_qty, row.allocated_stock_qty, row.expected_receipt_qty, row.already_requested_qty]
						.map((value) => `<td>${escape(quantity(value, row.stock_uom))}</td>`).join("")}
					<td class="tjy-proc-purchase">${escape(amount(row))}</td>
				</tr>`).join("") || `<tr><td colspan="6" class="tjy-proc-empty">${rows.length
					? "当前筛选下没有食材需求。" : "暂无食材需求，请先完成餐次编排和人数核算。"}</td></tr>`);
			watchImages($body);
		}

		function watchImages($area) {
			$area.find("img").one("error", (event) => event.target.remove()).each((_, img) => {
				if (img.complete && !img.naturalWidth) img.remove();
			});
		}

		$view.on("click", "[data-day]", (event) => {
			selectedDate = event.currentTarget.dataset.day;
			$view.find("[data-day]").attr("aria-pressed", "false");
			event.currentTarget.setAttribute("aria-pressed", "true");
			renderRows();
		}).on("change", "[data-filter='purchase']", (event) => {
			purchaseOnly = event.currentTarget.checked;
			renderRows();
		}).on("click", "[data-entry]", (event) => {
			showDetail(Number(event.currentTarget.dataset.entry), true);
		}).on("click", "[data-action]", (event) => {
			const button = event.currentTarget;
			switch (button.dataset.action) {
				case "close-detail": {
					const index = selectedIndex;
					showDetail(null);
					$body.find(`[data-row="${index}"]`).trigger("focus");
					break;
				}
				case "review": review?.($(button)); break;
				case "plan": frappe.set_route("Form", "Production Plan", rows[selectedIndex].production_plan); break;
			}
		});
		renderRows();
	}

	window.tjyProcurementPreview = { render };
})();
