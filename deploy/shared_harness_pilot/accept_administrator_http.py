"""Live signed-session reads only; emit checks, never cookies or business values."""
import json
import os
from urllib.parse import urlsplit
import frappe
from ione_core import harness_auth
from accept_live_http import request


def main():
    cookies, sessions = [], []
    stage = "initialize"
    os.chdir("/home/zyd/frappe/native-bench")
    frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
    frappe.connect(set_admin_as_user=False)
    try:
        for user in ["Administrator", "317395616@qq.com"]:
            stage = "signed_login"
            frappe.set_user(user)
            harness_auth.launch()
            status, headers, _ = request("/employee/sso?" + urlsplit(frappe.local.response["location"]).query)
            assert status == 303
            cookie = headers["set-cookie"].split(";", 1)[0]
            cookies.append(cookie)
            status, _, body = request("/employee/status", cookie)
            assert status == 200 and body["agentExecution"] is True
            status, _, body = request("/employee/session/create", cookie, {})
            assert status == 200
            sessions.append(body["sessionId"])

        def read(index, doctype, fields=None, session=None):
            return request("/employee/session/read", cookies[index], {
                "sessionId": session or sessions[index], "operation": "frappe_list_documents",
                "arguments": {"doctype": doctype, "fields": fields or ["name"], "limit": 1}})

        stage = "administrator_business_read"
        status, _, body = read(0, "Item")
        assert status == 200 and isinstance(body["rows"], list)
        stage = "employee_scope_unchanged"
        status, _, _ = read(1, "Item")
        assert status in (401, 403)
        status, _, body = read(1, "Student")
        assert status == 200 and isinstance(body["rows"], list)
        stage = "protected_data_denied"
        status, _, _ = read(0, "User")
        assert status in (400, 401, 403)
        status, _, _ = read(0, "Item", ["api_key"])
        assert status in (400, 401, 403)
        stage = "cross_session_denied"
        status, _, _ = read(0, "Student", session=sessions[1])
        assert status in (403, 404)
        stage = "write_still_closed"
        status, _, _ = request("/employee/session/read", cookies[0], {
            "sessionId": sessions[0], "operation": "frappe_apply_document_update", "arguments": {}})
        assert status in (400, 401, 403)
        stage = "administrator_model_query"
        status, _, turn = request("/employee/session/prompt", cookies[0], {
            "sessionId": sessions[0],
            "text": "请调用 employee_frappe_read 工具查询 Item，fields 为 name，limit 为 1。只查询，不修改。最后只回复查询已完成，不展示具体数据。"})
        assert status == 200 and turn.get("settled") is True
        status, _, page = request("/employee/session/page", cookies[0], {
            "sessionId": sessions[0], "throughSeq": turn["throughSeq"], "maxMessages": 50})
        assert status == 200
        types = {row.get("event", {}).get("type") for row in page.get("records", [])}
        assert "tool/result" in types and "assistant/message" in types
        print(json.dumps({"passed": True, "checks": ["Administrator signed login", "Item read",
            "employee scope unchanged", "protected fields denied", "session isolation", "writes remain closed",
            "Administrator model tool turn"],
            "business_records_changed": 0, "harness_sessions_created": 2, "browser_tested": False}))
        return 0
    except Exception as error:
        print(json.dumps({"passed": False, "stage": stage, "error_type": type(error).__name__,
                          "http_status": locals().get("status")}))
        return 1
    finally:
        for cookie in cookies:
            try:
                request("/employee/logout", cookie, {})
            except Exception:
                pass  # Diagnostic cleanup; no cookie or failure details emitted.
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
