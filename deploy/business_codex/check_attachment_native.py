"""Synthetic native File acceptance; prepare is READ ONLY, run is explicit.

Run retains three private synthetic Files and an exclusive UUID evidence folder.
Only these newly created Files can be changed/restored. No model, HTTP upload,
RQ, business save, user/role/share mutation, production access or cleanup occurs.
The local task/claim ledger is a test fixture, NOT proof of real worker execution.
An uncertain native commit is retained for manual inspection, never retried.
"""
from __future__ import annotations

import argparse
from contextvars import Context
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_worker_live as worker_check

qa, fixture = worker_check.qa, worker_check.fixture
OTHER = 'QA Teacher 9680e04d9f Other'
DEPENDENCIES = qa.ROOT / 'python-deps-attachments-v1'
SOURCE_FILES = tuple(dict.fromkeys((*worker_check.SOURCE_FILES,
    'tongjianyun/business_agent_attachments.py',
    'deploy/business_codex/serve_business_journey.py',
    'deploy/business_codex/serve_business_browser.py',
    'deploy/business_codex/check_attachment_native.py')))


def canonical(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Canonical run UUID required')
    return value


def folder(run_id):
    return qa.safe_target(qa.ROOT / ('business-attachment-native-' + canonical(run_id)))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str, allow_nan=False).encode()).hexdigest()


def file_names(run_id):
    canonical(run_id)
    return {kind: 'synthetic-' + run_id + '-' + kind + '.' + kind for kind in ('txt', 'csv', 'xlsx')}


def assert_new_paths(run_id):
    """Read-only preflight; create rechecks these paths before native insert."""
    for name in file_names(run_id).values():
        path = qa.safe_target(qa.SITES / qa.SITE / 'private/files' / name)
        if path.exists() or path.is_symlink():
            raise FileExistsError('A planned synthetic path already exists; never adopt it')


def synthetic_files(run_id):
    """Small deterministic XLSX from stdlib; formulas stay data, never evaluated."""
    canonical(run_id)
    rows = ['SYNTHETIC ATTACHMENT ' + run_id, 'dish,ingredient,amount',
            'sample rice,rice,25 g', 'sample soup,water,100 ml', '=1+1']
    txt = ('\n'.join(rows) + '\n').encode()
    csv = ('synthetic_run,dish,ingredient,amount\n' + run_id + ',sample rice,rice,25 g\n'
           + run_id + ',sample soup,water,100 ml\n' + run_id + ',literal formula,=1+1,\n').encode()
    parts = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Synthetic" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + ''.join('<row r="%d"><c r="A%d" t="inlineStr"><is><t>%s</t></is></c></row>' % (n, n, value)
                      for n, value in enumerate(rows[:4], 1))
            + '<row r="5"><c r="A5"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>',
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as book:
        for name, content in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            book.writestr(info, content.encode())
    return {'txt': txt, 'csv': csv, 'xlsx': output.getvalue()}


def source_hashes():
    return {name: qa.digest_file(qa.SOURCE / name) for name in SOURCE_FILES}


def environment():
    if os.name != 'posix' or os.geteuid() == 0 or sys.flags.optimize:
        raise PermissionError('Existing non-root Linux site user required')
    if Path(__file__).resolve() != qa.SOURCE / 'deploy/business_codex/check_attachment_native.py':
        raise PermissionError('Only the reviewed candidate script is allowed')
    fixture.fixture_guard()
    qa.safe_target(DEPENDENCIES)
    info = DEPENDENCIES.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise PermissionError('Unsafe fixed QA parser dependency directory')
    sys.path.insert(0, str(DEPENDENCIES))
    return qa.runtime()


def denied(callback, error_types=(PermissionError,)):
    try:
        callback()
    except error_types:
        return True
    return False


def baseline(frappe, reader):
    # Explicit independent READ ONLY diagnostic only; no Admin enters write paths.
    from serve_business_journey import snapshot
    business = snapshot(frappe)
    def read_files():
        fixture.account_guard(frappe)
        previous = frappe.session.user
        try:
            frappe.set_user('Administrator')
            names = frappe.get_all('File', pluck='name', order_by='name', limit_page_length=2001)
            if len(names) > 2000:
                raise PermissionError('Bounded fixture exceeded; baseline may not truncate')
            return {name: digest(frappe.get_doc('File', name).as_dict()) for name in names}
        finally:
            frappe.set_user(previous)
    return {'business': business, 'file_metadata': reader.run_check(fixture.TEACHER, read_files),
            'scope': 'Declared business tables/teacher fields plus File metadata; not whole DB or original file bytes'}


