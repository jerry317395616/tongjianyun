"""Read-only verification of the actual meal scene service and role entry.

No credentials, child names or clinical details printed. No user promotion,
business writes, migrations or production sessions are created.
"""
import os
import sys
import json
from pathlib import Path
import frappe

if os.environ.get('MEAL_SCENE_SOURCE'):
    sys.path.insert(0,os.environ['MEAL_SCENE_SOURCE'])
frappe.init(site='child.myyr.top',sites_path=str(Path.cwd()/'sites'))
frappe.connect()
try:
    frappe.set_user('Administrator')
    from tongjianyun import meal_scene as service,workspace_entry as entry
    from frappe.website.page_renderers.template_page import TemplatePage
    renderer=TemplatePage('tongjianyun-meal-scene');renderer.set_pymodule()
    assert renderer.pymodule_name=='tongjianyun.www.tongjianyun_meal_scene'
    types=['Tongjianyun Recipe','Tongjianyun Class Meal Confirmation','Tongjianyun Daily Meal Confirmation',
        'Material Request','Purchase Order','Purchase Receipt','Purchase Invoice','Payment Entry','Student Attendance']
    before={dt:frappe.db.count(dt) for dt in types}
    overview=service.get_overview()
    assert overview['scene']['telemetry'] is False
    assert overview['capabilities']['recipe_create'] is True
    stock=service.get_stock() if overview['capabilities']['stock'] else None
    library=service.get_recipes()
    detail=service.get_recipe(library['rows'][0]['name']) if library['rows'] else None
    edit_mode=detail['edit']['mode'] if detail else None
    assert edit_mode in (None,'update','copy','none')
    clean_draft=service.new_draft_payload(detail['payload']) if detail else None
    assert not clean_draft or clean_draft['recipe']['workflowStatus']=='草稿'
    profiles=entry.entry_model()['profiles']
    assert any(p['id']=='meals' and p['enabled'] for p in profiles)
    ordinary_teacher_denied=None
    if frappe.db.exists('User','teacher.test@child.myyr.top'):
        frappe.set_user('teacher.test@child.myyr.top')
        ordinary_teacher_denied=not service.has_access()
        assert ordinary_teacher_denied
        teacher_profiles=entry.entry_model()['profiles']
        assert not any(p['id']=='meals' for p in teacher_profiles)
        try:service.get_overview()
        except frappe.PermissionError:pass
        else:raise AssertionError('Ordinary teacher accepted by management service')
    frappe.set_user('Administrator')
    after={dt:frappe.db.count(dt) for dt in types}
    assert before==after,'Read-only scene created business rows'
    print(json.dumps({'passed':True,'day':overview['day'],'recipes_for_day':len(overview['recipes']['rows']),
        'administrator_can_create_recipe_draft':overview['capabilities']['recipe_create'],
        'visible_meal_summary':overview['plans']['summary'], 'orders_in_page':len(overview['orders']['rows']),
        'receipts_in_page':len(overview['receipts']['rows']), 'stock_rows_in_page':len(stock['rows']) if stock else None,
        'recipe_detail_loaded':bool(detail),'recipe_edit_mode':edit_mode,
        'ordinary_teacher_denied':ordinary_teacher_denied,
        'real_recipe_payload_valid_for_scene_create':bool(clean_draft),
        'administrator_entries':[p['id'] for p in profiles], 'business_counts_unchanged':before==after},ensure_ascii=False,default=str))
finally:
    frappe.db.rollback();frappe.destroy()
