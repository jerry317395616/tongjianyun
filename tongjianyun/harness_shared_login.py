"""Opt-in Frappe launcher for the account-scoped Harness API.

Reuse IONE Core's signed handoff, never its privileged Host login carrier.
The old launcher and all application permissions remain unchanged.
"""
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import frappe
from ione_core import harness_auth

LAUNCH_PATH = "/api/method/tongjianyun.harness_shared_login.launch"


def _deny():
    frappe.throw("共享 AI 入口尚未向此账号开放，请联系管理员。", frappe.PermissionError)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def launch():
    """Issue a handoff only for the current enabled, explicitly admitted user.

    Deployment must enable this entry after shared routing and UI acceptance.
    Neither a request parameter nor Administrator status selects an actor or
    bypasses the account allowlist. No business records are changed.
    """
    frappe.local.response_headers.set("Cache-Control", "no-store")
    frappe.local.response_headers.set("Referrer-Policy", "no-referrer")
    if frappe.session.user in {"Guest", ""}:
        frappe.local.response.update({
            "type": "redirect",
            "location": "/login?" + urlencode({"redirect-to": LAUNCH_PATH}),
        })
        return

    # The existing signing implementation pins this issuer; do not mint a
    # child-site assertion for a user authenticated on another site.
    if frappe.local.site != "child.myyr.top":
        _deny()
    enabled = frappe.conf.get("tongjianyun_shared_harness_enabled")
    users = frappe.conf.get("tongjianyun_shared_harness_users")
    if (type(enabled) not in {bool, int} or enabled != 1
            or not isinstance(users, list) or not 1 <= len(users) <= 256
            or any(not isinstance(user, str) or not user or user != user.strip() for user in users)
            or len(set(users)) != len(users)
            or frappe.session.user not in users
            or frappe.session.user == "Administrator"):
        _deny()
    user = frappe.db.get_value("User", frappe.session.user, ["enabled", "user_type"], as_dict=True)
    if not user or not user.enabled or user.user_type != "System User":
        _deny()

    # IONE Core owns signing and expiry. Redirect only that launcher's exact
    # HTTPS destination to the employee exchange, never a caller-supplied URL.
    expected = urlsplit(harness_auth.HARNESS_SSO_URL)
    if (expected.scheme != "https" or expected.netloc != "harness.myyr.top"
            or expected.path != "/sso" or expected.query or expected.fragment):
        _deny()
    harness_auth.launch()
    response = frappe.local.response
    actual = urlsplit(response.get("location", ""))
    if (response.get("type") != "redirect" or actual.scheme != expected.scheme
            or actual.netloc != expected.netloc or actual.path != expected.path
            or actual.fragment or set(parse_qs(actual.query)) != {"token"}):
        response.pop("location", None)
        response.pop("type", None)
        _deny()
    response["location"] = urlunsplit((actual.scheme, actual.netloc, "/employee/sso", actual.query, ""))
