(() => {
	"use strict";

	const MARK = "data-ione-sidebar-selector-disabled";
	const EVENTS = ["pointerdown", "mousedown", "touchstart", "click", "keydown"];

	function block_selector_event(event) {
		if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") {
			return;
		}
		event.preventDefault();
		event.stopImmediatePropagation();
	}

	function disable_sidebar_selector() {
		document.querySelectorAll(".sidebar-header").forEach((header) => {
			if (header.hasAttribute(MARK)) {
				return;
			}

			header.setAttribute(MARK, "1");
			header.setAttribute("aria-disabled", "true");
			header.querySelector(".drop-icon")?.setAttribute("aria-hidden", "true");
			EVENTS.forEach((event_name) => {
				header.addEventListener(event_name, block_selector_event, true);
			});
		});
	}

	function initialize() {
		disable_sidebar_selector();
		new MutationObserver(disable_sidebar_selector).observe(document.body, {
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
