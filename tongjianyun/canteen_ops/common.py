from decimal import Decimal, InvalidOperation

import frappe
from frappe.model.document import Document
from frappe.permissions import get_user_permissions
from frappe.utils import cint, getdate

CANTEEN = "Tongjianyun Canteen"
POLICY = "Tongjianyun Canteen Policy"
CREDENTIAL = "Tongjianyun Canteen Credential"
TRAINING = "Tongjianyun Canteen Training"
TERM = "Tongjianyun Meal Term Project"
TASK = "Tongjianyun Meal Weekly Task"
DISPATCH = "Tongjianyun Canteen Purchase Dispatch"
PRICE = "Tongjianyun Canteen Price Review"
DELIVERY = "Tongjianyun Canteen Delivery"
RECEIVING = "Tongjianyun Canteen Receiving"
SAMPLE = "Tongjianyun Food Sample"
COMPANION = "Tongjianyun Meal Companion"
STATEMENT = "Tongjianyun Canteen Reconciliation"
VOUCHER = "Tongjianyun Canteen Finance Request"
FINDING = "Tongjianyun Canteen Finding"
LOT_MOVEMENT = "Tongjianyun Canteen Stock Lot Movement"
MANAGED = (CANTEEN, POLICY, CREDENTIAL, TRAINING, TERM, TASK, DISPATCH, PRICE, DELIVERY, RECEIVING,
           SAMPLE, COMPANION, STATEMENT, VOUCHER, FINDING, LOT_MOVEMENT)
SUPPLIER_ROLE = "膳食供应商"
EDU_ROLE, SAFETY_ROLE, FINANCE_ROLE = "膳食教育监管", "膳食食品安全监管", "膳食财政监管"
REGULATORS = frozenset((EDU_ROLE, SAFETY_ROLE, FINANCE_ROLE))
ROLES = (SUPPLIER_ROLE, *sorted(REGULATORS))
REGULATOR_CATEGORIES = {
    EDU_ROLE: {"供餐", "食品安全", "人员与证照"},
    SAFETY_ROLE: {"库存", "采购与验收", "食品安全", "人员与证照"},
    FINANCE_ROLE: {"财务", "采购与验收"},
}
DAY = "Meal Kitchen Day"
WEEK = "Meal Planning Week"
ZERO = Decimal("0")


def require(condition, message, error=None):
    if not condition:
        if error:
            frappe.throw(message, error)
        frappe.throw(message)


def permission(condition, message="当前账号没有操作该园所或单据的权限。"):
    require(condition, message, frappe.PermissionError)


def decimal(value):
    try:
        number = Decimal(str(value if value is not None and value != "" else 0))
        if number.is_finite():
            return number
    except (InvalidOperation, TypeError, ValueError):
        pass
    frappe.throw("请填写有效数字。")


def positive(value, message="数量必须大于零。"):
    number = decimal(value)
    require(number > 0, message)
    return number


def dates(start, end):
    require(start and end and getdate(start) <= getdate(end), "结束日期须晚于或等于起始日期。")


def records(doctype, filters=None, fields=None, **kwargs):
    return frappe.get_list(doctype, filters=filters or {}, fields=fields or ["name"], limit_page_length=0, **kwargs)


def linked(doctype, name, action="read", lock=False):
    require(name, f"请选择 {doctype}。")
    result = frappe.get_doc(doctype, name, for_update=lock)
    result.check_permission(action)
    return result


def lock_company(company):
    # All feature operations which claim availability share this existing native document lock.
    permission(bool(frappe.db.get_value("Company", company, "name", for_update=True)))


def locked_rows(doctype, filters, fields):
    return frappe.qb.get_query(doctype, filters=filters, fields=fields, for_update=True).run(as_dict=True)


def company_doc(doc, doctype, value, action="read"):
    source = linked(doctype, value, action)
    require(source.company == doc.company, "来源单据必须属于同一园所。")
    return source


def submitted(source):
    require(source.docstatus == 1, "请先提交来源单据。")
    return source


def roles(user=None):
    return set(frappe.get_roles(user or frappe.session.user))


def restricted_supplier(user=None):
    assigned = roles(user)
    return SUPPLIER_ROLE in assigned and "System Manager" not in assigned


def allowed_values(doctype, user=None):
    return {
        row["doc"] for row in get_user_permissions(user or frappe.session.user).get(doctype, [])
        if row.get("doc")
    }


def _in(column, values):
    return f"{column} in ({', '.join(frappe.db.escape(value) for value in sorted(values))})" if values else "1=0"


def regulator_categories(assigned):
    return set().union(*(REGULATOR_CATEGORIES[role] for role in REGULATORS & assigned))


def scoped_query(doctype):
    def condition(user=None):
        assigned = roles(user)
        if "System Manager" in assigned:
            return ""
        table = f"`tab{doctype}`"
        companies = allowed_values("Company", user)
        if SUPPLIER_ROLE in assigned:
            if doctype not in (DELIVERY, STATEMENT, CANTEEN):
                return "1=0"
            clauses = [_in(f"{table}.company", companies)]
            if doctype != CANTEEN:
                clauses.append(_in(f"{table}.supplier", allowed_values("Supplier", user)))
            return " and ".join(clauses)
        if companies or (REGULATORS & assigned):
            clauses = [_in(f"{table}.company", companies)]
            if doctype == FINDING and REGULATORS & assigned:
                clauses.append(_in(f"{table}.category", regulator_categories(assigned)))
            return " and ".join(clauses)
        return ""
    return condition


