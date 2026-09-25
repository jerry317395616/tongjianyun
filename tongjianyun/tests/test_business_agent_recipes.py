"""Pure finite-contract + fresh-context/native-service doubles, not live QA.

No Frappe server, model, real recipe, role, queue or database is changed. Native
transaction lifecycle is the production implementation loaded against explicit
Context/DB doubles; original history/weekly guards are also exercised directly.
Shared ledger/authority registry integration is intentionally a separate task.
"""
import ast
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import MagicMock, patch
import uuid

from tongjianyun import business_agent_recipes as recipes
from tongjianyun.business_agent_tasks import TaskIdentity, WorkerClaim
from tongjianyun.tests import test_business_agent_write_adapter as native_tests


PAYLOAD = {'recipe': {'title': '合成周食谱', 'weekStart': '2026-09-21', 'weekEnd': '2026-09-25'},
           'days': [{'date': '2026-09-21', 'day': '星期一', 'portions': [
               {'slot': 'lunch', 'dishes': ['米饭', '牛奶'], 'dishIngredientRows': [
                   {'dishName': '米饭', 'ingredient': '大米', 'amount': 50, 'unit': 'g'},
                   {'dishName': '牛奶', 'ingredient': '纯牛奶', 'amount': 200, 'unit': 'ml'}]}]}]}
CREATE = {'day': '2026-09-24', 'recipe': None, 'revision': '', 'payload': PAYLOAD}
REVISION = '2026-09-25 11:33:01.836028'


def snapshot(name='R1', payload=None):
    result = deepcopy(payload or PAYLOAD)
    result['recipe'].update(recipeId=name, revision=REVISION, workflowStatus='草稿')
    for day in result['days']:
        day['locked'] = False
    return {'name': name, 'revision': REVISION, 'payload': result,
            'edit': {'mode': 'update'}}


def original_function(filename, function, namespace):
    """Run the actual selected pure/native guard body, never an imitation."""
    path = Path(__file__).parents[1] / filename
    parsed = ast.parse(path.read_text(encoding='utf-8'))
    node = next(item for item in parsed.body if isinstance(item, ast.FunctionDef) and item.name == function)
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), namespace)
    return namespace[function]


