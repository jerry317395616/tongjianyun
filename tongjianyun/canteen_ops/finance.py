import frappe
from frappe.utils import cint, getdate, now_datetime

from tongjianyun import special_orders
from tongjianyun.canteen_ops.common import (
    CANTEEN, NUTRITION, RECEIVING, STATEMENT, TERM, VOUCHER, ZERO, Handler,
    active_policy, attached_file, company_doc, dates, decimal, linked, lock_company, locked_rows, permission,
    positive, records, require, restricted_supplier, submitted, unique_active,
)

RECEIPT, INVOICE, JOURNAL = "Purchase Receipt", "Purchase Invoice", "Journal Entry"
STATEMENT_ITEM = "Tongjianyun Canteen Reconciliation Item"


def amount(value, decimals=2):
    return decimal(value).quantize(decimal(1).scaleb(-decimals))


def active_receipts(company, canteen, supplier, start, end):
    names = [row.purchase_receipt for row in records(RECEIVING, {
        "company": company, "canteen": canteen, "supplier": supplier, "docstatus": 1,
        "purchase_receipt": ("is", "set"),
    }, ["purchase_receipt"])]
    if not names:
        return []
    return [linked(RECEIPT, row.name) for row in records(RECEIPT, {
        "name": ("in", names), "docstatus": 1, "is_return": 0, "posting_date": ("between", [start, end]),
    }, order_by="posting_date asc, name asc")]


def net_receipt_lines(receipt):
    from erpnext.stock.doctype.purchase_receipt.mapper import get_returned_qty_map

    returned_qty = get_returned_qty_map(receipt.name)
    return {row.name: (row, max(ZERO, decimal(row.qty) - abs(decimal(returned_qty.get(row.name)))))
            for row in receipt.items}


def committed_qty(receipt_item, current=None, lock=False):
    filters = {
        "parenttype": STATEMENT, "receipt_item": receipt_item, "docstatus": 1, "disputed": 0,
        "parent": ("!=", current or ""),
    }
    rows = locked_rows(STATEMENT_ITEM, filters, ["quantity"]) if lock else frappe.get_all(
        STATEMENT_ITEM, filters=filters, fields=["quantity"],
    )
    return sum((decimal(row.quantity) for row in rows), ZERO)


def _statement_policy(doc):
    policy = active_policy(doc.canteen, getdate(doc.to_date))
    doc.policy = policy.name
    return policy


