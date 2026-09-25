"""HTTP contracts + real private proposals, original validators and task store.

No Frappe site or model is started. Native authentication/CSRF middleware is not
reimplemented: decorator and request-boundary tests verify its required wiring;
real framework/browser CSRF acceptance remains an isolated integration check.
"""
from dataclasses import replace
import inspect
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from tongjianyun.tests import test_business_agent_proposals as fixtures


class ProposalAPITests(unittest.TestCase):
    def setUp(self):
        # Composition avoids rerunning all fixture class test methods as API
        # tests. The actual blueprint/gate/task implementations remain in use.
        self.fixture = fixtures.ProposalTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.current_viewer = f.viewer
        f.frappe.ValidationError = type('NativeValidationError', (Exception,), {})
        f.frappe.local = SimpleNamespace(request=SimpleNamespace(method='POST'), response={})
        f.frappe.form_dict = {}
        f.frappe.conf = SimpleNamespace(ignore_csrf=False)
        f.frappe.session = SimpleNamespace(data={'csrf_token': 'c' * 32})
        def whitelist(*, methods, allow_guest=False):
            def decorate(function):
                function.allowed_methods = methods
                function.allow_guest = allow_guest
                return function
            return decorate
        f.frappe.whitelist = whitelist
        self.workspace = ModuleType('tongjianyun.workspace_entry')
        def account():
            if self.current_viewer.owner not in f.enabled:
                raise f.frappe.PermissionError('private account facts')
        def private():
            f.frappe.local.response['headers'] = {'Cache-Control': 'private, no-store'}
        self.workspace.require_account = MagicMock(side_effect=account)
        self.workspace.mark_private_response = MagicMock(side_effect=private)
        self.app = SimpleNamespace(proposals=f.agent, viewer=MagicMock(side_effect=lambda: self.current_viewer))
        self.service = ModuleType('tongjianyun.business_agent_service')
        self.runtime = MagicMock()
        self.service.application = MagicMock(return_value=(self.app, self.runtime))
        self.http = fixtures.load_private(f.stack, 'business_proposal_api.py',
            {'frappe': f.frappe, 'tongjianyun.business_agent_service': self.service,
             'tongjianyun.workspace_entry': self.workspace})
        self.record = f.create()

    def call(self, name, *, method=None, raw_extra=None, **arguments):
        f = self.fixture
        function = getattr(self.http, name)
        f.frappe.local.request.method = method or function.allowed_methods[0]
        f.frappe.form_dict = {**arguments, **(raw_extra or {})}
        f.frappe.local.response = {}
        return function(**arguments)

    def handoff(self, record=None, recipient=None):
        f = self.fixture
        record = record or self.record
        return self.call('handoff', proposal_id=record['proposal_id'], revision=record['revision'], recipient=recipient or f.manager)

    def test_native_whitelist_post_actions_get_readers_and_no_guests(self):
        expected = {'check_recipient': 'POST', 'handoff': 'POST', 'accept_handoff': 'POST',
                    'list_sent': 'GET', 'list_received': 'GET', 'preview_handoff': 'GET'}
        for name, method in expected.items():
            function = getattr(self.http, name)
            self.assertEqual(function.allowed_methods, [method])
            self.assertFalse(function.allow_guest)
            self.assertNotIn('owner', inspect.signature(function).parameters)
            self.assertNotIn('site', inspect.signature(function).parameters)
        self.assertFalse(hasattr(self.http, 'activate'))

    def test_authentication_precedes_adapter_and_errors_are_private_fixed(self):
        f = self.fixture
        self.current_viewer = replace(f.viewer, owner='Guest')
        with self.assertRaises(f.frappe.PermissionError) as error:
            self.call('list_sent')
        self.assertEqual(str(error.exception), self.http.PERMISSION_MESSAGE)
        self.service.application.assert_not_called()
        self.assertEqual(f.frappe.local.response['headers']['Cache-Control'], 'private, no-store')

    def test_unconfigured_adapter_is_denied_without_old_admin_fallback(self):
        f = self.fixture
        self.app.proposals = None
        with self.assertRaises(f.frappe.PermissionError):
            self.call('list_sent')
        f.bp.propose.assert_not_called()
        f.bp.activate.assert_not_called()

    def test_handoff_uses_captured_live_viewer_no_model_or_enable(self):
        f = self.fixture
        result = self.handoff()
        self.assertEqual(result['revision'], self.record['revision'])
        self.assertEqual(result['state'], 'pending')
        self.assertFalse(result['enabled'])
        self.service.application.assert_called_once_with(require_ready=False)
        self.app.viewer.assert_called_once_with()
        self.assertEqual(f.repository.grant(f.manager, result['handoff_id'])['sender'], f.owner)
        self.assertEqual(self.runtime.mock_calls, [])
        f.bp.propose.assert_not_called()
        f.bp.activate.assert_not_called()

    def test_mutations_reject_get_and_csrf_disabled_site(self):
        f = self.fixture
        for name, arguments in [('handoff', {'proposal_id': self.record['proposal_id'], 'revision': self.record['revision'], 'recipient': f.manager}),
                                ('accept_handoff', {'handoff_id': self.record['proposal_id']}),
                                ('check_recipient', {'proposal_id': self.record['proposal_id'], 'revision': self.record['revision'], 'recipient': f.manager})]:
            with self.subTest(name=name), self.assertRaises(f.frappe.PermissionError):
                self.call(name, method='GET', **arguments)
        self.assertEqual(f.count('handoffs'), 0)
        f.frappe.conf.ignore_csrf = True
        with self.assertRaises(f.frappe.PermissionError):
            self.handoff()
        self.assertEqual(f.count('handoffs'), 0)
        self.service.application.assert_not_called()

    def test_native_session_without_saved_csrf_token_cannot_transfer(self):
        f = self.fixture
        for data in (None, {}, {'csrf_token': ''}, {'csrf_token': 'c' * 257}):
            f.frappe.session.data = data
            with self.assertRaises(f.frappe.PermissionError):
                self.handoff()
        self.assertEqual(f.count('handoffs'), 0)
        self.service.application.assert_not_called()
        # Missing CSRF token does not prevent authenticated read-only history.
        self.assertEqual(self.call('list_sent')['entries'], [])

    def test_parameter_filtering_cannot_hide_identity_execution_fields(self):
        f = self.fixture
        for field in ('owner', 'site', 'actor', 'ignore_permissions', 'method', 'sql', 'token', 'session'):
            with self.subTest(field=field), self.assertRaises(f.frappe.ValidationError) as error:
                self.call('handoff', proposal_id=self.record['proposal_id'], revision=self.record['revision'], recipient=f.manager,
                          raw_extra={field: 'Administrator'})
            self.assertEqual(str(error.exception), self.http.INPUT_MESSAGE)
        self.assertEqual(f.count('handoffs'), 0)

    def test_native_transport_fields_do_not_become_actor_credentials(self):
        result = self.call('list_sent', raw_extra={'cmd': 'native-selected-method', 'csrf_token': 'native-checked-token', '_': '123'})
        self.assertEqual(result['entries'], [])
        self.assertNotIn('native-checked-token', str(result))

    def test_check_recipient_exact_name_eligible_without_user_enumeration(self):
        f = self.fixture
        result = self.call('check_recipient', proposal_id=self.record['proposal_id'], revision=self.record['revision'], recipient=f.manager)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['recipient'], f.manager)
        self.assertFalse(result['enabled'])
        self.assertNotIn('users', result)
        self.assertNotIn('roles', result)
        self.assertEqual(f.count('handoffs'), 0)
        self.assertFalse(hasattr(f.frappe, 'get_all'))

    def test_unknown_disabled_nonmanager_and_self_have_same_recipient_response(self):
        f = self.fixture
        results = []
        for name in ('missing@example.invalid', 'other@example.invalid', f.owner):
            results.append(self.call('check_recipient', proposal_id=self.record['proposal_id'], revision=self.record['revision'], recipient=name))
        f.enabled.remove(f.manager)
        results.append(self.call('check_recipient', proposal_id=self.record['proposal_id'], revision=self.record['revision'], recipient=f.manager))
        for result in results:
            self.assertEqual(result, results[0])
            self.assertFalse(result['eligible'])
            self.assertIsNone(result['recipient'])

    def test_recipient_check_cannot_read_another_users_proposal(self):
        f = self.fixture
        self.current_viewer = replace(f.viewer, owner='other@example.invalid')
        with self.assertRaises(f.frappe.PermissionError):
            self.call('check_recipient', proposal_id=self.record['proposal_id'], revision=self.record['revision'], recipient=f.manager)

    def test_exact_revision_stale_after_edit_denied_and_fixed_conflict(self):
        f = self.fixture
        f.update(self.record)
        for name in ('handoff', 'check_recipient'):
            with self.subTest(name=name), self.assertRaises(f.frappe.ValidationError) as error:
                self.call(name, proposal_id=self.record['proposal_id'], revision=self.record['revision'], recipient=f.manager)
            self.assertEqual(str(error.exception), self.http.INPUT_MESSAGE)
        self.assertEqual(f.count('handoffs'), 0)

    def test_sender_and_recipient_lists_are_scoped_no_private_file_or_spec(self):
        f = self.fixture
        grant = self.handoff()
        sent = self.call('list_sent')
        self.assertEqual(sent['page_count'], 1)
        entry = sent['entries'][0]
        self.assertEqual(entry['recipient'], f.manager)
        self.assertEqual(entry['handoff_id'], grant['handoff_id'])
        self.assertFalse(entry['can_accept'])
        self.assertFalse(entry['enabled'])
        self.assertNotIn('spec', entry)
        self.assertNotIn('receipt', entry)
        self.current_viewer = f.manager_viewer
        incoming = self.call('list_received')
        self.assertEqual(incoming['entries'][0]['sender'], f.owner)
        self.assertTrue(incoming['entries'][0]['can_accept'])
        self.assertEqual(self.call('list_sent')['entries'], [])
        self.current_viewer = replace(f.viewer, owner='other@example.invalid')
        self.assertEqual(self.call('list_sent')['entries'], [])
        with self.assertRaises(f.frappe.PermissionError):
            self.call('list_received')

    def test_other_manager_cannot_list_or_preview_unassigned_handoff(self):
        f = self.fixture
        grant = self.handoff()
        f.managers.add('other@example.invalid')
        self.current_viewer = replace(f.viewer, owner='other@example.invalid')
        self.assertEqual(self.call('list_received')['entries'], [])
        with self.assertRaises(f.frappe.PermissionError):
            self.call('preview_handoff', handoff_id=grant['handoff_id'])

    def test_pending_edit_stale_visible_to_sender_not_receiver(self):
        f = self.fixture
        grant = self.handoff()
        f.update(self.record)
        sent = self.call('list_sent')
        self.assertEqual(sent['entries'][0]['state'], 'stale')
        self.current_viewer = f.manager_viewer
        self.assertEqual(self.call('list_received')['entries'], [])
        self.assertEqual(self.call('list_received', state='all')['entries'], [])
        with self.assertRaises(f.frappe.PermissionError):
            self.call('preview_handoff', handoff_id=grant['handoff_id'])

    def test_receiver_preview_is_get_only_exact_recipient_and_not_activation(self):
        f = self.fixture
        grant = self.handoff()
        with self.assertRaises(f.frappe.PermissionError):
            self.call('preview_handoff', handoff_id=grant['handoff_id'])
        self.current_viewer = f.manager_viewer
        preview = self.call('preview_handoff', handoff_id=grant['handoff_id'])
        self.assertEqual(preview['handoff_state'], 'pending')
        self.assertEqual(preview['sender'], f.owner)
        self.assertNotIn('selection', preview)
        self.assertNotIn('accepted_selection', preview)
        self.assertNotIn('can_handoff', preview['components'][0])
        self.assertFalse(preview['components'][0]['can_activate'])
        f.bp.propose.assert_not_called()
        f.frappe.db.commit.assert_not_called()

    def test_accept_only_recipient_original_file_copy_not_schema(self):
        f = self.fixture
        grant = self.handoff()
        with self.assertRaises(f.frappe.PermissionError):
            self.call('accept_handoff', handoff_id=grant['handoff_id'])
        self.current_viewer = f.manager_viewer
        result = self.call('accept_handoff', handoff_id=grant['handoff_id'])
        self.assertEqual(result['state'], 'accepted')
        self.assertFalse(result['enabled'])
        self.assertEqual(f.files[result['proposal_id']][0], f.manager)
        self.assertEqual(result['selection']['view'], 'business_blueprint')
        f.bp.activate.assert_not_called()
        f.bp.propose.assert_called_once()
        f.frappe.db.commit.assert_called_once()
        self.assertEqual(self.call('list_received')['entries'], [])
        accepted = self.call('list_received', state='all')['entries'][0]
        self.assertEqual(accepted['state'], 'accepted')
        self.assertFalse(accepted['can_accept'])
        self.assertEqual(self.call('accept_handoff', handoff_id=grant['handoff_id']), result)
        f.bp.propose.assert_called_once()

    def test_unknown_copy_commit_sanitized_fenced_and_visible_without_retry(self):
        f = self.fixture
        grant = self.handoff()
        self.current_viewer = f.manager_viewer
        f.frappe.db.commit.side_effect = RuntimeError('/private/files/secret.json private SQL token')
        with self.assertRaises(f.frappe.ValidationError) as error:
            self.call('accept_handoff', handoff_id=grant['handoff_id'])
        self.assertEqual(str(error.exception), self.http.UNAVAILABLE_MESSAGE)
        self.assertIs(f.frappe.local.response['proposal_retry_allowed'], False)
        self.assertIs(f.frappe.local.response['proposal_result_unconfirmed'], True)
        rows = self.call('list_received')['entries']
        self.assertEqual(rows[0]['state'], 'uncertain')
        self.assertFalse(rows[0]['can_accept'])
        result = self.call('accept_handoff', handoff_id=grant['handoff_id'])
        self.assertEqual(result['state'], 'uncertain')
        self.assertFalse(result['retry_allowed'])
        f.bp.propose.assert_called_once()

    def test_manager_permission_and_session_revocation_deny_list_and_accept(self):
        f = self.fixture
        grant = self.handoff()
        self.current_viewer = f.manager_viewer
        f.managers.remove(f.manager)
        for name, arguments in [('list_received', {}), ('preview_handoff', {'handoff_id': grant['handoff_id']}),
                                ('accept_handoff', {'handoff_id': grant['handoff_id']})]:
            with self.subTest(name=name), self.assertRaises(f.frappe.PermissionError):
                self.call(name, **arguments)
        f.managers.add(f.manager)
        f.sessions.remove(f.manager)
        with self.assertRaises(f.frappe.PermissionError):
            self.call('list_received')
        f.bp.propose.assert_not_called()

    def test_link_revocation_denies_list_instead_of_reporting_empty(self):
        f = self.fixture
        linked = f.create(spec=dict(fixtures.SPEC, key='linked_proposal', fields=[
            {'fieldname': 'student_link', 'label': '学生', 'fieldtype': 'Link', 'options': 'Student'}]), call='linked')
        self.handoff(linked)
        f.links.remove('Student')
        with self.assertRaises(f.frappe.PermissionError):
            self.call('list_sent')
        self.current_viewer = f.manager_viewer
        with self.assertRaises(f.frappe.PermissionError):
            self.call('list_received')

    def test_pagination_is_bounded_complete_and_preserves_uncertain_attention(self):
        f = self.fixture
        grant = self.handoff()
        for index in range(2):
            record = f.create(spec=dict(fixtures.SPEC, key='paged_' + str(index)), call='paged-' + str(index))
            self.handoff(record)
        first = self.call('list_sent', page_size='2')
        self.assertEqual(first['page_count'], 2)
        self.assertTrue(first['has_more'])
        second = self.call('list_sent', page_size=2, cursor=first['next_cursor'])
        self.assertEqual(second['page_count'], 1)
        self.assertFalse(second['has_more'])
        self.assertEqual(len({row['handoff_id'] for row in first['entries'] + second['entries']}), 3)
        f.repository.transition(f.manager, grant['handoff_id'], 'pending', 'copying')
        self.current_viewer = f.manager_viewer
        received = self.call('list_received')
        copying = next(row for row in received['entries'] if row['handoff_id'] == grant['handoff_id'])
        self.assertFalse(copying['can_accept'])
        self.assertFalse(copying['retry_allowed'])

    def test_finite_http_schema_rejects_bad_ids_filters_limits(self):
        f = self.fixture
        for size in ('01', '2.0', '21', '-1', '1' * 5000, 0, True, []):
            with self.subTest(size=str(size)[:20]), self.assertRaises(f.frappe.ValidationError):
                self.call('list_sent', page_size=size)
        for cursor in ('../private', '', self.record['revision']):
            with self.assertRaises(f.frappe.ValidationError):
                self.call('list_sent', cursor=cursor)
        self.current_viewer = f.manager_viewer
        for state in ('accepted', 'all OR 1=1', [], {'owner': f.owner}):
            with self.assertRaises(f.frappe.ValidationError):
                self.call('list_received', state=state)

    def test_all_unexpected_errors_have_fixed_message_without_private_text(self):
        f = self.fixture
        self.service.application.side_effect = RuntimeError('redis://password@private-host:6379 /home/private')
        with self.assertRaises(f.frappe.ValidationError) as error:
            self.call('list_sent')
        self.assertEqual(str(error.exception), self.http.UNAVAILABLE_MESSAGE)
        self.assertLess(len(str(error.exception)), 100)

    def test_real_viewer_binding_not_dictionary_identity_or_wrong_site(self):
        f = self.fixture
        self.current_viewer = replace(f.viewer, site='another.localhost')
        with self.assertRaises(f.frappe.PermissionError):
            self.call('list_sent')
        self.current_viewer = SimpleNamespace(owner=f.owner, site=f.site, sid=f.viewer.sid)
        with self.assertRaises(f.frappe.PermissionError):
            self.call('list_sent')

    def test_owner_preview_handoff_button_only_for_current_owned_revision(self):
        f = self.fixture
        preview = f.agent.preview_owned(f.viewer, self.record['proposal_id'], self.record['revision'])
        self.assertTrue(preview['components'][0]['can_handoff'])
        self.assertEqual(preview['summary']['state'], 'draft')
        f.update(self.record)
        old = f.agent.preview_owned(f.viewer, self.record['proposal_id'], self.record['revision'])
        self.assertFalse(old['components'][0]['can_handoff'])

    def test_accepted_get_preview_reads_original_file_no_mutator(self):
        f = self.fixture
        grant = self.handoff()
        self.current_viewer = f.manager_viewer
        receipt = self.call('accept_handoff', handoff_id=grant['handoff_id'])
        f.bp.propose.reset_mock()
        f.frappe.db.commit.reset_mock()
        with patch.object(f.agent, 'accept_handoff', side_effect=AssertionError('GET must not invoke mutation')):
            preview = self.call('preview_handoff', handoff_id=grant['handoff_id'])
        self.assertEqual(preview['accepted_selection'], receipt['selection'])
        self.assertEqual(preview['sender'], f.owner)
        self.assertEqual(preview['summary']['handoff_state'], 'accepted')
        self.assertNotIn('can_handoff', preview['components'][0])
        f.bp._load.assert_called_with(receipt['proposal_id'])
        f.bp.propose.assert_not_called()
        f.frappe.db.commit.assert_not_called()

    def test_accepted_preview_drift_missing_file_and_revocation_never_return_selection(self):
        f = self.fixture
        grant = self.handoff()
        self.current_viewer = f.manager_viewer
        receipt = self.call('accept_handoff', handoff_id=grant['handoff_id'])
        f.files[receipt['proposal_id']][1]['title'] = '已被修改的文件'
        with self.assertRaises(f.frappe.PermissionError):
            self.call('preview_handoff', handoff_id=grant['handoff_id'])
        f.files.clear()
        with self.assertRaises(f.frappe.ValidationError) as error:
            self.call('preview_handoff', handoff_id=grant['handoff_id'])
        self.assertEqual(str(error.exception), self.http.UNAVAILABLE_MESSAGE)
        f.managers.remove(f.manager)
        with self.assertRaises(f.frappe.PermissionError):
            self.call('preview_handoff', handoff_id=grant['handoff_id'])

    def test_rehandoff_same_revision_cannot_bypass_uncertain_copy_fence(self):
        f = self.fixture
        grant = self.handoff()
        self.current_viewer = f.manager_viewer
        f.frappe.db.commit.side_effect = RuntimeError('unknown commit')
        with self.assertRaises(f.frappe.ValidationError):
            self.call('accept_handoff', handoff_id=grant['handoff_id'])
        self.current_viewer = f.viewer
        duplicate = self.handoff()
        self.assertEqual(duplicate['handoff_id'], grant['handoff_id'])
        self.assertEqual(duplicate['state'], 'uncertain')
        self.assertEqual(f.count('handoffs'), 1)
        self.current_viewer = f.manager_viewer
        self.assertFalse(self.call('accept_handoff', handoff_id=duplicate['handoff_id'])['retry_allowed'])
        f.bp.propose.assert_called_once()

    def test_rehandoff_same_revision_reuses_accepted_file_receipt(self):
        f = self.fixture
        grant = self.handoff()
        self.current_viewer = f.manager_viewer
        receipt = self.call('accept_handoff', handoff_id=grant['handoff_id'])
        self.current_viewer = f.viewer
        duplicate = self.handoff()
        self.assertEqual(duplicate['handoff_id'], grant['handoff_id'])
        self.assertEqual(duplicate['state'], 'accepted')
        self.current_viewer = f.manager_viewer
        self.assertEqual(self.call('accept_handoff', handoff_id=duplicate['handoff_id']), receipt)
        f.bp.propose.assert_called_once()

    def test_list_checks_link_permissions_of_lookahead_too(self):
        f = self.fixture
        sources = {}
        for index, name in enumerate(('Student', 'Supplier')):
            record = f.create(spec=dict(fixtures.SPEC, key='lookahead_' + str(index), fields=[
                {'fieldname': 'related', 'label': '关联', 'fieldtype': 'Link', 'options': name}]), call='lookahead-' + str(index))
            grant = self.handoff(record)
            sources[grant['handoff_id']] = name
        # With size=1 the second sorted handoff is only the has_more source.
        f.links.remove(sources[max(sources)])
        with self.assertRaises(f.frappe.PermissionError):
            self.call('list_sent', page_size=1)
        self.current_viewer = f.manager_viewer
        with self.assertRaises(f.frappe.PermissionError):
            self.call('list_received', page_size=1)


if __name__ == '__main__':
    unittest.main()
