"""Create synthetic canteen data on an explicitly enabled demo site."""
from datetime import date, timedelta

import frappe
from frappe.utils import getdate, today

from tongjianyun.canteen_ops.common import CANTEEN, WEEK
from tongjianyun.canteen_ops.meal_operations import CHECKS, SAFETY
from tongjianyun.dish_library import DEFAULT_DISH_GROUP
from tongjianyun.ingredient_library import MARKER as INGREDIENT
from tongjianyun.ingredient_library_setup import ensure_food_masters
from tongjianyun.meal_planning import SLOTS, SLOT_FIELDS, confirm_stock_review
from tongjianyun.meal_procurement import create_material_request
from tongjianyun.meal_weights import confirm_requirement_weight_basis
from tongjianyun.standard_recipes import CATEGORY, DISH, DISH_CATEGORY, MARKER, set_review_pending
from tongjianyun.weekly_menu_editor import initialize, save_meal

COMPANY = "青禾溪畔示范幼儿园"
OTHER_COMPANY = "青禾林间示范幼儿园"
PLANNER = "planner@tongjianyun.invalid"
READER = "canteen-reader@tongjianyun.invalid"
MENUS = (
    ("主食", "小米南瓜粥", ("小米", "粮油及主食", 0.022), ("南瓜", "蔬菜", 0.035)),
    ("饮品", "温牛奶", ("牛奶", "蛋奶及豆制品", 0.150)),
    ("荤菜", "胡萝卜鸡丁饭", ("鸡胸肉", "肉禽水产", 0.047), ("胡萝卜", "蔬菜", 0.032),
     ("大米", "粮油及主食", 0.052)),
    ("水果", "苹果块", ("苹果", "水果", 0.085)),
    ("汤羹", "番茄蛋花汤", ("番茄", "蔬菜", 0.050), ("鸡蛋", "蛋奶及豆制品", 0.024)),
)


def _require_demo():
    frappe.only_for("System Manager")
    if not frappe.conf.get("tongjianyun_demo"):
        frappe.throw("请在独立测试站点显式开启 tongjianyun_demo。")
    if set(frappe.get_all("Company", pluck="name")) - {COMPANY, OTHER_COMPANY}:
        frappe.throw("演示脚本需要一个没有其他园所或公司的独立站点。")


def _insert(doctype, **fields):
    return frappe.get_doc({"doctype": doctype, **fields}).insert()


def _site(company, abbreviation):
    if not frappe.db.exists("Company", company):
        _insert("Company", company_name=company, abbr=abbreviation, default_currency="CNY", country="China")
    raw = _insert("Warehouse", warehouse_name="食堂原料仓", company=company)
    kitchen = _insert("Warehouse", warehouse_name="厨房周转仓", company=company)
    return _insert(CANTEEN, company=company, canteen_name="园本食堂", region="青禾市", district="清溪区",
                   raw_warehouse=raw.name, kitchen_warehouse=kitchen.name, service_mode="自主经营")


def _setup_erp(current):
    from erpnext.setup.setup_wizard.setup_wizard import setup_complete
    from frappe.desk.page.setup_wizard.setup_wizard import enable_setup_wizard_complete

    language = frappe.local.lang
    try:
        frappe.local.lang = "en"
        setup_complete(frappe._dict(
            country="China", currency="CNY", company_name=COMPANY, company_abbr="QHT",
            fy_start_date=date(current.year, 1, 1).isoformat(), fy_end_date=date(current.year, 12, 31).isoformat(),
        ))
    finally:
        frappe.local.lang = language
    for app in frappe.get_installed_apps():
        enable_setup_wizard_complete(app)
    frappe.db.set_single_value("System Settings", "setup_complete", 1)
    frappe.clear_document_cache("System Settings", "System Settings")


def _user(email, name, role):
    return _insert("User", email=email, first_name=name, send_welcome_email=0, user_type="System User",
                   roles=[{"role": role}])


def _school(company, start):
    end = start + timedelta(days=90)
    year = _insert("Academic Year", academic_year_name="青禾演示学年", company=company,
                   year_start_date=start, year_end_date=end)
    term = _insert("Academic Term", term_name="青禾演示学期", academic_year=year.name, company=company,
                   term_start_date=start, term_end_date=end)
    category = _insert("Fee Category", category_name="示范活动费")
    receivable = frappe.db.get_value("Company", company, "default_receivable_account")
    fees = _insert("Fee Term", fee_term_name="示范活动收费规则", company=company,
                   term_type="Session Based Fees", receivable_account=receivable,
                   fee_components=[{"fees_category": category.name, "value": 100}])
    scale = _insert("Grading Scale", grading_scale_name="示范活动评价标准", company=company,
                    intervals=[{"grade_code": "参与", "minimum_percentage": 0, "maximum_percentage": 100}])
    template = _insert("Grade Template", template_name="示范活动评价规则", company=company,
                       academic_year=year.name, academic_term=term.name, weightage_type="Attendance Weightage",
                       attendance_weights=[{"attendance_type": "Present", "weightage": 100}])
    course = _insert("Course", course_name="幼儿园活动", course_abbreviation="QH-ACT", company=company,
                     evaluation_type="Normal", short_description="示范园班级活动", fee_term=fees.name,
                     default_grading_scale=scale.name, grade_templates=[{"grade_template": template.name}])
    batch = _insert("Student Batch Name", batch_name="青禾青苗班", company=company, course=course.name,
                    start_date=start, end_date=end)
    for number in range(1, 13):
        _insert("Student", first_name=f"演示幼儿 {number:02}", joining_date=start,
                email_address=f"student-{number:02}@tongjianyun.invalid", custom_student_batch=batch.name)
    return year.name, term.name


