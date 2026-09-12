"""Fixed worker for the trusted authority; business actions remain in Tongjianyun."""
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import sys

BENCH = Path("/home/zyd/frappe/native-bench")
HELPERS = Path("/home/zyd/frappe/deepseek-harness/packages/extensions/tool-native-bench-frappe/python")
sys.path.insert(0, str(HELPERS))
from employee_read_broker import strict_json
from shared_identity import READ_FIELDS


def execute(request):
    from tongjianyun import harness_administrator as service
    import frappe
    if not isinstance(request, dict) or set(request) != {"operation", "arguments"}:
        raise ValueError("invalid request")
    operation, arguments = request["operation"], request["arguments"]
    service._administrator()
    users = frappe.conf.get("tongjianyun_shared_harness_users")
    enabled = frappe.conf.get("tongjianyun_shared_harness_enabled")
    if type(enabled) not in {int, bool} or enabled != 1 or not isinstance(users, list) or "Administrator" not in users:
        raise PermissionError("Administrator is not admitted")
    if operation == "check" and arguments == {}:
        return {"enabled": True}
    if operation == "application":
        from tongjianyun import harness_administrator_approvals as approvals
        return approvals.dispatch(arguments)
    if (not isinstance(operation, str) or operation not in READ_FIELDS or not isinstance(arguments, dict)
            or set(arguments) - READ_FIELDS[operation]):
        raise ValueError("unsupported read")
    doctype = arguments["doctype"]
    if operation == "frappe_get_document":
        service._name(arguments.get("name"))
    if operation == "frappe_describe_doctype":
        meta = service._meta(doctype)
        fields = [{"fieldname": "name", "fieldtype": "Data"}]
        for field in meta.fields:
            try:
                service._field(meta, field.fieldname)
            except ValueError:
                continue
            fields.append({"fieldname": field.fieldname, "fieldtype": field.fieldtype,
                           "label": field.label})
        from tongjianyun.harness_administrator_approvals import WRITE_ENABLE_KEY
        enabled = frappe.conf.get(WRITE_ENABLE_KEY)
        can_preview = type(enabled) in {int, bool} and enabled == 1
        for field in fields:
            try:
                service._field(meta, field["fieldname"], writing=True)
                field["writable"] = True
            except ValueError:
                field["writable"] = False
        return {"doctype": doctype, "fields": fields, "access": "preview-confirm" if can_preview else "read-only",
                "change_preview": {"tool": "employee_application_preview", "operation": "update",
                    "arguments": {"doctype": doctype, "name": "existing record name", "changes": "writable scalar fields only"},
                    "operations": ["create", "update", "submit", "cancel", "delete"],
                    "instructions": "Prepare only the requested change. A preview is NOT execution; the user must review and confirm separately."}
                if can_preview else None}
    options = {key: value for key, value in arguments.items() if key != "doctype"}
    if options.pop("order_by", "name asc") not in {None, "name asc"}:
        raise ValueError("Only name asc ordering is currently supported")
    rows = service.read_documents(doctype, **options)
    if operation == "frappe_get_document":
        return {"doctype": doctype, "name": arguments["name"], "document": rows[0] if rows else None}
    # read_documents above validates the DocType, fields and equality filters.
    # Count through Frappe's permission-aware list path, never the returned page.
    from frappe.desk.reportview import get_count
    filters = {key: service._scalar(value) for key, value in (options.get("filters") or {}).items()}
    if options.get("name") is not None:
        filters["name"] = options["name"]
    previous = frappe.local.form_dict
    try:
        frappe.local.form_dict = frappe._dict(doctype=doctype, filters=filters, distinct=1, limit=0)
        total = int(get_count())
    finally:
        frappe.local.form_dict = previous
    start = arguments.get("start", 0)
    has_more = start + len(rows) < total
    return {"doctype": doctype, "rows": rows, "limit": arguments.get("limit", 20),
            "start": start, "page_count": len(rows), "total_count": total,
            "count_scope": "all_matching_records", "permission_scope": "current_user",
            "filters": filters, "has_more": has_more,
            "next_start": start + len(rows) if has_more else None,
            "count_instructions": "总人数使用 total_count；page_count、limit 和 rows 长度仅为本页条数，不是总数。"}


def main():
    # Child stdout is a bounded protocol channel; logs and failures never leak.
    raw = sys.stdin.buffer.read(8193)
    if len(raw) > 8192:
        return 1
    try:
        request = strict_json(raw)
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            import frappe
            os.chdir(BENCH)
            frappe.init(site="child.myyr.top", sites_path=str(BENCH / "sites"))
            try:
                frappe.connect(set_admin_as_user=False)
                # The parent authority verified its private browser credential.
                # There is no user/site argument and no public worker endpoint.
                frappe.set_user("Administrator")
                result = execute(request)
            finally:
                frappe.db.rollback()
                frappe.destroy()
        output = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        if len(output) > 262144:
            return 1
        sys.stdout.buffer.write(output)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
