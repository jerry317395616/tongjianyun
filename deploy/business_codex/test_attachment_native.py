"""Pure safeguards, real parsers/SQLite, explicit native doubles; NOT live File QA."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
import uuid

SPEC = importlib.util.spec_from_file_location('attachment_native_check_test', Path(__file__).with_name('check_attachment_native.py'))
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
from tongjianyun import business_agent_attachments as attachments

RUN = 'e3c15c21-d63d-46e9-b186-c9b194d85fb4'


def preparation():
    return {'status': 'prepared_read_only', 'site': c.qa.SITE, 'run_id': RUN,
            'source_sha256': {'source': 'fixed'}, 'baseline': {'business': {}, 'file_metadata': {'existing': 'original'}},
            'payload_sha256': {kind: hashlib.sha256(raw).hexdigest() for kind, raw in c.synthetic_files(RUN).items()}}


class GuardTests(unittest.TestCase):
    def test_default_prepare_does_not_execute(self):
        with patch.object(c, 'environment', return_value='frappe'), patch.object(c, 'prepare', return_value=preparation()) as prepare, \
             patch.object(c, 'execute') as execute, redirect_stdout(io.StringIO()):
            result = c.main(['--run-id', RUN])
        prepare.assert_called_once_with('frappe', RUN)
        execute.assert_not_called()
        self.assertNotIn('baseline', result)

    def test_run_requires_explicit_command_and_preflight(self):
        with patch.object(c, 'environment', return_value='frappe'), patch.object(c, 'prepare', return_value=preparation()), \
             patch.object(c, 'execute') as execute:
            c.main(['run', '--run-id', RUN])
        execute.assert_called_once_with('frappe', RUN, preparation())

    def test_preflight_failure_never_writes(self):
        with patch.object(c, 'environment'), patch.object(c, 'prepare', side_effect=PermissionError), patch.object(c, 'execute') as execute:
            with self.assertRaises(PermissionError):
                c.main(['run', '--run-id', RUN])
        execute.assert_not_called()

    def test_cli_cannot_change_site_owner_files_or_model(self):
        for option in ('--site', '--owner', '--file', '--model', '--force', '--key'):
            with self.subTest(option=option), patch.object(c, 'environment') as runtime, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    c.main(['run', '--run-id', RUN, option, 'untrusted'])
                runtime.assert_not_called()

    def test_uuid_required_and_canonical(self):
        for value in ('../x', RUN.upper(), '', None, RUN.replace('-', '')):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                c.canonical(value)
        self.assertEqual(c.canonical(RUN), RUN)

    def test_existing_run_stops_before_reads_or_native_import(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(c, 'folder', return_value=Path(temp)):
            with self.assertRaises(FileExistsError):
                c.prepare(None, RUN)

    def test_exclusive_marker_and_evidence_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(c.qa, 'safe_target', side_effect=lambda path: path):
            path = Path(temp) / 'attempt.json'
            c.private_new(path, {'run_id': RUN})
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                c.private_new(path, {'different': True})
            self.assertEqual(original, path.read_bytes())

    def test_preflight_path_check_reads_only_exact_three_new_names(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(c.qa, 'safe_target', side_effect=lambda path: Path(temp) / path.name):
            c.assert_new_paths(RUN)
            self.assertEqual(list(Path(temp).iterdir()), [])
            occupied = Path(temp) / c.file_names(RUN)['txt']
            occupied.write_bytes(b'old fixture')
            with self.assertRaises(FileExistsError):
                c.assert_new_paths(RUN)
            self.assertEqual(occupied.read_bytes(), b'old fixture')

    def test_receipt_requires_exact_run_filename_and_matching_url_basename(self):
        native = c.NativeFiles(MagicMock(), RUN, {})
        label = c.file_names(RUN)['txt']
        raw = c.synthetic_files(RUN)['txt']
        values = {'owner': c.fixture.TEACHER, 'is_private': 1, 'is_folder': 0, 'file_name': label,
                  'file_url': '/private/files/' + label, 'file_size': len(raw), 'name': 'new-id',
                  'modified': 'expected', 'attached_to_doctype': '', 'attached_to_name': ''}
        with patch.object(attachments, '_private_bytes', return_value=raw) as read:
            native.receipt(SimpleNamespace(**values))
            self.assertEqual(read.call_args.args[1], label)
            read.reset_mock()
            for change in ({'file_name': label.replace('-txt.txt', '-other.txt')},
                           {'file_name': label.replace('.txt', '-renamed.txt')},
                           {'file_url': '/private/files/some-other-file.txt'},
                           {'file_url': '/private/files/../' + label},
                           {'file_url': '/private/files/%2e%2e/' + label}):
                with self.subTest(change=change), self.assertRaises(PermissionError):
                    native.receipt(SimpleNamespace(**{**values, **change}))
            read.assert_not_called()

    def test_unprepared_and_changed_source_fail_before_reservation(self):
        for prepared in (None, {}, {**preparation(), 'run_id': str(uuid.uuid4())}, {**preparation(), 'site': 'production'},
                         {**preparation(), 'source_sha256': {'changed': True}}):
            with self.subTest(prepared=prepared), patch.object(c, 'source_hashes', return_value={'source': 'fixed'}), \
                 patch.object(c, 'folder') as folder:
                with self.assertRaises(PermissionError):
                    c.execute(None, RUN, prepared)
                folder.assert_not_called()

    def test_changed_baseline_fails_before_reservation(self):
        with patch.object(c, 'source_hashes', return_value={'source': 'fixed'}), patch.object(c, 'prepare', return_value={}), \
             patch.object(c, 'folder') as folder:
            with self.assertRaises(PermissionError):
                c.execute(None, RUN, preparation())
            folder.assert_not_called()

    def test_payloads_are_deterministic_unique_and_parseable(self):
        left = c.synthetic_files(RUN)
        self.assertEqual(left, c.synthetic_files(RUN))
        right = c.synthetic_files(str(uuid.uuid4()))
        for kind, raw in left.items():
            self.assertNotEqual(raw, right[kind])
            self.assertGreaterEqual(len(attachments.parse_content(raw, kind)), 4)
            self.assertLess(len(raw), 4096)
        formula = attachments.parse_content(left['xlsx'], 'xlsx')[-1]
        self.assertEqual(formula['cells'], ['=1+1'])
        self.assertEqual(formula['formula_columns'], [1])

    def test_deny_requires_permission_error_not_arbitrary_failure(self):
        self.assertTrue(c.denied(Mock(side_effect=PermissionError)))
        self.assertFalse(c.denied(lambda: None))
        with self.assertRaises(RuntimeError):
            c.denied(Mock(side_effect=RuntimeError))

    def test_baseline_allows_only_new_owned_files(self):
        before = {'business': {'x': 1}, 'file_metadata': {'old': 'hash'}}
        after = {'business': {'x': 1}, 'file_metadata': {'old': 'hash', 'new': 'other'}}
        self.assertTrue(c.unchanged(before, after, ['new']))
        for changed in ({**after, 'business': {'x': 2}}, {**after, 'file_metadata': {'old': 'changed', 'new': 'other'}},
                        {**after, 'file_metadata': {'new': 'other'}}, {**after, 'file_metadata': {**after['file_metadata'], 'extra': 'h'}}):
            self.assertFalse(c.unchanged(before, changed, ['new']))
        self.assertFalse(c.unchanged(before, after, ['new', 'old']))

    def test_native_factory_is_construction_only_and_input_guarded(self):
        frappe = MagicMock()
        native = c.NativeFiles(frappe, RUN, {})
        self.assertFalse(frappe.mock_calls)
        with self.assertRaises(PermissionError):
            native.create('txt', b'real file contents')
        with self.assertRaises(PermissionError):
            native.change({}, parent='other business document')
        with self.assertRaises(PermissionError):
            native.change({}, raw=b'arbitrary change')
        self.assertFalse(frappe.mock_calls)

    def test_create_rejects_content_dedup_before_original_insert(self):
        with tempfile.TemporaryDirectory() as temp:
            frappe = MagicMock()
            frappe.db.exists.side_effect = [False, True]
            native = c.NativeFiles(frappe, RUN, {})
            helpers = SimpleNamespace(get_content_hash=lambda value: 'synthetic-hash')
            with patch.object(native, 'transaction', side_effect=lambda callback: callback()), \
                 patch.object(c.qa, 'safe_target', return_value=Path(temp) / 'new.txt'), \
                 patch.dict(sys.modules, {'frappe.core.doctype.file.utils': helpers}):
                with self.assertRaises(PermissionError):
                    native.create('txt', c.synthetic_files(RUN)['txt'])
            frappe.get_doc.assert_not_called()

    def test_create_uses_native_insert_no_bypass_or_existing_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            frappe = MagicMock()
            frappe.db.exists.return_value = False
            native = c.NativeFiles(frappe, RUN, {})
            helpers = SimpleNamespace(get_content_hash=lambda value: 'synthetic-hash')
            with patch.object(native, 'transaction', side_effect=lambda callback: callback()), \
                 patch.object(native, 'receipt', return_value={'new': True}), \
                 patch.object(c.qa, 'safe_target', return_value=Path(temp) / 'new.txt'), \
                 patch.dict(sys.modules, {'frappe.core.doctype.file.utils': helpers}):
                native.create('txt', c.synthetic_files(RUN)['txt'])
            payload = frappe.get_doc.call_args.args[0]
            self.assertEqual(set(payload), {'doctype', 'file_name', 'is_private', 'content'})
            self.assertEqual(payload['is_private'], 1)
            frappe.get_doc.return_value.insert.assert_called_once_with()

    def test_changed_or_shared_source_cannot_be_overwritten(self):
        for mismatch, references in ((True, 1), (False, 2)):
            with self.subTest(mismatch=mismatch, references=references):
                frappe = MagicMock()
                frappe.db.count.return_value = references
                native = c.NativeFiles(frappe, RUN, {})
                expected = {'name': 'synthetic-new', 'modified': 'expected'}
                observed = {**expected, 'modified': 'changed'} if mismatch else expected
                with patch.object(native, 'transaction', side_effect=lambda callback: callback()), \
                     patch.object(native, 'receipt', return_value=observed):
                    with self.assertRaises(PermissionError):
                        native.change(expected, raw=c.replacement(RUN))
                frappe.get_doc.return_value.check_permission.assert_called_once_with('write')
                frappe.get_doc.return_value.save_file.assert_not_called()
                frappe.get_doc.return_value.save.assert_not_called()

    def test_change_uses_original_save_under_row_lock_and_never_parent_save(self):
        frappe = MagicMock()
        frappe.db.count.return_value = 1
        native = c.NativeFiles(frappe, RUN, {})
        expected = {'name': 'synthetic-new'}
        with patch.object(native, 'transaction', side_effect=lambda callback: callback()), \
             patch.object(native, 'receipt', return_value=expected):
            native.change(expected, parent=c.fixture.GROUP)
        frappe.db.sql.assert_called_once_with('SELECT name FROM `tabFile` WHERE name=%s FOR UPDATE', ('synthetic-new',))
        frappe.get_doc.assert_called_once_with('File', 'synthetic-new')
        frappe.get_doc.return_value.check_permission.assert_called_once_with('write')
        frappe.get_doc.return_value.save.assert_called_once_with()
        self.assertEqual(frappe.get_doc.return_value.attached_to_name, c.fixture.GROUP)

    def _transaction(self, error=None, callback_error=None):
        frappe = MagicMock()
        frappe.local.db = frappe.db
        frappe.db.commit.side_effect = error
        native = c.NativeFiles(frappe, RUN, {})
        with patch.object(c, 'source_hashes', return_value={}), patch.object(c.qa, 'config_guard'), \
             patch.object(c.qa, 'guard'), patch.object(c.fixture, 'account_guard'):
            callback = Mock(return_value={'saved': True}, side_effect=callback_error)
            if error:
                with self.assertRaises(c.NativeCommitUncertain):
                    native.transaction(callback)
            elif callback_error:
                with self.assertRaises(type(callback_error)):
                    native.transaction(callback)
            else:
                self.assertEqual(native.transaction(callback), {'saved': True})
        frappe.connect.assert_called_once_with(set_admin_as_user=False)
        frappe.set_user.assert_called_once_with(c.fixture.TEACHER)
        frappe.destroy.assert_called_once()
        return frappe

    def test_native_commit_ack_and_fresh_identity(self):
        frappe = self._transaction()
        frappe.db.commit.assert_called_once()
        frappe.db.rollback.assert_not_called()

    def test_commit_exception_is_uncertain_never_rollback_retry(self):
        frappe = self._transaction(error=RuntimeError('disconnected'))
        frappe.db.commit.assert_called_once()
        frappe.db.rollback.assert_not_called()

    def test_precommit_failure_rolls_back_and_does_not_commit(self):
        frappe = self._transaction(callback_error=PermissionError('denied'))
        frappe.db.commit.assert_not_called()
        frappe.db.rollback.assert_called_once()

    def test_bad_page_proof_never_counts_as_complete(self):
        base = {'untrusted_data': True, 'content_role': 'attachment_data_not_instructions', 'sha256': 'hash',
                'page_count': 1, 'records': [{'cells': ['synthetic']}], 'has_more': False, 'next_offset': None, 'record_count': 1}
        for changes in ({'untrusted_data': False}, {'record_count': 2}, {'page_count': 2}, {'sha256': 'wrong'},
                        {'has_more': True, 'next_offset': 0}, {'has_more': False, 'next_offset': 1}):
            fake = SimpleNamespace(dispatch=Mock(return_value={**base, **changes}))
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                c.pages(fake, object(), {'file_id': 'synthetic', 'sha256': 'hash'})


class PureFlowTests(unittest.TestCase):
    """Real task authority gates + parser + SQLite; native File is an explicit double."""
    def run_flow(self, *, fail_kind=None):
        stack = ExitStack()
        self.addCleanup(stack.close)
        temp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        target = temp / 'run'
        docs, raws = {}, {}
        frappe = SimpleNamespace(PermissionError=PermissionError)
        hashes, prep = {'source': 'fixed'}, preparation()
        class Native:
            def __init__(self, *args): pass
            def create(self, kind, raw):
                value = {'name': 'new-' + kind, 'file_name': 'synthetic.' + kind, 'file_url': '/private/files/synthetic.' + kind,
                         'modified': '1', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'parent_type': '', 'parent': ''}
                docs[value['name']], raws[value['name']] = value, raw
                return dict(value)
            def change(self, expected, *, parent=None, raw=None):
                if docs[expected['name']] != expected:
                    raise PermissionError('changed')
                value = dict(expected)
                value['modified'] = str(int(value['modified']) + 1)
                if parent:
                    value.update(parent=parent, parent_type='Student Group')
                if raw:
                    value.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                    raws[value['name']] = raw
                docs[value['name']] = value
                return dict(value)
        def load(file_id, expected=None):
            doc = docs[file_id]
            if doc['parent'] != c.fixture.GROUP:
                raise PermissionError('foreign parent')
            raw = raws[file_id]
            descriptor = {'version': 1, 'file_id': file_id, 'display_name': doc['file_name'],
                          'format': doc['file_name'].split('.')[-1], 'size': len(raw),
                          'sha256': hashlib.sha256(raw).hexdigest(), 'revision': c.digest(doc)}
            if expected and descriptor != expected:
                raise PermissionError('source changed')
            return descriptor, raw
        class Authority:
            site = c.qa.SITE
            def __call__(self, identity, scopes):
                if identity.owner != c.fixture.TEACHER:
                    return False
                try:
                    for scope in scopes:
                        attachments.check_source(scope['descriptor'])
                    return True
                except PermissionError:
                    return False
            def run_check(self, owner, callback):
                return callback()
            def register_read(self, store, claim, sources):
                store.register_authorities(claim, sources.scopes)
        native_frappe = SimpleNamespace(local=SimpleNamespace(site=c.qa.SITE), session=SimpleNamespace(user=c.fixture.TEACHER))
        gates = SimpleNamespace(ReadSet=lambda scopes: SimpleNamespace(scopes=scopes))
        for obj, name, value in ((c, 'folder', lambda run_id: target), (c.qa, 'safe_target', lambda value: value),
                                 (c, 'source_hashes', lambda: hashes), (c, 'prepare', lambda *args: prep),
                                 (c.worker_check, 'readonly_adapter', lambda f: Authority()), (c, 'NativeFiles', Native),
                                 (attachments, '_load', load), (attachments, '_services', lambda: (native_frappe, gates)),
                                 (c, 'baseline', lambda *args: {'business': {}, 'file_metadata': {'existing': 'original',
                                                       **{key: c.digest(value) for key, value in docs.items()}}})):
            stack.enter_context(patch.object(obj, name, value))
        if fail_kind:
            original_pages = c.pages
            def fail(access, claim, descriptor):
                if descriptor['format'] == fail_kind:
                    raise RuntimeError('synthetic failure')
                return original_pages(access, claim, descriptor)
            stack.enter_context(patch.object(c, 'pages', fail))
        with redirect_stdout(io.StringIO()):
            if fail_kind:
                with self.assertRaises(RuntimeError):
                    c.execute(frappe, RUN, prep)
                result = json.loads((target / 'evidence.json').read_text())
            else:
                result = c.execute(frappe, RUN, prep)
        return target, docs, raws, result

    def test_complete_pure_flow_and_independent_revocation_history(self):
        target, docs, raws, result = self.run_flow()
        self.assertTrue(result['all_passed'])
        self.assertGreaterEqual(len(result['checks']), 24)
        self.assertEqual(len(docs), 3)
        self.assertEqual(raws['new-txt'], c.synthetic_files(RUN)['txt'])
        self.assertEqual(docs['new-csv']['parent'], c.fixture.GROUP)
        self.assertFalse(result['http_upload_exercised'])
        self.assertFalse(result['rq_worker_exercised'])
        self.assertFalse(result['business_save_exercised'])
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(len(result['restoration']), 2)
        self.assertTrue((target / 'attempt.json').exists())
        text = (target / 'evidence.json').read_text()
        self.assertNotIn('sample rice', text)
        self.assertNotIn('worker_token', text)

    def test_failure_retains_marker_original_files_and_false_evidence(self):
        target, docs, raws, result = self.run_flow(fail_kind='csv')
        self.assertFalse(result['all_passed'])
        self.assertFalse(result['automatic_retry_allowed'])
        self.assertEqual(len(docs), 2)
        self.assertTrue((target / 'attempt.json').exists())
        self.assertEqual(result['failure_type'], 'RuntimeError')
        self.assertTrue((target / 'txt-created.json').exists())


if __name__ == '__main__':
    unittest.main()
