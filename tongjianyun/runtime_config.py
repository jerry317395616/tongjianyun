from __future__ import annotations

import re
from pathlib import Path

WEB_PROGRAM = "[program:frappe-bench-frappe-web]"
WEB_REQUEST_TIMEOUT = 900


def ensure_web_request_timeout(
	config_path: str | Path | None = None,
	timeout: int = WEB_REQUEST_TIMEOUT,
) -> bool:
	"""Keep long-running Flow SSE requests alive beyond Press's 120-second default."""
	path = Path(config_path) if config_path else _supervisor_config_path()
	if not path.is_file():
		return False

	content = path.read_text(encoding="utf-8")
	start = content.find(WEB_PROGRAM)
	if start < 0:
		return False

	end = content.find("\n[", start + len(WEB_PROGRAM))
	if end < 0:
		end = len(content)

	block = content[start:end]
	updated_block, replacements = re.subn(
		r"(?<![\w-])(--timeout\s+)\d+",
		rf"\g<1>{int(timeout)}",
		block,
		count=1,
	)
	if replacements != 1 or updated_block == block:
		return False

	path.write_text(content[:start] + updated_block + content[end:], encoding="utf-8")
	return True


def _supervisor_config_path() -> Path:
	from frappe.utils import get_bench_path

	return Path(get_bench_path()) / "config" / "supervisor.conf"
