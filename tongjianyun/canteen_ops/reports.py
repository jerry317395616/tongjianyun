from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import cint, getdate, now_datetime

from tongjianyun import ingredient_analysis, meal_ledger
from tongjianyun.canteen_ops import inventory, purchasing, safety
from tongjianyun.canteen_ops.common import (
    CANTEEN, COMPANION, CREDENTIAL, DAY, DELIVERY, FINDING, FINANCE_ROLE, POLICY, PRICE,
    RECEIVING, SAMPLE, STATEMENT, SUBSIDY, TERM, VOUCHER, WEEK, ZERO, EDU_ROLE, SAFETY_ROLE, REGULATORS,
    active_policy, decimal, linked, permission, records, regulator_categories, require, roles,
)

SYSTEM = "System Manager"
STOCK_COUNT = "Stock Reconciliation"


def col(key, label, kind="Data", width=135, **options):
    return dict(fieldname=key, label=label, fieldtype=kind, width=width, **options)


COMPANY_COLS = [col("company", "园所", "Link", options="Company"), col("canteen", "食堂", "Link", options=CANTEEN)]
SOURCE_COLS = [col("source_type", "原单类型", hidden=1), col("source", "原单", "Dynamic Link", 175, options="source_type")]


def dates_cols():
    return [col("date", "日期", "Date", 105)]


def currencies(*pairs):
    return [col(field, label, "Currency", 130, options="currency") for field, label in pairs]


def accessible(doctype, filters=None, fields=None):
    return records(doctype, filters, fields) if frappe.has_permission(doctype, "read") else []


def readable(doctype, name):
    if not name or not frappe.has_permission(doctype, "read"):
        return False
    try:
        return bool(frappe.get_doc(doctype, name).has_permission("read"))
    except frappe.DoesNotExistError:
        frappe.clear_messages()
        return False


def reference(doctype, name):
    return {"source_type": doctype, "source": name} if readable(doctype, name) else {}


def date_filter(context):
    return ("between", [context.start, context.end])


class Context:
    def __init__(self, filters):
        self.filters = frappe._dict(filters or {})
        self.today = getdate()
        self.end = getdate(self.filters.get("to_date") or self.today)
        self.start = getdate(self.filters.get("from_date") or (self.end - timedelta(days=29)))
        require(self.start <= self.end <= self.start + timedelta(days=731), "请选择两年内有效的起止日期。")
        constraints = {}
        for attr in ("name", "company", "region", "district"):
            value = self.filters.get("canteen" if attr == "name" else attr)
            if value:
                constraints[attr] = value
        if self.filters.get("canteen"):
            site = linked(CANTEEN, self.filters.canteen)
            require(not self.filters.company or site.company == self.filters.company, "所选食堂不属于当前园所。")
        self.sites = records(CANTEEN, constraints,
                             ["name", "company", "region", "district", "raw_warehouse", "kitchen_warehouse",
                              "quarantine_warehouse", "manager"])
        self.assigned_roles = roles()

    def companies(self):
        return {site.company for site in self.sites}

    def scope(self, site):
        return dict(company=site.company, canteen=site.name)

    def can_audit(self, kind):
        if SYSTEM in self.assigned_roles or not (self.assigned_roles & REGULATORS):
            return True
        return kind in regulator_categories(self.assigned_roles)


def quotation_comparison(ctx):
    name = ctx.filters.get("quotation_request")
    cols = dates_cols() + [col("item_code", "食材", "Link", options="Item"), col("supplier", "供应商", "Link", options="Supplier"),
                            col("quotation", "供应商报价单", "Link", options=purchasing.QUOTE),
                            col("quantity", "报价数量", "Float"), col("uom", "报价单位"),
                            col("currency", "报价币种"), col("rate", "原报价", "Currency"),
                            col("base_stock_rate", "本位币每库存单位净价", "Float", 178, precision=6),
                            col("rank", "同食材有效报价排名", "Int", 167), col("stage", "报价状态"),
                            col("fact", "价格异常依据", width=225)] + SOURCE_COLS
    if not name:
        alerts = [dict(row, stage="待采购复核", base_stock_rate=row["value"])
                  for site in ctx.sites for row in price_alerts(site, ctx)]
        return cols, alerts, "未指定询价单时，显示尚未完成价格复核的采购订单。选择询价单可比较有效报价。"
    doc = linked(purchasing.RFQ, name)
    permission(doc.company in ctx.companies())
    if ctx.filters.get("canteen"):
        requests = set(line.material_request for line in doc.items if line.material_request)
        matches = accessible(purchasing.DISPATCH, {"canteen": ctx.filters.canteen, "docstatus": 1,
                                                    "material_request": ("in", list(requests))}) if requests else []
        require(matches, "所选询价单不属于该食堂的采购申请。")
    rows = purchasing.quotation_rows(doc, ctx.filters.get("item_code"))
    ranks = defaultdict(int)
    for row in sorted(rows, key=lambda r: (r.item_code, r.base_stock_rate, r.supplier)):
        if row.active:
            ranks[row.item_code] += 1
            row.rank = ranks[row.item_code]
        row.stage = "有效" if row.active else "已过期"
    if cint(ctx.filters.only_anomalies):
        rows = [row for row in rows if not row.active]
    return cols, rows, "净价统一按库存单位和本位币展示。实际选商仍应核对规格、交期、税费及运费。"


