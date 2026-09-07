"""Fixed read-only worker for the trusted shared authority, never a model CLI."""
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
        return {"doctype": doctype, "fields": fields, "access": "read-only"}
    options = {key: value for key, value in arguments.items() if key != "doctype"}
    if options.pop("order_by", "name asc") not in {None, "name asc"}:
        raise ValueError("Only name asc ordering is currently supported")
    rows = service.read_documents(doctype, **options)
    if operation == "frappe_get_document":
        return {"doctype": doctype, "name": arguments["name"], "document": rows[0] if rows else None}
    return {"doctype": doctype, "rows": rows, "limit": arguments.get("limit", 20),
            "start": arguments.get("start", 0)}


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