def scoped_permission(doc, user=None, permission_type=None, **kwargs):
    assigned = roles(user)
    if "System Manager" in assigned:
        return True
    companies = allowed_values("Company", user)
    if SUPPLIER_ROLE in assigned:
        if doc.doctype not in (DELIVERY, STATEMENT, CANTEEN) or doc.company not in companies:
            return False
        if doc.doctype != CANTEEN and doc.supplier not in allowed_values("Supplier", user):
            return False
    elif (companies or REGULATORS & assigned) and doc.company not in companies:
        return False
    if doc.doctype == FINDING and REGULATORS & assigned and doc.category not in regulator_categories(assigned):
        return False
    # Frappe's DocType roles and native document access still decide the operation.
    return True


def validate_scope(doc):
    permission(frappe.session.user != "Guest")
    permission(scoped_permission(doc) is not False)
    if not restricted_supplier():
        linked("Company", doc.company)
    if doc.get("canteen"):
        site = linked(CANTEEN, doc.canteen)
        require(site.company == doc.company and (not cint(site.disabled) or not doc.is_new()),
                "请选择同一园所的有效食堂。")


def canteen_for_week(week, canteen=None):
    filters = {"company": week.company, "disabled": 0}
    for key in ("raw_warehouse", "kitchen_warehouse"):
        value = week.get(key) or (week.get("raw_material_warehouse") if key == "raw_warehouse" else None)
        if value:
            filters[key] = value
    if canteen:
        filters["name"] = canteen
    rows = records(CANTEEN, filters)
    require(len(rows) == 1, "请先为周食谱的原料仓和厨房仓维护唯一的食堂档案。")
    return linked(CANTEEN, rows[0].name)


def active_policy(canteen, event_date, *, required=True):
    # Rules are validated upon submission and can be read internally for enforcement.
    day = getdate(event_date)
    names = frappe.get_all(POLICY, filters={
        "canteen": canteen, "docstatus": 1, "from_date": ("<=", day), "to_date": (">=", day),
    }, pluck="name", limit_page_length=2)
    if not names and not required:
        return None
    require(len(names) == 1, "该食堂在业务日期须有一条已生效的采购和财务规则。")
    return frappe.get_doc(POLICY, names[0])


def attached_file(doc, url, *, required=False, image=False):
    if not url and not required:
        return
    require(url and str(url).startswith("/private/files/"), "请在本单上传私有附件。")
    require(not doc.is_new(), "请先保存表单，再上传附件。")
    matches = frappe.get_all("File", filters={"file_url": url, "is_private": 1, "attached_to_doctype": doc.doctype,
                                               "attached_to_name": doc.name}, fields=["name", "file_name"])
    require(matches, "附件须附在当前单据上。")
    if image:
        require(matches[0].file_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".heic")),
                "请上传现场照片。")


def unique_active(doc, filters, message):
    lock_company(doc.company)
    if frappe.db.exists(doc.doctype, {**filters, "docstatus": ("<", 2), "name": ("!=", doc.name or "")}):
        frappe.throw(message)


class CanteenDocument(Document):
    def _handler(self):
        from tongjianyun.canteen_ops import finance, inventory, purchasing, safety

        handlers = {
            CANTEEN: safety.Canteen,
            POLICY: purchasing.Policy,
            CREDENTIAL: safety.Credential,
            TRAINING: safety.Training,
            TERM: safety.Term,
            TASK: safety.WeeklyTask,
            DISPATCH: purchasing.Dispatch,
            PRICE: purchasing.PriceReview,
            DELIVERY: purchasing.Delivery,
            RECEIVING: purchasing.Receiving,
            SAMPLE: safety.FoodSample,
            COMPANION: safety.Companion,
            STATEMENT: finance.Statement,
            VOUCHER: finance.Voucher,
            FINDING: safety.Finding,
            LOT_MOVEMENT: inventory.Movement,
        }
        return handlers[self.doctype](self)

    def validate(self):
        validate_scope(self)
        self._handler().validate()

    def before_insert(self):
        method = getattr(self._handler(), "before_insert", None)
        if method:
            method()

    def before_submit(self):
        method = getattr(self._handler(), "before_submit", None)
        if method:
            method()

    def on_submit(self):
        method = getattr(self._handler(), "on_submit", None)
        if method:
            method()

    def before_update_after_submit(self):
        validate_scope(self)
        method = getattr(self._handler(), "before_update_after_submit", None)
        if method:
            method()

    def before_cancel(self):
        validate_scope(self)
        method = getattr(self._handler(), "before_cancel", None)
        if method:
            method()


class Handler:
    def __init__(self, doc):
        self.doc = doc


PERMISSION_QUERIES = {}
for doctype in MANAGED:
    method = "query_" + doctype.lower().replace(" ", "_")
    globals()[method] = scoped_query(doctype)
    PERMISSION_QUERIES[doctype] = f"tongjianyun.canteen_ops.common.{method}"
