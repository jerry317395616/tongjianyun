from datetime import timedelta
from hashlib import sha256

import frappe
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime

from tongjianyun.canteen_ops.common import (
    CANTEEN, COMPANION, CREDENTIAL, DAY, DELIVERY, FINDING, NUTRITION, POLICY, PRICE,
    RECEIVING, SAMPLE, STATEMENT, TASK, TERM, VOUCHER, WEEK, REGULATORS, Handler,
    active_policy, attached_file, canteen_for_week, company_doc, dates, linked, lock_company,
    permission, positive, records, require, roles, submitted, unique_active,
)

TASKS = (("食谱审核", 0), ("准备采购", 0), ("逐餐供餐与日结", 4), ("周核销", 6))
FINDING_SOURCES = {CANTEEN, COMPANION, CREDENTIAL, DAY, DELIVERY, POLICY, PRICE, RECEIVING, SAMPLE,
                   STATEMENT, VOUCHER, WEEK, "Purchase Order", "Batch", "Purchase Receipt"}


class Canteen(Handler):
    def validate(self):
        doc = self.doc
        names = [doc.raw_warehouse, doc.kitchen_warehouse]
        if doc.quarantine_warehouse:
            names.append(doc.quarantine_warehouse)
        require(len(set(names)) == len(names), "原料仓、厨房仓及隔离仓必须分别设置。")
        for name in names:
            warehouse = company_doc(doc, "Warehouse", name)
            require(not warehouse.is_group and not warehouse.disabled, "请使用有效的明细仓。")
        lock_company(doc.company)
        filters = {"company": doc.company, "name": ("!=", doc.name or ""), "disabled": 0}
        if not doc.disabled:
            require(not frappe.db.exists(CANTEEN, {**filters, "kitchen_warehouse": doc.kitchen_warehouse}),
                    "一个厨房仓只对应一个启用的食堂。")
            require(not frappe.db.exists(CANTEEN, {**filters, "canteen_name": doc.canteen_name}),
                    "同一园所已有同名食堂。")
        previous = doc.get_doc_before_save()
        if previous and any(doc.get(key) != previous.get(key) for key in ("company", "raw_warehouse", "kitchen_warehouse")):
            for kind in (TERM, POLICY, DELIVERY, RECEIVING, SAMPLE, COMPANION, STATEMENT):
                require(not frappe.db.exists(kind, {"canteen": doc.name, "docstatus": ("<", 2)}),
                        "食堂已有业务历史。变更账套或仓库请新建档案并停用旧档案。")


class Credential(Handler):
    def validate(self):
        doc = self.doc
        dates(doc.from_date, doc.to_date)
        if doc.subject_kind == "从业人员":
            company_doc(doc, "Employee", doc.employee)
            require(not doc.supplier, "从业人员证照仅关联员工。")
        elif doc.subject_kind == "供应商":
            linked("Supplier", doc.supplier)
            require(not doc.employee, "供应商证照仅关联供应商。")
        else:
            require(not doc.employee and not doc.supplier, "食堂资质由食堂档案确认归属。")
        attached_file(doc, doc.evidence)

    def before_submit(self):
        doc = self.doc
        attached_file(doc, doc.evidence, required=True)
        unique_active(doc, {"canteen": doc.canteen, "subject_kind": doc.subject_kind,
                            "credential_number": doc.credential_number, "docstatus": 1},
                      "本食堂已有同类同号有效证照。")


class Training(Handler):
    def validate(self):
        doc = self.doc
        employee = company_doc(doc, "Employee", doc.employee)
        require(getdate(doc.training_date) <= getdate(), "培训完成日期不能晚于今天。")
        if not doc.designation:
            doc.designation = employee.designation
        attached_file(doc, doc.evidence)


