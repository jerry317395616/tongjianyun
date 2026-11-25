"""School-scoped operational records and published family menus."""
import secrets
from contextvars import ContextVar
from datetime import timedelta

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, get_datetime, now_datetime, today

from tongjianyun.canteen_ops.common import (
    CANTEEN, FINDING, WEEK, allowed_values, decimal, linked, lock_company, permission, require,
)


family_submission = ContextVar("tjy_family_submission", default=False)

SAFETY = "Tongjianyun Meal Safety Check"
FEEDBACK = "Tongjianyun Meal Class Feedback"
DIET = "Tongjianyun Meal Diet Arrangement"
HANDOVER = "Tongjianyun Meal Diet Handover"
PUBLIC = "Tongjianyun Meal Publication"
OPINION = "Tongjianyun Meal Family Opinion"
DELIVERY = "Tongjianyun Meal Delivery Handover"
TYPES = (SAFETY, FEEDBACK, DIET, HANDOVER, PUBLIC, OPINION, DELIVERY)
PRIVATE = (DIET, HANDOVER, FEEDBACK)
CHECKS = {
    "日管控": ("人员健康与卫生", "进货验收与储存温度", "生熟分开与加工温控", "清洗消毒与分餐", "留样、陪餐与添加剂"),
    "周排查": ("本周日检查与遗漏", "风险趋势与隐患处置", "整改复核及下周措施"),
    "月调度": ("听取食品安全工作汇报", "本月检查及整改情况", "下月重点与责任分工"),
}


def _scope(doctype, user=None):
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))
    if "System Manager" in roles:
        return {}
    companies = allowed_values("Company", user)
    scope = {"company": companies}
    sites = allowed_values(CANTEEN, user)
    if sites:
        scope["canteen"] = sites
    if doctype in PRIVATE and "膳食班级教师" in roles and not roles.intersection({"膳食保健员", "膳食园方负责人"}):
        scope["student_group"] = allowed_values("Student Batch Name", user)
    return scope


def permission_query(doctype):
    def query(user=None):
        clauses = []
        for key, values in _scope(doctype, user).items():
            if not values:
                return "1=0"
            names = ", ".join(frappe.db.escape(n) for n in sorted(values))
            clauses.append(f"`tab{doctype}`.`{key}` in ({names})")
        return " and ".join(clauses)
    return query


def permitted(doc, user=None, permission_type=None, **kwargs):
    if doc.is_new() and not doc.get("company"):
        return None
    return all(doc.get(key) in values for key, values in _scope(doc.doctype, user).items())


class Operation(Document):
    def validate(self):
        if not (self.doctype == OPINION and family_submission.get()):
            permission(permitted(self))
        site = frappe.db.get_value(CANTEEN, self.canteen, ["company", "disabled", "service_mode"], as_dict=True)
        require(site and site.company == self.company and not site.disabled, "请选择本园所的启用食堂。")
        self.flags.service_mode = site.service_mode
        if self.get("student_group"):
            require(frappe.db.get_value("Student Batch Name", self.student_group, "company") == self.company,
                    "班级与园所不相符。")
        if self.get("service_date"):
            self.service_date = getdate(self.service_date)
        lock_company(self.company)

    def unique(self, *keys):
        filters = {key: self.get(key) for key in keys}
        filters.update(name=["!=", self.name or ""], docstatus=["<", 2])
        require(not frappe.db.exists(self.doctype, filters), "已存在相同范围的记录，请打开原单。")


def create_finding(doc, description):
    require(doc.assigned_to and doc.due_date, "异常须填写整改责任人及期限。")
    found = frappe.get_doc({"doctype": FINDING, "company": doc.company, "canteen": doc.canteen,
        "finding_title": description[:120], "category": "食品安全", "source_type": doc.doctype, "source": doc.name,
        "description": description, "assigned_to": doc.assigned_to, "due_date": doc.due_date, "progress": "待整改"})
    found.flags.generated_finding = True
    found.insert(ignore_permissions=True)
    doc.db_set("finding", found.name, update_modified=False)


