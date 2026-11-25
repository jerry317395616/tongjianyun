from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any


TOKEN_PREFIX = "ione1"
MAX_TOKEN_LENGTH = 4096


def _decode_segment(value: str) -> bytes:
	padding = "=" * (-len(value) % 4)
	return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _shared_secret() -> str:
	import frappe

	secret = str(frappe.conf.get("ione_agent_identity_shared_secret") or "").strip()
	if len(secret) < 32:
		frappe.throw("I-ONE Agent identity verification is not configured")
	return secret


def verify_actor_token(token: str, *, now: int | None = None) -> dict[str, Any]:
	"""Verify a short-lived identity assertion issued by the trusted Agent bridge."""
	import frappe

	value = str(token or "").strip()
	if not value or len(value) > MAX_TOKEN_LENGTH:
		frappe.throw("A valid Manager login identity is required", frappe.AuthenticationError)
	parts = value.split(".")
	if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
		frappe.throw("Manager login identity is invalid", frappe.AuthenticationError)

	signed = f"{parts[0]}.{parts[1]}".encode("ascii")
	expected = hmac.new(_shared_secret().encode("utf-8"), signed, hashlib.sha256).digest()
	try:
		provided = _decode_segment(parts[2])
	except (ValueError, UnicodeError):
		frappe.throw("Manager login identity is invalid", frappe.AuthenticationError)
	if not hmac.compare_digest(provided, expected):
		frappe.throw("Manager login identity is invalid", frappe.AuthenticationError)

	try:
		payload = json.loads(_decode_segment(parts[1]).decode("utf-8"))
	except (ValueError, UnicodeError, json.JSONDecodeError):
		frappe.throw("Manager login identity is invalid", frappe.AuthenticationError)
	if not isinstance(payload, dict) or payload.get("v") != 1 or payload.get("iss") != "ione-agent":
		frappe.throw("Manager login identity is invalid", frappe.AuthenticationError)

	current = int(time.time() if now is None else now)
	issued_at = int(payload.get("iat") or 0)
	expires_at = int(payload.get("exp") or 0)
	if issued_at > current + 60 or expires_at < current or expires_at - issued_at > 900:
		frappe.throw("Manager login identity has expired", frappe.AuthenticationError)

	current_site = str(getattr(frappe.local, "site", "") or "").strip().lower()
	audience = str(payload.get("aud") or "").strip().lower()
	if not current_site or not audience or not hmac.compare_digest(audience, current_site):
		frappe.throw("Manager login identity is for a different site", frappe.AuthenticationError)

	email = str(payload.get("email") or "").strip()
	if not email or len(email) > 254:
		frappe.throw("Manager login identity does not contain an account", frappe.AuthenticationError)
	return payload


def resolve_actor_user(token: str) -> str:
	"""Resolve a signed Manager user hint and email to one enabled System User."""
	import frappe

	payload = verify_actor_token(token)
	email = str(payload["email"]).strip()
	hint = str(payload.get("user") or "").strip()

	def valid_user(name: str | None) -> str | None:
		if not name:
			return None
		user_doc = frappe.get_doc("User", name)
		if str(user_doc.email or "").strip().casefold() != email.casefold():
			return None
		if not user_doc.enabled or user_doc.user_type != "System User":
			return None
		return str(user_doc.name)

	user = None
	if hint:
		user = valid_user(frappe.db.get_value("User", {"name": hint}, "name"))
		if not user:
			user = valid_user(frappe.db.get_value("User", {"username": hint}, "name"))

	if not user:
		matches = frappe.get_all(
			"User",
			filters={"email": email, "enabled": 1, "user_type": "System User"},
			pluck="name",
			limit_page_length=3,
		)
		if len(matches) == 1:
			user = valid_user(matches[0])
		elif len(matches) > 1:
			frappe.throw(
				"The logged-in Manager email is linked to multiple accounts; sign in again to identify the account",
				frappe.AuthenticationError,
			)

	if not user:
		frappe.throw("The logged-in Manager account no longer exists", frappe.AuthenticationError)
	return str(user)


def actor_identity_required() -> bool:
	"""Return whether this site requires all generic MCP tools to use a signed actor."""
	import frappe

	value = frappe.conf.get("ione_mcp_require_actor_token")
	if isinstance(value, str):
		return value.strip().lower() not in {"", "0", "false", "no", "off"}
	return bool(value)


@contextmanager
def actor_context(token: str | None):
	"""Temporarily run a tool as the signed, currently logged-in Frappe user.

	Sites that have not enabled ``ione_mcp_require_actor_token`` remain backward
	compatible: when no token is supplied, the authenticated integration user is
	used exactly as before.
	"""
	import frappe

	from tongjianyun.mcp.security import require_login

	integration_user = require_login()
	value = str(token or "").strip()
	if not value:
		if actor_identity_required():
			frappe.throw("The current Frappe login identity is required", frappe.AuthenticationError)
		yield integration_user
		return

	actor_user = resolve_actor_user(value)
	previous_integration_user = getattr(frappe.local, "ione_mcp_integration_user", None)
	frappe.local.ione_mcp_integration_user = integration_user
	frappe.set_user(actor_user)
	try:
		yield actor_user
	finally:
		frappe.set_user(integration_user)
		if previous_integration_user is None:
			try:
				delattr(frappe.local, "ione_mcp_integration_user")
			except AttributeError:
				pass
		else:
			frappe.local.ione_mcp_integration_user = previous_integration_user


def as_verified_actor(fn):
	"""Run one MCP tool inside :func:`actor_context` while preserving its schema."""
	@wraps(fn)
	def wrapper(*args, **kwargs):
		import inspect

		bound = inspect.signature(fn).bind_partial(*args, **kwargs)
		with actor_context(bound.arguments.get("actor_token")):
			return fn(*args, **kwargs)

	return wrapper