class Term(Handler):
    def validate(self):
        doc = self.doc
        dates(doc.from_date, doc.to_date)
        if doc.nutrition_plan:
            plan = submitted(company_doc(doc, NUTRITION, doc.nutrition_plan))
            require(getdate(plan.start_date) <= getdate(doc.to_date) and getdate(plan.end_date) >= getdate(doc.from_date),
                    "营养计划应覆盖该学期的适用日期。")
        if doc.financial_project:
            company_doc(doc, "Project", doc.financial_project)

    def before_cancel(self):
        require(not frappe.db.exists(TASK, {"term_project": self.doc.name, "docstatus": ("<", 2)}),
                "该学期仍有有效任务，请先撤销相关任务。")


class WeeklyTask(Handler):
    def validate(self):
        doc = self.doc
        term = submitted(company_doc(doc, TERM, doc.term_project))
        monday = getdate(doc.week_start)
        require(monday.weekday() == 0 and monday <= getdate(term.to_date)
                and monday + timedelta(days=6) >= getdate(term.from_date) and doc.canteen == term.canteen,
                "请选择学期范围内的自然周及同一食堂。")
        if doc.meal_week:
            week = company_doc(doc, WEEK, doc.meal_week)
            require(getdate(week.week_start) == monday and canteen_for_week(week, doc.canteen).name == doc.canteen,
                    "关联周食谱须属于本周和本食堂。")
        unique_active(doc, {"term_project": term.name, "week_start": monday, "task_kind": doc.task_kind},
                      "该学期本周已有同名任务。")
        if not doc.docstatus:
            doc.confirmed_at = None

    def before_submit(self):
        doc = self.doc
        week = submitted(company_doc(doc, WEEK, doc.meal_week))
        if doc.task_kind == "准备采购":
            from ione_core.meal_procurement import get_procurement_preview

            if not week.material_request:
                preview = get_procurement_preview(week.name)
                require(not preview["blockers"] and not any(
                    row.get("status") == "purchase" and float(row.get("purchase_qty") or 0) > 0
                    for row in preview["rows"]
                ), "采购需求仍未生成申请。")
        if doc.task_kind == "逐餐供餐与日结":
            from tongjianyun.meal_ledger import _day_proof, _week_proof

            children = records(DAY, {"meal_week": week.name, "docstatus": 1})
            require(len(children) == 5 and all(
                _day_proof(linked(DAY, child.name), _week_proof(week)) for child in children
            ), "须完成并核对本周五日的厨房日结。")
        if doc.task_kind == "周核销":
            from ione_core.meal_kitchen import verify_week_kitchen_reconciled

            proof = verify_week_kitchen_reconciled(week.name)
            require(proof and proof.get("reconciled"), "请先完成原生厨房周核销。")
        doc.confirmed_at = now_datetime()


@frappe.whitelist(methods=["POST"])
def generate_week_tasks(term_project, week_start, meal_week=None):
    term = submitted(linked(TERM, term_project, "write", lock=True))
    monday = getdate(week_start)
    require(monday.weekday() == 0 and monday <= getdate(term.to_date)
            and monday + timedelta(days=6) >= getdate(term.from_date), "请选择学期内的周一。")
    result = []
    for kind, offset in TASKS:
        key = {"term_project": term.name, "week_start": monday, "task_kind": kind}
        previous = frappe.db.get_value(TASK, {**key, "docstatus": ("<", 2)}, "name", for_update=True)
        if previous:
            result.append(linked(TASK, previous).name)
            continue
        task = frappe.get_doc({"doctype": TASK, **key, "company": term.company, "canteen": term.canteen,
                               "due_date": monday + timedelta(days=offset), "assigned_to": term.responsible_user,
                               "meal_week": meal_week})
        task.insert()
        result.append(task.name)
    return result