def price_alerts(site, ctx):
    if not frappe.has_permission(purchasing.ORDER, "read"):
        return
    dispatched = accessible(purchasing.DISPATCH, {**ctx.scope(site), "docstatus": 1}, ["material_request"])
    parents = purchasing.native_parents("Purchase Order Item", "material_request",
                                        {row.material_request for row in dispatched}, purchasing.ORDER)
    if not parents:
        return
    for row in records(purchasing.ORDER, {"name": ("in", parents), "company": site.company, "docstatus": 0}):
        order = linked(purchasing.ORDER, row.name)
        if purchasing.order_site(order, strict=False) != site.name:
            continue
        policy = active_policy(site.name, order.transaction_date, required=False)
        if not policy or frappe.db.exists(PRICE, {"purchase_order": order.name, "docstatus": 1}):
            continue
        for finding in purchasing.price_basis(order, policy):
            if ctx.filters.item_code and finding["item_code"] != ctx.filters.item_code:
                continue
            if finding["reasons"]:
                yield dict(date=order.transaction_date, item_code=finding["item_code"], supplier=order.supplier,
                           fact="、".join(finding["reasons"]), value=float(decimal(finding["unit_rate"])),
                           source_type=purchasing.ORDER, source=order.name, order_item=finding["order_item"])


def ingredient_purchases(ctx):
    cols, output = COMPANY_COLS + ingredient_analysis.columns(ingredient_analysis.PURCHASE), []
    for site in ctx.sites:
        source = ingredient_analysis.Sources(site.company, ctx.start, ctx.end, ctx.filters.item_code)
        if not source.can_read_purchases:
            continue
        for row in source.purchases(ctx.filters.supplier):
            week = source.document(WEEK, row["meal_week"])
            if not week or week.raw_material_warehouse != site.raw_warehouse:
                continue
            if week.get("kitchen_warehouse") and week.kitchen_warehouse != site.kitchen_warehouse:
                continue
            output.append(dict(row, **ctx.scope(site)))
    return cols, output, "按原采购单据日期统计。采购退货单独列示，数量按库存单位。"


def inventory_batches(ctx):
    cols = COMPANY_COLS + [col("warehouse", "仓库", "Link", options="Warehouse"), col("item_code", "食材", "Link", options="Item"),
        col("lot_number", "供应商批号"), col("lot_key", "追溯号"), col("expires_on", "到期日", "Date"),
        col("posted_qty", "账存或已追溯数量", "Float", 153), col("usable_qty", "合格批次数量", "Float"),
        col("reserved_qty", "原生库存预留", "Float"), col("stage", "状态", width=170)] + SOURCE_COLS
    rows = [row for site in ctx.sites for row in inventory.inventory_rows(site, ctx.filters, ctx.today)]
    if cint(ctx.filters.only_anomalies):
        rows = [row for row in rows if row["stage"] != "正常"]
    return cols, rows, "原生账存与可追溯批次分别核对。预留数量取 ERPNext 库存记录。"


def stock_count(ctx):
    cols = COMPANY_COLS + dates_cols() + [col("warehouse", "仓库", "Link", options="Warehouse"),
        col("item_code", "食材", "Link", options="Item"), col("expected", "盘点前账存", "Float"),
        col("actual", "盘点数量", "Float"), col("difference", "盘点差异", "Float"), col("stage", "单据状态")] + SOURCE_COLS
    rows = []
    for site in ctx.sites:
        warehouses = {site.raw_warehouse, site.kitchen_warehouse, site.quarantine_warehouse}
        filters = {"company": site.company, "posting_date": date_filter(ctx), "docstatus": ("<", 2)}
        if ctx.filters.stock_reconciliation:
            filters["name"] = ctx.filters.stock_reconciliation
        for row in accessible(STOCK_COUNT, filters):
            doc = linked(STOCK_COUNT, row.name)
            for line in doc.items:
                if line.warehouse and line.warehouse in warehouses and (
                    not ctx.filters.warehouse or ctx.filters.warehouse == line.warehouse
                ):
                    before, after = line.get("current_qty"), line.get("qty")
                    rows.append(dict(ctx.scope(site), date=doc.posting_date, item_code=line.item_code, warehouse=line.warehouse,
                                     expected=before, actual=after, difference=float(decimal(after) - decimal(before)),
                                     stage="已过账" if doc.docstatus == 1 else "草稿",
                                     source_type=STOCK_COUNT, source=doc.name))
    return cols, rows, "报表可导出和打印。盘点审批与库存调整通过原生盘点单办理。"