def unchanged(before, after, owned):
    prior, current = before['file_metadata'], after['file_metadata']
    return (before['business'] == after['business']
            and all(current.get(key) == value for key, value in prior.items())
            and set(current) - set(prior) == set(owned) and not set(owned) & set(prior))


def prepare(frappe, run_id):
    target = folder(run_id)
    if target.exists() or target.is_symlink():
        raise FileExistsError('Run already reserved; retain and inspect it, never retry')
    assert_new_paths(run_id)
    from tongjianyun import business_agent_authority as gates, business_agent_attachments as attachments
    reader = worker_check.readonly_adapter(frappe)
    def check():
        fixture.account_guard(frappe)
        if frappe.get_doc({'doctype': 'File', 'file_name': 'synthetic.txt', 'is_private': 1,
                           'owner': fixture.TEACHER}).has_permission('create') is not True:
            raise PermissionError('Original teacher cannot create private File')
        gates._document('Student Group', fixture.GROUP, ['read'])
        if not denied(lambda: gates._document('Student Group', OTHER, ['read']), (PermissionError, frappe.PermissionError)):
            raise PermissionError('Foreign fixture is unexpectedly readable')
        for key in ('write_file', 'before_write_file', 'delete_file_data_content', 'ignore_file_permissions'):
            if frappe.get_hooks(key):
                raise PermissionError('File hooks require separate review')
        from frappe.core.doctype.file.file import File
        if type(frappe.get_doc({'doctype': 'File'})) is not File:
            raise PermissionError('Custom File controller requires review')
        path = qa.safe_target(qa.SITES / qa.SITE / 'private/files')
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise PermissionError('Unsafe private File directory')
        return True
    reader.run_check(fixture.TEACHER, check)
    payloads = synthetic_files(run_id)
    parsed = {kind: attachments.parse_content(raw, kind) for kind, raw in payloads.items()}
    if not all(len(rows) >= 4 for rows in parsed.values()):
        raise RuntimeError('Synthetic parser fixture invalid')
    return {'status': 'prepared_read_only', 'site': qa.SITE, 'run_id': run_id,
            'source_sha256': source_hashes(), 'baseline': baseline(frappe, reader),
            'payload_sha256': {kind: hashlib.sha256(raw).hexdigest() for kind, raw in payloads.items()},
            'planned_filenames': list(file_names(run_id).values()),
            'native_file_sha256': qa.digest_file(Path(sys.modules['frappe.core.doctype.file.file'].__file__)),
            'file_writes': 0, 'model_calls': 0, 'task_created': False}


