"""Render real entry controller/template for isolated synthetic browser cases.

No login/session is minted. No real accounts or business rows are used.
"""
import copy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode

import frappe
from frappe import _dict
from jinja2 import Environment, select_autoescape

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from tongjianyun import workspace_entry as entry
from tongjianyun.www import tongjianyun_entry as page

destination = Path(os.environ.get("TEACHER_ENTRY_FIXTURES", "/tmp/tjy-teacher-entry-fixtures.json"))
environment = Environment(autoescape=select_autoescape(default=True))
template = environment.from_string((root/"tongjianyun/www/tongjianyun-entry.html").read_text())


def make_model(groups, roles, instructor=True, employee=True, business=True):
    assignment = {"employee_linked": employee, "instructor_linked": instructor,
        "class_linked": bool(groups), "can_read_classroom": True,
        "groups": [{"name":"DEMO-C"+str(i+1),"student_group_name":["小太阳班 · 验收演示","彩虹班 · 验收演示"][i]} for i in range(groups)]}
    return {"profiles":entry.choose_profiles("synthetic-teacher",roles,assignment,business),
        "groups":assignment["groups"],"checks":{k:v for k,v in assignment.items() if k!="groups"},
        "business_available":business,"user_label":"验收教师（合成）"}


cases = {"single":make_model(1,["Instructor","Tongjianyun Business Operator"]),
         "multi":make_model(2,["Instructor"]),
         "dual":make_model(1,["Instructor","System Manager"]),
         "setup":make_model(0,["Instructor"],instructor=False,employee=False,business=False),
         "operator":make_model(0,["Tongjianyun Business Operator"],instructor=False,employee=False),
         "unknown":make_model(0,[],instructor=False,employee=False,business=False)}
queries = ["", "choose=1", "profile=teacher", "profile=business", "profile=Administrator",
           "profile=teacher&class=DEMO-C1", "profile=teacher&class=DEMO-C2", "profile=teacher&class=FOREIGN",
           "role=Administrator&user=someone-else&next=https%3A%2F%2Fevil.example"]
results = {}
for name, model in {**cases, "guest":None}.items():
    rendered = {}
    for query in queries:
        args = _dict({k:v[0] for k,v in parse_qs(query).items()})
        with patch.object(page.frappe,"session",_dict(user="Guest" if name=="guest" else "synthetic-teacher")), \
                patch.object(page.frappe,"form_dict",args), patch.object(page.frappe.local,"flags",_dict(),create=True), \
                patch.object(page.frappe.local,"response_headers",{},create=True), patch.object(entry,"entry_model",return_value=copy.deepcopy(model)):
            context = _dict()
            try:
                page.get_context(context)
                outcome = {"status":200,"body":template.render(**context)}
            except frappe.Redirect as exc:
                outcome = {"status":exc.http_status_code,"location":frappe.local.flags.redirect_location}
            except frappe.PermissionError:
                outcome = {"status":403,"body":"<html lang='zh-CN'><h1>当前入口不可访问</h1></html>"}
            outcome["headers"] = dict(frappe.local.response_headers)
            if outcome["status"] != 403:
                assert "no-store" in outcome["headers"]["Cache-Control"]
            rendered[urlencode(sorted((k,v[0]) for k,v in parse_qs(query).items()))] = outcome
    results[name] = {"routes":rendered,"model":model}
# Verify source-declared icon route; no patching of the native apps template.
from tongjianyun import hooks
assert hooks.app_home == entry.ENTRY
assert hooks.add_to_apps_screen[0]["route"] == entry.ENTRY
destination.write_text(json.dumps({"cases":results,"icon_route":hooks.app_home}, ensure_ascii=False))
print(json.dumps({"rendered_entry_cases":len(results)*len(queries),"synthetic_only":True,"output":str(destination)}))