def credential_rows(ctx, site):
    for credential in accessible(CREDENTIAL, {**ctx.scope(site), "docstatus": 1},
                                 ["name", "subject_kind", "credential_type", "from_date", "to_date", "employee", "supplier"]):
        policy = active_policy(site.name, ctx.today, required=False)
        threshold = ctx.today + timedelta(days=cint(policy.credential_warning_days) if policy else 30)
        expiration = getdate(credential.to_date)
        state = "已过期" if expiration < ctx.today else "临期" if expiration <= threshold else "有效"
        yield dict(ctx.scope(site), **credential, date=credential.to_date, stage=state,
                   days_left=(expiration - ctx.today).days, source_type=CREDENTIAL, source=credential.name)


def credential_expiry(ctx):
    cols = COMPANY_COLS + [col("subject_kind", "证照归属"), col("credential_type", "证照类别"),
        col("employee", "员工"), col("supplier", "供应商"), col("from_date", "起始日期", "Date"),
        col("date", "有效期至", "Date"), col("days_left", "剩余天数", "Int"), col("stage", "有效状态")] + SOURCE_COLS
    rows = [row for site in ctx.sites for row in credential_rows(ctx, site)
            if not cint(ctx.filters.only_anomalies) or row["stage"] != "有效"]
    return cols, rows, "按当前日期核对所有已提交证照，可从本报表打开证照原单。"


def kitchen_days(ctx, site):
    filters = {"company": site.company, "source_warehouse": site.raw_warehouse,
               "kitchen_warehouse": site.kitchen_warehouse, "meal_date": date_filter(ctx), "docstatus": ("<", 2)}
    narrow_regulatory_view = bool(ctx.assigned_roles & {EDU_ROLE, SAFETY_ROLE})
    native = frappe.get_all(DAY, filters=filters, fields=["name"]) if narrow_regulatory_view else accessible(DAY, filters)
    for row in native:
        if narrow_regulatory_view:
            day = frappe.get_doc(DAY, row.name)
            week = frappe.get_doc(WEEK, day.meal_week)
        else:
            day = linked(DAY, row.name)
            week = linked(WEEK, day.meal_week) if readable(WEEK, day.meal_week) else None
        if week and week.company == site.company and week.docstatus == 1:
            proof = meal_ledger._day_proof(day, meal_ledger._week_proof(week)) if day.docstatus == 1 else None
            yield day, week, proof


def stock_cost(site, proof, action, can_read_cost):
    if not can_read_cost:
        return None
    names = {row["name"] for row in proof["stock_entries"] if row["action"] == action}
    if not names:
        return 0
    if any(not readable("Stock Entry", name) for name in names):
        return None
    rows = records("Stock Ledger Entry", {"company": site.company, "voucher_type": "Stock Entry",
                                          "voucher_no": ("in", list(names)), "warehouse": site.kitchen_warehouse,
                                          "is_cancelled": 0}, ["stock_value_difference", "voucher_no"])
    if {row.voucher_no for row in rows} != names:
        return None
    return float(-sum((decimal(row.stock_value_difference) for row in rows), ZERO))


def operations_report(ctx):
    cols = COMPANY_COLS + dates_cols() + [col("planned", "计划人次", "Int"), col("actual", "实际人次", "Int"),
        col("difference", "人次差异", "Int"), col("currency", "本位币", width=82),
        *currencies(("used_value", "食材耗用成本"), ("loss_value", "食材损耗金额"), ("unit_cost", "每餐食材成本")),
        col("stage", "日结状态")] + SOURCE_COLS
    rows = []
    can_cost = frappe.has_permission("Stock Ledger Entry", "read")
    for site in ctx.sites:
        currency = frappe.db.get_value("Company", site.company, "default_currency")
        for day, _week, proof in kitchen_days(ctx, site):
            line = dict(ctx.scope(site), date=day.meal_date, currency=currency, **reference(DAY, day.name))
            if not proof:
                rows.append(dict(line, stage="日结依据待核对" if day.docstatus else "待日结"))
                continue
            planned = sum(row["planned_headcount"] for row in proof["actual_meals"])
            actual = sum(row["actual_headcount"] for row in proof["actual_meals"])
            used = stock_cost(site, proof, "耗用", can_cost)
            loss = stock_cost(site, proof, "损耗", can_cost)
            rows.append(dict(line, planned=planned, actual=actual, difference=actual - planned, used_value=used,
                             loss_value=loss, unit_cost=used / actual if used is not None and actual else None, stage="已日结"))
    return cols, rows, "食材成本取已核对的库存账变动。同一天有多餐时显示日均单餐成本。"


