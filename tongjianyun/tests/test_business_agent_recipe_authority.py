"""Real task store, reader and authority with isolated native Frappe doubles.

No server, model, credentials or real recipe is touched. FreshFrappeChecks uses
its actual Context()/connect(set_admin_as_user=False)/destroy implementation;
native permissions, query rows and recipe snapshots are explicit test doubles.
The recipe_week canonicalizer is the original meal_views.selection function.
"""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import uuid

import tongjianyun
from tongjianyun import business_agent_tasks as tasks, business_agent_recipes as recipes
from tongjianyun.tests import test_business_agent_write_adapter as fixtures
from tongjianyun.tests.test_business_agent_recipes import original_function, snapshot


class RecipeAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.native = fixtures.NativeWriteAdapterTests(methodName='runTest')
        self.addCleanup(self.native.doCleanups)
        self.native.setUp()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.frappe, self.tools = self.native.frappe, self.native.tools
        self.site, self.owner = self.native.site, self.native.owner
        # Load a fresh unpatched authority registry, NOT the fixture's reduced
        # write test registry that replaces _projection and _check_scope.
        self.authority = fixtures.load_private(self.stack, 'business_agent_authority.py',
            {'frappe': self.frappe, 'tongjianyun.business_agent_tools': self.tools})
        self.readable = {'R1', 'R2'}
        self.discoverable = ['R1']
        self.allowed_types = set(recipes.FIELDS)
        self.allowed_fields = {name: set(fields) for name, fields in recipes.FIELDS.items()}
        self.detail_allowed, self.calendar_allowed = True, True
        self.recipe_snapshot = snapshot()
        self.recipe_contexts = []
        self.scene = ModuleType('tongjianyun.meal_scene')
        self.scene.get_recipe = MagicMock(side_effect=self.get_recipe)
        self.scene.require_recipe_create = MagicMock()
        self.storage = SimpleNamespace()
        self.stack.enter_context(patch.object(recipes, '_services',
            return_value=(self.frappe, self.authority, self.scene, self.storage)))
        self.project = ModuleType('tongjianyun.frappe_project_views')
        self.project._doctype = self.doctype
        self.project.module_apps = lambda: {'Recipes': 'tongjianyun'}
        self.scene_access = ModuleType('tongjianyun.scene_access')
        self.scene_access.require_view_access = MagicMock(side_effect=self.view_access)
        self.model = ModuleType('frappe.model')
        self.model.get_permitted_fields = lambda dt, **kw: self.allowed_fields.get(dt, set())
        self.views = ModuleType('tongjianyun.meal_views')
        self.nutrition = ModuleType('tongjianyun.meal_nutrition_view')
        self.nutrition.FIELDS, self.nutrition.nutrition_selection = set(), None
        self.stock = ModuleType('tongjianyun.stock_reconciliation')
        self.stock.FIELDS, self.stock.selection = set(), None
        modules = {'frappe.model': self.model, 'tongjianyun.frappe_project_views': self.project,
                   'tongjianyun.scene_access': self.scene_access, 'tongjianyun.meal_views': self.views,
                   'tongjianyun.meal_nutrition_view': self.nutrition, 'tongjianyun.stock_reconciliation': self.stock}
        self.stack.enter_context(patch.dict(sys.modules, modules))
        self.frappe.throw = lambda text: (_ for _ in ()).throw(ValueError(text))
        self.views.selection = original_function('meal_views.py', 'selection', {
            'json': json, 'frappe': self.frappe, 'PROPOSAL_VIEWS': {}, 'PROPOSAL_FIELDS': set(),
            'VIEWS': {'recipe_week': '本周食谱'}, 'BUSINESS_FIELDS': set(), 'PROJECT_FIELDS': set(),
            'PROJECT_VIEWS': {}, 'BUSINESS_VIEWS': {}, 'business_day': date.fromisoformat,
            'meal_key': lambda value: value if value in self.tools.MEALS else self.frappe.throw('invalid meal')})
        self.frappe.get_list = MagicMock(side_effect=self.get_list)
        self.frappe.get_doc.side_effect = self.get_doc
        self.frappe.has_permission.side_effect = lambda dt, action: dt in self.allowed_types and action == 'read'
        runner = self.authority.FreshFrappeChecks(self.site, self.native.temp)
        self.adapter = self.authority.FrappeBusinessAuthority(self.site, run_check=runner)
        directory = Path(self.native.temp) / 'recipe-tasks'
        directory.mkdir(mode=0o700)
        self.store = tasks.BusinessTaskStore(directory, self.site, authorize=self.adapter,
            observe_execution=lambda identity, claim: tasks.ExecutionObservation(claim, 'running', 0),
            observe_queue=lambda job: tasks.QueueObservation(job, 'present'))
        self.identity = tasks.TaskIdentity(self.site, self.owner, str(uuid.uuid4()))
        self.store.create(self.owner, self.identity.task_id, '读取本周食谱')
        ticket = self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(ticket)
        self.claim = self.store.claim(self.identity, ticket.job_id)
        self.reader = recipes.BusinessRecipes(self.adapter, self.store)

    def doctype(self, name, modules):
        if name not in self.allowed_types:
            raise self.frappe.PermissionError('native DocType denied')
        return SimpleNamespace(issingle=False, name=name)

    def get_list(self, doctype, **kwargs):
        name = kwargs['filters'].get('name')
        if name is not None:
            return [name] if name in self.readable else []
        return [{'name': name} for name in self.discoverable if name in self.readable]

    def get_doc(self, doctype, name):
        if name not in self.readable:
            raise self.frappe.PermissionError('native document unavailable')
        return self.native.document

    def get_recipe(self, name):
        local = self.native.local.get()
        self.assertEqual(local.site, self.site)
        self.assertEqual(local.session.user, self.owner)
        self.assertIsNot(local, self.native.outer)
        self.assertIsNot(local.db, self.native.outer.db)
        self.recipe_contexts.append(local.db)
        if name not in self.readable or not self.detail_allowed:
            raise self.frappe.PermissionError('original whole-recipe policy denied')
        result = deepcopy(self.recipe_snapshot)
        result['name'], result['payload']['recipe']['recipeId'] = name, name
        return result

    def view_access(self, name):
        self.assertEqual(name, 'recipe_week')
        if not self.calendar_allowed:
            raise self.frappe.PermissionError('original calendar denied')

    def read(self, **kwargs):
        return self.reader.dispatch(self.claim, 'recipe_read', {'day': '2026-09-24', **kwargs})

    def assert_blocked_replay(self):
        with self.assertRaises(PermissionError):
            self.store.events(self.identity)
        with self.assertRaises(PermissionError):
            self.store.history(self.owner)
        with self.store._transaction() as db:
            self.assertEqual(db.execute('SELECT status FROM tasks').fetchone()['status'], 'stopping')

    def test_actual_reader_registers_native_aggregate_projection_and_calendar_before_event(self):
        result = self.read()
        self.assertEqual(result['recipe'], 'R1')
        scopes = self.store.required_scopes(self.identity)
        self.assertIn({'kind': 'recipe', 'recipe': 'R1'}, scopes)
        self.assertIn({'kind': 'capability', 'name': recipes.PROJECTION}, scopes)
        self.assertIn({'kind': 'view', 'selection': {'view': 'recipe_week', 'day': '2026-09-24', 'meal': 'lunch'}}, scopes)
        self.assertTrue(any(event['kind'] == 'view' for event in self.store.events(self.identity)))
        self.assertTrue(self.recipe_contexts)
        self.assertGreater(len({id(db) for db in self.recipe_contexts}), 1)
        self.assertIs(self.native.local.get(), self.native.outer)
        self.assertEqual(self.native.outer.session.user, 'outer-user')
        self.assertEqual(len(self.native.opened), len(self.native.destroyed))
        for db in self.native.opened:
            db.commit.assert_not_called()
        for call in self.frappe.connect.call_args_list:
            self.assertEqual(call.kwargs, {'set_admin_as_user': False})

    def test_parent_query_visibility_revocation_stops_old_recipe_history(self):
        self.read()
        self.readable.remove('R1')
        self.assertTrue(self.adapter(self.identity, [recipes.source_scope('R2')]))
        self.assert_blocked_replay()

    def test_detail_policy_revocation_stops_history_despite_parent_still_readable(self):
        self.read()
        self.detail_allowed = False
        self.assertTrue(self.adapter(self.identity, [self.authority._read(recipes.RECIPE, 'R1')]))
        self.assert_blocked_replay()

    def test_ingredient_field_revocation_stops_empty_and_nonempty_recipe_history(self):
        for empty in (False, True):
            with self.subTest(empty=empty):
                self.discoverable = [] if empty else ['R1']
                self.allowed_fields[recipes.INGREDIENT].add('amount')
                if empty:
                    self.store.cancel(self.identity)
                    self.identity = replace(self.identity, task_id=str(uuid.uuid4()))
                    self.store.create(self.owner, self.identity.task_id, '空查询也复核权限')
                    ticket = self.store.take_dispatch(self.identity)
                    self.store.acknowledge_dispatch(ticket)
                    self.claim = self.store.claim(self.identity, ticket.job_id)
                self.read()
                self.allowed_fields[recipes.INGREDIENT].remove('amount')
                self.assertFalse(self.adapter(self.identity, [{'kind': 'capability', 'name': recipes.PROJECTION}]))
                self.assert_blocked_replay()

    def test_empty_discovery_does_not_assert_global_zero_or_register_fictional_recipe(self):
        self.discoverable = []
        result = self.read()
        self.assertIsNone(result['recipe'])
        self.assertFalse(result['visible_recipe_found'])
        self.assertIn('不证明全站没有', result['note'])
        self.assertEqual(self.store.required_scopes(self.identity), [{'kind': 'capability', 'name': recipes.PROJECTION}])
        self.scene.get_recipe.assert_not_called()

    def test_missing_explicit_recipe_or_native_error_never_becomes_empty_result(self):
        for failure in (self.frappe.PermissionError('private denied'), RuntimeError('private DB failure')):
            with self.subTest(failure=type(failure)), patch.object(self.scene, 'get_recipe', side_effect=failure):
                with self.assertRaises(type(failure)):
                    self.read(recipe='R1')
        self.assertEqual(self.store.required_scopes(self.identity), [])
        self.assertFalse(any(event['kind'] == 'view' for event in self.store.events(self.identity)))
        self.readable.remove('R1')
        self.assertFalse(self.adapter(self.identity, [recipes.source_scope('R1')]))

    def test_recipe_week_uses_real_canonical_schema_and_original_gate_not_roster_projection(self):
        choice = {'view': 'recipe_week', 'day': '2026-09-24', 'meal': 'lunch'}
        scopes = self.adapter.view_scopes(self.identity, choice)
        self.assertEqual(scopes, ({'kind': 'view', 'selection': choice}, {'kind': 'capability', 'name': recipes.PROJECTION}))
        self.scene_access.require_view_access.assert_called_with('recipe_week')
        self.calendar_allowed = False
        with self.assertRaises(self.frappe.PermissionError):
            self.adapter.view_scopes(self.identity, choice)
        for extra in ('recipe', 'group', 'revision', 'offset', 'owner', 'payload'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.tools._validate_arguments('business_view', {'selection': {**choice, extra: 'x'}})

    def test_parent_content_update_preserves_aggregate_authority_but_invalidates_mixed_page(self):
        first = self.read(page_size=1)
        self.recipe_snapshot['payload']['days'][0]['portions'][0]['dishIngredientRows'][0]['amount'] = 80
        self.assertTrue(self.adapter(self.identity, self.store.required_scopes(self.identity)))
        with self.assertRaisesRegex(ValueError, 'content changed'):
            self.read(offset=1, content_revision=first['content_revision'])
        # The exact aggregate contract never grants arbitrary missing/deleted
        # detail documents, even though native edits rebuild those IDs.
        self.assertFalse(self.adapter(self.identity, [self.authority._read(recipes.DISH, 'deleted-detail')]))

    def test_projection_and_account_fail_closed_before_model_or_calendar_delivery(self):
        self.allowed_types.remove(recipes.DISH)
        with self.assertRaises(self.frappe.PermissionError):
            self.read()
        self.allowed_types.add(recipes.DISH)
        self.native.account['enabled'] = 0
        with self.assertRaises(PermissionError):
            self.read()
        self.scene.get_recipe.assert_not_called()
        self.scene_access.require_view_access.assert_not_called()

    def test_full_union_preserves_previously_read_recipe_across_later_recipe(self):
        self.read(recipe='R1')
        self.read(recipe='R2')
        self.assertIn(recipes.source_scope('R1'), self.store.required_scopes(self.identity))
        self.assertIn(recipes.source_scope('R2'), self.store.required_scopes(self.identity))
        self.readable.remove('R1')
        with self.assertRaises(PermissionError):
            self.read(recipe='R2')
        self.assert_blocked_replay()

    def test_revocation_after_native_read_prevents_registration_and_result_delivery(self):
        def read_then_revoke(name):
            result = self.get_recipe(name)
            self.readable.remove(name)
            return result
        self.scene.get_recipe.side_effect = read_then_revoke
        with self.assertRaises(self.frappe.PermissionError):
            self.read(recipe='R1')
        self.assertEqual(self.store.required_scopes(self.identity), [])
        self.assertFalse(any(event['kind'] == 'view' for event in self.store.events(self.identity)))

    def test_unknown_recipe_projection_and_cross_site_identity_do_not_enter_native_reader(self):
        self.assertFalse(self.adapter(self.identity, [{'kind': 'capability', 'name': recipes.PROJECTION + ':bypass'}]))
        self.assertFalse(self.adapter(replace(self.identity, site='other.localhost'), [recipes.source_scope('R1')]))
        self.assertFalse(self.adapter(replace(self.identity, mode='admin_project'), [recipes.source_scope('R1')]))
        self.scene.get_recipe.assert_not_called()

    def test_legacy_tool_dispatch_does_not_route_recipe_operations_to_meals(self):
        for tool in ('recipe_read', 'recipe_save'):
            with (self.subTest(tool=tool), patch.object(self.tools, '_meal_read') as meal_read,
                    patch.object(self.tools, '_write') as write, self.assertRaises(ValueError)):
                self.tools.dispatch(None, tool, {'day': '2026-09-24'})
            meal_read.assert_not_called()
            write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