def _recipes(company):
    ingredients = {}
    plans = {}
    for index, (slot, (category, name, *rows)) in enumerate(zip(SLOTS, MENUS), 1):
        items = []
        for ingredient, group, quantity in rows:
            if ingredient not in ingredients:
                item = _insert("Item", item_code=f"QH-FOOD-{len(ingredients) + 1:02}", item_name=ingredient,
                               item_group=group, stock_uom="Kg", is_stock_item=1,
                               is_purchase_item=1, is_sales_item=0, custom_meal_procurement_policy="采购",
                               **{INGREDIENT: 1})
                ingredients[ingredient] = item.name
            items.append({"item_code": ingredients[ingredient], "qty": quantity, "rate": 10, "uom": "Kg"})
        dish = _insert("Item", item_code=f"QH-DISH-{index:02}", item_name=name, item_group=DEFAULT_DISH_GROUP,
                       stock_uom="份", is_stock_item=1, is_purchase_item=0, is_sales_item=0,
                       **{DISH: 1, DISH_CATEGORY: category, SLOT_FIELDS[slot]: 1})
        recipe = _insert("BOM", item=dish.name, company=company, quantity=1, items=items,
                         **{MARKER: 1, CATEGORY: category})
        set_review_pending(recipe.name, 1)
        recipe.reload().submit()
        plans[slot] = recipe.name
    return plans


def _week(site, start, year, term, recipes):
    admin = frappe.session.user
    try:
        frappe.set_user(PLANNER)
        doc = _insert(WEEK, company=site.company, custom_tjy_canteen=site.name, week_start=start,
                      academic_year=year, academic_term=term,
                      raw_material_warehouse=site.raw_warehouse, kitchen_warehouse=site.kitchen_warehouse)
        initialize(doc.name)
        doc.reload()
        modified = str(doc.modified)
        for row in doc.meals:
            result = save_meal(doc.name, str(row.meal_date), row.meal_type, modified,
                               frappe.as_json([recipes[row.meal_type]]))
            modified = result["modified"]
        confirm_requirement_weight_basis(doc.name)
        confirm_stock_review(doc.name)
    finally:
        frappe.set_user(admin)
    return doc.reload().submit()


def _existing_data():
    return {
        "company": COMPANY,
        "canteen": frappe.db.get_value(CANTEEN, {"company": COMPANY}, "name"),
        "meal_week": frappe.db.get_value(WEEK, {"company": COMPANY}, "name"),
        "safety_check": frappe.db.get_value(SAFETY, {"company": COMPANY}, "name"),
        "purchase_request": frappe.db.get_value(WEEK, {"company": COMPANY}, "material_request"),
    }


def seed():
    """Run with bench execute on an existing, separate demo site."""
    _require_demo()
    if frappe.db.exists("Company", COMPANY):
        result = _existing_data()
        if not all(result.values()):
            frappe.throw("发现未完成的演示数据。请在新的演示站点初始化。")
        return result

    current = getdate(today())
    _setup_erp(current)
    ensure_food_masters()
    site = _site(COMPANY, "QHT")
    _site(OTHER_COMPANY, "QHL")
    _user(PLANNER, "演示食谱编排员", "System Manager")
    _user(READER, "演示食堂安全员", "膳食安全员")
    for doctype, name in (("Company", site.company), (CANTEEN, site.name)):
        _insert("User Permission", user=READER, allow=doctype, for_value=name, apply_to_all_doctypes=1)

    start = current + timedelta(days=7 - current.weekday())
    year, term = _school(site.company, start)
    week = _week(site, start, year, term, _recipes(site.company))
    create_material_request(week.name)

    _insert(SAFETY, company=site.company, canteen=site.name, service_date=current, period="日管控",
            checks=[{"control": control, "result": "正常"} for control in CHECKS["日管控"]]).submit()
    return _existing_data()


def verify():
    """Validate the demo links and effective cross-company permissions using live documents."""
    _require_demo()
    data = _existing_data()
    if not all(data.values()):
        raise RuntimeError("The demo seed did not finish.")
    week = frappe.get_doc(WEEK, data["meal_week"])
    if week.docstatus != 1 or len(week.meals) != 25 or any(row.planned_headcount != 12 for row in week.meals):
        raise RuntimeError("The submitted demo menu does not contain the expected roster and meals.")
    request = frappe.get_doc("Material Request", data["purchase_request"])
    if request.company != COMPANY or request.material_request_type != "Purchase" or not request.items:
        raise RuntimeError("The approved menu did not generate the expected material request.")
    if frappe.get_doc(SAFETY, data["safety_check"]).docstatus != 1:
        raise RuntimeError("The daily safety check is missing or unsubmitted.")

    other = frappe.db.get_value(CANTEEN, {"company": OTHER_COMPANY}, "name")
    owner = frappe.session.user
    try:
        frappe.set_user(READER)
        visible = set(frappe.get_list(CANTEEN, pluck="name"))
        if visible != {data["canteen"]}:
            raise RuntimeError("The scoped user could not list exactly their own canteen.")
        if frappe.has_permission(CANTEEN, "read", doc=other):
            raise RuntimeError("The scoped user could open the other company's canteen.")
    finally:
        frappe.set_user(owner)
    return data
