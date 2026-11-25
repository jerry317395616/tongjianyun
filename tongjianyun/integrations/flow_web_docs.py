from __future__ import annotations

import ipaddress
import re
import socket
from typing import Annotated, Any
from urllib.parse import urljoin, urlsplit, urlunsplit

ALLOWED_HOSTS = frozenset({"docs.frappe.io"})
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_MARKDOWN_CHARACTERS = 40_000
REQUEST_TIMEOUT = (10, 45)
USER_AGENT = "I-ONE-Flow-Docs/1.0 (+https://myyr.top)"


def fetch_frappe_document(
	url: Annotated[str, "Full HTTPS URL of one page on docs.frappe.io."],
) -> dict[str, Any]:
	"""Read one official Frappe documentation page and return its main content as Markdown."""
	from requests import Session

	current_url = _validate_target_url(url)
	session = Session()
	# Production may have a workstation proxy configured globally. Official docs
	# must use the server's direct connection so that a dead proxy cannot break Flow.
	session.trust_env = False
	session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"})

	for redirect_count in range(MAX_REDIRECTS + 1):
		response = session.get(
			current_url,
			allow_redirects=False,
			stream=True,
			timeout=REQUEST_TIMEOUT,
		)
		try:
			if response.is_redirect or response.is_permanent_redirect:
				if redirect_count >= MAX_REDIRECTS:
					raise ValueError("Frappe documentation URL redirected too many times.")
				location = response.headers.get("Location")
				if not location:
					raise ValueError("Frappe documentation redirect did not include a target URL.")
				current_url = _validate_target_url(urljoin(current_url, location))
				continue

			response.raise_for_status()
			content_type = response.headers.get("Content-Type", "").lower()
			if not (content_type.startswith("text/html") or content_type.startswith("text/plain")):
				raise ValueError(f"Unsupported documentation content type: {content_type or 'unknown'}.")

			content_length = response.headers.get("Content-Length")
			if content_length and int(content_length) > MAX_RESPONSE_BYTES:
				raise ValueError("Frappe documentation page is larger than the allowed size.")

			payload = _read_limited_response(response)
			encoding = response.encoding or "utf-8"
			html = payload.decode(encoding, errors="replace")
			title, markdown = _extract_document(html, current_url)
			return {
				"url": current_url,
				"title": title,
				"markdown": markdown,
				"characters": len(markdown),
			}
		finally:
			response.close()

	raise ValueError("Unable to read the Frappe documentation page.")


def _validate_target_url(url: str) -> str:
	if not isinstance(url, str) or not url.strip():
		raise ValueError("A Frappe documentation URL is required.")

	parsed = urlsplit(url.strip())
	host = (parsed.hostname or "").lower().rstrip(".")
	if parsed.scheme.lower() != "https":
		raise ValueError("Only HTTPS Frappe documentation URLs are allowed.")
	if parsed.username or parsed.password:
		raise ValueError("Credentials are not allowed in documentation URLs.")
	if parsed.port not in (None, 443):
		raise ValueError("Only the standard HTTPS port is allowed.")
	if host not in ALLOWED_HOSTS:
		raise ValueError("Only docs.frappe.io pages can be read by this tool.")

	addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
	if not addresses:
		raise ValueError("The Frappe documentation host could not be resolved.")
	for address in {row[4][0] for row in addresses}:
		if not ipaddress.ip_address(address).is_global:
			raise ValueError("The documentation URL resolved to a non-public address.")

	path = parsed.path or "/"
	return urlunsplit(("https", host, path, parsed.query, ""))


def _read_limited_response(response: Any) -> bytes:
	chunks: list[bytes] = []
	total = 0
	for chunk in response.iter_content(chunk_size=64 * 1024):
		if not chunk:
			continue
		total += len(chunk)
		if total > MAX_RESPONSE_BYTES:
			raise ValueError("Frappe documentation page is larger than the allowed size.")
		chunks.append(chunk)
	return b"".join(chunks)


def _extract_document(html: str, source_url: str) -> tuple[str, str]:
	from bs4 import BeautifulSoup
	from markdownify import markdownify

	soup = BeautifulSoup(html, "html.parser")
	content = soup.select_one(".prose") or soup.find("article") or soup.find("main")
	if content is None:
		raise ValueError("The Frappe documentation page did not contain readable article content.")

	for element in content.select("script, style, nav, form, button, noscript, svg"):
		element.decompose()
	for element in content.select("a[href]"):
		element["href"] = urljoin(source_url, element.get("href", ""))
	for element in content.select("img[src]"):
		element["src"] = urljoin(source_url, element.get("src", ""))

	h1 = content.find("h1") or soup.find("h1")
	title = h1.get_text(" ", strip=True) if h1 else ""
	if not title and soup.title:
		title = soup.title.get_text(" ", strip=True).split(" | ", 1)[0]
	title = title or "Frappe Documentation"

	markdown = markdownify(str(content), heading_style="ATX", bullets="-")
	markdown = re.sub(r"[ \t]+\n", "\n", markdown)
	markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
	if len(markdown) < 80:
		raise ValueError("The Frappe documentation page did not contain enough readable content.")
	if len(markdown) > MAX_MARKDOWN_CHARACTERS:
		markdown = markdown[:MAX_MARKDOWN_CHARACTERS].rstrip() + "\n\n[Content truncated by Flow tool]"
	return title, markdown
