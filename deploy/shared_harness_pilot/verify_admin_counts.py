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
    def query(operation, **arguments):
        return execute({'operation':operation,'arguments':arguments})
    bad=query('frappe_describe_doctype',doctype='Meal')
    assert bad['error']['code']=='not_found', bad
    bad=query('frappe_list_documents',doctype='Student',fields=['not_a_real_field'])
    assert bad['error']['code']=='invalid_query', bad
    denied=query('frappe_describe_doctype',doctype='User')
    assert denied['error']['code']=='access_denied', denied
    meta=query('frappe_describe_doctype',doctype='Tongjianyun Recipe Dish')
    assert 'fields' in meta, meta
    today=meta['query_context']['today']
    dishes=query('frappe_list_documents',doctype='Tongjianyun Recipe Dish',fields=['recipe','meal_date','meal_slot','dish_name'],filters={'meal_date':today},limit=100)
    assert 'total_count' in dishes, dishes
    print(json.dumps({'today':today,'today_dish_count':dishes['total_count'],'error_classification':'passed'},ensure_ascii=False))
    for label,dt in meta['query_context']['business_objects'].items():
        result=query('frappe_describe_doctype',doctype=dt)
        assert 'fields' in result,(dt,result)
    print(json.dumps({'business_metadata_checks':len(meta['query_context']['business_objects'])}))
finally:
    frappe.db.rollback()
    frappe.destroy()