class RecipeContractTests(unittest.TestCase):
    def test_detached_payload_retains_quantities_units_dates_and_order(self):
        source = deepcopy(CREATE)
        clean = recipes.normalize_arguments('recipe_save', source)
        self.assertEqual(clean['payload']['days'][0]['portions'][0]['dishIngredientRows'][1]['unit'], 'ml')
        self.assertEqual(clean['payload']['days'][0]['portions'][0]['dishIngredientRows'][1]['amount'], 200)
        source['payload']['days'][0]['portions'][0]['dishes'].clear()
        self.assertEqual(clean['payload']['days'][0]['portions'][0]['dishes'], ['米饭', '牛奶'])

    def test_missing_unknown_unit_is_not_guessed_or_converted(self):
        for unit in (None, '', True):
            payload = deepcopy(PAYLOAD)
            payload['days'][0]['portions'][0]['dishIngredientRows'][0]['unit'] = unit
            with self.subTest(unit=unit), self.assertRaises(ValueError):
                recipes.normalize_payload(payload)
        payload = deepcopy(PAYLOAD)
        row = payload['days'][0]['portions'][0]['dishIngredientRows'][0]
        row['unit'] = '份'
        clean = recipes.normalize_payload(payload)
        self.assertEqual(clean['days'][0]['portions'][0]['dishIngredientRows'][0]['unit'], '份')
        # Explicit units unknown to gram conversion remain literal native units.

    def test_finite_quantities_and_original_native_limits(self):
        for amount in (True, '10', float('nan'), float('inf'), -1, 100001):
            payload = deepcopy(PAYLOAD)
            payload['days'][0]['portions'][0]['dishIngredientRows'][0]['amount'] = amount
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                recipes.normalize_payload(payload)
        payload = deepcopy(PAYLOAD)
        rows = payload['days'][0]['portions'][0]['dishIngredientRows']
        rows[:] = [rows[0]] * 301
        with self.assertRaises(ValueError):
            recipes.normalize_payload(payload)

    def test_reject_model_identity_lifecycle_metadata_and_publication(self):
        for key in ('actor', 'owner', 'site', 'operation_id', 'publish', 'method', 'sql'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                recipes.normalize_arguments('recipe_save', {**CREATE, key: 'Administrator'})
        for key in ('recipeId', 'revision', 'workflowStatus', 'sourceFileName', 'importedAt'):
            payload = deepcopy(PAYLOAD)
            payload['recipe'][key] = '已发布'
            with self.subTest(key=key), self.assertRaises(ValueError):
                recipes.normalize_payload(payload)
        payload = deepcopy(PAYLOAD)
        payload['days'][0]['locked'] = False
        with self.assertRaises(ValueError):
            recipes.normalize_payload(payload)

    def test_week_not_rolling_seven_days_and_target_must_match(self):
        self.assertEqual(recipes.week_bounds('2026-09-24'), ('2026-09-21', '2026-09-27'))
        for change in ({'day': '2026-09-28'}, {'day': '20260924'}, {'day': '2026-02-30'}):
            with self.assertRaises(ValueError):
                recipes.normalize_arguments('recipe_save', {**CREATE, **change})
        payload = deepcopy(PAYLOAD)
        payload['recipe'].update(weekStart='2026-09-25', weekEnd='2026-09-28')
        with self.assertRaises(ValueError):
            recipes.normalize_payload(payload)

    def test_native_revision_is_mandatory_for_edit_and_empty_only_for_create(self):
        for values in ({'recipe': 'R1', 'revision': ''}, {'recipe': None, 'revision': REVISION}):
            with self.assertRaises(ValueError):
                recipes.normalize_arguments('recipe_save', {**CREATE, **values})
        self.assertEqual(recipes.normalize_arguments('recipe_save', {**CREATE, 'recipe': 'R1', 'revision': REVISION})['revision'], REVISION)

    def test_resource_keys_are_calendar_week_wide_not_owner_or_task(self):
        self.assertEqual(recipes.resource_keys(CREATE), ('["recipe_week","2026-09-21"]',))
        self.assertEqual(recipes.resource_keys({**CREATE, 'day': '2026-09-21'}), recipes.resource_keys(CREATE))
        edited = {**CREATE, 'recipe': 'R1', 'revision': REVISION}
        self.assertIn('["recipe_week","2026-09-21"]', recipes.resource_keys(edited))
        self.assertIn('["recipe","R1"]', recipes.resource_keys(edited))

    def test_same_operation_replay_keeps_exact_target_different_operation_cannot_collide(self):
        operation = str(uuid.uuid4())
        first = recipes.write_plan('qa.localhost', operation, CREATE)
        self.assertEqual(first.target_recipe, recipes.write_plan('qa.localhost', operation, CREATE).target_recipe)
        self.assertNotEqual(first.target_recipe, recipes.write_plan('other.localhost', operation, CREATE).target_recipe)
        self.assertNotEqual(first.target_recipe, recipes.write_plan('qa.localhost', str(uuid.uuid4()), CREATE).target_recipe)
        self.assertNotIn(operation, first.target_recipe)
        for bad in (None, 'task-id', 'a' * 64):
            with self.assertRaises(ValueError):
                recipes.write_plan('qa.localhost', bad, CREATE)

    def test_plan_is_immutable_and_model_arguments_cannot_supply_target(self):
        plan = recipes.write_plan('qa.localhost', str(uuid.uuid4()), CREATE)
        args = plan.arguments
        args['payload']['recipe']['title'] = 'changed'
        self.assertEqual(plan.arguments['payload']['recipe']['title'], PAYLOAD['recipe']['title'])
        with self.assertRaises(Exception):
            plan.operation_id = 'changed'

    def test_aggregate_source_is_only_exact_recipe_identity(self):
        self.assertEqual(recipes.normalize_source({'kind': 'recipe', 'recipe': 'R1'}), {'kind': 'recipe', 'recipe': 'R1'})
        for value in ({'kind': 'document', 'recipe': 'R1'}, {'kind': 'recipe', 'recipe': 'R1', 'doctype': 'File'},
                      {'kind': 'recipe', 'recipe': 'R1', 'revision': REVISION}, {'kind': 'recipe', 'recipe': '../secret\n'}):
            with self.assertRaises(ValueError):
                recipes.normalize_source(value)


class RecipeReadTests(unittest.TestCase):
    def setUp(self):
        self.site, self.owner = 'qa.localhost', 'caterer@example.invalid'
        self.claim = WorkerClaim(TaskIdentity(self.site, self.owner, str(uuid.uuid4())), str(uuid.uuid4()), 't' * 43)
        self.state = {'site': self.site, 'owner': self.owner, 'task_id': self.claim.identity.task_id,
                      'mode': 'business', 'status': 'running', 'cancel_requested': '0'}
        self.store = SimpleNamespace(site=self.site, binding_state=MagicMock(side_effect=lambda claim: dict(self.state)), emit=MagicMock())
        self.scopes = []
        self.trace = []
        self.frappe = SimpleNamespace(get_list=MagicMock(return_value=[{'name': 'R1'}]))
        self.gates = SimpleNamespace(_account=MagicMock(), _doctype=MagicMock(), _fields=MagicMock(),
            _document=MagicMock(), ReadSet=lambda scopes: SimpleNamespace(scopes=scopes))
        self.scene = SimpleNamespace(get_recipe=MagicMock(return_value=snapshot()))
        def register(store, claim, sources):
            self.scopes.extend(sources.scopes)
            self.trace.append('registered')
        self.authority = SimpleNamespace(site=self.site, run_check=lambda owner, callback: callback(),
            register_read=MagicMock(side_effect=register))
        self.store.emit.side_effect = lambda *args: self.trace.append('view')
        self.patch = patch.object(recipes, '_services', return_value=(self.frappe, self.gates, self.scene, None))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.reader = recipes.BusinessRecipes(self.authority, self.store)

    def read(self, **kwargs):
        return self.reader.dispatch(self.claim, 'recipe_read', {'day': '2026-09-24', **kwargs})

    def test_complete_units_and_registration_precede_model_view(self):
        result = self.read()
        self.assertEqual(result['recipe'], 'R1')
        self.assertEqual(result['ingredient_count'], 2)
        self.assertEqual(result['dishes'][1]['ingredients'], [{'ingredient': '纯牛奶', 'amount': 200, 'unit': 'ml'}])
        self.assertTrue(result['complete'])
        self.assertIn(recipes.source_scope('R1'), self.scopes)
        self.assertIn({'kind': 'capability', 'name': recipes.PROJECTION}, self.scopes)
        self.assertEqual(self.trace[-1], 'view')
        self.gates._document.assert_called_once_with(recipes.RECIPE, 'R1', ['read'])

    def test_every_consumed_native_field_requires_projection_permission(self):
        self.read()
        for dt, fields in recipes.FIELDS.items():
            self.gates._fields.assert_any_call(dt, fields)
        self.gates._fields.side_effect = PermissionError('ingredient amount field revoked')
        with self.assertRaises(PermissionError):
            self.read()

    def test_page_preserves_whole_dish_and_requires_content_pin_for_next(self):
        first = self.read(page_size=1)
        self.assertFalse(first['complete']); self.assertTrue(first['has_more'])
        self.assertEqual(first['next_offset'], 1)
        self.assertEqual(len(first['dishes'][0]['ingredients']), 1)
        with self.assertRaises(ValueError):
            self.read(offset=1)
        second = self.read(offset=1, content_revision=first['content_revision'])
        self.assertEqual(second['dishes'][0]['dish'], '牛奶')
        self.assertFalse(second['has_more']); self.assertFalse(second['complete'])

    def test_page_byte_limit_never_silently_drops_half_a_dish(self):
        with patch.object(recipes, 'MAX_PAGE_BYTES', 1), self.assertRaisesRegex(ValueError, 'complete dish'):
            self.read()
        self.store.emit.assert_not_called()

    def test_missing_ingredients_are_unknown_not_zero_and_unknown_units_remain_literal(self):
        data = snapshot()
        rows = data['payload']['days'][0]['portions'][0]['dishIngredientRows']
        rows.pop()
        rows[0]['unit'] = '份'
        self.scene.get_recipe.return_value = data
        result = self.read()
        self.assertEqual(result['dishes'][0]['ingredients'][0]['unit'], '份')
        self.assertFalse(result['dishes'][1]['ingredients_recorded'])
        self.assertEqual(result['dishes'][1]['ingredients'], [])
        self.assertIn('未登记食材不是零用量', result['note'])

    def test_changed_detail_even_unchanged_parent_modified_rejects_mixed_pages(self):
        first = self.read(page_size=1)
        data = snapshot()
        data['payload']['days'][0]['portions'][0]['dishIngredientRows'][1]['amount'] = 180
        self.scene.get_recipe.return_value = data
        with self.assertRaisesRegex(ValueError, 'content changed'):
            self.read(offset=1, content_revision=first['content_revision'])

    def test_no_recipe_only_means_no_visible_current_recipe_and_empty_scope_still_registered(self):
        self.frappe.get_list.return_value = []
        result = self.read()
        self.assertIsNone(result['recipe'])
        self.assertIn('不证明全站没有', result['note'])
        self.scene.get_recipe.assert_not_called(); self.store.emit.assert_not_called()
        self.assertEqual(self.scopes, [{'kind': 'capability', 'name': recipes.PROJECTION}])

    def test_duplicate_week_refuses_arbitrary_choice(self):
        self.frappe.get_list.return_value = [{'name': 'R1'}, {'name': 'R2'}]
        with self.assertRaisesRegex(ValueError, 'multiple visible'):
            self.read()
        self.scene.get_recipe.assert_not_called(); self.store.emit.assert_not_called()

    def test_exact_target_never_falls_back_to_later_week_recipe(self):
        self.scene.get_recipe.side_effect = PermissionError('old target is gone')
        with self.assertRaises(PermissionError):
            self.read(recipe='OLD')
        self.frappe.get_list.assert_not_called()
        self.scene.get_recipe.assert_called_once_with('OLD')

    def test_archived_or_other_week_refuses_current_week_claim(self):
        for modify in ({'workflowStatus': '已归档'}, {'weekStart': '2026-09-28', 'weekEnd': '2026-10-02'}):
            data = snapshot(); data['payload']['recipe'].update(modify)
            self.scene.get_recipe.return_value = data
            with self.assertRaises(ValueError):
                self.read(recipe='R1')
        self.store.emit.assert_not_called()

    def test_cancel_or_source_revocation_suppresses_delivery(self):
        self.state['cancel_requested'] = '1'
        with self.assertRaises(PermissionError):
            self.read()
        self.scene.get_recipe.assert_not_called()
        self.state['cancel_requested'] = '0'
        self.authority.register_read.side_effect = PermissionError('source revoked')
        with self.assertRaises(PermissionError):
            self.read()
        self.store.emit.assert_not_called()

    def test_aggregate_check_reuses_exact_whole_recipe_and_not_generic_document(self):
        recipes.check_source(recipes.source_scope('R1'))
        self.scene.get_recipe.assert_called_once_with('R1')
        self.gates._document.assert_called_once_with(recipes.RECIPE, 'R1', ['read'])
        self.scene.get_recipe.side_effect = PermissionError('one native detail row hidden')
        with self.assertRaises(PermissionError):
            recipes.check_source(recipes.source_scope('R1'))

    def test_original_history_checks_parent_and_complete_current_reader_before_snapshot(self):
        doc = SimpleNamespace(name='R1', check_permission=MagicMock())
        version = SimpleNamespace(ref_doctype=recipes.RECIPE, docname='R1', data=json.dumps({'recipe_snapshot': {'old': 'data'}}), name='V1', creation='now')
        frappe = SimpleNamespace(get_doc=MagicMock(side_effect=lambda dt, name: doc if dt == recipes.RECIPE else version),
                                 throw=lambda *args: (_ for _ in ()).throw(PermissionError()), PermissionError=PermissionError)
        scene_module = ModuleType('tongjianyun.meal_scene')
        scene_module.get_recipe = MagicMock(side_effect=PermissionError('one current detail is hidden'))
        namespace = {'Any': object, '_require_login': lambda: None, '_get_recipe_name': lambda name: name,
                     'RECIPE_DOCTYPE': recipes.RECIPE, 'frappe': frappe, 'json': json}
        read_history = original_function('recipe_storage.py', 'get_recipe_history', namespace)
        with patch.dict(sys.modules, {'tongjianyun.meal_scene': scene_module}):
            with self.assertRaises(PermissionError):
                read_history('R1', 'V1')
            doc.check_permission.assert_called_with('read')
            scene_module.get_recipe.assert_called_once_with('R1')
            scene_module.get_recipe.side_effect = None
            self.assertEqual(read_history('R1', 'V1')['payload'], {'old': 'data'})
            version.docname = 'OTHER'
            with self.assertRaises(PermissionError):
                read_history('R1', 'V1')


class RecipeNativeTransactionTests(unittest.TestCase):
    def setUp(self):
        # Reuse the explicit Context/DB fixture, not its unrelated test methods.
        self.base = native_tests.NativeWriteAdapterTests('test_factory_is_detached_pure_and_never_opens_request_db')
        self.base.setUp(); self.addCleanup(self.base.doCleanups)
        b = self.base
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.operation = str(uuid.uuid4())
        self.args = deepcopy(CREATE)
        self.edit = {**deepcopy(CREATE), 'recipe': 'R1', 'revision': REVISION}
        self.original_snapshot = snapshot()
        self.scene = SimpleNamespace(require_recipe_create=MagicMock(), get_recipe=MagicMock(side_effect=lambda name: self.current_snapshot(name)),
            new_draft_payload=MagicMock(side_effect=lambda value: {'recipe': {**deepcopy(value['recipe']), 'recipeId': 'ORIGINAL-RANDOM', 'workflowStatus': '草稿'}, 'days': deepcopy(value['days'])}),
            save_recipe_edit=MagicMock(side_effect=self.edit_native))
        self.saved, self.contexts = [], []
        self.storage = SimpleNamespace(save_recipe_payload=MagicMock(side_effect=self.create_native))
        self.stack.enter_context(patch.object(recipes, '_native_adapter_types', return_value=(b.module.FrappeWriteAdapter, b.module.NativeWriteTransaction)))
        self.stack.enter_context(patch.object(recipes, '_services', return_value=(b.frappe, b.authority, self.scene, self.storage)))
        self.stack.enter_context(patch.object(b.authority, '_doctype'))
        self.stack.enter_context(patch.object(b.authority, '_fields'))
        self.stack.enter_context(patch.object(b.authority, '_document'))
        self.adapter = recipes.RecipeWriteAdapter(b.site, b.temp, store=b.store)

    def current_snapshot(self, name):
        self.contexts.append(self.base.local.get().db)
        result = deepcopy(self.original_snapshot)
        result['name'] = name
        result['payload']['recipe']['recipeId'] = name
        return result

    def create_native(self, payload, *, commit):
        self.assertIs(commit, False)
        self.saved.append((deepcopy(payload), self.base.local.get().db, self.base.local.get().session.user))
        return {'recipe': {'workflowStatus': '草稿'}, 'erp_sync': {'recipe': payload['recipe']['recipeId'], 'status': 'queued'}}

    def edit_native(self, name, revision, payload):
        if revision != self.original_snapshot['revision']:
            raise ValueError('Original native revision conflict')
        self.saved.append((deepcopy(payload), self.base.local.get().db, self.base.local.get().session.user))
        return {'name': name, 'status': '草稿', 'mode': 'update', 'source': name, 'sync': {'recipe': name, 'status': 'queued'}}

    def tx(self, args=None, operation=None):
        tx = self.adapter.transaction_factory(self.base.claim, 'recipe_save', args or self.args,
                                              operation_id=operation or self.operation)
        self.addCleanup(tx.close)
        return tx

    def test_factory_requires_trusted_operation_and_opens_no_connection(self):
        with self.assertRaises(ValueError):
            self.adapter.transaction_factory(self.base.claim, 'recipe_save', self.args)
        tx = self.tx()
        self.base.frappe.connect.assert_not_called()
        self.base.store.binding_state.assert_not_called()
        self.assertEqual(tx.recipe_plan.operation_id, self.operation)

    def test_create_uses_native_validation_fixed_identity_and_never_commits_in_save(self):
        tx = self.tx(); tx.begin(); receipt = tx.save()
        self.scene.require_recipe_create.assert_called()
        self.scene.new_draft_payload.assert_called_once_with(tx._arguments['payload'])
        self.assertEqual(self.saved[0][0]['recipe']['recipeId'], tx.recipe_plan.target_recipe)
        self.assertEqual(self.saved[0][0]['days'], tx._arguments['payload']['days'])
        self.assertEqual(self.saved[0][2], self.base.owner)
        tx._database.commit.assert_not_called()
        self.assertFalse(receipt['ingredient_sync_completed'])
        self.assertTrue(receipt['ingredient_sync_scheduled'])
        tx.commit(); self.assertTrue(tx.close())
        tx._database.commit.assert_called_once()
        self.base.outer.db.commit.assert_not_called()

    def test_edit_keeps_original_id_revision_and_complete_untouched_payload(self):
        tx = self.tx(self.edit); tx.begin(); tx.save()
        self.scene.save_recipe_edit.assert_called_once_with('R1', REVISION, tx._arguments['payload'])
        self.storage.save_recipe_payload.assert_not_called()
        self.assertEqual(self.saved[0][0]['days'], recipes.normalize_payload(PAYLOAD)['days'])
        self.assertTrue(tx.rollback())

    def test_native_revision_and_locked_date_errors_are_not_retried(self):
        for message in ('original revision conflict', 'locked day cannot be removed', 'same calendar week already has a recipe'):
            self.scene.save_recipe_edit.side_effect = ValueError(message)
            before = self.scene.save_recipe_edit.call_count
            tx = self.tx(self.edit); tx.begin()
            with self.assertRaisesRegex(ValueError, message):
                tx.save()
            self.assertEqual(self.scene.save_recipe_edit.call_count, before + 1)
            tx._database.commit.assert_not_called()
            self.assertTrue(tx.rollback()); self.assertTrue(tx.close())

    def test_conflicting_reserved_name_is_never_interpreted_as_success(self):
        self.base.persisted_meal = True
        tx = self.tx(); tx.begin()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            tx.save()
        self.storage.save_recipe_payload.assert_not_called()
        tx._database.commit.assert_not_called(); self.assertTrue(tx.rollback())

    def test_reject_mismatched_native_receipt_before_commit(self):
        self.storage.save_recipe_payload.side_effect = None
        self.storage.save_recipe_payload.return_value = {'recipe': {'workflowStatus': '草稿'}, 'erp_sync': {'recipe': 'OTHER'}}
        tx = self.tx(); tx.begin()
        with self.assertRaises(RuntimeError):
            tx.save()
        self.assertTrue(tx.rollback()); tx._database.commit.assert_not_called()

    def test_cancel_or_permission_revocation_before_commit_refuses_commit(self):
        tx = self.tx(); tx.begin(); tx.save()
        self.base.state['cancel_requested'] = True
        with self.assertRaises(self.base.frappe.PermissionError):
            tx.commit()
        tx._database.commit.assert_not_called(); self.assertTrue(tx.rollback())
        self.base.state['cancel_requested'] = False
        self.scene.require_recipe_create.side_effect = PermissionError('original recipe create revoked')
        with self.assertRaises(PermissionError):
            self.adapter.authorize(self.base.claim, 'recipe_save', self.args)

    def test_commit_response_loss_is_uncertain_and_no_fake_rollback(self):
        tx = self.tx(); tx.begin(); tx.save()
        tx._database.commit.side_effect = RuntimeError('ack lost')
        with self.assertRaises(RuntimeError):
            tx.commit()
        self.assertFalse(tx.rollback()); self.assertTrue(tx.close())
        self.assertEqual(tx._phase, 'uncertain')
        tx._database.rollback.assert_not_called()

    def test_no_readback_before_close_and_replay_pins_original_target(self):
        tx = self.tx(); tx.begin(); tx.save(); tx.commit()
        with self.assertRaisesRegex(RuntimeError, 'drain'):
            self.adapter.fresh_read(self.base.claim, 'recipe_save', self.args, operation_id=self.operation)
        self.assertTrue(tx.close())
        self.adapter.reader.dispatch = MagicMock(return_value={'recipe': tx.recipe_plan.target_recipe, 'dishes': []})
        result = self.adapter.fresh_read(self.base.claim, 'recipe_save', self.args, operation_id=self.operation)
        self.assertEqual(result['recipe'], tx.recipe_plan.target_recipe)
        self.adapter.reader.dispatch.assert_called_once_with(self.base.claim, 'recipe_read',
            {'day': self.args['day'], 'recipe': tx.recipe_plan.target_recipe})
        # A fresh adapter has no in-memory save receipt; it still resolves only
        # the ledger's original target rather than whatever exists this week.
        fresh = recipes.RecipeWriteAdapter(self.base.site, self.base.temp, store=self.base.store)
        fresh.reader.dispatch = MagicMock(side_effect=PermissionError('original target was archived or deleted'))
        with self.assertRaises(PermissionError):
            fresh.fresh_read(self.base.claim, 'recipe_save', self.args, operation_id=self.operation)
        self.assertEqual(fresh.reader.dispatch.call_args.args[2]['recipe'], tx.recipe_plan.target_recipe)
        self.assertEqual(len(self.saved), 1)

    def test_real_reader_readback_uses_new_connection_and_registers_sources_before_delivery(self):
        b = self.base
        tx = self.tx(); tx.begin(); tx.save(); tx.commit(); self.assertTrue(tx.close())
        b.state['cancel_requested'] = '0'
        registered = []
        # Shared authority_scope has not yet registered this new source kind;
        # use an explicit source container ONLY for this standalone fixture.
        self.stack.enter_context(patch.object(b.authority, 'ReadSet', side_effect=lambda scopes: SimpleNamespace(scopes=scopes)))
        self.adapter.authority.register_read = MagicMock(side_effect=lambda store, claim, sources: registered.extend(sources.scopes))
        b.store.emit = MagicMock()
        self.contexts.clear()
        result = self.adapter.fresh_read(b.claim, 'recipe_save', self.args, operation_id=self.operation)
        self.assertEqual(result['recipe'], tx.recipe_plan.target_recipe)
        self.assertTrue(self.contexts)
        self.assertTrue(all(context is not tx._database and context is not b.outer.db for context in self.contexts))
        self.assertIn(recipes.source_scope(tx.recipe_plan.target_recipe), registered)
        self.assertEqual(result['dishes'][1]['ingredients'][0]['unit'], 'ml')
        self.assertIs(b.local.get(), b.outer)

    def test_original_scene_revision_guard_blocks_stale_before_storage(self):
        b = self.base
        week = ModuleType('tongjianyun.recipe_week'); week.lock_recipe_writes = MagicMock()
        storage = ModuleType('tongjianyun.recipe_storage'); storage.save_recipe_payload = MagicMock()
        frappe = SimpleNamespace(throw=lambda text: (_ for _ in ()).throw(ValueError(text)))
        native_save = original_function('meal_scene.py', 'save_recipe_edit', {
            'require_access': lambda: None, 'get_recipe': lambda name: snapshot(name), 'frappe': frappe})
        with patch.dict(sys.modules, {'tongjianyun.recipe_week': week, 'tongjianyun.recipe_storage': storage}):
            with self.assertRaisesRegex(ValueError, '其他人修改'):
                native_save('R1', 'old-revision', PAYLOAD)
        week.lock_recipe_writes.assert_called_once(); storage.save_recipe_payload.assert_not_called()
        b.outer.db.commit.assert_not_called()

    def test_original_storage_preserves_locked_day_and_rejects_change_or_omission(self):
        old = deepcopy(PAYLOAD['days'][0]); old['locked'] = True
        doc = SimpleNamespace(name='R1', modified=REVISION, week_start='2026-09-21', week_end='2026-09-25',
            check_permission=MagicMock(), get=lambda key: None)
        frappe = SimpleNamespace(db=SimpleNamespace(exists=lambda *a: 'R1', get_value=lambda *a, **kw: REVISION),
            get_doc=lambda *a: doc, throw=lambda text: (_ for _ in ()).throw(ValueError(text)))
        week = ModuleType('tongjianyun.recipe_week')
        week.lock_recipe_writes = MagicMock(); week.validate_weekly_recipe = MagicMock(); week.week_bounds = lambda *a: None
        scene = ModuleType('tongjianyun.meal_scene')
        scene.editable_day_content = original_function('meal_scene.py', 'editable_day_content', {})
        save_doc = MagicMock()
        native_save = original_function('recipe_storage.py', '_save_current_recipe', {
            'Any': object, '_require_recipe_write': lambda: None, '_as_dict': lambda value: value or {},
            '_as_list': lambda value: value or [], '_clean': lambda value: str(value or '').strip(),
            'RECIPE_DOCTYPE': recipes.RECIPE, 'frappe': frappe, 'getdate': lambda value: date.fromisoformat(value),
            '_current_recipe_payload': lambda recipe: {'days': [deepcopy(old)]}, '_save_doc': save_doc})
        changed = deepcopy(old); changed['portions'][0]['dishes'][0] = '被改为粥'
        with patch.dict(sys.modules, {'tongjianyun.recipe_week': week, 'tongjianyun.meal_scene': scene}):
            for days in ([], [changed]):
                with self.assertRaisesRegex(ValueError, '锁定'):
                    native_save({'recipe': {**PAYLOAD['recipe'], 'recipeId': 'R1', 'revision': REVISION}, 'days': days}, commit=False)
        save_doc.assert_not_called()

    def test_other_site_admin_or_model_operation_arguments_fail_before_db(self):
        for change in ({'site': 'other.localhost'}, {'mode': 'admin_project'}, {'owner': 'Administrator'}):
            claim = replace(self.base.claim, identity=replace(self.base.claim.identity, **change))
            with self.assertRaises(self.base.frappe.PermissionError):
                self.adapter.transaction_factory(claim, 'recipe_save', self.args, operation_id=self.operation)
        with self.assertRaises(ValueError):
            self.tx({**self.args, 'operation_id': self.operation})
        self.base.frappe.connect.assert_not_called()

    def test_original_week_guard_serializes_empty_week_and_rejects_any_existing_current_recipe(self):
        frappe = SimpleNamespace(db=SimpleNamespace(sql=MagicMock(side_effect=[[], [('hidden-original',)]])),
                                 throw=lambda text: (_ for _ in ()).throw(ValueError(text)))
        lock = original_function('recipe_week.py', 'lock_recipe_writes', {'frappe': frappe, 'RECIPE': recipes.RECIPE})
        validate = original_function('recipe_week.py', 'validate_weekly_recipe', {
            'frappe': frappe, 'lock_recipe_writes': lock,
            'week_bounds': lambda start, end: (date(2026, 9, 21), date(2026, 9, 27))})
        doc = SimpleNamespace(name='NEW', week_start='2026-09-21', week_end='2026-09-25', get=lambda key: None)
        with self.assertRaises(ValueError) as caught:
            validate(doc)
        self.assertNotIn('hidden-original', str(caught.exception))
        self.assertIn('FOR UPDATE', frappe.db.sql.call_args_list[0].args[0])
        self.assertIn('FOR UPDATE', frappe.db.sql.call_args_list[1].args[0])


if __name__ == '__main__':
    unittest.main()
