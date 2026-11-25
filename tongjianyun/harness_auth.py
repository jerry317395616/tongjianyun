"""Frappe SSO launcher for the local DeepSeek Harness instance.

The endpoint intentionally issues a short-lived, single-use signed hand-off
token.  Harness never receives the Frappe session cookie and the token is
consumed by the local gateway before the Harness UI is opened.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import frappe


TOKEN_TTL_SECONDS = 60
HARNESS_SSO_URL = "https://harness.myyr.top/sso"


def _b64url(value: bytes) -> str:
	return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _secret() -> bytes:
	value = str(frappe.conf.get("harness_sso_shared_secret") or "").strip()
	if len(value) < 32:
		frappe.throw("DeepSeek Harness 单点登录尚未配置，请联系管理员。")
	return value.encode("utf-8")


@frappe.whitelist(allow_guest=True)
def launch():
	"""Redirect the current Frappe user to Harness through the SSO gateway."""
	if frappe.session.user in {"Guest", ""}:
		redirect_to = "/api/method/tongjianyun.harness_auth.launch"
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = "/login?" + urlencode({"redirect-to": redirect_to})
		return

	now = int(time.time())
	payload = {
		"iss": "child.myyr.top",
		"sub": str(frappe.session.user),
		"iat": now,
		"exp": now + TOKEN_TTL_SECONDS,
		"jti": secrets.token_urlsafe(18),
	}
	body = _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
	signature = _b64url(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
	token = body + "." + signature

	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = HARNESS_SSO_URL + "?" + urlencode({"token": token})
