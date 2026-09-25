"""Fixed isolated-QA catalog acceptance. Default prepare; --run reads only.

Reuses check_meal_reads.setup's exact site/config/ordinary-teacher checks and
database-enforced READ ONLY on EVERY connection. No model, real queue, browser,
login/session change, permission change, fixture creation or business writes.
Only a new private QA directory receives synthetic task/scope SQLite metadata
and sanitized evidence. Native permission failures are failures, not a reason
to add roles, switch users or weaken the original read adapter.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_meal_reads as fixture

qa = fixture.qa
OWNER, GROUP, OTHER = fixture.OWNER, fixture.GROUP, fixture.OTHER
DAY, MEAL = fixture.SAVED_DAY, fixture.MEAL
EMPTY_KEYWORD = 'QA-no-catalog-entry-9680e04d9f'


def source_guard(modules):
    """Called after setup but before any database connection or metadata write."""
    if sys.flags.optimize:
        raise PermissionError('Unoptimized QA guards are required')
    expected = qa.SOURCE / 'deploy/business_codex/check_business_catalog.py'
    if Path(__file__).resolve() != expected or Path(__file__).is_symlink():
        raise PermissionError('Only the fixed reviewed QA candidate may run')
    paths = [Path(__file__), Path(fixture.__file__), Path(qa.__file__)]
    paths.extend(Path(module.__file__) for module in modules)
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(qa.SOURCE):
            raise PermissionError('A read dependency is outside the fixed candidate')
    return {path.relative_to(qa.SOURCE).as_posix(): qa.digest_file(path) for path in paths}


def prepare(frappe, runner):
    from tongjianyun import business_agent_authority as gates, frappe_project_views as native
    from tongjianyun.attendance_scope import allowed_groups
    def check():
        gates._account(OWNER, qa.SITE)
        roles = set(frappe.get_roles())
        if (allowed_groups() != [GROUP] or not {'Instructor', 'Academics User'} <= roles
                or roles & {'System Manager', 'Education Manager', 'Tongjianyun Business Operator'}):
            raise PermissionError('Only the retained ordinary synthetic teacher is allowed')
        if frappe.db.sql('SELECT @@session.tx_read_only')[0][0] != 1:
            raise PermissionError('The database connection is not read-only')
        gates._projection(gates.CATALOG)
        gates._document('Student Group', GROUP, ['read'])
        # Existence only, for a meaningful existing-record rejection later.
        # No foreign document/roster body is read or placed in public evidence.
        if not frappe.db.exists('Student Group', OTHER):
            raise RuntimeError('The retained foreign synthetic group is missing')
        module = gates._doctype('Student Group', ['read']).module
        app = native.module_apps().get(module)
        if not app or app not in frappe.get_installed_apps():
            raise PermissionError('Native Student Group module is unavailable')
        return {'status': 'prepared_read_only', 'site': qa.SITE, 'teacher': OWNER,
                'session_transaction_read_only': True, 'ordinary_teacher': True,
                'existing_foreign_fixture': True, 'app': app, 'module': module,
                'business_writes': False, 'model_calls': 0}
    return runner(OWNER, check)


def require_prepared(value):
    if (type(value) is not dict or value.get('status') != 'prepared_read_only'
            or value.get('site') != qa.SITE or value.get('teacher') != OWNER
            or any(value.get(key) is not True for key in
                   ('session_transaction_read_only', 'ordinary_teacher', 'existing_foreign_fixture'))
            or value.get('business_writes') is not False or type(value.get('model_calls')) is not int
            or value['model_calls'] != 0
            or any(not isinstance(value.get(key), str) or not value[key] for key in ('app', 'module'))):
        raise PermissionError('Successful fixed read-only preparation is required')


def native_keys(frappe, gates, native, filters=None):
    """Independent native metadata oracle; no business-record data or counts."""
    gates._account(OWNER, qa.SITE)
    choice = {'kind': 'doctype', **(filters or {})}
    modules = native.module_apps()
    if choice.get('app'):
        modules = {module: app for module, app in modules.items() if app == choice['app']}
    if choice.get('module'):
        modules = {module: app for module, app in modules.items() if module == choice['module']}
    return sorted((modules[row['module']], row['module'], row['name'])
                  for row in native.catalog_entries(choice, modules)
                  if row['kind'] == 'doctype' and row['name'] not in gates.CONTROL_DOCTYPES)


def entry_keys(result):
    return [(row['app'], row['module'], row['doctype']) for row in result['entries']]


def execute(frappe, modules, runner, before_connect, readonly, prepared, hashes):
    require_prepared(prepared)
    if source_guard(modules) != hashes:
        raise PermissionError('Candidate changed since preparation')
    qa.config_guard()
    from tongjianyun import business_agent_authority as gates, business_agent_catalog as catalog
    from tongjianyun import frappe_project_views as native
    from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation

    folder = qa.safe_target(qa.ROOT / ('business-catalog-readonly-' + uuid.uuid4().hex[:10]))
    folder.mkdir(mode=0o700)
    output = folder / 'evidence.json'
    evidence = {'version': 1, 'site': qa.SITE, 'checks': [], 'all_passed': False, 'preflight': prepared,
                'business_writes': False, 'sessions_mutated': False, 'users_modified': False,
                'codex_executed': False, 'queue_used': False, 'production_access': False,
                'browser_display_verified': False, 'session_transaction_read_only': True,
                'scope_store': str(folder), 'source_hashes': hashes,
                'store_purpose': 'Synthetic claimed read-only task metadata; never queued or launched'}
    def check(name, condition):
        item = {'name': name, 'passed': bool(condition)}
        evidence['checks'].append(item)
        qa.private_json(output, evidence)
        print(json.dumps(item), flush=True)
        if not condition:
            raise AssertionError(name)

    try:
        adapter = gates.FrappeBusinessAuthority(qa.SITE, run_check=runner)
        store = BusinessTaskStore(folder, qa.SITE, authorize=adapter,
            observe_queue=lambda job: QueueObservation(job, 'unknown'),
            observe_execution=lambda identity, claim: ExecutionObservation(claim, 'unknown', 0))
        identity = TaskIdentity(qa.SITE, OWNER, str(uuid.uuid4()))
        frappe.init(qa.SITE, sites_path=str(qa.SITES))
        before_connect()
        frappe.connect(set_admin_as_user=False)
        frappe.set_user(OWNER)
        readonly()
        outer = (frappe.db._get_current_object(), frappe.session.sid, frappe.local.request_cache)
        evidence['protected_before'] = runner(OWNER, lambda: fixture.protected_digest(frappe))
        store.create(OWNER, identity.task_id, '隔离QA：只读原生业务目录与视图', {'day': DAY, 'meal': MEAL})
        ticket = store.take_dispatch(identity)
        store.acknowledge_dispatch(ticket)  # Private synthetic state only, NOT an RQ enqueue.
        claim = store.claim(identity, ticket.job_id)
        reader = catalog.BusinessCatalog(adapter, store)
        expected = runner(OWNER, lambda: native_keys(frappe, gates, native))
        check('ordinary_teacher_has_multiple_native_business_entries', len(expected) >= 2)
        first = reader.dispatch(claim, 'business_catalog_read', {'page_size': 1})
        check('first_native_page_has_lookahead_not_fake_business_total',
              first['available'] and entry_keys(first) == expected[:1] and first['page_count'] == 1
              and first['has_more'] is True and first['visible_entry_count'] is None and bool(first['next_cursor']))
        required = store.required_scopes(identity)
        check('returned_and_lookahead_native_sources_are_persisted_before_delivery',
              all(gates._read(key[2]) in required for key in expected[:2])
              and gates._capability(gates.CATALOG) in required and gates._capability(gates.SCENE) in required)
        second = reader.dispatch(claim, 'business_catalog_read', {'page_size': 1, 'cursor': first['next_cursor']})
        check('native_second_page_advances_without_claiming_site_total',
              second['available'] and entry_keys(second) == expected[1:2] and second['visible_entry_count'] is None)

        filters = {'app': prepared['app'], 'module': prepared['module'], 'keyword': 'Student Group'}
        filtered_expected = runner(OWNER, lambda: native_keys(frappe, gates, native, filters))
        filtered = reader.dispatch(claim, 'business_catalog_read', {**filters, 'page_size': 30})
        check('installed_app_module_keyword_filters_match_native_reader',
              0 < len(filtered_expected) <= 30 and entry_keys(filtered) == filtered_expected
              and filtered['visible_entry_count'] == len(filtered_expected) and not filtered['has_more'])
        check('directory_exposes_only_noncontrol_entry_metadata_and_scopes',
              all(set(entry) == {'app', 'module', 'doctype', 'title', 'selection'}
                  and entry['doctype'] not in gates.CONTROL_DOCTYPES
                  and gates._read(entry['doctype']) in store.required_scopes(identity)
                  for result in (first, second, filtered) for entry in result['entries'])
              and not any(event['kind'] == 'view' for event in store.events(identity)))
        empty = reader.dispatch(claim, 'business_catalog_read', {'keyword': EMPTY_KEYWORD})
        check('genuinely_empty_metadata_filter_is_not_business_zero', empty['available'] and not empty['entries']
              and empty['visible_entry_count'] == 0 and not empty['has_more'])

        group_entry = next(entry for entry in filtered['entries'] if entry['doctype'] == 'Student Group')
        requested = ({'view': 'frappe_catalog', **filters}, group_entry['selection'],
                     {'view': 'frappe_document', 'doctype': 'Student Group', 'document': GROUP})
        results = [reader.dispatch(claim, 'business_view', {'selection': choice}) for choice in requested]
        views = [event for event in store.events(identity) if event['kind'] == 'view']
        check('native_business_views_publish_canonical_selection_only', len(views) == 3
              and all(event['selection'] == result['selection'] for event, result in zip(views, results))
              and all(result['display_requested'] is True and result['executed_business_operation'] is False
                      and result['selection']['day'] == DAY and result['selection']['meal'] == MEAL for result in results)
              and all(set(event) == {'id', 'kind', 'version', 'selection', 'title'} for event in views))
        check('native_own_document_read_scope_is_registered', gates._read('Student Group', GROUP)
              in store.required_scopes(identity))

        def rejected(name, tool, arguments, exceptions):
            old_events, old_scopes = store.events(identity), store.required_scopes(identity)
            denied = False
            try:
                reader.dispatch(claim, tool, arguments)
            except exceptions:
                denied = True
            check(name, denied and store.events(identity) == old_events and store.required_scopes(identity) == old_scopes)
        forbidden = (PermissionError, frappe.PermissionError)
        rejected('control_doctype_denied_without_event_or_source', 'business_view',
                 {'selection': {'view': 'frappe_doctype', 'doctype': 'User'}}, forbidden)
        rejected('existing_foreign_class_document_denied_without_event_or_source', 'business_view',
                 {'selection': {'view': 'frappe_document', 'doctype': 'Student Group', 'document': OTHER}}, forbidden)
        rejected('uninstalled_application_denied', 'business_catalog_read', {'app': 'qa_nonexistent_9680e04d9f'}, forbidden)
        rejected('cursor_cannot_be_reused_with_different_filters', 'business_catalog_read',
                 {'cursor': first['next_cursor'], 'keyword': EMPTY_KEYWORD}, (ValueError,))
        rejected('model_cannot_supply_an_owner', 'business_catalog_read', {'owner': 'Administrator'}, (ValueError,))
        check('full_persisted_scope_union_remains_native_authorized', adapter(identity, store.required_scopes(identity)))
        check('outer_context_and_read_only_database_are_unchanged', frappe.session.user == OWNER
              and frappe.db._get_current_object() is outer[0] and frappe.session.sid == outer[1]
              and frappe.local.request_cache is outer[2] and frappe.db.sql('SELECT @@session.tx_read_only')[0][0] == 1)
        evidence['protected_after'] = runner(OWNER, lambda: fixture.protected_digest(frappe))
        check('independent_connection_protected_business_digest_unchanged',
              evidence['protected_before'] == evidence['protected_after'])
        check('candidate_sources_unchanged_during_acceptance', source_guard(modules) == hashes)
        evidence.update(scope_count=len(store.required_scopes(identity)), view_event_count=len(views), all_passed=True)
    except BaseException as error:
        evidence['failure_type'] = type(error).__name__  # No raw DB values/errors or pupil names.
        raise
    finally:
        qa.private_json(output, evidence)
        frappe.destroy()
        print(json.dumps({'evidence': str(output), 'all_passed': evidence['all_passed']}), flush=True)


def runtime_modules(base_modules):
    from tongjianyun import business_agent_catalog, business_agent_tasks, frappe_project_views
    from tongjianyun import business_views, meal_scene, scene_access, attendance_scope, meal_views, business_agent_tools
    return (*base_modules, business_agent_catalog, business_agent_tasks, frappe_project_views,
            business_views, meal_scene, scene_access, attendance_scope, meal_views, business_agent_tools)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Perform read-only business checks and retain private test metadata')
    args = parser.parse_args(argv)
    frappe, base_modules, runner, before_connect, readonly = fixture.setup()
    modules = runtime_modules(base_modules)
    hashes = source_guard(modules)
    prepared = prepare(frappe, runner)
    require_prepared(prepared)
    print(json.dumps(prepared), flush=True)
    if args.run:
        execute(frappe, modules, runner, before_connect, readonly, prepared, hashes)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'failed', 'failure_type': type(error).__name__}), flush=True)
        sys.exit(1)
