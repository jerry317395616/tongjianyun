from __future__ import annotations

CRM_I18N_ASSET = "/assets/tongjianyun/js/crm_i18n_20260804.js?v=20260804-3"
CRM_I18N_MARKER = 'data-ione-crm-i18n="20260804-3"'
UTF8_PRIVATE_FILE_CONTENT_TYPES = {
	"application/csv",
	"application/json",
	"application/markdown",
	"text/csv",
	"text/markdown",
	"text/plain",
}


def utf8_private_file_content_type(
	*,
	path: str,
	method: str,
	status_code: int,
	content_type: str,
) -> str | None:
	"""Return a UTF-8 content type for private text attachments when needed."""
	normalized_path = (path or "").split("?", 1)[0]
	normalized_content_type = (content_type or "").strip()
	mime_type = normalized_content_type.split(";", 1)[0].strip().lower()
	if (
		method.upper() != "GET"
		or status_code != 200
		or not normalized_path.startswith("/private/files/")
		or "charset=" in normalized_content_type.lower()
		or mime_type not in UTF8_PRIVATE_FILE_CONTENT_TYPES
	):
		return None
	return f"{mime_type}; charset=utf-8"


def ensure_utf8_private_file_response(response, request) -> None:
	"""Declare UTF-8 for private text files so browsers render Chinese correctly."""
	try:
		content_type = utf8_private_file_content_type(
			path=request.path,
			method=request.method,
			status_code=response.status_code,
			content_type=response.headers.get("Content-Type", ""),
		)
		if content_type:
			response.headers["Content-Type"] = content_type
	except (AttributeError, RuntimeError, TypeError):
		# Response hooks must not make private file downloads unavailable.
		return


def is_crm_html_response(
	*,
	path: str,
	method: str,
	status_code: int,
	content_type: str,
	language: str,
) -> bool:
	"""Return whether a response needs the CRM-only localization asset."""
	normalized_path = (path or "").split("?", 1)[0].rstrip("/") or "/"
	normalized_language = (language or "").lower().replace("-", "_")
	return (
		method.upper() == "GET"
		and status_code == 200
		and (normalized_path == "/crm" or normalized_path.startswith("/crm/"))
		and "text/html" in (content_type or "").lower()
		and normalized_language.split("_", 1)[0] == "zh"
	)


def inject_crm_i18n_asset(html: str) -> str:
	"""Insert the localization script once, immediately before the closing body tag."""
	if not html or CRM_I18N_MARKER in html or "</body>" not in html:
		return html
	tag = (
		f'<script defer charset="utf-8" src="{CRM_I18N_ASSET}" '
		f'{CRM_I18N_MARKER}></script>'
	)
	return html.replace("</body>", f"{tag}\n</body>", 1)


def inject_crm_i18n(response, request) -> None:
	"""Inject I-ONE CRM localization without changing the upstream CRM application."""
	try:
		import frappe

		language = str(getattr(frappe.local, "lang", "") or "")
		content_type = response.headers.get("Content-Type", "")
		if not is_crm_html_response(
			path=request.path,
			method=request.method,
			status_code=response.status_code,
			content_type=content_type,
			language=language,
		):
			return

		html = response.get_data(as_text=True)
		localized_html = inject_crm_i18n_asset(html)
		if localized_html != html:
			response.set_data(localized_html)
	except (AttributeError, RuntimeError, TypeError, UnicodeDecodeError):
		# Response hooks must never make CRM unavailable if a non-HTML response differs.
		return