def supplier_accounts(ctx):
    cols = COMPANY_COLS + [col("supplier", "供应商", "Link", options="Supplier"), col("date", "对账期末", "Date"),
        col("item_code", "食材", "Link", options="Item"), col("currency", "币种", width=80),
        col("quantity", "确认数量", "Float"), *currencies(("confirmed", "税前对账金额"), ("due", "发票含税金额"),
        ("paid", "累计已结算"), ("outstanding", "应付未结")), col("stage", "结算进度", width=150),
        col("reconciliation", "对账单", "Link", 145, options=STATEMENT)] + SOURCE_COLS
    rows, counted = [], set()
    for site in ctx.sites:
        filters = {**ctx.scope(site), "from_date": ("<=", ctx.end), "to_date": (">=", ctx.start), "docstatus": ("<", 2)}
        if ctx.filters.supplier:
            filters["supplier"] = ctx.filters.supplier
        for entry in accessible(STATEMENT, filters):
            doc = linked(STATEMENT, entry.name)
            for row in doc.items:
                line = dict(ctx.scope(site), supplier=doc.supplier, date=doc.to_date, item_code=row.item_code,
                            currency=doc.currency, confirmed=row.net_value, quantity=row.quantity, reconciliation=doc.name)
                if row.disputed:
                    rows.append(dict(line, stage="争议待处理", **reference(purchasing.RECEIPT, row.purchase_receipt)))
                    continue
                invoice = None
                if readable("Purchase Invoice", row.purchase_invoice):
                    invoice = linked("Purchase Invoice", row.purchase_invoice)
                if not invoice or invoice.docstatus != 1:
                    status = "待开票" if doc.docstatus else "待确认"
                    if invoice and invoice.docstatus == 0:
                        status = "发票待审核"
                    rows.append(dict(line, stage=status, **reference(purchasing.RECEIPT, row.purchase_receipt)))
                    continue
                outstanding = decimal(invoice.outstanding_amount)
                state = "已结清" if outstanding <= ZERO else "部分结算" if outstanding < decimal(invoice.grand_total) else "待付"
                if invoice.name not in counted:
                    counted.add(invoice.name)
                    line.update(due=invoice.grand_total, outstanding=float(outstanding),
                                paid=float(decimal(invoice.grand_total) - outstanding))
                rows.append(dict(line, stage=state, source_type="Purchase Invoice", source=invoice.name))
    return cols, rows, "同一发票的含税和未结金额只展示一次。累计已结算包含已分配的付款、抵扣及贷项。"


def financial_centers(site, ctx):
    rows = accessible(POLICY, {**ctx.scope(site), "docstatus": 1, "from_date": ("<=", ctx.end),
                              "to_date": (">=", ctx.start)}, ["name", "cost_center", "from_date", "to_date"])
    if not rows and FINANCE_ROLE in ctx.assigned_roles:
        rows = frappe.get_all(POLICY, filters={**ctx.scope(site), "docstatus": 1, "from_date": ("<=", ctx.end),
                                              "to_date": (">=", ctx.start)},
                              fields=["name", "cost_center", "from_date", "to_date"])
    return {row.cost_center for row in rows if row.cost_center}


def accounting_rows(ctx, site):
    centers = financial_centers(site, ctx)
    if not centers:
        return []
    criteria = {"company": site.company, "cost_center": ("in", list(centers)),
                "posting_date": date_filter(ctx), "is_cancelled": 0}
    fields = ["posting_date", "account", "project", "cost_center", "voucher_type", "voucher_no", "debit", "credit"]
    if frappe.has_permission("GL Entry", "read"):
        entries = records("GL Entry", criteria, fields)
    elif FINANCE_ROLE in ctx.assigned_roles:
        # Reporting access for an explicitly scoped regulator is limited to approved canteen cost centres.
        entries = frappe.get_all("GL Entry", filters=criteria, fields=fields)
    else:
        return []
    accounts = {row.account for row in entries}
    roots = {row.name: (row.root_type, row.account_type) for row in (frappe.get_all(
        "Account", filters={"company": site.company, "name": ("in", list(accounts))},
        fields=["name", "root_type", "account_type"],
    ) if accounts else [])}
    currency = frappe.db.get_value("Company", site.company, "default_currency")
    rows = []
    for entry in entries:
        root, kind = roots.get(entry.account, (None, None))
        rows.append(dict(ctx.scope(site), date=entry.posting_date, currency=currency, account=entry.account,
                         root_type=root, account_type=kind, project=entry.project, debit=entry.debit, credit=entry.credit,
                         **reference(entry.voucher_type, entry.voucher_no)))
    return rows