def meal_context(doc):
    from ione_core.meal_adjustments import get_effective_meals

    day = company_doc(doc, DAY, doc.meal_day)
    week = submitted(company_doc(doc, WEEK, day.meal_week))
    canteen_for_week(week, doc.canteen)
    date = getdate(day.meal_date)
    native = next((row for row in day.meals if row.meal_type == doc.meal_type), None)
    require(native and native.actual_confirmed and cint(native.actual_headcount) > 0,
            "请先在厨房执行单填写并确认本餐实际供餐人数。")
    actual = next((row for row in get_effective_meals(week)
                   if getdate(row.meal_date) == date and row.meal_type == doc.meal_type), None)
    require(actual is not None and actual.production_plan, "本餐缺少已经生效的配方单。")
    return day, company_doc(doc, "Production Plan", actual.production_plan)


def meal_evidence_date(value, expected):
    require(value and getdate(value) == getdate(expected) and get_datetime(value) <= now_datetime(),
            "实际登记时间须为本餐供餐当天，且不能晚于当前时间。")


def sample_scope_dishes(day, week, meal_type):
    """Resolve the scoped, approved meal plan without exposing native student or week documents."""
    from json import JSONDecodeError, loads

    if week.has_permission("read"):
        from ione_core.meal_adjustments import get_effective_meals

        row = next((row for row in get_effective_meals(week)
                    if getdate(row.meal_date) == getdate(day.meal_date) and row.meal_type == meal_type), None)
        return _sample_plan_dishes(day, week, meal_type, row.production_plan) if row else set()

    reference = next((row.production_plan for row in week.meals
                      if getdate(row.meal_date) == getdate(day.meal_date) and row.meal_type == meal_type), None)
    updates = frappe.get_all("Meal Plan Adjustment", filters={"meal_week": week.name, "docstatus": 1,
                             "meal_date": day.meal_date, "meal_type": meal_type},
                             fields=["name", "applied_snapshot", "replacement_plan", "source_adjustment"],
                             order_by="creation asc, name asc")
    previous = None
    for update in updates:
        try:
            proof = loads(update.applied_snapshot or "{}")
        except (JSONDecodeError, TypeError):
            return set()
        if not proof or proof.get("week") != week.name or proof.get("adjustment") != update.name:
            return set()
        if (update.source_adjustment or None) != previous or proof.get("source", {}).get("production_plan") != reference:
            return set()
        reference = proof.get("effective_meal", {}).get("production_plan")
        if reference != update.replacement_plan:
            return set()
        previous = update.name
    return _sample_plan_dishes(day, week, meal_type, reference)


def _sample_plan_dishes(day, week, meal_type, reference):
    if not reference:
        return set()
    plan = frappe.get_doc("Production Plan", reference)
    if (plan.company != day.company or plan.docstatus != 1 or plan.get("custom_meal_week") != week.name
            or getdate(plan.get("custom_meal_date")) != getdate(day.meal_date) or plan.get("custom_meal_type") != meal_type):
        return set()
    return {row.bom_no for row in plan.po_items if row.bom_no}


class FoodSample(Handler):
    def validate(self):
        doc = self.doc
        day, plan = meal_context(doc)
        require(doc.dish in {row.bom_no for row in plan.po_items}, "留样成品须来自本餐生效配方。")
        doc.meal_date = day.meal_date
        meal_evidence_date(doc.sampled_at, doc.meal_date)
        policy = active_policy(doc.canteen, doc.meal_date)
        weight = positive(doc.weight)
        require(weight >= positive(policy.sample_min_weight), "留样量低于本食堂有效规则。")
        doc.dispose_after = add_to_date(doc.sampled_at, hours=policy.sample_keep_hours, as_datetime=True)
        if not doc.docstatus:
            doc.operator = None
            doc.disposed_at = None
            doc.disposal_note = None
        attached_file(doc, doc.photo, image=True)

    def before_submit(self):
        doc = self.doc
        attached_file(doc, doc.photo, required=True, image=True)
        unique_active(doc, {"meal_day": doc.meal_day, "meal_type": doc.meal_type, "dish": doc.dish},
                      "本餐已登记相同成品留样。")
        doc.operator = frappe.session.user

    def before_update_after_submit(self):
        doc = self.doc
        permission(doc.flags.get("recording_disposal"), "请使用留样表单的处置操作。")


