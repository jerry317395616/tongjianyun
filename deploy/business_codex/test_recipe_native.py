"""Pure checker safeguards. No QA connection, native write, model or browser."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch


SPEC = importlib.util.spec_from_file_location('recipe_native_check_test', Path(__file__).with_name('check_recipe_native.py'))
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
from tongjianyun import business_agent_recipes as recipes, business_agent_writes as writes

RUN = 'd386ad2d-e4b8-4276-bd95-3c8e9d5b5087'


def baseline():
    return {doctype: {} for doctype in ('Tongjianyun Recipe', 'Tongjianyun Recipe Dish',
                                      'Tongjianyun Recipe Ingredient', 'Version')}


def preparation(owner=c.OWNER):
    return {'status': 'prepared_read_only', 'site': c.qa.SITE, 'run_id': RUN,
            'day': c.DAY, 'week_end': c.END, 'owner': owner, 'source_sha256': {},
            'empty_week_verified': True, 'baseline': baseline(),
            'actor_scope': 'existing_qa_manager_native_permissions' if owner == c.MANAGER else 'original_qa_teacher_permissions'}


class PreparationTests(unittest.TestCase):
    def test_default_only_prepares_teacher(self):
        with patch.object(c, 'environment', return_value='frappe'), \
             patch.object(c, 'prepare', return_value=preparation()) as preflight, \
             patch.object(c, 'execute') as execute, redirect_stdout(io.StringIO()):
            c.main(['--run-id', RUN])
        preflight.assert_called_once_with('frappe', RUN, c.OWNER)
        execute.assert_not_called()

    def test_manager_requires_explicit_fixed_owner_selection(self):
        with patch.object(c, 'environment', return_value='frappe'), \
             patch.object(c, 'prepare', return_value=preparation(c.MANAGER)) as preflight, \
             patch.object(c, 'execute') as execute, redirect_stdout(io.StringIO()):
            c.main(['run', '--run-id', RUN, '--owner', 'manager'])
        preflight.assert_called_once_with('frappe', RUN, c.MANAGER)
        execute.assert_called_once_with('frappe', RUN, preparation(c.MANAGER), c.MANAGER)

    def test_stopped_prepare_never_runs(self):
        with patch.object(c, 'environment'), \
             patch.object(c, 'prepare', return_value={'status': 'stopped_read_only'}), \
             patch.object(c, 'execute') as execute, redirect_stdout(io.StringIO()):
            c.main(['run', '--run-id', RUN])
        execute.assert_not_called()

    def test_arbitrary_actor_site_week_or_force_cannot_be_selected(self):
        for args in (['--owner', 'Administrator'], ['--owner', 'real-user@example.com'],
                     ['--site', 'production'], ['--day', '2026-09-26'], ['--force']):
            with self.subTest(args=args), patch.object(c, 'environment') as setup, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    c.main(['--run-id', RUN, *args])
                setup.assert_not_called()

    def test_canonical_run_uuid_required_before_environment(self):
        for value in ('../run', RUN.upper(), ' ' + RUN, 'no'):
            with self.subTest(value=value), patch.object(c, 'environment') as setup, redirect_stderr(io.StringIO()):
                with self.assertRaises((SystemExit, ValueError)):
                    c.main(['--run-id', value])
                setup.assert_not_called()

    def test_existing_run_stops_without_native_access(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(c, 'folder', return_value=Path(temp)):
            frappe = MagicMock()
            with self.assertRaises(FileExistsError):
                c.prepare(frappe, RUN)
            frappe.assert_not_called()

    def test_missing_native_permissions_are_reported_without_escalation(self):
        reader = SimpleNamespace(run_check=lambda owner, callback: callback())
        frappe = SimpleNamespace(PermissionError=PermissionError)
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            stack.enter_context(patch.object(c, 'folder', return_value=Path(temp) / 'unused'))
            stack.enter_context(patch.object(c, 'source_hashes', return_value={}))
            stack.enter_context(patch.object(c.worker_check, 'readonly_adapter', return_value=reader))
            stack.enter_context(patch.object(c, 'account_guard'))
            stack.enter_context(patch.object(recipes, 'check_projection', side_effect=PermissionError('denied')))
            scene = SimpleNamespace(require_recipe_create=Mock())
            stack.enter_context(patch.dict(sys.modules, {'tongjianyun.meal_scene': scene}))
            import tongjianyun
            stack.enter_context(patch.object(tongjianyun, 'meal_scene', scene, create=True))
            result = c.prepare(frappe, RUN)
            self.assertEqual(result['status'], 'stopped_read_only')
            self.assertEqual(result['native_writes'], 0)
            self.assertFalse((Path(temp) / 'unused').exists())
            scene.require_recipe_create.assert_not_called()

    def test_occupied_or_orphan_week_is_rejected_including_archived_records(self):
        frappe = MagicMock()
        for names, orphan in ((['archived-or-hidden'], False), ([], True)):
            with self.subTest(names=names), patch.object(c, 'week_names', return_value=names):
                frappe.db.exists.return_value = orphan
                with self.assertRaises(PermissionError):
                    c.assert_empty_target(frappe)
        frappe.db.commit.assert_not_called()

    def test_default_diagnostics_keep_read_only_nonlocking_reads(self):
        frappe = MagicMock()
        frappe.db.sql.return_value = []
        frappe.db.exists.return_value = False
        self.assertEqual(c.week_names(frappe), [])
        c.assert_empty_target(frappe)
        self.assertTrue(all('FOR UPDATE' not in call.args[0] for call in frappe.db.sql.call_args_list))
        frappe.db.exists.assert_called_once_with('Tongjianyun Recipe Dish', {'meal_date': ['between', [c.DAY, c.END]]})
        frappe.db.commit.assert_not_called()

    def test_changed_preparation_cannot_reserve_or_execute(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(c, 'folder', return_value=Path(temp) / 'unused'), \
             patch.object(c, 'source_hashes', return_value={}), \
             patch.object(c, 'prepare', return_value={**preparation(), 'empty_week_verified': False}):
            with self.assertRaises(PermissionError):
                c.execute(None, RUN, preparation())
            self.assertFalse((Path(temp) / 'unused').exists())

    def test_preparation_identity_and_hashes_are_bound(self):
        for change in ({'status': 'stopped_read_only'}, {'owner': c.MANAGER}, {'site': 'production'},
                       {'empty_week_verified': 1}, {'run_id': str(__import__('uuid').uuid4())},
                       {'source_sha256': {'changed': True}}):
            with self.subTest(change=change), patch.object(c, 'source_hashes', return_value={}):
                with self.assertRaises(PermissionError):
                    c.require_prepared({**preparation(), **change}, RUN)

    def test_private_evidence_is_exclusive_and_retained(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(c.qa, 'safe_target', side_effect=lambda path: path):
            path = Path(temp) / 'attempt.json'
            c.private_new(path, {'run_id': RUN})
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                c.private_new(path, {'replacement': True})
            self.assertEqual(path.read_bytes(), original)

    def test_synthetic_week_is_monday_and_native_payload_has_no_ingredient_work(self):
        self.assertEqual(recipes.week_bounds(c.DAY), (c.DAY, c.END))
        for version in (1, 2, 3):
            value = recipes.normalize_payload(c.payload(RUN, version))
            self.assertEqual(value, c.payload(RUN, version))
            self.assertEqual(value['days'][0]['portions'][0]['dishIngredientRows'], [])

    def test_existing_data_digest_must_stay_identical_and_new_records_must_be_owned(self):
        before = baseline()
        before['Tongjianyun Recipe']['existing'] = {'recipe': 'existing', 'sha256': 'original'}
        after = copy.deepcopy(before)
        after['Tongjianyun Recipe']['new'] = {'recipe': 'new', 'sha256': 'new'}
        after['Version']['new-history'] = {'recipe': 'new', 'sha256': 'history'}
        self.assertTrue(c.unchanged(before, after, {'new'}))
        for changed in ('old', 'foreign', 'removed'):
            value = copy.deepcopy(after)
            if changed == 'old': value['Tongjianyun Recipe']['existing']['sha256'] = 'changed'
            elif changed == 'foreign': value['Version']['new-history']['recipe'] = 'existing'
            else: del value['Tongjianyun Recipe']['existing']
            self.assertFalse(c.unchanged(before, value, {'new'}))


class NativeGuardTests(unittest.TestCase):
    def test_locked_guard_sees_late_archived_or_orphan_rows_outside_old_snapshot(self):
        for late_row in ('archived_recipe', 'orphan_dish', 'current_recipe', 'none'):
            with self.subTest(late_row=late_row), ExitStack() as stack:
                locked, queries = [], []
                frappe = MagicMock()
                frappe.db.exists.return_value = False
                def sql(query, arguments):
                    queries.append(query)
                    # A pre-lock consistent read would see an empty old
                    # snapshot. Current reads must run after the week lock.
                    if 'FOR UPDATE' not in query:
                        return []
                    self.assertEqual(locked, [True])
                    if '`tabTongjianyun Recipe Dish`' in query:
                        self.assertEqual(arguments, (c.DAY, c.END))
                        return [('new-orphan',)] if late_row == 'orphan_dish' else []
                    self.assertNotIn('workflow_status', query)
                    self.assertNotIn('is_deleted', query)
                    self.assertEqual(arguments, (c.END, c.DAY))
                    return [(late_row,)] if late_row in ('archived_recipe', 'current_recipe') else []
                frappe.db.sql.side_effect = sql
                args = {'day': c.DAY, 'recipe': None, 'revision': '', 'payload': c.payload(RUN, 1)}
                plan = recipes.write_plan(c.qa.SITE, '9f30d2ac-3079-40e4-9a89-0c11e5fe319c', args)
                transaction = SimpleNamespace(recipe_plan=plan)
                guard = c.ObservedTransaction(transaction, frappe, RUN, {}, set(), {}, c.MANAGER)
                week = SimpleNamespace(lock_recipe_writes=lambda: locked.append(True))
                stack.enter_context(patch.dict(sys.modules, {'tongjianyun.recipe_week': week}))
                stack.enter_context(patch.object(c, 'source_hashes', return_value={}))
                stack.enter_context(patch.object(c, 'account_guard'))
                self.assertEqual(c.week_names(frappe), [])
                queries.clear()
                if late_row == 'none':
                    guard.guard()
                    # Both the emptiness check and the subsequent ownership
                    # check use the latest committed week after the same lock.
                    self.assertEqual(sum('`tabTongjianyun Recipe`' in query for query in queries), 2)
                else:
                    with self.assertRaises(PermissionError):
                        guard.guard()
                self.assertTrue(queries)
                self.assertTrue(all('FOR UPDATE' in query for query in queries))
                if late_row == 'orphan_dish':
                    self.assertTrue(any('`tabTongjianyun Recipe Dish`' in query for query in queries))
                frappe.db.commit.assert_not_called()

    def guarded(self, *, known=(), existing_week=(), existing_identity=False, recipe=None, content=None):
        args = {'day': c.DAY, 'recipe': recipe, 'revision': '1' if recipe else '',
                'payload': content or c.payload(RUN, 1)}
        plan = recipes.write_plan(c.qa.SITE, '9f30d2ac-3079-40e4-9a89-0c11e5fe319c', args)
        native = SimpleNamespace(recipe_plan=plan)
        frappe = MagicMock()
        frappe.db.exists.return_value = existing_identity
        guard = c.ObservedTransaction(native, frappe, RUN, {}, set(known), {}, c.MANAGER)
        with ExitStack() as stack:
            week = SimpleNamespace(lock_recipe_writes=Mock())
            stack.enter_context(patch.dict(sys.modules, {'tongjianyun.recipe_week': week}))
            stack.enter_context(patch.object(c, 'source_hashes', return_value={}))
            stack.enter_context(patch.object(c, 'account_guard'))
            stack.enter_context(patch.object(c, 'assert_empty_target'))
            stack.enter_context(patch.object(c, 'native_snapshot', return_value={}))
            stack.enter_context(patch.object(c, 'week_names', return_value=list(existing_week)))
            guard.guard()
            week.lock_recipe_writes.assert_called_once()

    def test_locked_guard_refuses_foreign_week_even_if_account_can_write_it(self):
        with self.assertRaises(PermissionError):
            self.guarded(existing_week=('existing-real-recipe',))

    def test_locked_guard_refuses_preexisting_identity_or_adopted_edit(self):
        with self.assertRaises(PermissionError):
            self.guarded(existing_identity=True)
        with self.assertRaises(PermissionError):
            self.guarded(recipe='existing-real-recipe')

    def test_locked_guard_accepts_only_exact_reviewed_synthetic_payloads(self):
        self.guarded()
        altered = c.payload(RUN, 1)
        altered['recipe']['title'] = 'unrelated original recipe'
        with self.assertRaises(PermissionError):
            self.guarded(content=altered)

    def test_manager_guard_rejects_changed_roles_and_never_switches_actor(self):
        frappe = MagicMock()
        frappe.local.site, frappe.session.user = c.qa.SITE, c.MANAGER
        frappe.db.get_value.return_value = SimpleNamespace(enabled=1, user_type='System User')
        frappe.get_doc.return_value.roles = [SimpleNamespace(role=role) for role in ('System Manager', 'Academics User')]
        c.account_guard(frappe, c.MANAGER)
        frappe.get_doc.return_value.roles.append(SimpleNamespace(role='New Role'))
        with self.assertRaises(PermissionError):
            c.account_guard(frappe, c.MANAGER)
        frappe.set_user.assert_not_called()

    def test_unknown_commit_does_not_get_ack_or_automatic_rollback(self):
        transaction = MagicMock()
        transaction.commit.side_effect = RuntimeError('connection lost')
        record = {}
        observed = c.ObservedTransaction(transaction, object(), RUN, {}, set(), record)
        with self.assertRaises(RuntimeError):
            observed.commit()
        self.assertTrue(record['commit_attempted'])
        self.assertNotIn('commit_acknowledged', record)
        transaction.rollback.assert_not_called()
        transaction.commit.assert_called_once()

    def test_native_sync_enqueue_is_rejected_before_commit(self):
        transaction = MagicMock()
        transaction.save.return_value = {'recipe': 'new', 'ingredient_sync_scheduled': True,
                                         'ingredient_sync_completed': False}
        observed = c.ObservedTransaction(transaction, object(), RUN, {}, set(), {})
        with self.assertRaises(PermissionError):
            observed.save()
        transaction.commit.assert_not_called()

    def test_native_rejection_classification_requires_exact_original_message(self):
        stale = '食谱已被其他人修改，请刷新后重新核对。'
        duplicate = (c.DAY + ' 这一周已有食谱。请编辑本周现有食谱，不要新建或另存副本；'
                     '如有历史重复记录，请先确认保留哪一份并将其余归档。')
        for message, expected in ((stale, 'stale_revision'), (duplicate, 'duplicate_week'),
                ('食谱已更新或缺少版本号。请重新读取这份食谱后再保存，不要另建副本。', 'stale_revision'),
                ('database unavailable secret details', 'other'), ('prefix ' + stale, 'other'),
                (duplicate.replace(c.DAY, '2037-01-12'), 'other')):
            with self.subTest(expected=expected):
                tx, record = MagicMock(), {}
                tx.save.side_effect = ValueError(message)
                observed = c.ObservedTransaction(tx, object(), RUN, {}, set(), record)
                with self.assertRaises(ValueError):
                    observed.save()
                self.assertEqual(record, {'save_error_type': 'ValueError', 'save_error_classification': expected})
                self.assertNotIn(message, json.dumps(record))


class PureLedgerFlowTests(unittest.TestCase):
    """Real SQLite ledger/store; all native DB behavior below is a test double."""
    def flow(self, fail_commit=False, unexpected_save_error=False):
        stack = ExitStack()
        self.addCleanup(stack.close)
        temp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        target = temp / 'run'
        docs = {}
        class Authority:
            site = c.qa.SITE
            def __call__(self, identity, scopes): return identity.owner == c.MANAGER
            def run_check(self, owner, callback): return callback()
        authority = Authority()
        class Transaction:
            def __init__(self, plan):
                self.recipe_plan, self._database, self._closed = plan, None, False
                self._context = SimpleNamespace(run=lambda callback: callback())
            def begin(self): pass
            def save(self):
                args = self.recipe_plan.arguments
                if args['recipe'] is None and docs:
                    raise ValueError(c.DAY + ' 这一周已有食谱。请编辑本周现有食谱，不要新建或另存副本；'
                                     '如有历史重复记录，请先确认保留哪一份并将其余归档。')
                if args['recipe'] is not None and args['revision'] != docs[args['recipe']]['revision']:
                    raise ValueError('unexpected native failure' if unexpected_save_error else '食谱已被其他人修改，请刷新后重新核对。')
                return {'recipe': self.recipe_plan.target_recipe, 'ingredient_sync_scheduled': False,
                        'ingredient_sync_completed': False}
            def commit(self):
                if fail_commit: raise RuntimeError('commit acknowledgement lost')
                key = self.recipe_plan.target_recipe
                old = docs.get(key)
                dishes = self.recipe_plan.arguments['payload']['days'][0]['portions'][0]['dishes']
                docs[key] = {'name': key, 'revision': '2' if old else '1', 'payload_sha256': 'edit' if old else 'create',
                    'dishes': dishes, 'history_payload_sha256': ['create'] if old else [],
                    'history_names': ['history-1'] if old else [], 'week_names': [key], 'ingredient_count': 0}
            def rollback(self): return True
            def close(self): self._closed = True; return True
        class Adapter:
            def __init__(self, *args, **kwargs): self.authority = authority
            def authorize(self, *args): return True
            def transaction_factory(self, claim, tool, arguments, *, operation_id=None):
                return Transaction(recipes.write_plan(c.qa.SITE, operation_id, arguments))
            def fresh_read(self, claim, tool, arguments, *, operation_id=None):
                plan = recipes.write_plan(c.qa.SITE, operation_id, arguments)
                return {'recipe': plan.target_recipe, 'day': c.DAY, 'operation_id': operation_id,
                    'calendar_week_start': c.DAY, 'calendar_week_end': c.END,
                    'week_start': c.DAY, 'week_end': c.END, 'visible_recipe_found': True,
                    'selection': {'view': 'recipe_week', 'day': c.DAY, 'meal': 'lunch'},
                    'dishes': [{}], 'dish_count': 1, 'page_count': 1, 'has_more': False,
                    'complete': True, 'offset': 0, 'next_offset': None}
        def protected(_):
            result = baseline()
            result['Tongjianyun Recipe'] = {name: {'recipe': name, 'sha256': c.digest(value)} for name, value in docs.items()}
            return result
        prepared = preparation(c.MANAGER)
        for obj, name, value in ((c, 'folder', lambda _: target), (c, 'source_hashes', lambda: {}),
                (c, 'prepare', lambda *args: prepared), (c.qa, 'safe_target', lambda path: path),
                (c.worker_check, 'readonly_adapter', lambda _: authority), (recipes, 'RecipeWriteAdapter', Adapter),
                (c.ObservedTransaction, 'guard', lambda _: None),
                (c, 'native_snapshot', lambda f, run, recipe, owner: copy.deepcopy(docs[recipe])),
                (c, 'baseline', protected)):
            stack.enter_context(patch.object(obj, name, value))
        with redirect_stdout(io.StringIO()):
            if fail_commit or unexpected_save_error:
                with self.assertRaises(AssertionError):
                    c.execute(object(), RUN, prepared, c.MANAGER)
                evidence = json.loads((target / 'evidence.json').read_text())
            else:
                evidence = c.execute(object(), RUN, prepared, c.MANAGER)
        return target, evidence, docs

    def test_complete_flow_uses_real_ledger_and_retains_limited_evidence(self):
        target, evidence, docs = self.flow()
        self.assertTrue(evidence['all_passed'])
        self.assertEqual(len(docs), 1)
        self.assertEqual(len(evidence['transactions']), 4)
        self.assertEqual(sum(row['commit_acknowledged'] for row in evidence['transactions']), 2)
        self.assertFalse(evidence['teacher_authority_proven'])
        self.assertFalse(evidence['browser_exercised'])
        self.assertFalse(evidence['rq_worker_exercised'])
        self.assertEqual(evidence['model_calls'], 0)
        self.assertTrue(evidence['host_gate']['admission_closed'])
        self.assertTrue((target / 'attempt.json').exists())
        self.assertEqual(len(list(target.glob('operation-*.json'))), 4)

    def test_unknown_commit_retains_ledger_fence_and_stops_without_retry(self):
        target, evidence, docs = self.flow(fail_commit=True)
        self.assertFalse(evidence['all_passed'])
        self.assertFalse(evidence['automatic_retry_allowed'])
        self.assertEqual(len(evidence['transactions']), 1)
        self.assertEqual(evidence['host_gate']['uncertain_writes'], 1)
        self.assertTrue(evidence['host_gate']['admission_closed'])
        self.assertEqual(docs, {})
        self.assertTrue((target / 'attempt.json').exists())

    def test_unrelated_native_failure_cannot_pass_stale_revision_negative(self):
        target, evidence, docs = self.flow(unexpected_save_error=True)
        self.assertFalse(evidence['all_passed'])
        self.assertEqual(len(evidence['transactions']), 3)
        self.assertEqual(evidence['transactions'][-1]['save_error_classification'], 'other')
        self.assertEqual(evidence['checks'][-1], {'name': 'native_stale_revision_refusal_rolled_back', 'passed': False})
        self.assertFalse((target / 'duplicate-week-receipt.json').exists())
        self.assertEqual(len(docs), 1)


if __name__ == '__main__':
    unittest.main()