class Statement(Handler):
    def validate(self):
        doc = self.doc
        old = doc.get_doc_before_save()
        if restricted_supplier():
            permission(bool(old and doc.flags.get("supplier_confirming")), "供应商可确认对账结果。")
            return
        dates(doc.from_date, doc.to_date)
        linked("Supplier", doc.supplier)
        require(doc.items, "请通过对账明细预览加入已验收食材。")
        policy = _statement_policy(doc)
        require(policy.settlement_cycle != "按周" or (getdate(doc.to_date) - getdate(doc.from_date)).days <= 6,
                "本食堂按周对账，单次范围不得超过七天。")
        require(policy.settlement_cycle != "按月" or
                (getdate(doc.from_date).year, getdate(doc.from_date).month) ==
                (getdate(doc.to_date).year, getdate(doc.to_date).month), "本食堂按月对账，日期不得跨月。")
        receipts = {}
        totals = ZERO
        keys = set()
        for row in doc.items:
            if row.purchase_receipt not in receipts:
                receipt = submitted(company_doc(doc, RECEIPT, row.purchase_receipt))
                require(not receipt.is_return and receipt.supplier == doc.supplier and receipt.currency == doc.currency,
                        "对账明细须来自本供应商、同币种的合格收货单。")
                require(getdate(doc.from_date) <= getdate(receipt.posting_date) <= getdate(doc.to_date),
                        "采购收货日期超出对账期间。")
                require(bool(frappe.db.exists(RECEIVING, {"canteen": doc.canteen, "docstatus": 1,
                                                        "purchase_receipt": receipt.name})),
                        "采购收货须对应本食堂的合格验收。")
                receipts[receipt.name] = net_receipt_lines(receipt)
            pair = receipts[row.purchase_receipt].get(row.receipt_item)
            require(pair and row.receipt_item not in keys, "采购收货明细无效或重复。")
            keys.add(row.receipt_item)
            origin, net_qty = pair
            qty = positive(row.quantity)
            require(qty <= net_qty, "对账数量超过扣除退货后的合格数量。")
            if row.disputed:
                require(row.reason, "请填写争议原因。")
            row.item_code = origin.item_code
            row.unit_rate = origin.get("net_rate") if origin.get("net_rate") is not None else origin.rate
            row.net_value = float(amount(decimal(row.unit_rate) * qty, doc.precision("net_total")))
            row.purpose = origin.get(special_orders.USE) or "未标识"
            row.nutrition_plan = origin.get(special_orders.PLAN)
            if not row.disputed:
                totals += decimal(row.net_value)
        doc.net_total = float(totals)
        attached_file(doc, doc.supplier_response)
        # Any changes to a confirmed basis reopen supplier confirmation.
        if old and old.supplier_confirmed_at:
            if statement_signature(old) != statement_signature(doc):
                doc.supplier_confirmed_at = None
        else:
            doc.supplier_confirmed_at = None

    def before_submit(self):
        doc = self.doc
        lock_company(doc.company)
        require(not restricted_supplier(), "对账须由校方财务审核。")
        if not doc.supplier_confirmed_at:
            require(doc.supplier_statement_no, "请输入供应商书面确认回执号或请对方在线确认。")
            attached_file(doc, doc.supplier_response, required=True)
        policy = _statement_policy(doc)
        if policy.finance_reviewer:
            permission(frappe.session.user == policy.finance_reviewer, "须由地方流程指定财务审核人提交。")
        if policy.settlement_limit:
            require(decimal(doc.net_total) <= decimal(policy.settlement_limit),
                    "对账金额超过本食堂单批授权限额，请按当地流程复核。")
        require(any(not row.disputed for row in doc.items), "本单无可确认结算的明细。")
        checked = {}
        for row in doc.items:
            if row.disputed:
                continue
            if row.purchase_receipt not in checked:
                receipt = submitted(linked(RECEIPT, row.purchase_receipt, lock=True))
                checked[receipt.name] = net_receipt_lines(receipt)
            _origin, net_qty = checked[row.purchase_receipt][row.receipt_item]
            require(decimal(row.quantity) + committed_qty(row.receipt_item, doc.name, lock=True) <= net_qty,
                    "该验收明细的余额不足，可能已退货或由另一份对账单确认。")

    def before_update_after_submit(self):
        permission(self.doc.flags.get("assigning_invoice"), "只可通过财务办理操作关联发票草稿。")

    def before_cancel(self):
        for invoice in {r.purchase_invoice for r in self.doc.items if r.purchase_invoice}:
            require(frappe.db.get_value(INVOICE, invoice, "docstatus") in (None, 2),
                    "关联采购发票仍有效，请先处理发票或付款。")


def statement_signature(doc):
    return doc.company, doc.canteen, doc.supplier, doc.currency, str(doc.from_date), str(doc.to_date), tuple(
        (row.receipt_item, decimal(row.quantity), cint(row.disputed), decimal(row.net_value)) for row in doc.items
    )


@frappe.whitelist(methods=["GET"])
def preview_statement(canteen, supplier, from_date, to_date, currency):
    site = linked(CANTEEN, canteen)
    permission(not restricted_supplier() and frappe.has_permission(STATEMENT, "create"))
    linked("Supplier", supplier)
    dates(from_date, to_date)
    result = []
    for receipt in active_receipts(site.company, site.name, supplier, getdate(from_date), getdate(to_date)):
        if receipt.currency != currency:
            continue
        for row, qty in net_receipt_lines(receipt).values():
            pending = qty - committed_qty(row.name)
            if pending > 0:
                result.append({"purchase_receipt": receipt.name, "receipt_item": row.name, "item_code": row.item_code,
                               "quantity": float(pending), "unit_rate": row.get("net_rate") or row.rate,
                               "purpose": row.get(special_orders.USE) or "未标识",
                               "nutrition_plan": row.get(special_orders.PLAN)})
    return result


