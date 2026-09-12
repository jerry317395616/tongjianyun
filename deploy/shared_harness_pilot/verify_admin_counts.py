"""Read-only live regression: totals must not depend on page size or offset."""
import json, os, sys
os.chdir('/home/zyd/frappe/native-bench')
sys.path.insert(0,'/home/zyd/frappe/native-bench/apps/tongjianyun/deploy/shared_harness_pilot')
import frappe
from administrator_worker import execute
frappe.init(site='child.myyr.top',sites_path='/home/zyd/frappe/native-bench/sites')
try:
    frappe.connect(set_admin_as_user=False)
    frappe.set_user('Administrator')
    expected=frappe.db.count('Student')
    original=frappe.local.form_dict
    for start,limit in [(0,20),(0,100),(100,100),(200,100)]:
        r=execute({'operation':'frappe_list_documents','arguments':{'doctype':'Student','fields':['name'],'start':start,'limit':limit}})
        assert r['total_count']==expected
        assert r['page_count']==min(limit,max(0,expected-start))
        assert r['has_more']==(start+r['page_count']<expected)
        assert frappe.local.form_dict is original
        print(json.dumps({k:r[k] for k in ['start','page_count','total_count','has_more']}))
    r=execute({'operation':'frappe_list_documents','arguments':{'doctype':'Student','fields':['name'],'filters':{'enabled':0}}})
    assert r['total_count']==frappe.db.count('Student',{'enabled':0})
    print(json.dumps({'disabled_total':r['total_count'],'checks':'passed'}))
finally:
    frappe.db.rollback()
    frappe.destroy()