class SafetyCheck(Operation):
    def validate(self):
        super().validate()
        require(self.service_date <= getdate(today()), "不能提前登记检查。")
        self.unique("canteen", "period", "service_date")
        if not self.checks:
            for control in CHECKS[self.period]:
                self.append("checks", {"control": control})
        self.signed_by = self.finding = None
        if self.docstatus == 1:
            if self.period == "月调度":
                permission(bool({"System Manager", "膳食园方负责人"} & set(frappe.get_roles())))
            require(set(CHECKS[self.period]) <= {r.control for r in self.checks} and
                    all(r.result and (r.result == "正常" or r.observation) for r in self.checks),
                    "请完成风险清单，说明异常或不适用的原因。")
            require(self.period == "日管控" or self.summary, "请记录本期研判及后续安排。")
            self.signed_by = frappe.session.user

    def on_submit(self):
        problems = [f"{r.control}：{r.observation}" for r in self.checks if r.result == "异常"]
        if problems:
            create_finding(self, "；".join(problems))


def week_for(doc):
    week = frappe.get_doc(WEEK, doc.meal_week)
    from tongjianyun.canteen_ops.task_menus import WeekMenus
    same = WeekMenus(doc.company, [getdate(week.week_start)]).match(doc.canteen, getdate(week.week_start))[0]
    require(week.docstatus == 1 and same and same.name == week.name, "请选择本食堂已审核的周食谱。")
    return week


def menu_lines(pub):
    if not pub.meal_week:
        return [{"date": str(r.service_date), "slot": r.meal_type, "menu": r.menu} for r in pub.meals]
    from tongjianyun.meal_adjustments import get_effective_meals
    week = week_for(pub)
    rows = get_effective_meals(week)
    return [{"date": str(row.meal_date), "slot": row.meal_type, "menu": row.menu or "",
             "stopped": bool(row.service_suspended), "changed": bool(row.get("adjustment"))} for row in rows]


def feedback_source(doc):
    monday = doc.service_date - timedelta(days=doc.service_date.weekday())
    if frappe.db.get_value(CANTEEN, doc.canteen, "service_mode") == "园外供餐":
        doc.publication = frappe.db.get_value(PUBLIC, {"canteen": doc.canteen, "company": doc.company,
            "week_start": monday, "docstatus": 1, "meal_week": ["is", "not set"]})
        doc.meal_week = None
    else:
        from tongjianyun.canteen_ops.task_menus import WeekMenus
        week = WeekMenus(doc.company, [monday]).match(doc.canteen, monday)[0]
        doc.meal_week = week.name if week and week.docstatus == 1 else None
        doc.publication = None


def meal_dishes(doc):
    require(bool(doc.get("meal_week")) != bool(doc.get("publication")), "请选择周食谱或园外供餐菜单。")
    if doc.get("meal_week"):
        from tongjianyun.canteen_ops.safety import sample_scope_dishes
        week = week_for(doc)
        scope = frappe._dict(company=doc.company, meal_date=doc.service_date)
        recipes = sample_scope_dishes(scope, week, doc.meal_type)
        if not recipes:
            return set()
        codes = frappe.get_all("BOM", filters={"name": ["in", sorted(recipes)]}, pluck="item")
        return {r.item_name or r.name for r in frappe.get_all("Item", filters={"name": ["in", codes]}, fields=["name", "item_name"])}
    pub = frappe.get_doc(PUBLIC, doc.publication)
    require(pub.docstatus == 1 and pub.canteen == doc.canteen and pub.company == doc.company and not pub.meal_week,
            "请选择本食堂已发布的园外供餐菜单。")
    return {r.menu for r in pub.meals if getdate(r.service_date) == doc.service_date and r.meal_type == doc.meal_type}


