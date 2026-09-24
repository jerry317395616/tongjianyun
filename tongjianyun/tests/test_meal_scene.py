"""Read-model, state semantics and write boundaries, no production facts written."""
import unittest
from unittest.mock import patch, MagicMock
from datetime import date
from pathlib import Path
import ast

import frappe
from frappe import _dict
from tongjianyun import meal_scene as service, workspace_entry as entry


class MealSceneTests(unittest.TestCase):
    def test_missing_plans_are_unknown_not_zero(self):
        result=service.meal_summary([{'has_plan':False,'confirmed':False,'expected':None,'actual':None}],1)
        self.assertIsNone(result['expected']); self.assertIsNone(result['actual']); self.assertEqual(result['missing_groups'],1)

    def test_partial_actual_is_explicit_subtotal(self):
        result=service.meal_summary([
            {'has_plan':True,'confirmed':True,'expected':3,'actual':2},
            {'has_plan':True,'confirmed':False,'expected':4,'actual':None}],2)
        self.assertEqual(result['expected'],7);self.assertIsNone(result['actual']);self.assertEqual(result['confirmed_subtotal'],2)

    def test_zero_actual_is_not_missing(self):
        result=service.meal_summary([{'has_plan':True,'confirmed':True,'expected':0,'actual':0}],1)
        self.assertEqual(result['actual'],0);self.assertEqual(result['expected'],0)

    def test_empty_scope_is_not_complete(self):
        result=service.meal_summary([],0)
        self.assertIsNone(result['expected']);self.assertIsNone(result['actual'])

    def test_strict_business_date(self):
        self.assertEqual(service.business_day('2026-09-23'),date(2026,9,23))
        with patch.object(service.frappe,'throw',side_effect=ValueError):
            for bad in ['20260923','2026-02-30','2026-09-23T10:00','tomorrow']:
                with self.subTest(bad=bad),self.assertRaises(ValueError):service.business_day(bad)

    def test_known_meals_only(self):
        for meal in service.MEALS:self.assertEqual(service.meal_key(meal),meal)
        with patch.object(service.frappe,'throw',side_effect=ValueError),self.assertRaises(ValueError):service.meal_key('anything')

    def test_pagination_validated(self):
        self.assertEqual(service.page_offset('0'),0)
        with patch.object(service.frappe,'throw',side_effect=ValueError):
            for value in [-1,'all',100001]:
                with self.subTest(value=value),self.assertRaises(ValueError):service.page_offset(value)

    def test_inactive_or_guest_cannot_open(self):
        with patch.object(service,'require_account',side_effect=frappe.PermissionError),patch.object(service,'can') as can:
            self.assertFalse(service.has_access());can.assert_not_called()

    def test_teacher_meal_read_alone_is_not_management_entry(self):
        with patch.object(service,'require_account'),patch.object(service,'can',side_effect=lambda dt,action='read':dt==service.CLASS_MEAL):
            self.assertFalse(service.has_access())

    def test_existing_domain_permission_enables_entry_without_role_grant(self):
        with patch.object(service,'require_account'),patch.object(service,'can',side_effect=lambda dt,action='read':dt=='Purchase Order'):
            self.assertTrue(service.has_access())

    def test_unavailable_source_never_queries_rows(self):
        with patch.object(service,'can',return_value=False),patch.object(service.frappe,'get_list') as read:
            result=service.visible_rows('Purchase Order',['name']);self.assertFalse(result['available']);read.assert_not_called()

    def test_bounded_visible_pagination(self):
        with patch.object(service,'can',return_value=True),patch.object(service.frappe,'get_list',return_value=[_dict(name=str(i)) for i in range(21)]) as read:
            result=service.visible_rows('Purchase Order',['name'],offset=20)
            self.assertEqual(len(result['rows']),20);self.assertTrue(result['has_more']);self.assertEqual(read.call_args.kwargs['limit_start'],20)

    def test_unknown_document_kind_rejected(self):
        with patch.object(service.frappe,'throw',side_effect=ValueError),self.assertRaises(ValueError):service.purchase_rows(date(2026,9,23),'User')

    def test_receipts_use_posting_date_not_order_date(self):
        with patch.object(service,'visible_rows',return_value={'rows':[],'available':True,'has_more':False}) as read:
            result=service.purchase_rows(date(2026,9,23),'receipt')
            self.assertEqual(result['date_field'],'posting_date');self.assertEqual(result['start'],'2026-09-17');self.assertIn('posting_date',read.call_args.args[2])

    def test_foreign_warehouse_fails_before_stock_read(self):
        with patch.object(service,'require_access'),patch.object(service,'can',return_value=True),patch.object(service.frappe,'get_list',return_value=[_dict(name='WH-1',company='C')]),patch.object(service,'visible_rows') as bins:
            with self.assertRaises(frappe.PermissionError):service.get_stock('WH-OTHER')
            bins.assert_not_called()

    def test_stock_requires_all_three_read_permissions(self):
        with patch.object(service,'require_access'),patch.object(service,'can',side_effect=lambda dt:dt!='Item'),patch.object(service.frappe,'get_list') as read:
            with self.assertRaises(frappe.PermissionError):service.get_stock()
            read.assert_not_called()

    def test_stock_filters_before_paging_and_does_not_sum_units(self):
        with patch.object(service,'require_access'),patch.object(service,'can',return_value=True),patch.object(service.frappe,'get_list',side_effect=[[_dict(name='WH-1',company='C')],[_dict(name='I1',item_name='item')]]),patch.object(service,'visible_rows',return_value={'rows':[{'item_code':'I1','actual_qty':2,'stock_uom':'Kg'}],'has_more':False}) as bins:
            result=service.get_stock('WH-1')
            self.assertEqual(bins.call_args.args[2]['item_code'],['in',['I1']]);self.assertNotIn('total_qty',result)

    def test_recipe_permission_checked_before_native_helper(self):
        with patch.object(service,'require_access'),patch.object(service,'read_doc',side_effect=frappe.PermissionError),patch('tongjianyun.recipe_storage.get_recipe_detail') as get:
            with self.assertRaises(frappe.PermissionError):service.get_recipe('R')
            get.assert_not_called()

    def test_scene_create_needs_existing_recipe_create_permission(self):
        with patch.object(service,'require_access'),patch.object(service,'can',side_effect=lambda dt, action='read': action != 'create'),patch('tongjianyun.recipe_storage.save_recipe_payload') as save:
            with self.assertRaises(frappe.PermissionError):service.create_recipe_draft({})
            save.assert_not_called()

    def test_scene_draft_cannot_publish_or_overwrite_supplied_identity(self):
        source={'recipe':{'recipeId':'EXISTING','title':'本周食谱','weekStart':'2026-09-21','weekEnd':'2026-09-25','workflowStatus':'已发布'},
            'days':[{'date':'2026-09-21','portions':[{'slot':'lunch','dishes':['米饭'],'dishIngredientRows':[{'dishName':'米饭','ingredient':'大米','amount':40,'unit':'g'}]}]}]}
        clean=service.new_draft_payload(source)
        self.assertTrue(clean['recipe']['recipeId'].startswith('SCENE-20260921-'))
        self.assertEqual(clean['recipe']['workflowStatus'],'草稿')
        self.assertEqual(clean['days'][0]['portions'][0]['label'],'午餐')
        with patch.object(service.frappe,'throw',side_effect=ValueError),self.assertRaises(ValueError):
            service.new_draft_payload({'recipe':source['recipe'],'days':[source['days'][0],source['days'][0]]})

    def test_scene_save_delegates_only_new_draft(self):
        source={'recipe':{'recipeId':'EXISTING','title':'本周食谱','workflowStatus':'已发布'},
            'days':[{'date':'2026-09-21','portions':[]}]}
        with patch.object(service,'require_access'),patch.object(service,'can',return_value=True),patch('tongjianyun.recipe_storage.save_recipe_payload',return_value={'erp_sync':{'recipe':'NEW-DRAFT','status':'blocked'}}) as save:
            result=service.create_recipe_draft(source)
            self.assertEqual(result['name'],'NEW-DRAFT')
            self.assertEqual(save.call_args.args[0]['recipe']['workflowStatus'],'草稿')
            self.assertNotEqual(save.call_args.args[0]['recipe']['recipeId'],'EXISTING')

    def test_scene_import_provenance_comes_from_same_user_job(self):
        source={'recipe':{'title':'校对后的食谱'},'days':[{'date':'2026-09-21','portions':[]}]}
        status={'status':'completed','source_file':'private-week.xlsx','result':{'payload':{'recipe':{'parser':'I-ONE Agent'}}}}
        with patch.object(service,'require_access'),patch.object(service,'can',return_value=True),patch('tongjianyun.recipe_import.get_recipe_import_status',return_value=status) as imported,patch('tongjianyun.recipe_storage.save_recipe_payload',return_value={'erp_sync':{'recipe':'NEW-DRAFT','status':'blocked'}}) as save:
            service.create_recipe_draft(source,'task-1')
            imported.assert_called_once_with('task-1')
            self.assertEqual(save.call_args.args[0]['recipe']['sourceFileName'],'private-week.xlsx')
            self.assertEqual(save.call_args.args[0]['recipe']['parser'],'I-ONE Agent')

    def test_scene_edit_policy_protects_published_linked_and_locked_recipes(self):
        doc=_dict(recipe_id='R-ID',workflow_status='草稿')
        payload={'days':[{'date':'2026-09-21','locked':False}]}
        with patch.object(service,'can',return_value=True),patch('tongjianyun.recipe_storage._recipe_business_links',return_value=[]):
            self.assertEqual(service.recipe_edit_policy(doc,payload)['mode'],'update')
            doc.workflow_status='已发布'
            self.assertEqual(service.recipe_edit_policy(doc,payload)['mode'],'copy')
            doc.workflow_status='草稿';payload['days'][0]['locked']=True
            self.assertEqual(service.recipe_edit_policy(doc,payload)['mode'],'copy')
        payload['days'][0]['locked']=False
        with patch.object(service,'can',return_value=True),patch('tongjianyun.recipe_storage._recipe_business_links',return_value=[{'doctype':'Material Request'}]):
            self.assertEqual(service.recipe_edit_policy(doc,payload)['mode'],'copy')

    def test_scene_edit_rejects_stale_revision_before_any_write(self):
        source={'recipe':{'title':'原食谱'},'days':[{'date':'2026-09-21','portions':[]}]}
        with patch.object(service,'require_access'),patch.object(service,'get_recipe',return_value={'revision':'new','payload':source}),patch.object(service.frappe,'throw',side_effect=ValueError),patch('tongjianyun.recipe_storage.save_recipe_payload') as save:
            with self.assertRaises(ValueError):service.save_recipe_edit('R','old',source)
            save.assert_not_called()

    def test_scene_draft_edit_keeps_identity_and_provenance(self):
        source={'recipe':{'title':'改后草稿','weekStart':'2026-09-21','weekEnd':'2026-09-25'},
            'days':[{'date':'2026-09-21','portions':[{'slot':'lunch','dishes':['米饭'],'dishIngredientRows':[]}]}]}
        previous={'recipe':{'title':'原草稿'},'days':[{'id':'OLD-DAY','date':'2026-09-21','version':3,'portions':[{'slot':'lunch','dishes':['粥'],'dishIngredientRows':[]}]}]}
        doc=_dict(name='R',recipe_id='ORIGINAL',workflow_status='草稿',week_start='2026-09-21',week_end='2026-09-25',source_file_name='source.xlsx',parser='parser',relation_source='import',imported_at='2026-09-20')
        doc.check_permission=MagicMock()
        with patch.object(service,'require_access'),patch.object(service,'get_recipe',return_value={'revision':'rev1','payload':previous}),patch.object(service,'read_doc',return_value=doc),patch.object(service,'recipe_edit_policy',return_value={'mode':'update'}),patch.object(service.frappe.db,'sql',return_value=[{'modified':'rev1'}]),patch.object(service.frappe.db,'exists',return_value='R'),patch('tongjianyun.recipe_storage.save_recipe_payload',return_value={'erp_sync':{'recipe':'R'}}) as save:
            result=service.save_recipe_edit('R','rev1',source)
            sent=save.call_args.args[0]
            self.assertEqual(result['mode'],'update');self.assertEqual(result['name'],'R')
            self.assertEqual(sent['recipe']['recipeId'],'ORIGINAL')
            self.assertEqual(sent['recipe']['sourceFileName'],'source.xlsx')
            self.assertEqual(sent['days'][0]['id'],'OLD-DAY')
            self.assertEqual(sent['days'][0]['version'],4)
            self.assertEqual(sent['days'][0]['portions'][0]['dishes'],['米饭'])

    def test_scene_published_edit_creates_independent_draft(self):
        source={'recipe':{'recipeId':'EXISTING','title':'修订草稿','weekStart':'2026-09-21','weekEnd':'2026-09-25','workflowStatus':'已发布'},
            'days':[{'date':'2026-09-21','portions':[]}]}
        doc=_dict(name='PUBLISHED',recipe_id='EXISTING',workflow_status='已发布')
        doc.check_permission=MagicMock()
        with patch.object(service,'require_access'),patch.object(service,'get_recipe',return_value={'revision':'rev1','payload':source}),patch.object(service,'read_doc',return_value=doc),patch.object(service,'recipe_edit_policy',return_value={'mode':'copy'}),patch.object(service,'can',return_value=True),patch.object(service.frappe.db,'sql',return_value=[{'modified':'rev1'}]),patch('tongjianyun.recipe_storage.save_recipe_payload',return_value={'erp_sync':{'recipe':'NEW'}}) as save:
            result=service.save_recipe_edit('PUBLISHED','rev1',source)
            sent=save.call_args.args[0]
            self.assertEqual(result['mode'],'copy');self.assertEqual(result['name'],'NEW')
            self.assertNotEqual(sent['recipe']['recipeId'],'EXISTING')
            self.assertEqual(sent['recipe']['workflowStatus'],'草稿')
            self.assertEqual(sent['recipe']['relationSource'],'修订自 PUBLISHED')

    def test_create_requires_explicit_confirmation(self):
        with patch.object(service,'require_access'),patch.object(service.frappe,'throw',side_effect=ValueError),patch('tongjianyun.recipe_procurement.create_request') as create:
            with self.assertRaises(ValueError):service.create_demand('R',{}, {},'t',0)
            create.assert_not_called()

    def test_create_rejects_existing_demand_and_stale_preview(self):
        for token,existing in [('stale',[]),('current',[{'name':'MR1'}])]:
            with self.subTest(token=token),patch.object(service,'require_access'),patch.object(service,'read_doc',return_value=_dict(name='R')),patch.object(service.frappe.db,'get_value'),patch.object(service,'demand_arguments',return_value={'recipe':'R'}),patch('tongjianyun.recipe_procurement.preview',return_value={'token':'current'}),patch('tongjianyun.recipe_procurement.revision_impact',return_value={'requests':existing}),patch.object(service.frappe,'throw',side_effect=ValueError),patch('tongjianyun.recipe_procurement.create_request') as create:
                with self.assertRaises(ValueError):service.create_demand('R',{}, {},token,1)
                create.assert_not_called()

    def test_only_creates_request_never_completes_financial_cycle(self):
        with patch.object(service,'require_access'),patch.object(service,'read_doc',return_value=_dict(name='R')),patch.object(service.frappe.db,'get_value'),patch.object(service,'demand_arguments',return_value={'recipe':'R','include_history':0}),patch('tongjianyun.recipe_procurement.preview',return_value={'token':'current'}),patch('tongjianyun.recipe_procurement.revision_impact',return_value={'requests':[]}),patch('tongjianyun.recipe_procurement.create_request',return_value={'name':'MR-DRAFT'}) as create,patch('tongjianyun.recipe_procurement.complete_purchase_cycle') as cycle:
            self.assertEqual(service.create_demand('R',{}, {},'current',1)['name'],'MR-DRAFT');cycle.assert_not_called();self.assertEqual(create.call_args.kwargs['confirmed'],1)

    def test_read_functions_do_not_call_daily_initialiser(self):
        source=Path(service.__file__).read_text()
        for forbidden in ['get_daily_meal_confirmation(', 'refresh_confirmation(', 'recipe_execution.start(', 'create_purchase(', 'ignore_permissions=True', 'set_user(']:
            self.assertNotIn(forbidden,source)

    def test_protected_health_not_in_broad_read_model(self):
        source=Path(service.__file__).read_text()
        self.assertNotIn('medical_history',source);self.assertNotIn('allergy_history',source);self.assertNotIn('contact_phone',source)

    def test_meal_writes_delegate_original_scope_and_lock_validation(self):
        with patch.object(service,'require_access'),patch('tongjianyun.classroom.save_meals',return_value={'saved':True}) as save:
            self.assertTrue(service.save_meals('C1','2026-09-23',[],confirm=0)['saved'])
            self.assertEqual(save.call_args.kwargs['workspace'],'business')

    def test_new_role_entry_only_routes_when_present(self):
        model={'profiles':[{'id':'meals','enabled':True}], 'groups':[]}
        self.assertEqual(entry.resolve_entry(model)['destination'],'/tongjianyun-meal-scene')
        with self.assertRaises(frappe.PermissionError):entry.resolve_entry({'profiles':[], 'groups':[]},'meals')

    def test_teacher_only_classification_is_preserved(self):
        assignment={'instructor_linked':True,'employee_linked':True,'can_read_classroom':True,'groups':[{'name':'C1'}]}
        result=entry.choose_profiles('teacher',['Instructor'],assignment,False)
        self.assertEqual([r['id'] for r in result],['teacher'])


if __name__=='__main__': unittest.main()