def accounting_records(ctx):
    cols = COMPANY_COLS + dates_cols() + [col("account", "会计科目", "Link", width=165, options="Account"),
        col("root_type", "会计类别"), col("project", "会计项目", "Link", options="Project"), col("currency", "本位币", width=80),
        *currencies(("debit", "借方"), ("credit", "贷方"))] + SOURCE_COLS
    rows = [row for site in ctx.sites for row in accounting_rows(ctx, site)]
    return cols, rows, "读取有效总账分录，依据已配置的食堂成本中心。"


def income_expense(ctx):
    cols = COMPANY_COLS + [col("currency", "本位币", width=80), *currencies(("income", "本期确认收入"),
        ("expense", "本期确认费用"), ("surplus", "收入费用差额"), ("cash_in", "食堂账面收到现金银行"),
        ("cash_out", "食堂账面付出现金银行"), ("cash_change", "现金银行净变动"))]
    output = []
    for site in ctx.sites:
        rows = accounting_rows(ctx, site)
        if not rows:
            continue
        income = sum((decimal(row["credit"]) - decimal(row["debit"]) for row in rows if row["root_type"] == "Income"), ZERO)
        expense = sum((decimal(row["debit"]) - decimal(row["credit"]) for row in rows if row["root_type"] == "Expense"), ZERO)
        cash = [row for row in rows if row["account_type"] in ("Cash", "Bank")]
        value_in = sum((decimal(row["debit"]) for row in cash), ZERO)
        value_out = sum((decimal(row["credit"]) for row in cash), ZERO)
        output.append(dict(ctx.scope(site), currency=rows[0]["currency"], income=float(income), expense=float(expense),
                           surplus=float(income - expense), cash_in=float(value_in) if cash else None,
                           cash_out=float(value_out) if cash else None, cash_change=float(value_in - value_out) if cash else None))
    return cols, output, "仅统计已归属食堂成本中心的总账。未能归属的现金银行分录不计入已确认食堂收付。"


def subsidy_activity(ctx, site):
    scope = ctx.scope(site)
    currency = frappe.db.get_value("Company", site.company, "default_currency")
    for row in accessible(SUBSIDY, {**scope, "docstatus": 1, "meal_date": date_filter(ctx)},
                          ["name", "meal_date", "meal_type", "nutrition_plan", "confirmed_people", "subsidy_total"]):
        yield dict(scope, currency=currency, date=row.meal_date, meal_type=row.meal_type, nutrition_plan=row.nutrition_plan,
                   people=row.confirmed_people, entitlement=row.subsidy_total, stage="已核实受益",
                   source_type=SUBSIDY, source=row.name)
    vouchers = {row.journal_entry: row for row in accessible(
        VOUCHER, {**scope, "operation": "专项补助到账", "docstatus": 1, "posting_date": date_filter(ctx)},
        ["name", "journal_entry", "posting_date", "nutrition_plan", "amount"],
    ) if row.journal_entry}
    for journal, row in vouchers.items():
        if frappe.db.get_value("Journal Entry", journal, "docstatus") == 1:
            yield dict(scope, currency=currency, date=row.posting_date, nutrition_plan=row.nutrition_plan, funding=row.amount,
                       stage="已到账", source_type=VOUCHER, source=row.name)
    terms = accessible(TERM, {**scope, "docstatus": 1},
                       ["name", "financial_project", "nutrition_plan", "approved_budget", "from_date", "to_date"])
    projects = {row.financial_project: row.nutrition_plan for row in terms if row.financial_project and row.nutrition_plan}
    for term in terms:
        if term.nutrition_plan and term.approved_budget and getdate(term.from_date) <= ctx.end and getdate(term.to_date) >= ctx.start:
            yield dict(scope, currency=currency, date=term.from_date, nutrition_plan=term.nutrition_plan,
                       budget=term.approved_budget, stage="适用学期批准预算", source_type=TERM, source=term.name)

    invoices = {}
    for statement in accessible(STATEMENT, {**scope, "docstatus": 1}):
        for item in linked(STATEMENT, statement.name).items:
            if item.nutrition_plan and item.purchase_invoice and not item.disputed:
                invoices[item.purchase_invoice] = item.nutrition_plan
    for name, plan in invoices.items():
        if not readable("Purchase Invoice", name) and FINANCE_ROLE not in ctx.assigned_roles:
            continue
        invoice = frappe.db.get_value("Purchase Invoice", {"name": name, "company": site.company,
                                                            "docstatus": 1, "is_return": 0},
                                      ["posting_date", "base_grand_total", "outstanding_amount", "conversion_rate"], as_dict=True)
        if invoice and ctx.start <= getdate(invoice.posting_date) <= ctx.end:
            outstanding = decimal(invoice.outstanding_amount) * decimal(invoice.conversion_rate)
            yield dict(scope, currency=currency, date=invoice.posting_date, nutrition_plan=plan,
                       billed=invoice.base_grand_total, outstanding=float(outstanding),
                       settled=float(decimal(invoice.base_grand_total) - outstanding), stage="专项采购发票",
                       **reference("Purchase Invoice", name))

    for entry in accounting_rows(ctx, site):
        if entry["project"] not in projects or entry["root_type"] != "Expense":
            continue
        yield dict(scope, currency=currency, date=entry["date"], nutrition_plan=projects[entry["project"]],
                   expenditure=float(decimal(entry["debit"]) - decimal(entry["credit"])), stage="已入账费用",
                   source_type=entry.get("source_type"), source=entry.get("source"))