class ClassFeedback(Operation):
    def validate(self):
        super().validate()
        self.unique("canteen", "student_group", "service_date", "meal_type")
        require(self.service_date <= getdate(today()) and self.attendance >= 0, "请核对就餐日期和人数。")
        feedback_source(self)
        dishes = meal_dishes(self)
        require(dishes, "找不到该次供餐。")
        if self.docstatus == 1:
            if self.publication:
                confirmed = frappe.db.exists(DELIVERY, {"publication": self.publication, "meal_type": self.meal_type,
                    "service_date": self.service_date, "result": "接收", "docstatus": 1})
            else:
                name = frappe.db.get_value("Meal Kitchen Day", {"meal_week": self.meal_week,
                    "meal_date": self.service_date, "docstatus": ["<", 2]})
                confirmed = name and any(row.meal_type == self.meal_type and row.actual_confirmed and row.actual_headcount
                                          for row in frappe.get_doc("Meal Kitchen Day", name).meals)
            require(confirmed, "请在厨房确认实供或园外成品接收后提交班级反馈。")
        require(len({r.dish for r in self.observations}) == len(self.observations), "同一道菜只需记录一次。")
        for row in self.observations:
            require(row.dish in dishes, "反馈菜品须来自本餐菜单。")
            if row.weighed:
                require(decimal(row.served_g) > 0 and 0 <= decimal(row.plate_g) <= decimal(row.served_g),
                        "餐盘剩余须在零与实际供出量之间，单位均为克。")
            else:
                row.plate_g = row.served_g = None


def member(group, student):
    from tongjianyun.meal_population import STUDENT_BATCH_FIELD
    return frappe.db.get_value("Student", student, STUDENT_BATCH_FIELD) == group


class DietArrangement(Operation):
    def validate(self):
        super().validate()
        require(member(self.student_group, self.student), "幼儿须属于所选班级。")
        require(getdate(self.from_date) <= getdate(self.to_date), "请核对安排有效期。")
        if self.docstatus == 1:
            require(not frappe.db.exists(DIET, {"name": ["!=", self.name], "docstatus": 1, "canteen": self.canteen,
                "student": self.student, "from_date": ["<=", self.to_date], "to_date": [">=", self.from_date]}),
                "该幼儿已有同期安排，请合并限制和替代餐。")


class DietHandover(Operation):
    def validate(self):
        super().validate()
        plan = frappe.get_doc(DIET, self.arrangement)
        require(plan.docstatus == 1 and self.canteen == plan.canteen and self.company == plan.company and
                self.student_group == plan.student_group and self.student == plan.student and
                getdate(plan.from_date) <= self.service_date <= getdate(plan.to_date), "交接须符合已确认的幼儿、班级和有效期。")
        self.unique("arrangement", "service_date", "meal_type")
        self.confirmed_at = None
        if self.docstatus == 1:
            require(self.service_date <= getdate(today()) and self.received_by == frappe.session.user,
                    "须由接餐人本人在实际供餐后确认。")
            self.confirmed_at = now_datetime()


class Publication(Operation):
    def validate(self):
        super().validate()
        self.unique("canteen", "week_start")
        start = getdate(self.week_start)
        require(start.weekday() == 0, "请选择供餐周一。")
        if self.meal_week:
            week = week_for(self)
            require(week.has_permission("read") and start == getdate(week.week_start), "周食谱或日期不匹配。")
            self.set("meals", [])
        else:
            require(self.flags.service_mode == "园外供餐" and self.meals, "园内供餐请引用审核后的周食谱。")
            require(all(start <= getdate(r.service_date) <= start + timedelta(days=6) for r in self.meals),
                    "配送菜品须在本周范围内。")
        self.public_revision = 1 if self.docstatus == 1 else 0
        self.change_notice = None
        self.public_key = secrets.token_urlsafe(32) if self.docstatus == 1 else None
        self.public_menu = frappe.as_json(menu_lines(self)) if self.docstatus == 1 else None