@frappe.whitelist(methods=["POST"])
def confirm_statement(name):
    doc = linked(STATEMENT, name, "write", lock=True)
    permission(restricted_supplier(), "须由本供应商账号确认。")
    require(not doc.docstatus, "须在财务提交前确认。")
    if not doc.supplier_confirmed_at:
        doc.flags.supplier_confirming = True
        doc.supplier_confirmed_at = now_datetime()
        doc.save()
    return doc.name


def _project(doc, plan):
    if not plan:
        return None
    programme = company_doc(doc, NUTRITION, plan)
    terms = records(TERM, {"canteen": doc.canteen, "nutrition_plan": plan, "docstatus": 1,
                           "from_date": ("<=", getdate(programme.end_date)), "to_date": (">=", getdate(programme.start_date))},
                    ["financial_project"])
    projects = {row.financial_project for row in terms if row.financial_project}
    require(len(projects) == 1, "该食堂须在学期膳食项目配置唯一的专项会计项目。")
    project = company_doc(doc, "Project", next(iter(projects)))
    return project.name


@frappe.whitelist(methods=["POST"])
def make_invoice(name, receipt, bill_no, bill_date):
    from erpnext.stock.doctype.purchase_receipt.mapper import make_purchase_invoice

    current = submitted(linked(STATEMENT, name, "write"))
    lock_company(current.company)
    doc = submitted(linked(STATEMENT, name, "write", lock=True))
    permission(not restricted_supplier())
    require(str(bill_no or "").strip() and bill_date and getdate(bill_date) <= getdate(), "请录入真实凭证号和发票日期。")
    source = submitted(company_doc(doc, RECEIPT, receipt))
    items = {row.receipt_item: row for row in doc.items if row.purchase_receipt == source.name and not row.disputed}
    require(items, "请选择本对账单有合格结算数量的收货单。")
    previous = {row.purchase_invoice for row in items.values() if row.purchase_invoice
                and frappe.db.get_value(INVOICE, row.purchase_invoice, "docstatus") in (0, 1)}
    if previous:
        require(len(previous) == 1, "对账发票链接存在冲突。")
        return linked(INVOICE, next(iter(previous))).name
    invoice = make_purchase_invoice(source.name, args={"filtered_children": list(items)})
    buyer = {row.pr_detail: row for row in invoice.items}
    require(set(buyer) == set(items), "部分明细已开票或已退货，请先处理差异。")
    policy = frappe.get_doc("Tongjianyun Canteen Policy", doc.policy)
    require(policy.cost_center, "请先配置食堂的会计成本中心。")
    invoice.bill_no, invoice.bill_date, invoice.update_stock = str(bill_no).strip(), getdate(bill_date), 0
    invoice.set_posting_time = 0
    plans = set()
    for key, row in items.items():
        target = buyer[key]
        require(decimal(target.qty) >= decimal(row.quantity), "本次开票数量超过原生待开票数量。")
        target.qty = row.quantity
        target.cost_center = policy.cost_center
        if row.purpose == "专项":
            require(row.nutrition_plan, "专项收货缺少已审批营养计划。")
            target.project = _project(doc, row.nutrition_plan)
            plans.add(target.project)
        else:
            target.project = None
    require(len(plans) <= 1 and (not plans or all(r.purpose == "专项" for r in items.values())),
            "普通和专项、不同专项须按采购用途分别结算。")
    invoice.project = next(iter(plans), None)
    if plans and policy.liability_account:
        invoice.credit_to = policy.liability_account
    invoice.flags.canteen_statement = doc.name
    invoice.run_method("calculate_taxes_and_totals")
    invoice.insert()
    for row in items.values():
        row.purchase_invoice = invoice.name
    doc.flags.assigning_invoice = True
    doc.save()
    return invoice.name