def nutrition_subsidy(ctx):
    cols = COMPANY_COLS + dates_cols() + [col("meal_type", "餐次"), col("nutrition_plan", "营养改善计划"),
        col("stage", "数据口径"), col("people", "核实受益人次", "Int"), col("currency", "本位币", width=80),
        *currencies(("budget", "适用学期预算"), ("entitlement", "核实应享金额"), ("funding", "实际到账金额"),
                    ("billed", "期间专项已开票"), ("settled", "对应发票累计已结算"), ("outstanding", "对应发票当前未结"),
                    ("expenditure", "已入账专项费用"))] + SOURCE_COLS
    rows = [row for site in ctx.sites for row in subsidy_activity(ctx, site)]
    return cols, rows, "预算按学期、到款与开票按入账日期、结算按发票当前状态统计。专项费用读取有效总账。"


def fund_hierarchy(ctx):
    cols = [col("level", "级别"), col("region", "市级行政区"), col("district", "区县"), *COMPANY_COLS,
        col("currency", "本位币", width=80), col("people", "核实受益人次", "Int"),
        *currencies(("budget", "适用学期预算"), ("entitlement", "核实应享金额"), ("funding", "期间到账"),
                    ("billed", "期间已开票"), ("settled", "对应发票累计结算"), ("outstanding", "对应发票当前未结"),
                    ("expenditure", "期间账面费用"), ("period_gap", "到账与费用差额"))]
    groups = defaultdict(lambda: defaultdict(lambda: ZERO))
    for site in ctx.sites:
        for row in subsidy_activity(ctx, site):
            keys = (("市级", site.region, "", "", ""), ("区县", site.region, site.district, "", ""),
                    ("学校", site.region, site.district, site.company, ""),
                    ("食堂", site.region, site.district, site.company, site.name))
            for key in keys:
                total = groups[(*key, row["currency"])]
                for field in ("people", "budget", "entitlement", "funding", "billed", "settled", "outstanding", "expenditure"):
                    total[field] += decimal(row.get(field))
    output = []
    for (level, region, district, company, canteen, currency), values in groups.items():
        output.append(dict(level=level, region=region, district=district, company=company, canteen=canteen,
                           currency=currency, **{key: float(number) for key, number in values.items()},
                           period_gap=float(values["funding"] - values["expenditure"])))
    return cols, output, "各层级分别汇总本辖区食堂的数据。期间差额不等于结转余额，跨币种分别列示。"


