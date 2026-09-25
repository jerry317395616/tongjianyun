import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tongjianyun import business_proposal_views as views

PROPOSAL = '11111111-1111-4111-8111-111111111111'
HANDOFF = '22222222-2222-4222-8222-222222222222'
REVISION = 'a' * 64


class ProposalViewTests(unittest.TestCase):
    def setUp(self):
        self.adapter = MagicMock()
        self.viewer = SimpleNamespace(owner='manager', site='qa')
        self.service = patch.object(views, '_application', return_value=(self.adapter, self.viewer))
        self.service.start()
        self.addCleanup(self.service.stop)
        self.choice = {'view': 'business_proposal_handoff', 'handoff_id': HANDOFF}
        self.preview = {'handoff_id': HANDOFF, 'handoff_state': 'pending', 'sender': '<script>teacher',
                        'title': '活动登记', 'components': [{'type': 'business_proposal', 'proposal_id': PROPOSAL,
                        'revision': REVISION, 'can_activate': False}], 'actions': [], 'source': 'private'}
        self.adapter.preview_handoff.return_value = self.preview
        self.page = {'entries': [{'handoff_id': HANDOFF, 'proposal_id': PROPOSAL, 'revision': REVISION,
                    'title': '私有方案', 'state': 'pending', 'sender': 'teacher', 'recipient': 'manager'}],
                     'has_more': False, 'next_cursor': None, 'scope': 'owner-scoped', 'note': 'not activation'}
        self.adapter.list_sent.return_value = self.page
        self.adapter.list_received.return_value = self.page

    def test_canonical_timeless_selection(self):
        self.assertEqual(views.selection(self.choice), self.choice)
        self.assertEqual(views.selection({'view': 'business_proposal_inbox', 'folder': 'sent'}),
                         {'view': 'business_proposal_inbox', 'folder': 'sent', 'state': 'all'})
        self.assertEqual(views.selection({'view': 'business_proposal_inbox', 'folder': 'received'})['state'], 'pending')

    def test_rejects_identity_scripts_unrelated_filters_and_bad_ids(self):
        for extra in ({'owner': 'other'}, {'site': 'other'}, {'recipient': 'other'}, {'day': '2026-09-22'},
                      {'components': ['table']}, {'html': '<script>'}, {'state': 'accepted'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                views.selection({**self.choice, **extra})
        for value in (None, {}, {'view': 'unknown'}, {**self.choice, 'handoff_id': 'invalid'},
                      {'view': 'business_proposal_inbox', 'folder': 'sent', 'state': 'pending'},
                      {'view': 'business_proposal_inbox', 'folder': ['received']},
                      {'view': 'business_proposal_inbox', 'folder': 'received', 'cursor': None}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                views.selection(value)

    def test_sent_list_can_only_open_own_fixed_version(self):
        result = views.get_view({'view': 'business_proposal_inbox', 'folder': 'sent'})
        self.adapter.list_sent.assert_called_once_with(self.viewer, cursor=None, size=10)
        target = result['components'][0]['rows'][0]['action']['selection']
        self.assertEqual(target, {'view': 'business_proposal', 'proposal_id': PROPOSAL, 'revision': REVISION})
        self.assertFalse(result['summary']['activation_verified'])
        self.assertNotIn('teacher', str(result['summary']))
        self.adapter.accept_handoff.assert_not_called()

    def test_received_list_binds_current_viewer_and_all_pages(self):
        self.page.update(has_more=True, next_cursor=HANDOFF)
        choice = {'view': 'business_proposal_inbox', 'folder': 'received', 'state': 'all', 'cursor': PROPOSAL}
        result = views.get_view(choice)
        self.adapter.list_received.assert_called_once_with(self.viewer, cursor=PROPOSAL, size=10, state='all')
        self.assertEqual(result['components'][0]['rows'][0]['action']['selection'], self.choice)
        self.assertEqual(result['actions'][1]['selection']['cursor'], HANDOFF)
        self.assertNotIn('cursor', result['actions'][0]['selection'])

    def test_empty_list_is_not_zero_enabled_businesses(self):
        self.page['entries'] = []
        result = views.get_view({'view': 'business_proposal_inbox', 'folder': 'sent'})
        self.assertIn('暂无可见', result['components'][1]['text'])
        self.assertIn('不代表', result['summary']['answer'])

    def test_recipient_preview_has_no_owner_grant_or_activation(self):
        result = views.get_view(self.choice)
        self.adapter.preview_handoff.assert_called_once_with(self.viewer, HANDOFF)
        block = result['components'][0]
        self.assertEqual(block['type'], 'business_proposal_handoff')
        self.assertFalse(block['can_handoff'])
        self.assertFalse(block['can_activate'])
        self.assertTrue(block['can_accept'])
        self.assertEqual(block['sender'], '<script>teacher')
        self.assertEqual(self.preview['components'][0]['type'], 'business_proposal')
        self.adapter.accept_handoff.assert_not_called()

    def test_pending_uncertain_and_accepted_are_different(self):
        for state in ('copying', 'uncertain', 'accepted'):
            self.preview['handoff_state'] = state
            self.preview['accepted_selection'] = {'view': 'business_blueprint', 'proposal_id': 'FILE-1'}
            result = views.get_view(self.choice)
            self.assertFalse(result['components'][0]['can_accept'])
            self.assertFalse(result['summary']['activation_verified'])
            if state == 'accepted':
                self.assertEqual(result['components'][0]['accepted_selection']['proposal_id'], 'FILE-1')
            else:
                self.assertNotIn('accepted_selection', result['components'][0])

    def test_accepted_read_requires_verified_original_file_target(self):
        self.preview['handoff_state'] = 'accepted'
        for target in (None, {}, {'view': 'frappe_new', 'proposal_id': 'FILE-1'},
                       {'view': 'business_blueprint', 'proposal_id': 'FILE-1', 'owner': 'other'},
                       {'view': 'business_blueprint', 'proposal_id': 'FILE\n1'}):
            self.preview['accepted_selection'] = target
            with self.subTest(target=target), self.assertRaises(ValueError):
                views.get_view(self.choice)
        self.adapter.accept_handoff.assert_not_called()

    def test_wrong_handoff_and_unexpected_component_fail_closed(self):
        for patch_data in ({'handoff_id': PROPOSAL}, {'handoff_state': 'active'},
                           {'components': [{'type': 'html'}]}):
            self.adapter.preview_handoff.return_value = {**self.preview, **patch_data}
            with self.assertRaises(ValueError):
                views.get_view(self.choice)

    def test_permission_revocation_is_not_an_empty_success(self):
        self.adapter.list_received.side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError):
            views.get_view({'view': 'business_proposal_inbox', 'folder': 'received'})
        self.adapter.preview_handoff.side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError):
            views.get_view(self.choice)


if __name__ == '__main__':
    unittest.main()
