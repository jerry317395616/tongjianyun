import frappe
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import CANTEEN, TERM
from tongjianyun.canteen_ops.meal_operations import PUBLIC, DELIVERY


def external(site):
    return frappe.db.get_value(CANTEEN, site, "service_mode") == "园外供餐"


def evidence(company, canteen, monday):
    names = frappe.get_all(PUBLIC,filters={"company":company,"canteen":canteen,"week_start":monday,"docstatus":1,
                           "meal_week":["is","not set"]},pluck="name",limit=2)
    if len(names) != 1:
        return None, set(), set()
    menu = frappe.get_doc(PUBLIC,names[0])
    expected = {(getdate(r.service_date),r.meal_type) for r in menu.meals}
    accepted = {(getdate(r.service_date),r.meal_type) for r in frappe.get_all(DELIVERY,filters={
        "company":company,"canteen":canteen,"publication":menu.name,"result":"接收","docstatus":1},
        fields=["service_date","meal_type"])}
    return menu, expected, accepted


def progress(term, schedule):
    rows=[]
    for monday, service in schedule.items():
        menu,expected,accepted = evidence(term.company,term.canteen,monday)
        done=bool(expected and expected <= accepted)
        status=[("食谱审核",bool(menu),"已审核" if menu else "待公示"),("准备采购",True,"供餐方负责"),
                ("逐餐供餐与日结",done,f"已交接 {len(expected & accepted)}/{len(expected)} 餐"),("周核销",True,"园外供餐")]
        rows.append(dict(monday=str(monday),first=service["days"][0],last=service["days"][-1],week=None,request=None,
                         kitchen_days=[],steps=[dict(kind=k,due=service["due"][k],complete=b,status=s) for k,b,s in status]))
    return rows


def queue(doc, method=None):
    from tongjianyun.canteen_ops.term_projects import _queue
    monday = doc.get("week_start") or frappe.db.get_value(PUBLIC,doc.publication,"week_start")
    from datetime import timedelta
    for name in frappe.get_all(TERM,filters={"company":doc.company,"canteen":doc.canteen,"docstatus":1,
                              "from_date":["<=",getdate(monday)+timedelta(days=6)],"to_date":[">=",monday]},pluck="name"):
        _queue(name)