def quality_rows(ctx, site):
    base = ctx.scope(site)

    def row(category, rule, on, doctype, name, facts, extra="", status="需处理"):
        return dict(base, category=category, rule=rule, date=on, source_type=doctype, source=name,
                    fact=facts, stage=status, finding_key=safety.finding_key(rule, name, extra))

    policy = active_policy(site.name, ctx.today, required=False)
    if not policy:
        yield row("采购与验收", "缺少生效规则", ctx.today, CANTEEN, site.name, "请维护食堂有效期内规则。")
    if ctx.can_audit("人员与证照"):
        for entry in credential_rows(ctx, site):
            if entry["stage"] != "有效":
                yield row("人员与证照", entry["stage"], entry["date"], CREDENTIAL, entry["name"], entry["credential_type"])
    if ctx.can_audit("采购与验收"):
        for entry in accessible(DELIVERY, {**base, "docstatus": 1, "expected_on": date_filter(ctx)}):
            doc = linked(DELIVERY, entry.name)
            applicable = active_policy(site.name, getdate(doc.expected_on), required=False)
            if applicable:
                for lot in doc.items:
                    problems = purchasing.evidence_problems(doc, lot, applicable, getdate(doc.expected_on))
                    if problems:
                        yield row("采购与验收", "配送票证待核对", doc.expected_on, DELIVERY, doc.name,
                                  f"{lot.item_code} / {lot.lot_number} · {'、'.join(problems)}", lot.name)
            if getdate(doc.expected_on) < ctx.today and not accessible(RECEIVING, {"delivery": doc.name, "docstatus": 1}):
                yield row("采购与验收", "配送待完成验收", doc.expected_on, DELIVERY, doc.name, doc.progress)
        for entry in accessible(PRICE, {**base, "docstatus": 0}):
            yield row("采购与验收", "异常价格待复核", ctx.today, PRICE, entry.name, "采购价格核对单尚待主管完成。")
        for entry in price_alerts(site, ctx):
            yield row("采购与验收", "采购价格异常", entry["date"], entry["source_type"], entry["source"],
                      f"{entry['item_code']} · {entry['fact']}", entry["order_item"])
    if ctx.can_audit("库存"):
        for entry in inventory.inventory_rows(site, ctx.filters, ctx.today):
            if entry.get("stage") != "正常":
                anchor = entry.get("source") or site.name
                yield row("库存", entry["stage"], ctx.today, entry.get("source_type") or CANTEEN, anchor,
                          f"{entry['item_code']} / {entry.get('lot_number', entry.get('warehouse'))}",
                          f"{entry['warehouse']}-{entry['item_code']}-{entry.get('lot_key', '')}")
    if ctx.can_audit("供餐") or ctx.can_audit("食品安全"):
        for day, week, proof in kitchen_days(ctx, site):
            date = getdate(day.meal_date)
            if date > ctx.today:
                continue
            if not proof and date < ctx.today and ctx.can_audit("供餐"):
                yield row("供餐", "日结待核对", date, DAY, day.name, "实际供餐、库存或日结依据尚待核对。")
            if not ctx.can_audit("食品安全"):
                continue
            policy = active_policy(site.name, date, required=False)
            if not policy:
                continue
            for slot in day.meals:
                if not slot.actual_confirmed or not slot.actual_headcount:
                    continue
                if policy.companion_required and not accessible(COMPANION, {"meal_day": day.name, "meal_type": slot.meal_type, "docstatus": 1}):
                    yield row("食品安全", "缺陪餐记录", date, DAY, day.name, slot.meal_type, slot.meal_type)
                if policy.sample_required and frappe.has_permission(SAMPLE, "read"):
                    dishes = safety.sample_scope_dishes(day, week, slot.meal_type)
                    found = {entry.dish for entry in accessible(SAMPLE, {"meal_day": day.name, "meal_type": slot.meal_type,
                                                                         "docstatus": 1}, ["dish"])}
                    for dish in dishes - found:
                        yield row("食品安全", "缺成品留样", date, DAY, day.name, f"{slot.meal_type} / {dish}",
                                  f"{slot.meal_type}-{dish}")
        if ctx.can_audit("食品安全"):
            for entry in accessible(COMPANION, {**base, "meal_date": date_filter(ctx), "docstatus": 1,
                                                 "evaluation": ("!=", "满意")}, ["name", "meal_date", "evaluation", "meal_type"]):
                yield row("食品安全", "陪餐反馈待整改", entry.meal_date, COMPANION, entry.name,
                          f"{entry.meal_type} · {entry.evaluation}")
            for entry in accessible(SAMPLE, {**base, "docstatus": 1, "dispose_after": ("<=", now_datetime()),
                                              "disposed_at": ("is", "not set")}, ["name", "meal_date", "dish"]):
                yield row("食品安全", "留样待处置", entry.meal_date, SAMPLE, entry.name, entry.dish)
    if ctx.can_audit("专项与财务"):
        for entry in accessible(VOUCHER, {**base, "posting_date": date_filter(ctx), "docstatus": 1},
                                ["name", "posting_date", "journal_entry"]):
            if not entry.journal_entry or frappe.db.get_value("Journal Entry", entry.journal_entry, "docstatus") != 1:
                yield row("专项与财务", "审核资金待记账", entry.posting_date, VOUCHER, entry.name, "待提交原生会计凭证。")
        for entry in accessible(STATEMENT, {**base, "docstatus": ("<", 2), "to_date": date_filter(ctx)}):
            doc = linked(STATEMENT, entry.name)
            for line in doc.items:
                if line.disputed or line.purpose == "未标识":
                    yield row("专项与财务", "对账争议" if line.disputed else "资金用途待核对", doc.to_date,
                              STATEMENT, doc.name, line.reason or line.item_code, line.name)


def data_quality(ctx):
    if ctx.filters.get("view") == "完整性统计":
        return completeness(ctx)
    cols = COMPANY_COLS + dates_cols() + [col("category", "事项类型"), col("rule", "发现问题", width=155),
        col("fact", "依据", width=240), col("stage", "整改进度"), col("finding_key", "整改依据", hidden=1),
        col("finding", "整改记录", "Link", 155, options=FINDING)] + SOURCE_COLS
    output = []
    for site in ctx.sites:
        problems = [row for row in quality_rows(ctx, site) if ctx.can_audit(row["category"])]
        tracked = {row.finding_key: row for row in accessible(
            FINDING, ctx.scope(site), ["name", "finding_key", "progress"],
        )}
        for row in problems:
            open_finding = tracked.get(row["finding_key"])
            if open_finding:
                row.update(finding=open_finding.name, stage=open_finding.progress)
            if row.get("source") and not readable(row["source_type"], row["source"]):
                row["source"] = None
            if not cint(ctx.filters.only_anomalies) or row["stage"] != "已销项":
                output.append(row)
    return cols, output, "问题来自可见范围内的业务事实。整改须在独立记录复核，已销项事项可在整改列表追溯。"