def check_invoice(invoice, method=None):
    if invoice.is_return or not frappe.db.table_exists(STATEMENT):
        return
    references = {row.purchase_receipt for row in invoice.items if row.get("purchase_receipt")}
    tracked = {receipt for receipt in references if frappe.db.exists(RECEIVING, {
        "purchase_receipt": receipt, "docstatus": 1,
    })}
    from tongjianyun.canteen_ops.purchasing import order_site

    managed = {order for order in {row.purchase_order for row in invoice.items if row.get("purchase_order")}
               if order_site(frappe.get_doc("Purchase Order", order), strict=False)}
    if not tracked and not managed:
        return
    if managed:
        require(all(row.purchase_receipt in tracked for row in invoice.items if row.get("purchase_order") in managed),
                "食堂采购发票须关联合格验收和已核对的收货明细。")
    require(not invoice.update_stock, "通过验收已经完成入库。采购发票须引用验收，不重复更新库存。")
    name = frappe.db.get_value(STATEMENT_ITEM, {"purchase_invoice": invoice.name, "docstatus": 1}, "parent")
    require(name, "请从已确认的供应商对账单生成此采购发票。")
    statement = linked(STATEMENT, name)
    require(invoice.company == statement.company and invoice.supplier == statement.supplier and invoice.currency == statement.currency,
            "发票账套、供应商与币种须与对账一致。")
    current = {row.receipt_item: row for row in statement.items if row.purchase_invoice == invoice.name and not row.disputed}
    require(len(invoice.items) == len(current) and {row.pr_detail for row in invoice.items} == set(current),
            "发票明细须与对账确认结果一致。")
    policy = frappe.get_doc("Tongjianyun Canteen Policy", statement.policy)
    projects = set()
    for row in invoice.items:
        origin = current[row.pr_detail]
        require(row.purchase_receipt == origin.purchase_receipt
                and row.item_code == origin.item_code and decimal(row.qty) == decimal(origin.quantity)
                and amount(row.net_rate, statement.precision("net_total")) ==
                amount(origin.unit_rate, statement.precision("net_total"))
                and row.cost_center == policy.cost_center,
                "发票数量、单价、来源或成本中心须与原对账一致。")
        project = _project(statement, origin.nutrition_plan) if origin.purpose == "专项" else None
        require((row.project or None) == project, "发票会计项目须与已确认专项归属一致。")
        if project:
            projects.add(project)
    if projects:
        require(invoice.project in projects and (not policy.liability_account or invoice.credit_to == policy.liability_account),
                "专项应付科目或会计项目不符合有效配置。")


class Voucher(Handler):
    def validate(self):
        doc = self.doc
        require(doc.posting_date and getdate(doc.posting_date) <= getdate(), "拟入账日期不能晚于今天。")
        positive(doc.amount, "凭证金额必须大于零。")
        policy = active_policy(doc.canteen, getdate(doc.posting_date))
        doc.policy = policy.name
        if doc.operation == "专项补助到账":
            plan = submitted(company_doc(doc, NUTRITION, doc.nutrition_plan))
            doc.financial_project = _project(doc, plan.name)
            doc.debit_account = policy.subsidy_debit_account
            doc.credit_account = policy.subsidy_credit_account
        elif doc.financial_project:
            company_doc(doc, "Project", doc.financial_project)
        require(doc.debit_account and doc.credit_account and doc.debit_account != doc.credit_account and policy.cost_center,
                "请配置不同的借贷明细科目与食堂成本中心。")
        currency = linked("Company", doc.company).default_currency
        for account in (doc.debit_account, doc.credit_account):
            source = company_doc(doc, "Account", account)
            require(not source.disabled and not source.is_group and source.account_currency == currency
                    and source.account_type not in ("Receivable", "Payable"),
                    "凭证须使用有效的本位币账户，往来科目应使用对应原生单据。")
        attached_file(doc, doc.evidence)

    def before_submit(self):
        doc = self.doc
        attached_file(doc, doc.evidence, required=True)
        policy = active_policy(doc.canteen, getdate(doc.posting_date))
        if policy.finance_reviewer:
            permission(frappe.session.user == policy.finance_reviewer, "须由指定财务审核人提交。")
        unique_active(doc, {"canteen": doc.canteen, "external_reference": doc.external_reference,
                            "operation": doc.operation}, "同一业务依据已有有效凭证申请。")

    def before_update_after_submit(self):
        permission(self.doc.flags.get("assigning_journal"), "只可通过凭证生成操作关联会计凭证。")

    def before_cancel(self):
        require(not self.doc.journal_entry or frappe.db.get_value(JOURNAL, self.doc.journal_entry, "docstatus") in (None, 2),
                "请先处理已关联会计凭证。")