class Companion(Handler):
    def validate(self):
        doc = self.doc
        day, _plan = meal_context(doc)
        doc.meal_date = day.meal_date
        meal_evidence_date(doc.attended_at, doc.meal_date)
        previous = doc.get_doc_before_save()
        doc.companion = previous.companion if previous else frappe.session.user
        attached_file(doc, doc.photo, image=True)
        attached_file(doc, doc.video)

    def before_submit(self):
        doc = self.doc
        permission(doc.companion == frappe.session.user, "陪餐记录须由实际陪餐人确认。")
        require(doc.attested, "请确认本人参加本餐陪餐并核对记录。")
        unique_active(doc, {"meal_day": doc.meal_day, "meal_type": doc.meal_type, "companion": doc.companion},
                      "本餐已登记该陪餐人员。")


@frappe.whitelist(methods=["GET"])
def dishes_for_meal(meal_day, meal_type):
    day = linked(DAY, meal_day)
    week = linked(WEEK, day.meal_week)
    site = canteen_for_week(week)
    _day, plan = meal_context(frappe._dict(company=day.company, meal_day=day.name, canteen=site.name, meal_type=meal_type))
    return [{"bom": row.bom_no, "item": row.item_code,
             "label": row.item_name or row.item_code} for row in plan.po_items]


@frappe.whitelist(methods=["POST"])
def dispose_sample(name, reason):
    doc = submitted(linked(SAMPLE, name, "write", lock=True))
    require(reason and str(reason).strip() and not doc.disposed_at, "请填写处置说明。")
    require(now_datetime() >= get_datetime(doc.dispose_after), "留样尚未达到规定保存时间。")
    doc.flags.recording_disposal = True
    doc.disposed_at = now_datetime()
    doc.disposal_note = str(reason).strip()
    doc.save()
    return doc.name


class Finding(Handler):
    def validate(self):
        doc = self.doc
        permission(doc.source_type in FINDING_SOURCES, "请选择有效的膳食监管来源。")
        old = doc.get_doc_before_save()
        if not old and not doc.flags.get("generated_finding"):
            source = company_doc(doc, doc.source_type, doc.source)
            if source.get("canteen"):
                require(source.canteen == doc.canteen, "来源业务与整改食堂不一致。")
            if doc.source_type == COMPANION:
                require(source.evaluation != "满意", "请从有问题的陪餐记录发起整改。")
        attached_file(doc, doc.evidence)
        if doc.progress != (old.progress if old else "待整改"):
            permission(doc.flags.get("advance_progress"), "请使用整改提交或复核操作。")
        if old:
            for field in ("company", "canteen", "finding_key", "source_type", "source", "description", "category"):
                require(doc.get(field) == old.get(field), "整改原始问题须保留。")
            if old.progress == "已销项":
                frappe.throw("已销项的整改记录已归档。")
            if old.progress == "待复核" and not doc.flags.get("advance_progress"):
                frappe.throw("待复核的整改记录已锁定。")


@frappe.whitelist(methods=["POST"])
def advance_finding(name, action, note=None):
    doc = linked(FINDING, name, "write", lock=True)
    actor = frappe.session.user
    if action == "提交整改":
        require(doc.progress == "待整改" and doc.rectification, "请先记录整改情况。")
        permission(actor == doc.assigned_to or "System Manager" in roles(), "须由整改责任人提交。")
        attached_file(doc, doc.evidence, required=True)
        progress = "待复核"
    else:
        require(action in ("通过", "退回") and doc.progress == "待复核" and note, "请填写复核意见。")
        permission(actor != doc.assigned_to and (roles() & (REGULATORS | {"System Manager"})),
                   "须由独立监管人员复核。")
        doc.review_note = note
        progress = "已销项" if action == "通过" else "待整改"
    doc.flags.advance_progress = True
    doc.progress = progress
    doc.save()
    return doc.progress


def finding_key(rule, source, extra=""):
    return sha256(f"{rule}|{source}|{extra}".encode()).hexdigest()
