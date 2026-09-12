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


BUSINESS_OBJECTS = {
    "学生档案": "Student", "班级": "Student Group",
    "学生考勤": "Student Attendance", "食谱计划": "Tongjianyun Recipe",
    "每日餐次菜品": "Tongjianyun Recipe Dish",
    "就餐人数确认": "Tongjianyun Daily Meal Confirmation",
    "采购订单": "Purchase Order", "采购收货": "Purchase Receipt",
    "采购发票": "Purchase Invoice", "付款记录": "Payment Entry",
}


def default_read_fields(meta, detail=False):
    """Bounded projection from actual metadata; never SQL '*' or secret fields."""
    from tongjianyun import harness_administrator as service
    candidates = ["name", getattr(meta, "title_field", None)]
    candidates += [f.fieldname for f in meta.fields if detail or f.in_list_view]
    selected = []
    for field in candidates:
        try:
            service._field(meta, field)
        except ValueError:
            continue
        if field not in selected:
            selected.append(field)
    return selected[:64 if detail else 16]


QUERY_CONTRACT = {
    "fields": "显式 fields 为 1–64 个元数据字段名；省略时返回安全默认字段。只返回 name 不表示其他字段不可读。",
    "filters": "最多 20 个字段的等值字典；不接受 SQL、表达式或运算符。",
    "pagination": "limit 为 1–100 的整数，start 为 0–100000；总数使用 total_count，继续查询使用 next_start。",
    "order_by": "仅支持 name asc；业务排序在返回结果中处理。",
    "relations": "元数据 Link 字段的 options 是关联 DocType；使用该表的 get_document 并指定所需 fields，每次独立检查权限。",
}


def execute(request):
    """Keep authentication failures closed; classify business read failures safely."""
    from tongjianyun import harness_administrator as service
    import frappe
    service._administrator()
    if not isinstance(request, dict) or request.get("operation") not in READ_FIELDS:
        return _execute(request)
    # Admission is rechecked by _execute. Do not reveal context on admission failure.
    users = frappe.conf.get("tongjianyun_shared_harness_users")
    if frappe.conf.get("tongjianyun_shared_harness_enabled") != 1 or not isinstance(users, list) or "Administrator" not in users:
        raise PermissionError("Administrator is not admitted")
    try:
        result = _execute(request)
    except frappe.DoesNotExistError:
        result = {"ok": False, "error": {"code": "not_found", "message": "单据类型或记录不存在，不代表没有权限。请按业务对象目录核对名称。"}}
    except (frappe.PermissionError, PermissionError):
        result = {"ok": False, "error": {"code": "access_denied", "message": "此查询被访问策略拒绝；不能推断账号对所有业务都无权限。"}}
    except (ValueError, TypeError, KeyError, frappe.ValidationError):
        result = {"ok": False, "error": {"code": "invalid_query", "message": "查询参数或字段不受支持。先查询元数据；limit 必须为 1–100，过滤条件仅支持等值字典，排序仅支持 name asc。不是权限结论。"}}
    except Exception:
        result = {"ok": False, "error": {"code": "query_failed", "message": "业务查询执行失败，原因尚未确认；不得解释为无权限或无数据。"}}
    result["query_context"] = {
        "query_contract": QUERY_CONTRACT,
        "today": frappe.utils.nowdate(), "timezone": frappe.utils.get_system_timezone(),
        "business_objects": {label: dt for label, dt in BUSINESS_OBJECTS.items()
            if frappe.db.exists("DocType", dt) and frappe.has_permission(dt, "read")},
        "recipe_rule": "食谱主表 Tongjianyun Recipe；按 meal_date 查询 Tongjianyun Recipe Dish，并核对关联食谱 is_deleted=0、workflow_status。草稿不得当已发布食谱，无当天记录不得用最近食谱冒充。",
    }
    return result


def _execute(request):
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
                           "label": field.label,
                           "options": field.options if field.fieldtype in {"Link", "Select", "Dynamic Link"} else None})
        from tongjianyun.harness_administrator_approvals import WRITE_ENABLE_KEY
        enabled = frappe.conf.get(WRITE_ENABLE_KEY)
        can_preview = type(enabled) in {int, bool} and enabled == 1
        for field in fields:
            try:
                service._field(meta, field["fieldname"], writing=True)
                field["writable"] = True
            except ValueError:
                field["writable"] = False
        return {"doctype": doctype, "fields": fields,
                "default_list_fields": default_read_fields(meta),
                "default_detail_fields": default_read_fields(meta, detail=True),
                "access": "preview-confirm" if can_preview else "read-only",
                "change_preview": {"tool": "employee_application_preview", "operation": "update",
                    "arguments": {"doctype": doctype, "name": "existing record name", "changes": "writable scalar fields only"},
                    "operations": ["create", "update", "submit", "cancel", "delete"],
                    "instructions": "Prepare only the requested change. A preview is NOT execution; the user must review and confirm separately."}
                if can_preview else None}
    options = {key: value for key, value in arguments.items() if key != "doctype"}
    if options.get("fields") is None:
        options["fields"] = default_read_fields(service._meta(doctype), detail=operation == "frappe_get_document")
    if options.pop("order_by", "name asc") not in {None, "name asc"}:
        raise ValueError("Only name asc ordering is currently supported")
    rows = service.read_documents(doctype, **options)
    if operation == "frappe_get_document":
        return {"doctype": doctype, "name": arguments["name"], "selected_fields": options["fields"],
                "document": rows[0] if rows else None}
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
    return {"doctype": doctype, "rows": rows, "selected_fields": options["fields"], "limit": arguments.get("limit", 20),
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
