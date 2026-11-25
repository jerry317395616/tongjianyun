(() => {
	"use strict";

	if (!window.location.pathname.startsWith("/crm")) {
		return;
	}
	window.__ione_crm_i18n_loaded = true;

	const EXACT_LABELS = new Map([
		["Call Logs", "通话记录"],
		["Continue", "继续"],
		["Getting started", "入门指南"],
		["Help centre", "帮助中心"],
		["of", "/"],
		["Skip all", "全部跳过"],
		["Start now", "立即开始"],
		["Welcome to Frappe CRM", "欢迎使用客户关系管理"],
	]);
	const TRANSLATABLE_ATTRIBUTES = [
		"aria-label",
		"data-original-title",
		"placeholder",
		"title",
	];
	const SKIPPED_PARENTS = new Set(["SCRIPT", "STYLE", "TEXTAREA"]);
	const pending_nodes = new Set();
	let translation_scheduled = false;

	function translate_label(value) {
		if (!value) {
			return value;
		}

		const normalized = value.replace(/\s+/g, " ").trim();
		if (EXACT_LABELS.has(normalized)) {
			return EXACT_LABELS.get(normalized);
		}

		let match = normalized.match(/^(\d+)\/(\d+)\s+steps(?:\s+completed)?$/i);
		if (match) {
			return `${match[1]}/${match[2]} 个步骤已完成`;
		}

		match = normalized.match(/^(\d+)%\s+completed$/i);
		if (match) {
			return `已完成 ${match[1]}%`;
		}

		return value;
	}

	function replace_preserving_whitespace(value, translated) {
		const start = value.search(/\S/);
		if (start < 0) {
			return value;
		}
		const end = value.search(/\s*$/);
		return `${value.slice(0, start)}${translated}${value.slice(end)}`;
	}

	function translate_text_node(node) {
		const parent = node.parentElement;
		if (
			!parent ||
			SKIPPED_PARENTS.has(parent.tagName) ||
			parent.closest('[contenteditable="true"]')
		) {
			return;
		}

		const translated = translate_label(node.nodeValue || "");
		if (translated !== node.nodeValue) {
			node.nodeValue = replace_preserving_whitespace(node.nodeValue || "", translated);
		}
	}

	function translate_element(element) {
		for (const attribute of TRANSLATABLE_ATTRIBUTES) {
			const value = element.getAttribute(attribute);
			const translated = translate_label(value);
			if (value && translated !== value) {
				element.setAttribute(attribute, translated);
			}
		}
	}

	function translate_tree(root) {
		if (root.nodeType === Node.TEXT_NODE) {
			translate_text_node(root);
			return;
		}
		if (root.nodeType !== Node.ELEMENT_NODE) {
			return;
		}

		translate_element(root);
		root.querySelectorAll("*").forEach(translate_element);
		const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
		let node = walker.nextNode();
		while (node) {
			translate_text_node(node);
			node = walker.nextNode();
		}
	}

	function schedule_translation(node) {
		pending_nodes.add(node || document.body);
		if (translation_scheduled) {
			return;
		}
		translation_scheduled = true;
		window.requestAnimationFrame(() => {
			translation_scheduled = false;
			for (const pending_node of pending_nodes) {
				translate_tree(pending_node);
			}
			pending_nodes.clear();
		});
	}

	function initialize() {
		schedule_translation(document.body);
		const observer = new MutationObserver((mutations) => {
			for (const mutation of mutations) {
				if (mutation.type === "characterData") {
					schedule_translation(mutation.target);
					continue;
				}
				mutation.addedNodes.forEach(schedule_translation);
			}
		});
		observer.observe(document.body, {
			characterData: true,
			childList: true,
			subtree: true,
		});
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", initialize, { once: true });
	} else {
		initialize();
	}
})();