def private_new(path, value):
    qa.safe_target(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == 'posix':
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class NativeCommitUncertain(RuntimeError):
    pass


class NativeFiles:
    """Fixed actor, fresh connection, no ignore_permissions or general CRUD API."""
    def __init__(self, frappe, run_id, hashes):
        self.frappe, self.run_id, self.hashes = frappe, canonical(run_id), hashes

    def transaction(self, callback):
        frappe = self.frappe
        def run():
            attempted = False
            try:
                if source_hashes() != self.hashes:
                    raise PermissionError('Candidate changed during acceptance')
                frappe.init(qa.SITE, sites_path=str(qa.SITES))
                qa.config_guard()
                qa.guard(frappe.conf)
                frappe.connect(set_admin_as_user=False)
                frappe.set_user(fixture.TEACHER)
                fixture.account_guard(frappe)
                result = callback()
                fixture.account_guard(frappe)
                attempted = True
                frappe.db.commit()
                return result
            except BaseException as error:
                if attempted:
                    raise NativeCommitUncertain('Commit attempted; retain files/evidence, no automatic repair') from error
                if getattr(frappe.local, 'db', None):
                    frappe.db.rollback()
                raise
            finally:
                frappe.destroy()
        return Context().run(run)

    def receipt(self, doc):
        from tongjianyun.business_agent_attachments import _private_bytes
        if (doc.owner != fixture.TEACHER or not doc.is_private or doc.is_folder
                or type(doc.file_name) is not str or doc.file_name not in file_names(self.run_id).values()
                or type(doc.file_url) is not str or not doc.file_url.startswith('/private/files/')):
            raise PermissionError('Not this run\'s new private synthetic File')
        basename = doc.file_url[len('/private/files/'):]
        if basename != doc.file_name:
            raise PermissionError('Invalid synthetic file location')
        raw = _private_bytes(qa.SITES / qa.SITE / 'private/files', basename, int(doc.file_size))
        return {'name': doc.name, 'file_name': doc.file_name, 'file_url': doc.file_url,
                'modified': str(doc.modified), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                'parent_type': doc.attached_to_doctype or '', 'parent': doc.attached_to_name or ''}

    def create(self, kind, raw):
        if kind not in synthetic_files(self.run_id) or raw != synthetic_files(self.run_id)[kind]:
            raise PermissionError('Only the exact synthetic payload can be created')
        def insert():
            from frappe.core.doctype.file.utils import get_content_hash
            name = file_names(self.run_id)[kind]
            path = qa.safe_target(qa.SITES / qa.SITE / 'private/files' / name)
            if (path.exists() or path.is_symlink()
                    or self.frappe.db.exists('File', {'file_name': name})
                    or self.frappe.db.exists('File', {'content_hash': get_content_hash(raw), 'is_private': 1})):
                raise PermissionError('Synthetic source already exists; never adopt/deduplicate an old file')
            doc = self.frappe.get_doc({'doctype': 'File', 'file_name': name,
                                       'is_private': 1, 'content': raw})
            doc.insert()  # original permission checked; no parent => no existing-group Attachment Comment
            return self.receipt(doc)
        return self.transaction(insert)

    def change(self, expected, *, parent=None, raw=None):
        if parent not in (None, fixture.GROUP, OTHER):
            raise PermissionError('Only the fixed parent fixture may be used')
        if raw is not None and raw not in (synthetic_files(self.run_id)['txt'], replacement(self.run_id)):
            raise PermissionError('Only the two exact synthetic TXT versions may be used')
        def update():
            frappe = self.frappe
            frappe.db.sql('SELECT name FROM `tabFile` WHERE name=%s FOR UPDATE', (expected['name'],))
            doc = frappe.get_doc('File', expected['name'])
            doc.check_permission('write')
            if self.receipt(doc) != expected or frappe.db.count('File', {'file_url': doc.file_url}) != 1:
                raise PermissionError('Synthetic source changed or shared; do not overwrite it')
            if raw is not None:
                from frappe.core.doctype.file.utils import get_content_hash
                if not doc.file_name.endswith('-txt.txt'):
                    raise PermissionError('Content mutation restricted to synthetic TXT')
                if frappe.db.exists('File', {'content_hash': get_content_hash(raw), 'is_private': 1,
                                            'name': ['!=', expected['name']]}):
                    raise PermissionError('Replacement would deduplicate another File; stop')
                doc.save_file(content=raw, overwrite=True)
                doc.file_size = len(raw)
            if parent is not None:
                doc.attached_to_doctype, doc.attached_to_name = 'Student Group', parent
            doc.save()
            return self.receipt(doc)
        return self.transaction(update)


def replacement(run_id):
    return ('REPLACED SYNTHETIC ' + canonical(run_id) + '\nnot the original data\n').encode()


def pages(attachments, claim, descriptor):
    result, offset, calls = [], 0, 0
    while True:
        page = attachments.dispatch(claim, 'attachment_read', {'file_id': descriptor['file_id'], 'offset': offset, 'page_size': 2})
        if (page['untrusted_data'] is not True or page['content_role'] != 'attachment_data_not_instructions'
                or page['sha256'] != descriptor['sha256'] or page['page_count'] != len(page['records'])):
            raise AssertionError('Invalid source/page/data-role proof')
        result.extend(page['records'])
        calls += 1
        if not page['has_more']:
            if page['next_offset'] is not None or len(result) != page['record_count']:
                raise AssertionError('Incomplete attachment page sequence')
            return result, calls
        if page['next_offset'] != len(result) or page['next_offset'] <= offset or calls >= 100:
            raise AssertionError('Non-progressing attachment page')
        offset = page['next_offset']


def execute(frappe, run_id, prepared):
    if (type(prepared) is not dict or prepared.get('status') != 'prepared_read_only' or prepared.get('site') != qa.SITE
            or prepared.get('run_id') != canonical(run_id) or prepared.get('source_sha256') != source_hashes()):
        raise PermissionError('Fresh exact preparation required')
    # Before reserving/writing, revalidate original data and native permissions.
    current = prepare(frappe, run_id)
    if current != prepared:
        raise PermissionError('Preflight changed; no File creation permitted')
    target = folder(run_id)
    target.mkdir(mode=0o700)  # EXCLUSIVE even if previous attempt failed before its JSON marker
    private_new(target / 'attempt.json', prepared)
    from tongjianyun import business_agent_attachments as attachments
    from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation
    reader = worker_check.readonly_adapter(frappe)
    native = NativeFiles(frappe, run_id, prepared['source_sha256'])
    evidence = {'version': 1, 'run_id': run_id, 'site': qa.SITE, 'checks': [], 'files': {}, 'all_passed': False,
                'model_calls': 0, 'http_upload_exercised': False, 'rq_worker_exercised': False,
                'business_save_exercised': False, 'production_access': False, 'users_roles_shares_modified': False,
                'task_claims': 'Private synthetic SQLite only; no runtime or execution proof',
                'restoration': [], 'retained': True, 'source_sha256': prepared['source_sha256']}
    private_new(target / 'initial-evidence.json', evidence)
    def record(name, passed):
        event = {'name': name, 'passed': passed is True}
        evidence['checks'].append(event)
        private_new(target / ('check-%03d.json' % len(evidence['checks'])), event)
        if passed is not True:
            raise AssertionError(name)
    directory = target / 'tasks'
    directory.mkdir(mode=0o700)
    store = BusinessTaskStore(directory, qa.SITE, authorize=reader,
        observe_queue=lambda job: QueueObservation(job, 'unknown'),
        observe_execution=lambda identity, claim: ExecutionObservation(claim, 'unknown', 0))
    access = attachments.BusinessAttachments(reader, store)
    claims, descriptors = {}, {}
    errors = (PermissionError, frappe.PermissionError)
    def task(descriptor=None):
        identity = TaskIdentity(qa.SITE, fixture.TEACHER, str(uuid.uuid4()))
        store.create(identity.owner, identity.task_id, 'Synthetic attachment native QA only',
                     {'attachments': [descriptor]} if descriptor else {})
        ticket = store.take_dispatch(identity)
        store.acknowledge_dispatch(ticket)
        return store.claim(identity, ticket.job_id)
    def blocked(name, claim):
        kind = name.split('_')[0]
        # A one-row history page must inspect THIS task, not some earlier revoked
        # task in the same store; otherwise the second revocation test is vacuous.
        newer = claims['csv' if kind == 'txt' else 'xlsx'].identity.task_id
        record(name + '_task', denied(lambda: store.task(claim.identity), errors))
        record(name + '_events', denied(lambda: store.events(claim.identity), errors))
        record(name + '_history', denied(lambda: store.history(claim.identity.owner, before=newer, limit=1), errors))
        record(name + '_read', denied(lambda: access.dispatch(claim, 'attachment_read',
                    {'file_id': descriptors[kind]['file_id']}), errors))
    def suspended(claim):
        # Synthetic authenticated viewer callback: tests native per-source SSE
        # revalidation only. This is explicitly NOT a real HTTP/session exercise.
        stream = store.stream(claim.identity, authorize_viewer=lambda identity: True)
        if next(stream) != 'retry: 2000\n: connected\n\n' or 'id: ' not in next(stream):
            raise AssertionError('Expected a suspended native event iterator')
        return stream
    try:
        for kind, raw in synthetic_files(run_id).items():
            created = native.create(kind, raw)
            evidence['files'][kind] = created
            private_new(target / (kind + '-created.json'), created)
            current_file = native.change(created, parent=fixture.GROUP)
            evidence['files'][kind] = current_file
            private_new(target / (kind + '-linked.json'), current_file)
            identity = TaskIdentity(qa.SITE, fixture.TEACHER, str(uuid.uuid4()))
            descriptor = access.prepare(identity, current_file['name'])
            descriptors[kind] = descriptor
            claim = claims[kind] = task(descriptor)
            rows, count = pages(access, claim, descriptor)
            expected = attachments.parse_content(raw, kind)
            record(kind + '_native_private_source_and_all_pages', rows == expected and count >= 2
                   and descriptor['sha256'] == hashlib.sha256(raw).hexdigest())
            if kind == 'xlsx':
                record('xlsx_formula_is_literal_not_evaluated', rows[-1]['cells'] == ['=1+1']
                       and rows[-1]['formula_columns'] == [1])
            store.emit(claim, {'kind': 'message', 'item_id': 'synthetic_' + kind,
                               'text': 'Synthetic attachment check, no file body'})
            record(kind + '_source_registered', attachments.source_scope(descriptor) in store.required_scopes(claim.identity))
            public = json.dumps({'task': store.task(claim.identity), 'events': store.events(claim.identity)})
            record(kind + '_public_events_do_not_include_body', 'sample rice' not in public and 'sample soup' not in public)
        record('history_before_revocation_accessible', len(store.history(fixture.TEACHER)['tasks']) == 3)
        empty = task()
        record('same_file_unbound_task_denied', denied(lambda: access.dispatch(empty, 'attachment_read',
            {'file_id': descriptors['txt']['file_id']}), errors))
        record('other_file_bound_task_denied', denied(lambda: access.dispatch(claims['csv'], 'attachment_read',
            {'file_id': descriptors['txt']['file_id']}), errors))
        foreign_identity = TaskIdentity(qa.SITE, 'other-synthetic@example.invalid', claims['txt'].identity.task_id)
        record('task_owner_cannot_be_substituted', denied(lambda: store.events(foreign_identity), errors))
        original = evidence['files']['txt']
        txt_stream = suspended(claims['txt'])
        changed = native.change(original, raw=replacement(run_id))
        evidence['files']['txt'] = changed
        private_new(target / 'txt-replacement.json', changed)
        try:
            record('txt_replaced_suspended_sse_unavailable', next(txt_stream) == 'event: unavailable\ndata: {}\n\n')
            blocked('txt_replaced', claims['txt'])
        finally:
            txt_stream.close()
            restored = native.change(changed, raw=synthetic_files(run_id)['txt'])
            evidence['files']['txt'] = restored
            evidence['restoration'].append({'file': 'txt', 'original_content_restored': restored['sha256'] == original['sha256'],
                                            'original_revision_restored': False})
            private_new(target / 'txt-restored.json', restored)
        original = evidence['files']['csv']
        csv_stream = suspended(claims['csv'])
        changed = native.change(original, parent=OTHER)
        evidence['files']['csv'] = changed
        private_new(target / 'csv-parent-revoked.json', changed)
        try:
            record('csv_revoked_suspended_sse_unavailable', next(csv_stream) == 'event: unavailable\ndata: {}\n\n')
            # No expected descriptor: rejection must include actual current parent access,
            # not just an old metadata fingerprint mismatch.
            identity = TaskIdentity(qa.SITE, fixture.TEACHER, str(uuid.uuid4()))
            record('foreign_parent_fresh_prepare_denied', denied(lambda: access.prepare(identity, changed['name']), errors))
            blocked('csv_revoked', claims['csv'])
        finally:
            csv_stream.close()
            restored = native.change(changed, parent=fixture.GROUP)
            evidence['files']['csv'] = restored
            evidence['restoration'].append({'file': 'csv', 'own_parent_restored': restored['parent'] == fixture.GROUP,
                                            'original_revision_restored': False})
            private_new(target / 'csv-parent-restored.json', restored)
        for kind, value in evidence['files'].items():
            identity = TaskIdentity(qa.SITE, fixture.TEACHER, str(uuid.uuid4()))
            current_descriptor = access.prepare(identity, value['name'])
            record(kind + '_retained_private_source_readable', current_descriptor['sha256'] == prepared['payload_sha256'][kind])
        record('restoration_cannot_resurrect_old_task_revision',
               denied(lambda: store.events(claims['txt'].identity), errors)
               and denied(lambda: store.events(claims['csv'].identity), errors))
        evidence['after'] = baseline(frappe, reader)
        record('original_business_and_file_metadata_unchanged', unchanged(prepared['baseline'], evidence['after'],
                     [value['name'] for value in evidence['files'].values()]))
        record('candidate_still_pinned', source_hashes() == prepared['source_sha256'])
        evidence['all_passed'] = True
    except BaseException as error:
        evidence['failure_type'] = type(error).__name__
        evidence['automatic_retry_allowed'] = False
        raise
    finally:
        # Never manufacture terminal execution proof for our unexecuted synthetic claims.
        private_new(target / 'evidence.json', evidence)
        print(json.dumps({'evidence': str(target / 'evidence.json'), 'all_passed': evidence['all_passed'],
                          'acknowledged_file_count': len(evidence['files']), 'model_calls': 0}), flush=True)
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('prepare', 'run'), default='prepare')
    parser.add_argument('--run-id', required=True, type=canonical)
    args = parser.parse_args(argv)
    frappe = environment()
    prepared = prepare(frappe, args.run_id)
    if args.action == 'run':
        return execute(frappe, args.run_id, prepared)
    result = {key: value for key, value in prepared.items() if key not in ('baseline',)}
    result['baseline_sha256'] = digest(prepared['baseline'])
    print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error_type': type(error).__name__,
                          'detail': 'Stopped; preserve synthetic files/evidence; no automatic retry'}), flush=True)
        raise SystemExit(1) from None