class FamilyOpinion(Operation):
    def validate(self):
        super().validate()
        pub = frappe.get_doc(PUBLIC, self.publication)
        require(pub.company == self.company and pub.canteen == self.canteen and pub.docstatus == 1, "意见须关联本园已发布菜单。")
        old = self.get_doc_before_save()
        self.finding = old.finding if old else None
        self.receipt_hash = old.receipt_hash if old else (self.receipt_hash if family_submission.get() else None)
        if old:
            require(all(self.get(k) == old.get(k) for k in ("company","canteen","publication","category","opinion","service_date","menu_detail")),
                    "原始反馈须保留。")
        if self.docstatus == 1:
            require(self.reply, "请填写处理答复。")

    def on_update(self):
        if self.category == "食品安全" and not self.finding and self.assigned_to and self.due_date:
            create_finding(self, self.opinion)

    def before_submit(self):
        if self.category == "食品安全" and not self.finding:
            require(self.assigned_to and self.due_date, "请先分派食品安全意见的整改责任人及期限。")


class DeliveryHandover(Operation):
    def validate(self):
        super().validate()
        dishes = meal_dishes(self)
        require(dishes and self.flags.service_mode == "园外供餐", "请核对园外供餐菜单。")
        require(self.supplier == frappe.db.get_value(CANTEEN, self.canteen, "service_supplier"), "供餐单位须与食堂档案一致。")
        require(get_datetime(self.prepared_at) <= get_datetime(self.arrived_at) <= now_datetime() and self.portions > 0,
                "请核对烧熟时间、到园时间和份数。")
        require(getdate(self.arrived_at) == self.service_date, "到园时间须为供餐当天。")
        require(self.result != "拒收" or self.exception, "请记录拒收原因及处置。")
        if self.result == "接收" and self.docstatus == 1:
            require(self.served_at and get_datetime(self.arrived_at) <= get_datetime(self.served_at) <= now_datetime()
                    and get_datetime(self.served_at) - get_datetime(self.prepared_at) <= timedelta(hours=2),
                    "请核对实际食用时间及烧熟至食用时长。")
        self.unique("publication", "meal_type", "service_date", "batch")
        self.receiver = frappe.session.user if self.docstatus == 1 else None


@frappe.whitelist(methods=["GET"])
def review_period(canteen, period, service_date):
    require(period in ("周排查", "月调度"), "请选择周排查或月调度。")
    end = getdate(service_date)
    start = end.replace(day=1) if period == "月调度" else end - timedelta(days=end.weekday())
    return frappe.get_list(SAFETY, filters={"canteen": canteen, "docstatus": 1, "service_date": ["between", [start,end]],
        "period": "周排查" if period == "月调度" else "日管控"}, fields=["name", "service_date", "summary","finding","signed_by"],
        order_by="service_date asc", limit_page_length=0)


@frappe.whitelist(methods=["GET"])
def class_dishes(company, canteen, student_group, service_date, meal_type, meal_week=None, publication=None):
    doc = frappe.get_doc({"doctype": FEEDBACK, "company": company, "canteen": canteen, "student_group": student_group,
                          "service_date": getdate(service_date), "meal_type": meal_type, "meal_week":meal_week, "publication":publication})
    permission(frappe.has_permission(FEEDBACK,"create") and permitted(doc))
    require(frappe.db.get_value(CANTEEN,canteen,"company") == company and
            frappe.db.get_value("Student Batch Name",student_group,"company") == company, "请核对班级及食堂。")
    feedback_source(doc)
    return sorted(meal_dishes(doc))


@frappe.whitelist(methods=["GET"])
def diet_list(company, canteen, student_group, service_date):
    doc = frappe.get_doc({"doctype": HANDOVER,"company":company,"canteen":canteen,"student_group":student_group})
    permission(frappe.has_permission(HANDOVER,"create") and permitted(doc))
    require(frappe.db.get_value(CANTEEN,canteen,"company") == company and
            frappe.db.get_value("Student Batch Name",student_group,"company") == company,"请选择本园班级和食堂。")
    return frappe.get_all(DIET, filters={"company":company,"canteen":canteen,"student_group":student_group,"docstatus":1,
                          "from_date":["<=",service_date],"to_date":[">=",service_date]},
                          fields=["name","student","alternative"], order_by="student asc")