@frappe.whitelist(methods=["POST"])
def make_journal_entry(name):
    source = submitted(linked(VOUCHER, name, "write", lock=True))
    if source.journal_entry and frappe.db.get_value(JOURNAL, source.journal_entry, "docstatus") in (0, 1):
        return linked(JOURNAL, source.journal_entry).name
    policy = frappe.get_doc("Tongjianyun Canteen Policy", source.policy)
    value = float(decimal(source.amount))
    journal = frappe.get_doc({"doctype": JOURNAL, "voucher_type": "Journal Entry", "company": source.company,
                              "posting_date": source.posting_date, "user_remark": f"{source.operation} {source.name}",
                              "accounts": []})
    for account, debit, credit in ((source.debit_account, value, 0), (source.credit_account, 0, value)):
        journal.append("accounts", {"account": account, "cost_center": policy.cost_center,
                                    "project": source.financial_project,
                                    "debit_in_account_currency": debit, "credit_in_account_currency": credit})
    journal.insert()
    source.flags.assigning_journal = True
    source.journal_entry = journal.name
    source.save()
    return journal.name


def check_journal(journal, method=None):
    if not frappe.db.table_exists(VOUCHER):
        return
    name = frappe.db.get_value(VOUCHER, {"journal_entry": journal.name, "docstatus": 1}, "name")
    if not name:
        return
    source = submitted(linked(VOUCHER, name))
    policy = frappe.get_doc("Tongjianyun Canteen Policy", source.policy)
    require(journal.company == source.company and getdate(journal.posting_date) == getdate(source.posting_date)
            and len(journal.accounts) == 2, "记账凭证须与已审核的食堂资金申请一致。")
    expected = {source.debit_account: (decimal(source.amount), ZERO),
                source.credit_account: (ZERO, decimal(source.amount))}
    for row in journal.accounts:
        require(expected.get(row.account) == (decimal(row.debit_in_account_currency), decimal(row.credit_in_account_currency))
                and row.cost_center == policy.cost_center and (row.project or None) == (source.financial_project or None),
                "凭证金额、科目、成本中心或专项项目须与已审核依据一致。")


class Subsidy(Handler):
    def validate(self):
        from tongjianyun.canteen_ops.safety import meal_context
        from tongjianyun import special_ingredients

        doc = self.doc
        day, _plan = meal_context(doc)
        submitted(day)
        doc.meal_date = day.meal_date
        week = submitted(linked("Meal Planning Week", day.meal_week))
        plan = submitted(company_doc(doc, NUTRITION, doc.nutrition_plan))
        require(getdate(plan.start_date) <= getdate(doc.meal_date) <= getdate(plan.end_date),
                "该餐日期不在专项适用期间。")
        from ione_core.meal_adjustments import get_effective_meals

        source = [row for row in get_effective_meals(week)
                  if getdate(row.meal_date) == getdate(doc.meal_date) and row.meal_type == doc.meal_type]
        basis = [row for row in special_ingredients.ledger_rows(week, source)
                 if row.get("plan") == plan.name and row.get("eligible_people") is not None]
        require(basis, "该餐没有此专项已经审核的人数归属。")
        actual = next(row.actual_headcount for row in day.meals if row.meal_type == doc.meal_type)
        people = cint(doc.confirmed_people)
        require(0 <= people <= min(actual, max(row["eligible_people"] for row in basis)),
                "核实受益人次超过本餐实供人数或已批准的专项范围。")
        doc.subsidy_total = float(amount(positive(doc.subsidy_rate) * people, doc.precision("subsidy_total")))
        attached_file(doc, doc.evidence)
        unique_active(doc, {"meal_day": doc.meal_day, "meal_type": doc.meal_type, "nutrition_plan": plan.name},
                      "本餐的该专项已有有效的受益人次记录。")

    def before_submit(self):
        require(self.doc.evidence or self.doc.remarks, "请保留受益人次核对依据。")
