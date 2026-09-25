"""Rollback-only integration test: create/edit/history/duplicates/locks.

Only synthetic future-week recipes are written and every row is rolled back.
ERP sync is mocked so no background jobs or financial records are created.
"""
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import frappe

if os.environ.get('MEAL_SCENE_SOURCE'):
    sys.path.insert(0, os.environ['MEAL_SCENE_SOURCE'])
frappe.init(site='child.myyr.top', sites_path=str(Path.cwd()/'sites'))
frappe.connect()
try:
    frappe.set_user('Administrator')
    from tongjianyun import recipe_storage as storage, meal_scene as scene
    tracked=['Tongjianyun Recipe','Tongjianyun Recipe Dish','Tongjianyun Recipe Ingredient','Version','Material Request','Purchase Order','Tongjianyun Daily Meal Confirmation']
    before={dt:frappe.db.count(dt) for dt in tracked}
    week='2098-09-22'
    # Monday date in the synthetic week; refuse to touch existing test/business data.
    from datetime import date, timedelta
    start=date.fromisoformat(week);start-=timedelta(days=start.weekday());end=start+timedelta(days=4)
    assert not frappe.db.exists(storage.RECIPE_DOCTYPE, {'week_start':['between',[str(start),str(end)]]})
    payload={'recipe':{'recipeId':'TEST-WEEK-'+uuid4().hex,'title':'回滚测试','weekStart':str(start),'weekEnd':str(end)},
             'days':[{'id':'DAY-1','date':str(start),'portions':[{'slot':'lunch','dishes':['米饭'],'dishIngredientRows':[]}]}]}
    with patch('tongjianyun.recipe_item_sync.schedule_after_save',side_effect=lambda recipe:{'recipe':recipe,'status':'test'}):
        saved=storage.save_recipe_payload(payload);name=saved['recipe']['recipeId']
        assert frappe.db.count(storage.RECIPE_DOCTYPE)==before[storage.RECIPE_DOCTYPE]+1
        saved['days'][0]['portions'][0]['dishes']=['小米粥']
        edited=scene.save_recipe_edit(name,saved['recipe']['revision'],saved)
        assert edited['name']==name and edited['mode']=='update'
        assert frappe.db.count(storage.RECIPE_DOCTYPE)==before[storage.RECIPE_DOCTYPE]+1
        history=storage.get_recipe_history(name)['versions'];assert len(history)==1
        prior=storage.get_recipe_history(name,history[0]['name'])['payload']
        assert prior['days'][0]['portions'][0]['dishes']==['米饭']
        current=storage.get_recipe_detail(name)
        assert current['days'][0]['portions'][0]['dishes']==['小米粥']
        for trial in [saved, dict(deepcopy(current), recipe={**current['recipe'],'recipeId':'TEST-DUP-'+uuid4().hex})]:
            frappe.db.savepoint('rejected_save')
            try:storage.save_recipe_payload(trial)
            except frappe.ValidationError:frappe.db.rollback(save_point='rejected_save')
            else:raise AssertionError('stale revision / duplicate week accepted')
        # Direct DocType creation must also respect the shared weekly constraint.
        frappe.db.savepoint('direct_duplicate')
        try:
            frappe.get_doc({'doctype':storage.RECIPE_DOCTYPE,'recipe_id':'TEST-DIRECT-'+uuid4().hex,'title':'回滚重复测试','week_start':str(start+timedelta(days=1)),'week_end':str(end),'workflow_status':'草稿'}).insert()
        except frappe.ValidationError:frappe.db.rollback(save_point='direct_duplicate')
        else:raise AssertionError('native DocType duplicate accepted')
        current['days'][0]['locked']=True
        storage.save_recipe_payload(current)
        locked=storage.get_recipe_detail(name);locked['days'][0]['portions'][0]['dishes']=['不应保存']
        try:storage.save_recipe_payload(locked)
        except frappe.ValidationError:pass
        else:raise AssertionError('locked day changed')
        assert storage.get_recipe_detail(name)['days'][0]['portions'][0]['dishes']==['小米粥']
    frappe.db.rollback()
    after={dt:frappe.db.count(dt) for dt in tracked}
    assert before==after
    # Verify that another connection cannot pass the empty-week write guard.
    from threading import Event, Thread
    from tongjianyun.recipe_week import lock_recipe_writes
    started, acquired = Event(), Event()
    errors=[]
    def competing_writer():
        try:
            frappe.init(site='child.myyr.top', sites_path=str(Path.cwd()/'sites'));frappe.connect()
            started.set();lock_recipe_writes();acquired.set()
        except Exception as error:errors.append(str(error))
        finally:frappe.db.rollback();frappe.destroy()
    lock_recipe_writes()
    competitor=Thread(target=competing_writer,daemon=True);competitor.start()
    try:
        assert started.wait(5)
        assert not acquired.wait(.3), 'another writer escaped the transaction lock'
    finally:frappe.db.rollback()
    assert acquired.wait(5);competitor.join(5);assert not errors and not competitor.is_alive()
    print(json.dumps({'passed':True,'same_identity':True,'one_recipe_after_edit':True,'history_recoverable':True,'stale_rejected':True,'duplicate_week_rejected':True,'native_duplicate_rejected':True,'locked_day_protected':True,'concurrent_writes_serialized':True,'all_test_rows_rolled_back':True}))
finally:
    frappe.db.rollback();frappe.destroy()