@frappe.whitelist(methods=["GET"])
def dish_notes(week_name, bom_name, service_date):
    import re
    from tongjianyun.standard_recipes import ALLERGENS
    week = linked(WEEK, week_name)
    recipe = linked("BOM", bom_name)
    day = getdate(service_date)
    canteen = week.get("custom_tjy_canteen")
    require(recipe.company == week.company and getdate(week.week_start) <= day <= getdate(week.week_end), "食谱日期或配方园所不匹配。")
    if not canteen or not set(frappe.get_roles()).intersection({"System Manager","膳食保健员","膳食业务经办员","食谱编排员"}):
        return {"allergens":recipe.get(ALLERGENS), "conflicts":None,"feedback":[]}
    dish = frappe.db.get_value("Item", recipe.item, "item_name") or recipe.item
    labels = " ".join([recipe.get(ALLERGENS) or "", *[r.item_name or r.item_code for r in recipe.items]])
    filters = {"company":week.company,"canteen":canteen,"docstatus":1}
    cautions = set()
    for row in frappe.get_all(DIET,filters={**filters,"from_date":["<=",day],"to_date":[">=",day]},fields=["avoid"]):
        cautions.update(word for word in re.split(r"[,，、;；\s]+",row.avoid.strip()) if word and word in labels)
    feedback = []
    latest_observation = None
    if frappe.has_permission(FEEDBACK, "read"):
        records = frappe.get_list(FEEDBACK, filters={**filters, "service_date": ["between", [day-timedelta(days=90), day]]},
                                  fields=["name", "service_date"], order_by="service_date desc, creation desc", limit_page_length=0)
        if records:
            lines = frappe.get_all("Tongjianyun Meal Dish Feedback",
                filters={"parenttype": FEEDBACK, "parent": ["in", [r.name for r in records]], "dish": dish},
                fields=["parent", "acceptance", "reason"])
            by_record = {r.parent: r for r in lines}
            counts = {}
            for record in records:
                line = by_record.get(record.name)
                if line and (line.acceptance != "未观察" or line.reason):
                    if latest_observation is None:
                        latest_observation = dict(date=record.service_date, acceptance=line.acceptance, reason=line.reason)
                    if line.acceptance != "未观察":
                        counts[line.acceptance] = counts.get(line.acceptance, 0) + 1
            feedback = [dict(acceptance=key, observations=count) for key, count in counts.items()]
    return {"allergens":recipe.get(ALLERGENS), "conflicts":sorted(cautions), "feedback":feedback, "latest":latest_observation}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def scope_links(doctype, txt, searchfield, start, page_len, filters=None):
    from tongjianyun.canteen_ops.common import OPERATION_STAFF
    permission(bool(OPERATION_STAFF & set(frappe.get_roles())))
    require(doctype in ("Company", "Student Batch Name", "Student"), "请选择园所、班级或幼儿。")
    filters = frappe._dict(frappe.parse_json(filters) or {})
    companies = allowed_values("Company")
    if not companies:
        return []
    terms = {"name": ["like", f"%{txt or ''}%"]}
    if doctype == "Company":
        conditions = [["name", "in", sorted(companies)], ["name", "like", f"%{txt or ''}%"]]
    else:
        if filters.company not in companies:
            return []
        scope = _scope(FEEDBACK)
        if doctype == "Student Batch Name":
            conditions = [["company", "=", filters.company], ["disabled", "=", 0], ["name", "like", f"%{txt or ''}%"]]
            if "student_group" in scope:
                if not scope["student_group"]:
                    return []
                conditions.append(["name", "in", sorted(scope["student_group"])])
        else:
            if "膳食保健员" not in frappe.get_roles() or not filters.student_group:
                return []
            if frappe.db.get_value("Student Batch Name", filters.student_group, "company") != filters.company:
                return []
            conditions = {**terms, "custom_student_batch": filters.student_group}
    return frappe.get_all(doctype, filters=conditions, fields=["name"], as_list=True, order_by="name",
                          limit_start=max(0,int(start)), limit_page_length=min(50,max(1,int(page_len))))
