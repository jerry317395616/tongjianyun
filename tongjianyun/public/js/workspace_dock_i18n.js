(() => {
	"use strict";

	// Frappe's lazy asset loader determines the file type from the URL. The
	// site asset manifest is versioned with a query string, so strip the query
	// before resolving the extension (otherwise `?v=...` is mistaken for one).
	if (window.frappe?.assets?.extn && !window.frappe.assets.__ione_query_extn) {
		const original_extn = window.frappe.assets.extn;
		window.frappe.assets.extn = function (path) {
			const clean_path = String(path || "").split("?")[0].split("#")[0];
			return original_extn.call(this, clean_path);
		};
		window.frappe.assets.__ione_query_extn = true;
	}

	const PATCH_FLAG = "__ione_workspace_dock_i18n";
	const FALLBACK_LABELS = {
		Home: "首页",
		Invoicing: "发票",
		Payments: "收付款",
		Accounting: "会计",
		Selling: "销售",
		Buying: "采购",
		"Financial Reports": "财务报表",
		Stock: "库存",
		Assets: "资产",
		Manufacturing: "制造",
		Projects: "项目",
		Support: "支持",
		CRM: "客户关系",
		"Human Resources": "人力资源",
		Payroll: "薪资",
		Quality: "质量",
		Subcontracting: "委外",
		Tools: "工具",
		Settings: "设置",
		Integrations: "集成",
		Users: "用户",
		Website: "网站",
		Email: "邮件",
		Build: "构建",
		Automation: "自动化",
		Printing: "打印",
		"ERPNext Settings": "ERPNext 设置",
		"Reports & Masters": "报表与基础资料",
		Vacant: "空闲",
		"Previous sessions": "历史会话",
		"New chat": "新建会话",
		"Full screen": "全屏",
		"Close (Ctrl+I)": "关闭 (Ctrl+I)",
		"Ask about your data, draft records, or run a task.":
			"询问数据、起草单据或执行任务。",
		"Ask Flow…": "询问 Flow…",
		"Attach file": "附加文件",
		"All Assessment Groups": "全部考核组",
		"Education Settings": "教育管理设置",
		Actions: "操作",
		"Assign To": "分配给",
		"Clear Assignment": "清除分配",
		Delete: "删除",
		Message: "消息",
		Docstatus: "文档状态",
		Assign: "分配",
		Attachments: "附件",
		Share: "分享",
		Comments: "评论",
		"New Email": "新建邮件",
		Attach: "上传",
	};
	const UI_TEXT_FALLBACK_CONTAINERS = [
		".form-sidebar",
		".list-row-container",
		".modal",
		".dropdown-menu",
		".awesomplete",
		".page-actions",
	].join(",");
	const UI_TEXT_FALLBACK_SKIP_TAGS = new Set([
		"INPUT",
		"TEXTAREA",
		"SCRIPT",
		"STYLE",
	]);

	function translate_label(label) {
		if (!label) {
			return label;
		}

		const translated = typeof __ === "function" ? __(label) : label;
		return translated !== label ? translated : FALLBACK_LABELS[label] || label;
	}

	function set_item_label(item, label) {
		if (!item || !label) {
			return;
		}

		for (const attribute of ["title", "aria-label", "data-original-title"]) {
			if (item.getAttribute(attribute) !== label) {
				item.setAttribute(attribute, label);
			}
		}
	}

	function translate_existing_items() {
		document
			.querySelectorAll(".workspace-dock-items .workspace-dock-item")
			.forEach((item) => {
				const label =
					item.getAttribute("data-original-title") ||
					item.getAttribute("title") ||
					item.getAttribute("aria-label");
				set_item_label(item, translate_label(label));
			});
	}

	function translate_flow_panel() {
		const root = document.querySelector("#flow-root");
		if (!root) {
			return;
		}

		root
			.querySelectorAll("[title], [aria-label], [data-original-title], [placeholder]")
			.forEach((item) => {
				for (const attribute of [
					"title",
					"aria-label",
					"data-original-title",
					"placeholder",
				]) {
					const value = item.getAttribute(attribute);
					const translated = translate_label(value);
					if (translated && translated !== value) {
						item.setAttribute(attribute, translated);
					}
				}
			});

		root.querySelectorAll("*").forEach((item) => {
			for (const node of item.childNodes) {
				if (node.nodeType !== Node.TEXT_NODE) {
					continue;
				}
				const value = node.nodeValue || "";
				const trimmed = value.trim();
				const translated = FALLBACK_LABELS[trimmed];
				if (translated) {
					node.nodeValue = value.replace(trimmed, translated);
				}
			}
		});
	}

	function translate_workspace_content() {
		document
			.querySelectorAll(".ce-header .h4, .widget-control .es-badge")
			.forEach((item) => {
				const value = item.textContent || "";
				const trimmed = value.trim();
				const vacant = trimmed.match(/^(\d+)\s+Vacant$/);
				const translated = vacant
					? `${vacant[1]} 空闲`
					: FALLBACK_LABELS[trimmed];
				if (translated && translated !== trimmed) {
					item.textContent = value.replace(trimmed, translated);
				}
			});
	}

	function translate_ui_text_fallback() {
		document.querySelectorAll(UI_TEXT_FALLBACK_CONTAINERS).forEach((container) => {
			const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
			let node = walker.nextNode();
			while (node) {
				const parent = node.parentElement;
				if (
					parent &&
					!UI_TEXT_FALLBACK_SKIP_TAGS.has(parent.tagName) &&
					!parent.isContentEditable
				) {
					const value = node.nodeValue || "";
					const trimmed = value.trim();
					const translated = FALLBACK_LABELS[trimmed];
					if (translated && translated !== trimmed) {
						node.nodeValue = value.replace(trimmed, translated);
					}
				}
				node = walker.nextNode();
			}
		});
	}

	// The unified navigation sidebar renders one URL row for each application and the
	// application modules as the rows that follow it. Frappe's native sidebar only knows
	// how to collapse a section's nested links, so add the missing application-level group
	// behavior here without changing any of the underlying routes or permissions.
	const APP_GROUP_STATE_KEY = "ione-app-group-collapsed";
	const APP_GROUP_STYLE_ID = "ione-app-group-collapse-style";

	function read_app_group_state() {
		try {
			const value = window.localStorage.getItem(APP_GROUP_STATE_KEY);
			return value ? JSON.parse(value) || {} : {};
		} catch (error) {
			return {};
		}
	}

	function write_app_group_state(state) {
		try {
			window.localStorage.setItem(APP_GROUP_STATE_KEY, JSON.stringify(state));
		} catch (error) {
			// A private browsing context can deny localStorage; the menu still works for
			// the current page in that case.
		}
	}

	function ensure_app_group_styles() {
		if (document.getElementById(APP_GROUP_STYLE_ID)) {
			return;
		}

		const style = document.createElement("style");
		style.id = APP_GROUP_STYLE_ID;
		style.textContent = `
			/*
			 * The generated Setup sidebar has three levels:
			 * application (direct row), module (Section Break), and feature
			 * (the nested links under that Section Break). Keep those levels
			 * visually distinct without changing Frappe's routes or controls.
			 */
			.sidebar-items > .ione-app-group-header {
				margin-top: 10px;
			}
			.sidebar-items > .ione-app-group-header:first-child {
				margin-top: 0;
			}
			.sidebar-items > .ione-app-group-header > .standard-sidebar-item > .item-anchor {
				min-height: 34px;
				padding-left: 10px;
				font-weight: 700;
				color: var(--ink-gray-8, #1f2937);
				background: var(--surface-gray-2, #f3f7ff);
				border: 1px solid var(--outline-gray-2, #dbe5f5);
				border-radius: 8px;
			}
			.sidebar-items > .ione-app-group-header > .standard-sidebar-item > .item-anchor:hover {
				background: var(--surface-gray-3, #e9f1ff);
			}
			.sidebar-items > .ione-app-group-header > .standard-sidebar-item > .item-anchor > .sidebar-item-label {
				font-size: var(--text-base, 14px);
				letter-spacing: 0.01em;
			}
			.sidebar-items > .ione-app-group-header > .standard-sidebar-item > .item-anchor > .sidebar-item-icon {
				opacity: 1;
				color: var(--blue-600, #2563eb);
			}
			.sidebar-items > .ione-app-group-header > .standard-sidebar-item > .item-anchor > .ione-app-group-toggle {
				margin-right: 6px;
			}

			/* Module headings sit below their application header and use a lighter band. */
			.sidebar-items > .ione-app-group-header + .section-item {
				margin-top: 6px;
			}
			.sidebar-items > .section-item {
				margin-left: 10px;
			}
			.sidebar-items > .section-item > .standard-sidebar-item > .item-anchor {
				min-height: 30px;
				padding-left: 10px;
				font-weight: 600;
				color: var(--ink-gray-7, #4b5563);
				background: var(--surface-gray-1, #f8fafc);
				border-left: 3px solid var(--blue-300, #93c5fd);
				border-radius: 6px;
			}
			.sidebar-items > .section-item > .standard-sidebar-item > .item-anchor:hover {
				background: var(--surface-gray-2, #f3f7ff);
				color: var(--ink-gray-8, #1f2937);
			}
			.sidebar-items > .section-item > .nested-container {
				margin-left: 24px;
				padding-left: 4px;
				border-left: 1px solid var(--outline-gray-2, #dbe5f5);
			}
			.sidebar-items > .section-item > .nested-container .sidebar-item-label {
				font-weight: var(--font-weight-regular, 400);
				color: var(--ink-gray-6, #6b7280);
			}

			.sidebar-items .ione-app-group-header .ione-app-group-toggle {
				display: inline-flex;
				align-items: center;
				justify-content: center;
				margin-left: auto;
				color: var(--text-muted, #8c8c8c);
				transition: transform 120ms ease;
			}
			.sidebar-items .ione-app-group-header.ione-app-group-collapsed .ione-app-group-toggle {
				transform: rotate(-90deg);
			}
		`;
		document.head.appendChild(style);
	}

	function app_slug_from_anchor(anchor) {
		const href = anchor?.getAttribute("href");
		if (!href) {
			return null;
		}

		try {
			const url = new URL(href, window.location.origin);
			// Frappe may prepend the current sidebar shell to a desk URL (for example
			// `/desk/setup/home?app=erpnext`) even though the stored URL is
			// `/desk/home?app=erpnext`. Both forms identify an application header.
			if (!/^\/desk(?:\/[^/]+)?\/home\/?$/.test(url.pathname)) {
				return null;
			}
			return url.searchParams.get("app");
		} catch (error) {
			const match = href.match(/\/desk(?:\/[^/?#]+)?\/home\/?\?app=([^&#]+)/);
			return match ? decodeURIComponent(match[1]) : null;
		}
	}

	function app_group_rows(sidebar_items) {
		return Array.from(sidebar_items.children)
			.filter((row) => row?.classList?.contains("sidebar-item-container"))
			.map((row) => ({
				row,
				anchor: row.querySelector(".standard-sidebar-item > .item-anchor[data-link-type='URL']"),
				app: app_slug_from_anchor(
					row.querySelector(".standard-sidebar-item > .item-anchor[data-link-type='URL']")
				),
			}))
			.filter((entry) => entry.app);
	}

	function set_app_group_collapsed(group, collapsed, state, persist = false) {
		const { row, anchor, children, app } = group;
		if (!row || !anchor || !app) {
			return;
		}

		row.classList.toggle("ione-app-group-collapsed", collapsed);
		anchor.setAttribute("aria-expanded", collapsed ? "false" : "true");
		anchor.setAttribute("role", "button");
		children.forEach((child) => {
			child.hidden = collapsed;
		});

		if (persist) {
			state[app] = collapsed;
			write_app_group_state(state);
		}
	}

	function install_app_group_collapse() {
		const sidebar_items = document.querySelectorAll(".body-sidebar .sidebar-items");
		if (!sidebar_items.length) {
			return;
		}

		ensure_app_group_styles();
		const state = read_app_group_state();

		sidebar_items.forEach((items_container) => {
			const direct_rows = Array.from(items_container.children).filter((row) =>
				row?.classList?.contains("sidebar-item-container")
			);
			const headers = app_group_rows(items_container);

			headers.forEach((header, index) => {
				const row_index = direct_rows.indexOf(header.row);
				const next_header_index =
					index + 1 < headers.length ? direct_rows.indexOf(headers[index + 1].row) : direct_rows.length;
				const children =
					row_index >= 0 && next_header_index > row_index
						? direct_rows.slice(row_index + 1, next_header_index)
						: [];
				const group = { ...header, children };
				header.row.classList.add("ione-app-group-header");

				const control = header.anchor.querySelector(".sidebar-item-control");
				if (control) {
					control.classList.add("ione-app-group-toggle");
					if (!control.dataset.ioneAppGroupIcon) {
						control.innerHTML =
							typeof window.frappe?.utils?.icon === "function"
								? window.frappe.utils.icon("chevron-down", "sm")
								: "⌄";
						control.dataset.ioneAppGroupIcon = "1";
					}
				}

				if (!header.anchor.dataset.ioneAppGroupBound) {
					header.anchor.addEventListener("click", (event) => {
						// Keep normal browser affordances (open in a new tab, copy link, etc.).
						if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
							return;
						}
						event.preventDefault();
						event.stopImmediatePropagation();
						const next_state = read_app_group_state();
						const collapsed = !header.row.classList.contains("ione-app-group-collapsed");
						set_app_group_collapsed(group, collapsed, next_state, true);
					});
					header.anchor.dataset.ioneAppGroupBound = "1";
				}

				const collapsed = Boolean(state[header.app]);
				set_app_group_collapsed(group, collapsed, state);
			});
		});
	}

	let translation_scheduled = false;
	function schedule_translation() {
		if (translation_scheduled) {
			return;
		}
		translation_scheduled = true;
		window.requestAnimationFrame(() => {
			translation_scheduled = false;
			install_app_group_collapse();
			translate_existing_items();
			translate_flow_panel();
			translate_workspace_content();
			translate_ui_text_fallback();
		});
	}

	function install_workspace_dock_patch() {
		const prototype = window.frappe?.ui?.WorkspaceDock?.prototype;
		if (!prototype?.make_workspace_item) {
			return false;
		}

		if (prototype[PATCH_FLAG]) {
			return true;
		}

		const make_workspace_item = prototype.make_workspace_item;
		prototype.make_workspace_item = function (workspace) {
			const item = make_workspace_item.call(this, workspace);
			const label = workspace?.title || workspace?.label || workspace?.name;
			const translated = translate_label(label);

			if (item?.attr && translated) {
				item.attr({
					title: translated,
					"aria-label": translated,
					"data-original-title": translated,
				});
			}

			return item;
		};
		prototype[PATCH_FLAG] = true;
		return true;
	}

	function initialize() {
		let attempts = 0;
		const timer = window.setInterval(() => {
			attempts += 1;
			const installed = install_workspace_dock_patch();
			install_app_group_collapse();
			translate_existing_items();
			translate_flow_panel();
			translate_workspace_content();
			translate_ui_text_fallback();

			if (installed || attempts >= 100) {
				window.clearInterval(timer);
			}
		}, 100);

		const observer = new MutationObserver(schedule_translation);
		observer.observe(document.body, { childList: true, subtree: true });

		for (const delay of [1000, 3000, 8000]) {
			window.setTimeout(() => {
				install_app_group_collapse();
				translate_flow_panel();
				translate_workspace_content();
				translate_ui_text_fallback();
			}, delay);
		}
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", initialize, { once: true });
	} else {
		initialize();
	}
})();