def completeness(ctx):
    cols = COMPANY_COLS + [col("rule", "质量指标", width=190), col("expected", "应记录数", "Int"),
                           col("actual", "满足要求数", "Int"), col("rate", "完成率（%）", "Float", precision=2)]
    output = []
    for site in ctx.sites:
        base = ctx.scope(site)
        counters = defaultdict(lambda: [0, 0])

        def count(metric, completed):
            counters[metric][0] += 1
            counters[metric][1] += int(bool(completed))

        if ctx.can_audit("采购与验收") and all(frappe.has_permission(dt, "read") for dt in (DELIVERY, RECEIVING)):
            for entry in records(DELIVERY, {**base, "docstatus": 1, "expected_on": date_filter(ctx)}):
                delivery = linked(DELIVERY, entry.name)
                date = getdate(delivery.expected_on)
                if date > ctx.today:
                    continue
                accepted = records(RECEIVING, {"delivery": delivery.name, "docstatus": 1})
                count("到期配送已验收", accepted)
                policy = active_policy(site.name, date, required=False)
                if policy:
                    for lot in delivery.items:
                        if purchasing.evidence_rules(policy, lot.item_code):
                            count("随货批次票证齐全", not purchasing.evidence_problems(delivery, lot, policy, date))

        if ctx.can_audit("供餐") or ctx.can_audit("食品安全"):
            for day, _week, proof in kitchen_days(ctx, site):
                date = getdate(day.meal_date)
                if date >= ctx.today:
                    continue
                if ctx.can_audit("供餐"):
                    count("已建立执行日的日结完成", proof)
                if ctx.can_audit("食品安全") and frappe.has_permission(COMPANION, "read"):
                    policy = active_policy(site.name, date, required=False)
                    if not policy or not policy.companion_required:
                        continue
                    for meal in day.meals:
                        if meal.actual_confirmed and meal.actual_headcount > 0:
                            count("已实供餐次有陪餐记录",
                                  records(COMPANION, {"meal_day": day.name, "meal_type": meal.meal_type, "docstatus": 1}))
        output.extend(dict(base, rule=label, expected=expected, actual=actual, rate=100 * actual / expected)
                      for label, (expected, actual) in counters.items())
    return cols, output, "分母来自已到期的配送或已建立的执行日与实际供餐。无适用数据的指标留空。"


@frappe.whitelist(methods=["POST"])
def create_finding(canteen, key, due_date, assigned_to, from_date=None, to_date=None):
    from tongjianyun.canteen_ops.common import lock_company

    context = Context({"canteen": canteen, "from_date": from_date, "to_date": to_date})
    permission(frappe.has_permission(FINDING, "create") and len(context.sites) == 1)
    site = context.sites[0]
    lock_company(site.company)
    previous = records(FINDING, {**context.scope(site), "finding_key": key})
    if previous:
        return previous[0].name
    row = next((line for line in quality_rows(context, site)
                if line["finding_key"] == key and context.can_audit(line["category"])), None)
    require(row, "来源问题无法核实或已经不再命中规则。")
    require(due_date and getdate(due_date) >= getdate(), "整改期限须为今天或之后。")
    doc = frappe.get_doc({"doctype": FINDING, **context.scope(site), "finding_title": row["rule"], "category": row["category"],
                          "description": row["fact"], "source_type": row["source_type"], "source": row["source"],
                          "finding_key": key, "due_date": due_date, "assigned_to": assigned_to})
    doc.flags.generated_finding = True
    doc.insert()
    return doc.name


REPORT_FUNCTIONS = {
    "Canteen Data Quality": data_quality,
    "Canteen Supplier Accounts": supplier_accounts,
    "Canteen Accounting Records": accounting_records,
    "Canteen Operations Report": operations_report,
    "Canteen Income Expense": income_expense,
    "Canteen Ingredient Purchases": ingredient_purchases,
    "Canteen Nutrition Subsidy": nutrition_subsidy,
    "Canteen Fund Hierarchy": fund_hierarchy,
    "Canteen Quotation Comparison": quotation_comparison,
    "Canteen Inventory Batches": inventory_batches,
    "Canteen Stock Count": stock_count,
    "Canteen Credential Expiry": credential_expiry,
}


def run(report_name, filters=None):
    permission(frappe.session.user != "Guest" and report_name in REPORT_FUNCTIONS)
    frappe.has_permission(CANTEEN, "read", throw=True)
    return REPORT_FUNCTIONS[report_name](Context(filters))
