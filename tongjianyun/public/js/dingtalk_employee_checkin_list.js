/* Extend the native HRMS list; keep its actions, permissions and socket updates. */
(() => {
	const settings = (frappe.listview_settings["Employee Checkin"] ||= {});
	if (settings._dingtalk_realtime_installed) return;
	settings._dingtalk_realtime_installed = true;
	const original_onload = settings.onload;
	const original_refresh = settings.refresh;
	const original_indicator = settings.get_indicator;
	const original_name_formatter = settings.formatters?.employee_name;
	const contexts = new Map();
	const method = "tongjianyun.dingtalk_realtime.";
	settings.add_fields = [...new Set([...(settings.add_fields || []),
		"employee", "shift", "attendance", "offshift", "skip_auto_attendance"] )];
	settings.formatters = { ...(settings.formatters || {}) };
	settings.formatters.employee_name = (value, df, doc) => {
		const name = original_name_formatter ? original_name_formatter(value, df, doc) : value;
		const context = contexts.get(doc.name);
		// The native subject renderer assigns this value to textContent and title.
		return [name, context?.department, context?.shift].filter(Boolean).join(" · ");
	};
	settings.get_indicator = (doc) => {
		const original = original_indicator?.(doc);
		if (original) return original;
		if (doc.skip_auto_attendance) return [__("不参与自动考勤"), "gray", "skip_auto_attendance,=,1"];
		if (doc.attendance) return [__("已生成考勤"), "green", "attendance,is,set"];
		if (!doc.shift) return [__("待核对班次"), "orange", "shift,is,not set"];
		return [__("已记录，待考勤"), "blue", "attendance,is,not set"];
	};
	function active(listview) {
		const route = frappe.get_route();
		return route?.[0] === "List" && route[1] === "Employee Checkin" && cur_list === listview;
	}
	function hr_reader() {
		return ["System Manager", "HR Manager", "HR User"].some((role) => frappe.user.has_role(role));
	}
	function format_time(value) {
		if (!value) return __("暂无");
		const date = new Date(value);
		return Number.isNaN(date.valueOf()) ? __("暂无") : date.toLocaleString("zh-CN", {
			timeZone: "Asia/Shanghai", hour12: false,
		});
	}
	function show_status(listview) {
		const s = listview._dingtalk_status;
		if (!s) return;
		const labels = { connected: __("已连接"), reconnecting: __("正在重连"),
			paused: __("导入暂停"), unavailable: __("状态暂不可用") };
		const rows = [
			[__("钉钉连接"), labels[s.state]], [__("等待同步"), s.pending],
			[__("正在重试"), s.failed_pending],
			[__("需要检查的同步任务"), s.attention_pending],
			[__("最早未同步时间"), format_time(s.oldest_pending_received_at)],
			[__("最近收到打卡"), format_time(s.last_event_received)],
			[__("最近打卡同步成功"), format_time(s.last_import_success)],
			[__("最近补漏成功"), format_time(s.last_reconcile_success)],
			[__("最近补漏新增签到"), s.last_reconcile_created],
			[__("最近补漏发现需复核"), s.last_reconcile_review_count],
			[__("最近考勤结算成功"), format_time(s.last_settlement_success)],
			[__("最近结算等待打卡窗口结束"), s.last_settlement_deferred_count],
			[__("补漏状态"), s.reconcile_failed ? __("失败，等待重试") : __("正常")],
			[__("结算状态"), s.settlement_failed ? __("失败，等待重试") : __("正常")],
		];
		const esc = (value) => frappe.utils.escape_html(String(value ?? ""));
		frappe.msgprint({ title: __("钉钉考勤同步状态"),
			message: `<table class="table table-bordered"><tbody>${rows.map(([label, value]) =>
				`<tr><th>${esc(label)}</th><td>${esc(value)}</td></tr>`).join("")}</tbody></table>` +
				`<p class="text-muted small">${esc(__("时间均为北京时间。复核数量仅表示最近一次补漏发现的问题，不代表尚未处理总数。"))}</p>`,
		});
	}
	async function update_status(listview) {
		if (!hr_reader() || listview._dingtalk_status_loading) return;
		listview._dingtalk_status_loading = true;
		try {
			const { message: status } = await frappe.call({ method: method + "get_sync_status", silent: true });
			if (!status || !active(listview)) return;
			listview._dingtalk_status = status;
			const good = status.state === "connected" && !status.attention_pending &&
				!status.reconcile_failed && !status.settlement_failed;
			const labels = { connected: __("钉钉已连接"), reconnecting: __("钉钉重连中"),
				paused: __("钉钉导入暂停"), unavailable: __("钉钉状态暂不可用") };
			listview.page.set_indicator(`${labels[status.state]} · ${__("待同步")} ${status.pending}`, good ? "green" : "orange");
		} catch (_error) {
			if (active(listview)) listview.page.set_indicator(__("钉钉状态暂不可用"), "orange");
		} finally { listview._dingtalk_status_loading = false; }
	}
	function update_context(listview) {
		if (!active(listview) || listview._dingtalk_context_loading) return;
		const names = (listview.data || []).slice(0, 100).map((doc) => doc.name);
		const key = JSON.stringify((listview.data || []).slice(0, 100).map((doc) => [doc.name, doc.modified]));
		if (!names.length || (key === listview._dingtalk_context_key && Date.now() - listview._dingtalk_context_at < 60000)) return;
		listview._dingtalk_context_loading = true;
		Promise.resolve(frappe.call({ method: method + "get_checkin_context", args: { names }, silent: true }))
			.then(({ message }) => {
				if (!active(listview) || !message) return;
				for (const name of names) contexts.delete(name);
				Object.entries(message).forEach(([name, context]) => contexts.set(name, context));
				listview._dingtalk_context_key = key;
				listview._dingtalk_context_at = Date.now();
				// Redraw the native rows with cached text. Do not fetch the list again.
				listview._dingtalk_native_render();
			}).catch(() => {}).finally(() => { listview._dingtalk_context_loading = false; });
	}
	function start_poll(listview) {
		if (listview._dingtalk_timer) return;
		const tick = async () => {
			listview._dingtalk_timer = null;
			if (!active(listview)) return;
			if (!document.hidden) {
				await update_status(listview);
				// Recovery for a browser socket interruption. Standard queries retain
				// filters/User Permissions; respect native editing and bulk actions.
				if (Date.now() - (listview._dingtalk_fallback_at || 0) >= 60000 &&
					!listview.avoid_realtime_update?.() && !listview.checked_docnames?.size &&
					!listview.get_checked_items?.().length) {
					listview._dingtalk_fallback_at = Date.now();
					listview.refresh();
				}
			}
			if (active(listview)) listview._dingtalk_timer = setTimeout(tick, 30000);
		};
		listview._dingtalk_timer = setTimeout(tick, 30000);
	}
	settings.onload = function (listview) {
		original_onload?.call(this, listview);
		const native_render = listview.render_list.bind(listview);
		listview._dingtalk_native_render = native_render;
		listview.render_list = (...args) => { const result = native_render(...args); update_context(listview); return result; };
		if (hr_reader()) listview.page.add_inner_button(__("钉钉同步状态"), () => show_status(listview));
		update_status(listview);
		start_poll(listview);
	};
	settings.refresh = function (listview) {
		original_refresh?.call(this, listview);
		update_context(listview);
		start_poll(listview);
	};
})();
