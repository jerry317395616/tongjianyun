"""Private SQLite + real task store/blueprint validators, fake native permissions.

No Frappe site, model, private File, schema or business record is modified. Native
authorization and File acceptance are explicit doubles, not live E2E evidence.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from contextvars import ContextVar
import copy
from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import uuid

import tongjianyun
from tongjianyun import business_agent_proposals as proposals
from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation


SPEC = {'key': 'visitor_log', 'title': '访客登记', 'description': '到访信息草稿，不是已启用的出入审批。',
        'fields': [{'fieldname': 'visited_on', 'label': '日期', 'fieldtype': 'Date', 'reqd': 1}]}


def load_private(stack, filename, dependencies):
    name = '_business_proposal_test_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / filename)
    module = importlib.util.module_from_spec(spec)
    stack.enter_context(patch.dict(sys.modules, {name: module}))
    with patch.dict(sys.modules, dependencies):
        spec.loader.exec_module(module)
    return module


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.site, self.owner, self.manager = 'proposal-test.localhost', 'teacher@example.invalid', 'manager@example.invalid'
        self.actor = ContextVar('proposal-test-actor', default='outer')
        self.enabled = {self.owner, self.manager, 'other@example.invalid'}
        self.managers = {self.manager}
        self.sessions = {self.owner, self.manager, 'other@example.invalid'}
        self.links = {'Student', 'Supplier'}
        self.trace = []
        self.frappe = ModuleType('frappe')
        self.frappe.whitelist = lambda *a, **kw: lambda function: function
        self.frappe.PermissionError = type('NativePermissionError', (Exception,), {})
        self.frappe.db = MagicMock()
        self.frappe.has_permission = lambda name, action: self.actor.get() in self.managers and action == 'create'
        document = ModuleType('frappe.model.document')
        document.Document = type('Document', (), {'save': lambda _: None, 'insert': lambda _: None})
        base_document = ModuleType('frappe.model.base_document')
        base_document.RESERVED_KEYWORDS = {'select', 'delete'}
        dependencies = {'frappe': self.frappe, 'frappe.model.document': document, 'frappe.model.base_document': base_document}
        self.bp = load_private(self.stack, 'business_blueprints.py', dependencies)
        self.stack.enter_context(patch.object(tongjianyun, 'business_blueprints', self.bp, create=True))
        self.v2 = load_private(self.stack, 'business_blueprints_v2.py', {'frappe': self.frappe})
        self.stack.enter_context(patch.dict(sys.modules, {'tongjianyun.business_blueprints_v2': self.v2}))
        self.tools = load_private(self.stack, 'business_agent_tools.py', {'frappe': self.frappe})
        self.gates = load_private(self.stack, 'business_agent_authority.py', {'frappe': self.frappe, 'tongjianyun.business_agent_tools': self.tools})
        self.stack.enter_context(patch.object(self.gates, '_account', self.account))
        self.stack.enter_context(patch.object(self.gates, '_doctype', self.doctype))
        self.stack.enter_context(patch.object(self.gates, '_check_scope', self.check_scope))
        self.stack.enter_context(patch.object(self.bp, '_validate_links', self.validate_links))
        self.stack.enter_context(patch.object(self.bp, '_access', self.manager_access))
        self.stack.enter_context(patch.object(self.bp, 'propose', MagicMock(side_effect=self.native_propose)))
        self.stack.enter_context(patch.object(self.bp, '_load', MagicMock(side_effect=self.native_load)))
        self.stack.enter_context(patch.object(self.bp, 'activate', MagicMock(side_effect=AssertionError('No structure activation'))))
        self.stack.enter_context(patch.object(proposals, '_services', return_value=(self.frappe, self.gates, self.bp, self.v2)))
        self.files = {}
        self.native_after_propose = None
        self.path = self.root / self.site / 'private' / 'business-codex' / 'proposals'
        self.path.mkdir(parents=True, mode=0o700)
        self.repository = proposals.ProposalRepository(self.site, self.root)
        base = self.gates.FrappeBusinessAuthority(self.site, run_check=self.run_check)
        def viewer_active(viewer, identity=None):
            return (isinstance(viewer, self.gates.Viewer) and viewer.site == self.site
                    and viewer.owner in self.enabled and viewer.owner in self.sessions
                    and (identity is None or identity.owner == viewer.owner))
        self.stack.enter_context(patch.object(base, 'viewer_active', viewer_active))
        self.base = base
        self.authority = proposals.ProposalAuthority(base, self.repository)
        self.store = BusinessTaskStore(self.root, self.site, authorize=self.authority,
            observe_queue=lambda job: QueueObservation(job, 'present'),
            observe_execution=lambda identity, claim: ExecutionObservation(claim, 'running', 0))
        self.claim = self.make_claim(self.owner)
        self.agent = proposals.BusinessProposals(self.authority, self.store, self.repository)
        self.viewer = self.gates.Viewer(self.site, self.owner, 's' * 32)
        self.manager_viewer = self.gates.Viewer(self.site, self.manager, 'm' * 32)

    def make_claim(self, owner, context=None):
        identity = TaskIdentity(self.site, owner, str(uuid.uuid4()))
        self.store.create(owner, identity.task_id, '合成提案测试', context)
        ticket = self.store.take_dispatch(identity)
        self.store.acknowledge_dispatch(ticket)
        claim = self.store.claim(identity, ticket.job_id)
        self.repository.open_task(claim)
        return claim

    def run_check(self, owner, callback):
        token = self.actor.set(owner)
        try:
            self.trace.append(('fresh', owner))
            return callback()
        finally:
            self.actor.reset(token)

    def account(self, owner, site):
        if owner not in self.enabled or site != self.site or self.actor.get() != owner:
            raise self.frappe.PermissionError('account unavailable')

    def doctype(self, name, actions):
        if name not in self.links or actions != ['read']:
            raise self.frappe.PermissionError('Link source unavailable')
        return SimpleNamespace(name=name)

    def validate_links(self, spec):
        for name in proposals._links(spec):
            self.doctype(name, ['read'])

    def check_scope(self, scope):
        if scope['kind'] == 'doctype':
            self.doctype(scope['doctype'], scope['actions'])
        else:
            raise self.frappe.PermissionError('base refuses unknown scopes')

    def manager_access(self):
        if self.actor.get() not in self.managers:
            raise self.frappe.PermissionError('Original manager gate')

    def native_propose(self, spec):
        self.manager_access()
        self.validate_links(spec)
        file_id = 'FILE-' + str(len(self.files) + 1)
        self.files[file_id] = (self.actor.get(), copy.deepcopy(spec))
        if self.native_after_propose:
            self.native_after_propose()
        return {'proposal_id': file_id, 'revision': self.bp.revision(spec), 'state': 'proposed'}

    def native_load(self, file_id):
        self.manager_access()
        owner, spec = self.files[file_id]
        if owner != self.actor.get():
            raise self.frappe.PermissionError('Original File owner gate')
        return spec

    def create(self, *, spec=None, call='create', claim=None):
        return self.agent.dispatch(claim or self.claim, 'proposal_create', {'spec': spec or SPEC}, call)

    def update(self, record, *, title='更新的访客登记', call='update', claim=None):
        spec = copy.deepcopy(record['spec'])
        spec['title'] = title
        return self.agent.dispatch(claim or self.claim, 'proposal_update',
            {'proposal_id': record['proposal_id'], 'expected_revision': record['revision'], 'spec': spec}, call)

    def count(self, table):
        with closing(sqlite3.connect(self.repository.path)) as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def test_create_real_private_draft_registers_scope_before_event_no_native_write(self):
        record = self.create()
        self.assertEqual(record['state'], 'draft')
        self.assertFalse(record['enabled'])
        self.assertFalse(record['business_executed'])
        self.assertEqual(record['version'], 1)
        self.assertEqual(self.count('drafts'), 1)
        self.assertIn(proposals._capability(record['proposal_id'], record['revision']), self.store.required_scopes(self.claim.identity))
        self.assertLess(len(proposals._capability(record['proposal_id'], record['revision'])['name']), 140)
        events = self.store.events(self.claim.identity)
        self.assertTrue(any(event.get('kind') == 'view' for event in events))
        self.bp.propose.assert_not_called()
        self.bp.activate.assert_not_called()
        self.frappe.db.commit.assert_not_called()
        self.assertEqual(self.actor.get(), 'outer')

    def test_reopen_repository_reads_durable_same_owner_revision(self):
        record = self.create()
        reopened = proposals.ProposalRepository(self.site, self.root)
        self.assertEqual(reopened.read(self.owner, record['proposal_id'])['spec'], record['spec'])

    def test_cas_update_and_historical_read(self):
        original = self.create()
        newer = self.update(original)
        self.assertNotEqual(original['revision'], newer['revision'])
        self.assertEqual(newer['version'], 2)
        history = self.agent.dispatch(self.claim, 'proposal_read', {'proposal_id': original['proposal_id'], 'revision': original['revision']}, 'read')
        self.assertFalse(history['is_current'])
        self.assertEqual(history['spec'], original['spec'])
        self.assertEqual(len(self.store.required_scopes(self.claim.identity)), 2)
        with self.assertRaises(proposals.ProposalConflict):
            self.update(original, title='覆盖并发修改', call='stale')
        self.assertEqual(self.count('versions'), 2)

    def test_same_call_replay_and_alias_do_not_duplicate(self):
        first = self.create()
        second = self.create()
        alias = self.create(call='new-call')
        self.assertEqual(first['proposal_id'], second['proposal_id'])
        self.assertEqual(first['revision'], alias['revision'])
        self.assertEqual(self.count('versions'), 1)
        changed = dict(SPEC, title='不同内容')
        with self.assertRaises(PermissionError):
            self.create(spec=changed)
        with self.assertRaises(proposals.ProposalConflict):
            self.create(spec=changed, call='another')

    def test_update_receipt_replay_does_not_reapply_to_new_head(self):
        a = self.create()
        b = self.update(a)
        c = self.update(b, title='第三版', call='update-again')
        replay = self.update(a)
        self.assertEqual(replay['revision'], b['revision'])
        self.assertFalse(replay['is_current'])
        self.assertEqual(self.repository.read(self.owner, a['proposal_id'])['revision'], c['revision'])
        self.assertEqual(self.count('versions'), 3)

    def test_owner_site_task_mode_and_token_are_not_model_arguments(self):
        for extra in ('owner', 'actor', 'site', 'mode', 'task_id', 'ignore_permissions', 'method', 'sql'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.agent.dispatch(self.claim, 'proposal_create', {'spec': SPEC, extra: 'Administrator'}, 'id')
        for identity in (replace(self.claim.identity, site='other.localhost'), replace(self.claim.identity, mode='admin'), replace(self.claim.identity, owner='other@example.invalid')):
            with self.assertRaises((PermissionError, ValueError)):
                self.create(claim=replace(self.claim, identity=identity))
        with self.assertRaises(PermissionError):
            self.create(claim=replace(self.claim, token='a' * 43))
        self.assertEqual(self.count('drafts'), 0)

    def test_other_user_cannot_read_or_update_or_scope_own_record(self):
        record = self.create()
        other = self.make_claim('other@example.invalid')
        for tool, args in [('proposal_read', {'proposal_id': record['proposal_id']}),
                           ('proposal_update', {'proposal_id': record['proposal_id'], 'expected_revision': record['revision'], 'spec': record['spec']})]:
            with self.assertRaises(PermissionError):
                self.agent.dispatch(other, tool, args, 'other')
        self.assertFalse(self.authority(other.identity, [proposals._capability(record['proposal_id'], record['revision'])]))
        self.assertFalse(self.authority(other.identity, [{'kind': 'view', 'selection': record['selection']}]))

    def test_future_task_can_find_own_draft_but_not_another_owner(self):
        record = self.create()
        later = self.make_claim(self.owner)
        result = self.agent.dispatch(later, 'proposal_list', {}, 'list')
        self.assertEqual(result['entries'][0]['proposal_id'], record['proposal_id'])
        other = self.make_claim('other@example.invalid')
        self.assertEqual(self.agent.dispatch(other, 'proposal_list', {}, 'list')['entries'], [])

    def test_list_pagination_registers_lookahead(self):
        for index in range(3):
            self.create(spec=dict(SPEC, key='visitor_' + str(index)), call='create-' + str(index))
        claim = self.make_claim(self.owner)
        first = self.agent.dispatch(claim, 'proposal_list', {'page_size': 1}, 'list')
        self.assertTrue(first['has_more'])
        self.assertEqual(len(self.store.required_scopes(claim.identity)), 2)
        second = self.agent.dispatch(claim, 'proposal_list', {'page_size': 1, 'cursor': first['next_cursor']}, 'list2')
        self.assertNotEqual(first['entries'][0]['proposal_id'], second['entries'][0]['proposal_id'])
        self.assertEqual(len(self.store.required_scopes(claim.identity)), 3)

    def test_link_dependencies_are_full_and_revocation_blocks_old_history(self):
        linked = dict(SPEC, fields=[{'fieldname': 'student_ref', 'label': '学生', 'fieldtype': 'Link', 'options': 'Student'}])
        record = self.create(spec=linked)
        self.assertIn({'kind': 'doctype', 'doctype': 'Student', 'actions': ['read']}, self.store.required_scopes(self.claim.identity))
        self.links.remove('Student')
        self.assertFalse(self.authority(self.claim.identity, [proposals._capability(record['proposal_id'], record['revision'])]))
        with self.assertRaises(PermissionError):
            self.store.events(self.claim.identity)
        with self.assertRaises(PermissionError):
            self.create(spec=linked)
        self.assertEqual(self.count('drafts'), 1)

    def test_permission_revoked_before_write_leaves_no_draft(self):
        self.enabled.remove(self.owner)
        with self.assertRaises(PermissionError):
            self.create()
        self.assertEqual(self.count('drafts'), 0)

    def test_cancelled_task_cannot_begin_new_draft_or_replay(self):
        self.create()
        self.store.cancel(self.claim.identity)
        with self.assertRaises(PermissionError):
            self.create()
        with self.assertRaises(PermissionError):
            self.create(spec=dict(SPEC, key='another_draft'), call='after-stop')
        self.assertEqual(self.count('drafts'), 1)

    def test_cancel_at_precommit_rolls_back_sqlite_draft_and_receipt(self):
        checks = []
        def authorize():
            checks.append(True)
            if len(checks) == 3:
                self.store.cancel(self.claim.identity)
            self.agent._active(self.claim)
        with self.assertRaises(PermissionError):
            self.repository.mutate(self.claim, 'proposal_create', {'spec': SPEC}, 'cancelled', authorize=authorize)
        self.assertEqual(self.count('drafts'), 0)
        self.assertEqual(self.count('versions'), 0)
        self.assertEqual(self.count('receipts'), 0)

    def test_revocation_between_save_and_register_never_delivers_event(self):
        original = self.authority.register_read
        def revoke(*args):
            self.enabled.remove(self.owner)
            return original(*args)
        with patch.object(self.authority, 'register_read', revoke), self.assertRaises(self.frappe.PermissionError):
            self.create()
        self.assertEqual(self.count('drafts'), 1)  # Durable draft, not fake rollback.
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertFalse(any('"kind":"view"' in row[0] for row in db.execute('SELECT payload FROM events')))

    def test_concurrent_same_call_has_one_version_and_one_receipt(self):
        def create(_):
            return self.repository.mutate(self.claim, 'proposal_create', {'spec': SPEC}, 'parallel', authorize=lambda: self.agent._active(self.claim))
        with ThreadPoolExecutor(max_workers=2) as executor:
            records = list(executor.map(create, range(2)))
        self.assertEqual(records[0]['proposal_id'], records[1]['proposal_id'])
        self.assertEqual(self.count('drafts'), 1)
        self.assertEqual(self.count('receipts'), 1)

    def test_concurrent_expected_revision_only_one_edit_wins(self):
        record = self.create()
        def edit(index):
            try:
                return self.repository.mutate(self.claim, 'proposal_update',
                    {'proposal_id': record['proposal_id'], 'expected_revision': record['revision'], 'spec': dict(record['spec'], title='并发' + str(index))},
                    'parallel-' + str(index), authorize=lambda: self.agent._active(self.claim))
            except proposals.ProposalConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            records = list(executor.map(edit, range(2)))
        self.assertEqual(sum(record is not None for record in records), 1)
        self.assertEqual(self.count('versions'), 2)

    def test_native_validator_rejects_code_permissions_unsafe_links_and_nonfinite(self):
        for spec in [dict(SPEC, code='print(1)'), dict(SPEC, roles=['System Manager']),
                     dict(SPEC, fields=[{'fieldname': 'payload', 'label': '内容', 'fieldtype': 'HTML'}]),
                     dict(SPEC, fields=[{'fieldname': 'user_ref', 'label': '用户', 'fieldtype': 'Link', 'options': 'User'}])]:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                self.create(spec=spec)
        with self.assertRaises(ValueError):
            self.create(spec=dict(SPEC, extra=float('nan')))
        with self.assertRaises(ValueError):
            self.create(spec=dict(SPEC, description='x' * 45000))
        self.assertEqual(self.count('drafts'), 0)

    def test_current_link_permission_and_control_type_denied_before_persistence(self):
        for name in ('Private Supplier', 'System Settings'):
            spec = dict(SPEC, fields=[{'fieldname': 'reference', 'label': '关联', 'fieldtype': 'Link', 'options': name}])
            with self.assertRaises(self.frappe.PermissionError):
                self.create(spec=spec)
        self.assertEqual(self.count('drafts'), 0)

    def test_v2_child_link_sources_and_original_preview_are_reused(self):
        spec = {**SPEC, 'version': 2, 'tables': [{'fieldname': 'items', 'label': '明细', 'fields': [
            {'fieldname': 'supplier', 'label': '供应商', 'fieldtype': 'Link', 'options': 'Supplier'}]}], 'workflow': {'template': 'review'}}
        record = self.create(spec=spec)
        result = self.agent.preview_owned(self.viewer, record['proposal_id'], record['revision'])
        component = result['components'][0]
        self.assertEqual(component['tables'], self.v2.preview_extra(record['spec'])['tables'])
        self.assertEqual(component['workflow']['template'], 'review')
        self.assertFalse(component['can_activate'])
        self.assertIn({'kind': 'doctype', 'doctype': 'Supplier', 'actions': ['read']}, self.store.required_scopes(self.claim.identity))

    def test_preview_schema_readonly_and_canonical_selection(self):
        record = self.create()
        result = self.agent.preview_owned(self.viewer, record['proposal_id'], record['revision'])
        self.assertEqual(result['view'], 'business_proposal')
        self.assertEqual(result['selection'], record['selection'])
        self.assertEqual(result['components'][0]['type'], 'business_proposal')
        self.assertFalse(result['components'][0]['can_activate'])
        self.assertEqual(result['actions'], [])
        self.assertTrue(result['components'][0]['warnings'])
        for choice in [dict(record['selection'], owner=self.owner), dict(record['selection'], revision='invalid'), dict(record['selection'], view='business_blueprint')]:
            with self.assertRaises(ValueError):
                proposals.canonical_selection(choice)

    def test_view_scope_works_for_new_task_context_and_old_base_still_denies(self):
        record = self.create()
        scopes = self.authority.view_scopes(self.claim.identity, record['selection'])
        self.assertTrue(self.authority(self.claim.identity, scopes))
        self.assertFalse(self.base(self.claim.identity, scopes))
        newer = self.make_claim(self.owner, {'selection': record['selection']})
        self.assertEqual(self.store.binding_state(newer)['status'], 'running')
        self.assertFalse(self.authority(self.claim.identity, [{'kind': 'capability', 'name': 'proposal:root:all'}]))

    def test_expired_session_cannot_preview_but_does_not_cancel_task(self):
        record = self.create()
        self.sessions.remove(self.owner)
        with self.assertRaises(PermissionError):
            self.agent.preview_owned(self.viewer, record['proposal_id'], record['revision'])
        self.assertEqual(self.store.binding_state(self.claim)['status'], 'running')

    def test_different_viewer_or_site_cannot_preview(self):
        record = self.create()
        for viewer in (self.manager_viewer, replace(self.viewer, site='other.localhost')):
            with self.assertRaises(PermissionError):
                self.agent.preview_owned(viewer, record['proposal_id'], record['revision'])

    def test_handoff_is_not_a_model_tool(self):
        for name in ('handoff', 'proposal_handoff', 'accept_handoff', 'activate', 'proposal_activate'):
            with self.assertRaises(ValueError):
                self.agent.dispatch(self.claim, name, {}, 'model-action')

    def test_explicit_exact_recipient_handoff_and_acceptance_as_recipient_only(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        self.assertEqual(grant['state'], 'pending')
        same = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        self.assertEqual(grant['handoff_id'], same['handoff_id'])
        preview = self.agent.preview_handoff(self.manager_viewer, grant['handoff_id'])
        self.assertNotIn('selection', preview)
        accepted = self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        self.assertEqual(accepted['state'], 'accepted')
        self.assertFalse(accepted['enabled'])
        self.assertEqual(self.files[accepted['proposal_id']][0], self.manager)
        self.bp.propose.assert_called_once()
        self.frappe.db.commit.assert_called_once()
        self.bp.activate.assert_not_called()
        self.assertEqual(self.actor.get(), 'outer')
        self.assertEqual(self.agent.accept_handoff(self.manager_viewer, grant['handoff_id']), accepted)
        self.bp.propose.assert_called_once()

    def test_ordinary_user_cannot_assign_or_accept_manager_handoff(self):
        record = self.create()
        with self.assertRaises(self.frappe.PermissionError):
            self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], 'other@example.invalid')
        self.assertEqual(self.count('handoffs'), 0)
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        with self.assertRaises(PermissionError):
            self.agent.accept_handoff(self.viewer, grant['handoff_id'])
        self.managers.add('other@example.invalid')
        other = self.gates.Viewer(self.site, 'other@example.invalid', 'o' * 32)
        with self.assertRaises(PermissionError):
            self.agent.preview_handoff(other, grant['handoff_id'])

    def test_edit_invalidates_pending_handoff_but_keeps_history_owned(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        self.update(record)
        with self.assertRaises(PermissionError):
            self.agent.preview_handoff(self.manager_viewer, grant['handoff_id'])
        with self.assertRaises(proposals.ProposalConflict):
            self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        self.assertEqual(self.agent.preview_owned(self.viewer, record['proposal_id'], record['revision'])['components'][0]['state'], 'proposed')

    def test_manager_permission_or_session_revocation_blocks_accept(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        self.managers.remove(self.manager)
        with self.assertRaises(self.frappe.PermissionError):
            self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        self.bp.propose.assert_not_called()
        self.managers.add(self.manager)
        self.sessions.remove(self.manager)
        with self.assertRaises(PermissionError):
            self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])

    def test_unknown_commit_fences_acceptance_no_blind_retry(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        self.frappe.db.commit.side_effect = RuntimeError('commit reply lost')
        with self.assertRaises(RuntimeError):
            self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        retry = self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        self.assertEqual(retry['state'], 'uncertain')
        self.assertFalse(retry['retry_allowed'])
        self.bp.propose.assert_called_once()
        self.frappe.db.rollback.assert_not_called()  # Not an assertion of rollback.

    def test_manager_revoked_after_native_file_save_never_commits(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        self.native_after_propose = lambda: self.managers.remove(self.manager)
        with self.assertRaises(self.frappe.PermissionError):
            self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        self.frappe.db.commit.assert_not_called()
        self.assertEqual(self.repository.grant(self.manager, grant['handoff_id'])['state'], 'uncertain')

    def test_file_acceptance_drift_replay_rechecks_original_owner_revision(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        receipt = self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        self.files[receipt['proposal_id']][1]['title'] = '修改后的文件'
        with self.assertRaises(PermissionError):
            self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        self.bp.propose.assert_called_once()

    def test_repository_binding_corruption_and_inode_replacement_fail_closed(self):
        with closing(sqlite3.connect(self.repository.path)) as db:
            db.execute('UPDATE binding SET site=?', ('other.localhost',))
            db.commit()
        with self.assertRaises(PermissionError):
            proposals.ProposalRepository(self.site, self.root)
        alternate = self.path / 'other.sqlite3'
        alternate.touch(mode=0o600)
        self.repository.path.rename(self.path / 'original.sqlite3')
        alternate.rename(self.repository.path)
        with self.assertRaises(PermissionError):
            self.repository.list(self.owner)

    @unittest.skipUnless(os.name == 'posix', 'POSIX mode/hardlink constraints')
    def test_insecure_file_and_hardlink_rejected_without_chmod(self):
        os.chmod(self.repository.path, 0o644)
        with self.assertRaises(PermissionError):
            proposals.ProposalRepository(self.site, self.root)
        self.assertEqual(self.repository.path.stat().st_mode & 0o777, 0o644)
        os.chmod(self.repository.path, 0o600)
        os.link(self.repository.path, self.path / 'hardlink')
        with self.assertRaises(PermissionError):
            proposals.ProposalRepository(self.site, self.root)

    def test_finite_schema_rejects_bad_ids_page_sizes_and_other_business_key(self):
        for args in ({'cursor': '../file'}, {'page_size': True}, {'page_size': 21}, {'page_size': 0}, {'offset': 0}):
            with self.assertRaises(ValueError):
                self.agent.dispatch(self.claim, 'proposal_list', args, 'list')
        record = self.create()
        with self.assertRaises(ValueError):
            self.agent.dispatch(self.claim, 'proposal_update', {'proposal_id': record['proposal_id'], 'expected_revision': record['revision'], 'spec': dict(record['spec'], key='new_key')}, 'bad-key')
        self.assertEqual(self.count('versions'), 1)

    def test_closed_gate_cannot_reopen_replay_or_change_claim(self):
        self.create()
        self.assertIs(self.repository.open_task(self.claim), True)
        self.assertIs(self.repository.close_task(self.claim.identity, self.claim.claim_id), True)
        self.assertIs(self.repository.close_task(self.claim.identity, self.claim.claim_id), True)
        with self.assertRaises(PermissionError):
            self.repository.open_task(self.claim)
        with self.assertRaises(PermissionError):
            self.create()
        with self.assertRaises(PermissionError):
            self.repository.close_task(self.claim.identity, str(uuid.uuid4()))
        self.assertEqual(self.count('drafts'), 1)

    def test_pre_bind_seal_blocks_late_open_and_missing_gate_blocks_mutation(self):
        identity = replace(self.claim.identity, task_id=str(uuid.uuid4()))
        claim = replace(self.claim, identity=identity, claim_id=str(uuid.uuid4()))
        with self.assertRaises(PermissionError):
            self.repository.mutate(claim, 'proposal_create', {'spec': SPEC}, 'late', authorize=lambda: None)
        self.assertIs(self.repository.close_task(identity, claim.claim_id), True)
        with self.assertRaises(PermissionError):
            self.repository.open_task(claim)
        self.assertEqual(self.count('drafts'), 0)

    def test_close_waits_for_sqlite_mutation_then_permanently_stops_new_writes(self):
        inside, release, close_started = threading.Event(), threading.Event(), threading.Event()
        checks = []
        def authorize():
            self.agent._active(self.claim)
            checks.append(True)
            if len(checks) == 3:
                inside.set()
                if not release.wait(3):
                    raise RuntimeError('test synchronization failed')
        def close():
            close_started.set()
            return self.repository.close_task(self.claim.identity, self.claim.claim_id)
        with ThreadPoolExecutor(max_workers=2) as executor:
            write = executor.submit(self.repository.mutate, self.claim, 'proposal_create', {'spec': SPEC}, 'drain', authorize=authorize)
            try:
                self.assertTrue(inside.wait(3))
                closing_future = executor.submit(close)
                self.assertTrue(close_started.wait(3))
                self.assertFalse(closing_future.done())
            finally:
                release.set()
            record = write.result(3)
            self.assertIs(closing_future.result(3), True)
        self.assertEqual(self.repository.read(self.owner, record['proposal_id'])['state'], 'draft')
        with self.assertRaises(PermissionError):
            self.create(call='after-drain')

    def test_close_failure_does_not_claim_drain(self):
        with patch.object(self.repository, '_connection', side_effect=sqlite3.OperationalError('busy')), self.assertRaises(sqlite3.OperationalError):
            self.repository.close_task(self.claim.identity, self.claim.claim_id)
        self.assertIs(self.repository.open_task(self.claim), True)

    def test_closed_gate_persists_across_repository_restart(self):
        self.repository.close_task(self.claim.identity, self.claim.claim_id)
        reopened = proposals.ProposalRepository(self.site, self.root)
        with self.assertRaises(PermissionError):
            reopened.open_task(self.claim)
        with self.assertRaises(PermissionError):
            reopened.mutate(self.claim, 'proposal_create', {'spec': SPEC}, 'late', authorize=lambda: self.agent._active(self.claim))
        self.assertEqual(self.count('drafts'), 0)

    def test_open_gate_pins_token_and_exact_claim(self):
        for changed in (replace(self.claim, claim_id=str(uuid.uuid4())), replace(self.claim, token='x' * 43)):
            with self.assertRaises(PermissionError):
                self.repository.open_task(changed)
            with self.assertRaises(PermissionError):
                self.repository.mutate(changed, 'proposal_create', {'spec': SPEC}, 'forged', authorize=lambda: None)
        with closing(sqlite3.connect(self.repository.path)) as db:
            row = db.execute('SELECT token_hash FROM task_gates').fetchone()
        self.assertNotEqual(row[0], self.claim.token)
        self.assertEqual(len(row[0]), 64)

    def test_already_accepted_snapshot_is_not_updated_by_owner_edit(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        receipt = self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        updated = self.update(record)
        self.assertNotEqual(receipt['revision'], updated['revision'])
        self.assertEqual(self.agent.accept_handoff(self.manager_viewer, grant['handoff_id']), receipt)
        self.assertEqual(self.files[receipt['proposal_id']][1], record['spec'])

    def test_invalid_native_receipt_never_commits_or_claims_acceptance(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        self.bp.propose.side_effect = None
        self.bp.propose.return_value = {'proposal_id': 'FILE-test', 'revision': '0' * 64, 'state': 'proposed'}
        with self.assertRaises(ValueError):
            self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        self.frappe.db.commit.assert_not_called()
        self.assertEqual(self.repository.grant(self.manager, grant['handoff_id'])['state'], 'uncertain')

    def test_scope_budget_rejection_is_not_empty_and_emits_no_view(self):
        record = self.create()
        later = self.make_claim(self.owner)
        names = ['Test Type ' + str(index) for index in range(256)]
        self.links.update(names)
        full = tuple({'kind': 'doctype', 'doctype': name, 'actions': ['read']} for name in names)
        with patch.object(self.store, 'required_scopes', return_value=full):
            result = self.agent.dispatch(later, 'proposal_list', {}, 'budget')
            self.assertEqual(result['error'], 'scope_budget_exhausted')
            self.assertNotIn('entries', result)
            result = self.agent.dispatch(later, 'proposal_read', {'proposal_id': record['proposal_id']}, 'budget-read')
            self.assertEqual(result['error'], 'scope_budget_exhausted')
            self.assertNotIn('spec', result)
        self.assertFalse(any(event['kind'] == 'view' for event in self.store.events(later.identity)))

    def test_twenty_item_page_deduplicates_shared_links_before_readset_limit(self):
        names = ['Shared Business ' + str(index) for index in range(13)]
        self.links.update(names)
        fields = [{'fieldname': 'linked_' + str(index), 'label': '关联 ' + str(index),
                   'fieldtype': 'Link', 'options': name} for index, name in enumerate(names)]
        for index in range(19):
            self.create(spec=dict(SPEC, key='shared_links_' + str(index), fields=fields), call='shared-' + str(index))
        later = self.make_claim(self.owner)
        result = self.agent.dispatch(later, 'proposal_list', {'page_size': 20}, 'list')
        self.assertEqual(result['page_count'], 19)
        self.assertFalse(result['has_more'])
        scopes = self.store.required_scopes(later.identity)
        # Raw 19 * (one revision + 13 shared Links) = 266 > 256, but
        # the complete unique read set is only 19 + 13 = 32 scopes.
        self.assertEqual(len(scopes), 32)
        for name in names:
            self.assertIn({'kind': 'doctype', 'doctype': name, 'actions': ['read']}, scopes)
        for entry in result['entries']:
            self.assertIn(proposals._capability(entry['proposal_id'], entry['revision']), scopes)

        # Deduplication must not drop the next-page lookahead capability.
        for index in range(19, 21):
            self.create(spec=dict(SPEC, key='shared_links_' + str(index), fields=fields), call='shared-' + str(index))
        paged_claim = self.make_claim(self.owner)
        page = self.agent.dispatch(paged_claim, 'proposal_list', {'page_size': 20}, 'paged-list')
        self.assertEqual(page['page_count'], 20)
        self.assertTrue(page['has_more'])
        all_sources = self.store.required_scopes(paged_claim.identity)
        self.assertEqual(len(all_sources), 34)
        tail = self.agent.dispatch(paged_claim, 'proposal_list', {'page_size': 20, 'cursor': page['next_cursor']}, 'tail')
        self.assertEqual(tail['page_count'], 1)
        entry = tail['entries'][0]
        self.assertIn(proposals._capability(entry['proposal_id'], entry['revision']), all_sources)
        self.assertFalse(tail['has_more'])

    def context_claim(self, owner, selection):
        identity = TaskIdentity(self.site, owner, str(uuid.uuid4()))
        scopes = self.authority.view_scopes(identity, selection)
        self.store.create(owner, identity.task_id, '继续当前页面', {'selection': selection}, authority_scopes=scopes)
        ticket = self.store.take_dispatch(identity)
        self.store.acknowledge_dispatch(ticket)
        return self.store.claim(identity, ticket.job_id)

    def test_sent_context_is_exact_navigation_not_a_read_of_private_rows(self):
        selection = {'view': 'business_proposal_inbox', 'folder': 'sent', 'state': 'all', 'cursor': str(uuid.uuid4())}
        with (patch.object(self.repository, 'handoff_page', side_effect=AssertionError('No page read')),
                patch.object(self.repository, 'read', side_effect=AssertionError('No draft read')),
                patch.object(self.base, 'capture_viewer', side_effect=AssertionError('No manufactured browser session'))):
            claim = self.context_claim(self.owner, selection)
            self.assertEqual(self.store.required_scopes(claim.identity), [{'kind': 'view', 'selection': selection}])
            self.store.emit(claim, {'kind': 'message', 'item_id': 'nav', 'text': '未读取交接记录内容。'})
            self.assertTrue(self.store.events(claim.identity))
        self.bp.propose.assert_not_called()
        self.bp._load.assert_not_called()

    def test_received_navigation_requires_original_manager_permission_on_every_replay(self):
        selection = {'view': 'business_proposal_inbox', 'folder': 'received', 'state': 'pending'}
        with self.assertRaises(self.frappe.PermissionError):
            self.context_claim(self.owner, selection)
        claim = self.context_claim(self.manager, selection)
        self.store.emit(claim, {'kind': 'message', 'item_id': 'nav', 'text': '当前是收到方案页面，并未读入列表。'})
        self.managers.remove(self.manager)
        with self.assertRaises(PermissionError):
            self.store.events(claim.identity)

    def test_received_navigation_does_not_imply_doc_create_permission(self):
        selection = {'view': 'business_proposal_inbox', 'folder': 'received', 'state': 'all'}
        with patch.object(self.frappe, 'has_permission', return_value=False), self.assertRaises(PermissionError):
            self.context_claim(self.manager, selection)

    def test_handoff_context_registers_exact_recipient_version_and_all_links(self):
        linked = dict(SPEC, fields=[{'fieldname': 'student_ref', 'label': '学生', 'fieldtype': 'Link', 'options': 'Student'}])
        record = self.create(spec=linked)
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        selection = {'view': 'business_proposal_handoff', 'handoff_id': grant['handoff_id']}
        claim = self.context_claim(self.manager, selection)
        scopes = self.store.required_scopes(claim.identity)
        self.assertIn({'kind': 'view', 'selection': selection}, scopes)
        capability = proposals._handoff_capability(grant['handoff_id'], record['revision'])
        self.assertIn(capability, scopes)
        self.assertLessEqual(len(capability['name']), 140)
        self.assertIn({'kind': 'doctype', 'doctype': 'Student', 'actions': ['read']}, scopes)
        self.assertNotIn(proposals._capability(record['proposal_id'], record['revision']), scopes)
        self.bp.propose.assert_not_called()
        self.bp._load.assert_not_called()
        self.assertEqual(self.actor.get(), 'outer')
        # Task permission does not depend on keeping the sender's browser SID.
        self.sessions.clear()
        self.assertTrue(self.authority(claim.identity, scopes))
        self.links.remove('Student')
        with self.assertRaises(PermissionError):
            self.store.events(claim.identity)

    def test_handoff_context_is_not_readable_by_sender_or_another_manager(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        selection = {'view': 'business_proposal_handoff', 'handoff_id': grant['handoff_id']}
        self.managers.add('other@example.invalid')
        for owner in (self.owner, 'other@example.invalid'):
            with self.subTest(owner=owner), self.assertRaises(PermissionError):
                self.context_claim(owner, selection)
        identity = replace(self.claim.identity, owner=self.manager, site='other.localhost')
        with self.assertRaises(PermissionError):
            self.authority.view_scopes(identity, selection)

    def test_pending_handoff_invalidated_by_revision_blocks_old_context_history(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        claim = self.context_claim(self.manager, {'view': 'business_proposal_handoff', 'handoff_id': grant['handoff_id']})
        self.store.emit(claim, {'kind': 'message', 'item_id': 'old', 'text': '旧版讨论'})
        self.update(record)
        with self.assertRaises(PermissionError):
            self.store.events(claim.identity)

    def test_accepted_handoff_context_keeps_original_version_without_loading_native_file(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        self.agent.accept_handoff(self.manager_viewer, grant['handoff_id'])
        self.update(record)
        self.bp._load.reset_mock()
        with patch.object(self.bp, '_load', side_effect=AssertionError('Native File is browser-only')):
            claim = self.context_claim(self.manager, {'view': 'business_proposal_handoff', 'handoff_id': grant['handoff_id']})
            self.assertIn(proposals._handoff_capability(grant['handoff_id'], record['revision']), self.store.required_scopes(claim.identity))
        self.assertEqual(len(self.files), 1)

    def test_context_never_discards_previous_full_scope_union(self):
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        claim = self.context_claim(self.manager, {'view': 'business_proposal_handoff', 'handoff_id': grant['handoff_id']})
        self.store.register_authority(claim, {'kind': 'doctype', 'doctype': 'Supplier', 'actions': ['read']})
        self.links.remove('Supplier')
        sent = self.authority.view_scopes(claim.identity, {'view': 'business_proposal_inbox', 'folder': 'sent'})
        with self.assertRaises(PermissionError):
            self.authority.register_read(self.store, claim, self.gates.ReadSet(sent))
        with self.assertRaises(PermissionError):
            self.store.events(claim.identity)

    def test_malformed_context_and_forged_revision_capability_fail_closed(self):
        for selection in (
                {'view': 'business_proposal_inbox', 'folder': 'sent', 'state': 'pending'},
                {'view': 'business_proposal_inbox', 'folder': 'all'},
                {'view': 'business_proposal_inbox', 'folder': 'sent', 'owner': self.manager},
                {'view': 'business_proposal_handoff', 'handoff_id': str(uuid.uuid4()), 'revision': '0' * 64}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.authority.view_scopes(self.claim.identity, selection)
        record = self.create()
        grant = self.agent.handoff(self.viewer, record['proposal_id'], record['revision'], self.manager)
        identity = replace(self.claim.identity, owner=self.manager)
        self.assertFalse(self.authority(identity, (proposals._handoff_capability(grant['handoff_id'], '0' * 64),)))
        self.enabled.remove(self.manager)
        with self.assertRaises(PermissionError):
            self.authority.view_scopes(identity, {'view': 'business_proposal_handoff', 'handoff_id': grant['handoff_id']})

    def test_context_support_does_not_add_handoff_or_acceptance_model_tools(self):
        for tool in ('handoff', 'accept_handoff', 'proposal_accept', 'proposal_handoff'):
            with self.subTest(tool=tool), self.assertRaises(ValueError):
                self.agent.dispatch(self.claim, tool, {}, 'model-accept')
        self.bp.propose.assert_not_called()
        self.bp.activate.assert_not_called()

    def inbox_catalog(self, *, authority=None):
        from tongjianyun import business_agent_catalog as catalog
        # Only the native scene gate is doubled. The actual proposal authority,
        # full-union registration, SQLite task/event store and view schema run.
        def check(scope):
            if scope == self.gates._capability(self.gates.SCENE):
                return
            self.check_scope(scope)
        self.stack.enter_context(patch.object(self.gates, '_check_scope', check))
        self.stack.enter_context(patch.object(catalog, '_services',
            return_value=(self.frappe, self.gates, SimpleNamespace())))
        return catalog.BusinessCatalog(authority or self.authority, self.store)

    def open_inbox(self, reader, claim, **fields):
        return reader.dispatch(claim, 'business_view', {'selection': {
            'view': 'business_proposal_inbox', 'folder': 'received', **fields}})

    def test_catalog_received_inbox_persists_exact_scope_without_reading_private_rows(self):
        reader, claim = self.inbox_catalog(), self.make_claim(self.manager)
        with (patch.object(self.repository, 'handoff_page', side_effect=AssertionError('No page data in model')),
                patch.object(self.repository, 'read', side_effect=AssertionError('No draft data in model')),
                patch.object(self.repository, 'grant', side_effect=AssertionError('No individual grant read')),
                patch.object(self.base, 'capture_viewer', side_effect=AssertionError('No fake Viewer'))):
            result = self.open_inbox(reader, claim)
            self.assertEqual(result['selection'], {'view': 'business_proposal_inbox', 'folder': 'received', 'state': 'pending'})
            self.assertEqual(set(result), {'available', 'selection', 'display_requested', 'data_read',
                                          'executed_business_operation', 'display_note'})
            self.assertTrue(result['display_requested'])
            self.assertIs(result['data_read'], False)
            self.assertIs(result['executed_business_operation'], False)
            self.assertCountEqual(self.store.required_scopes(claim.identity), [
                self.gates._capability(self.gates.SCENE), {'kind': 'view', 'selection': result['selection']}])
            view = [event for event in self.store.events(claim.identity) if event['kind'] == 'view']
            self.assertEqual(len(view), 1)
            self.assertEqual(set(view[0]), {'id', 'kind', 'version', 'selection', 'title'})
            self.assertEqual(view[0]['selection'], result['selection'])
        self.bp.propose.assert_not_called()
        self.bp.activate.assert_not_called()
        self.bp._load.assert_not_called()
        self.frappe.db.commit.assert_not_called()
        self.assertEqual(self.actor.get(), 'outer')

    def test_catalog_received_inbox_browser_get_uses_only_its_real_recipient(self):
        from tongjianyun import business_proposal_views as views
        first = self.create()
        self.agent.handoff(self.viewer, first['proposal_id'], first['revision'], self.manager)
        other = 'other@example.invalid'
        self.managers.add(other)
        second = self.create(spec=dict(SPEC, key='another_log', title='只交给其他负责人'), call='second')
        self.agent.handoff(self.viewer, second['proposal_id'], second['revision'], other)
        result = self.open_inbox(self.inbox_catalog(), self.make_claim(self.manager))
        with patch.object(views, '_application', return_value=(self.agent, self.manager_viewer)):
            page = views.get_view(result['selection'])
        rows = page['components'][0]['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['cells'][0], first['spec']['title'])
        self.assertNotIn(second['spec']['title'], str(page))
        self.assertNotIn(first['spec']['title'], str(result))
        self.assertEqual(self.count('handoffs'), 2)
        self.assertEqual(self.files, {})
        self.bp.activate.assert_not_called()

    def test_catalog_received_inbox_original_manager_and_structure_gates_remain_required(self):
        reader = self.inbox_catalog()
        with self.assertRaises(self.frappe.PermissionError):
            self.open_inbox(reader, self.claim)
        claim = self.make_claim(self.manager)
        with patch.object(self.frappe, 'has_permission', return_value=False), self.assertRaises(PermissionError):
            self.open_inbox(reader, claim)
        self.assertFalse(any(event['kind'] == 'view' for event in self.store.events(claim.identity)))

    def test_catalog_received_inbox_no_proposal_wrapper_fails_without_generic_whitelist(self):
        reader = self.inbox_catalog(authority=self.base)
        self.assertNotIn('business_proposal_inbox', self.tools.VIEW_FIELDS)
        # The base resolves this import before validating its finite tool
        # schema. Its native canonicalizer must never be reached for inbox.
        native_views = ModuleType('tongjianyun.meal_views')
        native_views.selection = MagicMock(side_effect=AssertionError('No generic view fallback'))
        with patch.dict(sys.modules, {'tongjianyun.meal_views': native_views}), self.assertRaises(ValueError):
            self.open_inbox(reader, self.make_claim(self.manager))
        native_views.selection.assert_not_called()
        self.assertNotIn('business_blueprint', self.tools.VIEW_FIELDS)

    def test_catalog_received_inbox_replay_rechecks_manager_and_old_source_union(self):
        reader, claim = self.inbox_catalog(), self.make_claim(self.manager)
        self.store.register_authority(claim, {'kind': 'doctype', 'doctype': 'Supplier', 'actions': ['read']})
        self.open_inbox(reader, claim)
        self.managers.remove(self.manager)
        with self.assertRaises(PermissionError):
            self.store.events(claim.identity)
        with self.assertRaises(PermissionError):
            self.store.history(self.manager)
        self.managers.add(self.manager)
        self.assertTrue(self.store.events(claim.identity))
        self.assertEqual(self.store.history(self.manager)['tasks'][0]['task_id'], claim.identity.task_id)
        self.links.remove('Supplier')
        with self.assertRaises(PermissionError):
            self.store.events(claim.identity)
        with self.assertRaises(PermissionError):
            self.open_inbox(reader, claim, state='all')

    def test_catalog_received_inbox_cross_identity_and_cancelled_claim_refused(self):
        reader, claim = self.inbox_catalog(), self.make_claim(self.manager)
        for identity in (replace(claim.identity, owner='other@example.invalid'),
                         replace(claim.identity, site='other.localhost')):
            with self.subTest(identity=identity), self.assertRaises(PermissionError):
                self.open_inbox(reader, replace(claim, identity=identity))
        self.store.cancel(claim.identity)
        with self.assertRaises(PermissionError):
            self.open_inbox(reader, claim)

    def test_catalog_received_inbox_budget_refusal_is_not_empty_inbox(self):
        from tongjianyun import business_agent_catalog as catalog
        reader, claim = self.inbox_catalog(), self.make_claim(self.manager)
        with patch.object(catalog, 'MAX_SCOPES', 1):
            result = self.open_inbox(reader, claim)
        self.assertEqual(result['error'], 'scope_budget_exhausted')
        self.assertFalse(result['available'])
        self.assertNotIn('page_count', result)
        self.assertFalse(any(event['kind'] == 'view' for event in self.store.events(claim.identity)))

    def test_catalog_received_inbox_revoke_before_publish_never_emits_view(self):
        reader, claim = self.inbox_catalog(), self.make_claim(self.manager)
        original = self.authority.register_read
        def revoke(*args):
            original(*args)
            self.managers.remove(self.manager)
        with patch.object(self.authority, 'register_read', side_effect=revoke), self.assertRaises(PermissionError):
            self.open_inbox(reader, claim)
        self.managers.add(self.manager)
        self.assertFalse(any(event['kind'] == 'view' for event in self.store.events(claim.identity)))


if __name__ == '__main__':
    unittest.main()
