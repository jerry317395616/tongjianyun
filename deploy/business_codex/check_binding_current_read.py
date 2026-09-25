"""Real two-connection User-lock/MVCC proof, fixed isolated QA site only.

Creates one otherwise unassigned synthetic System User and a desk-access-only
role with no business DocPerm. It ends disabled. Existing accounts are untouched.
No business documents, Codex, production settings or global isolation changes.
"""
from __future__ import annotations

import json
from pathlib import Path
import queue
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified_business'))
import serve_isolated_browser as qa


def run():
    if sys.flags.optimize:
        raise RuntimeError('Optimized Python disables inherited QA assertions')
    qa.config_guard()
    frappe = qa.connect()
    from redis import Redis
    from tongjianyun import business_agent_tools as tools, business_agent_transport as transport
    for module in (tools, transport):
        assert Path(module.__file__).resolve().is_relative_to(qa.SOURCE)
    run_id = uuid.uuid4().hex[:10]
    task_id = str(uuid.uuid4())
    user = 'business-mvcc-' + run_id + '@example.invalid'
    role = 'QA Business MVCC ' + run_id
    directory = qa.safe_target(qa.ROOT / ('business-mvcc-' + run_id))
    directory.mkdir(mode=0o700)
    output = directory / 'evidence.json'
    evidence = {'version': 1, 'run_id': run_id, 'site': qa.SITE, 'new_synthetic_user': user,
                'new_ungranted_role': role, 'checks': [], 'status': 'running', 'production_writes': False,
                'business_writes': False, 'codex_executed': False, 'existing_users_modified': False,
                'source': {module.__name__: qa.digest_file(Path(module.__file__)) for module in (tools, transport)}}
    redis = None
    threads = []
    created = False

    def check(label, condition):
        assert condition, label
        evidence['checks'].append(label)
        qa.private_json(output, evidence)
        print(json.dumps({'passed': label}), flush=True)

    def other_connection_disable(expect_timeout):
        """Fresh thread-local Frappe context: native User.save, no SQL bypass."""
        replies = queue.Queue()

        def worker():
            started = time.monotonic()
            try:
                frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
                qa.guard(frappe.conf)
                frappe.connect()
                frappe.set_user('Administrator')
                frappe.db.sql('SET SESSION innodb_lock_wait_timeout = 1')
                doc = frappe.get_doc('User', user)
                assert doc.name == user and user.startswith('business-mvcc-') and user.endswith('@example.invalid')
                doc.enabled = 0
                doc.save()
                frappe.db.commit()
                replies.put({'state': 'committed', 'elapsed': round(time.monotonic() - started, 3)})
            except BaseException as error:
                timeout_type = getattr(frappe, 'QueryTimeoutError', ())
                code = error.args[0] if error.args else None
                timeout = isinstance(error, timeout_type) or code == 1205
                replies.put({'state': 'lock_timeout' if timeout else 'failed',
                             'error_type': type(error).__name__, 'elapsed': round(time.monotonic() - started, 3)})
            finally:
                if getattr(frappe.local, 'site', None):
                    frappe.db.rollback()
                    frappe.destroy()

        thread = threading.Thread(target=worker, daemon=True)
        threads.append(thread)
        thread.start()
        thread.join(timeout=8)
        assert not thread.is_alive(), 'Bounded MVCC worker did not return; release locks and inspect evidence'
        result = replies.get_nowait()
        evidence.setdefault('second_connection_results', []).append(result)
        assert result['state'] == ('lock_timeout' if expect_timeout else 'committed'), result
        return result

    try:
        from hashlib import sha256
        def snapshot():
            result = {}
            for doctype in ('Student Attendance', 'Tongjianyun Class Meal Confirmation', 'Tongjianyun Daily Meal Confirmation'):
                names = frappe.get_all(doctype, pluck='name', limit_page_length=1001)
                assert len(names) <= 1000
                for name in names:
                    raw = json.dumps(frappe.get_doc(doctype, name).as_dict(), sort_keys=True, ensure_ascii=False, default=str)
                    result[doctype + ':' + name] = sha256(raw.encode()).hexdigest()
            teacher = 'teacher-scope-9680e04d9f@example.invalid'
            raw = json.dumps(frappe.get_doc('User', teacher).as_dict(), sort_keys=True, ensure_ascii=False, default=str)
            result['User:' + teacher] = sha256(raw.encode()).hexdigest()
            return result
        protected = snapshot()
        frappe.get_doc({'doctype': 'Role', 'role_name': role, 'desk_access': 1}).insert()
        frappe.get_doc({'doctype': 'User', 'email': user, 'first_name': 'MVCC QA ' + run_id, 'enabled': 1,
                        'user_type': 'System User', 'send_welcome_email': 0, 'roles': [{'role': role}]}).insert()
        frappe.db.commit()
        created = True
        check('new_role_has_no_doctype_or_custom_grants', not frappe.db.count('DocPerm', {'role': role})
              and not frappe.db.count('Custom DocPerm', {'role': role}))
        frappe.set_user(user)
        from tongjianyun.attendance_scope import allowed_groups
        check('synthetic_user_has_no_assigned_groups_or_attendance_meal_permissions', allowed_groups() == []
              and all(not frappe.has_permission(dt, action) for dt in
                      ('Student Attendance', 'Tongjianyun Class Meal Confirmation') for action in ('read', 'create', 'write')))
        frappe.set_user('Administrator')
        frappe.db.rollback()
        isolation = frappe.db.sql('SELECT @@session.tx_isolation')[0][0]
        check('real_qa_default_is_repeatable_read', isolation.upper().replace('_', '-') == 'REPEATABLE-READ')
        redis = Redis.from_url(frappe.conf.redis_queue, decode_responses=True)
        key = f'business-codex-qa:mvcc:{qa.SITE}:{task_id}:task'
        task = {'task_id': task_id, 'site': qa.SITE, 'owner': user, 'mode': 'business',
                'status': 'running', 'cancel_requested': '0'}
        assert not redis.exists(key)
        redis.hset(key, mapping=task)
        evidence['qa_redis_task_key'] = key
        binding = tools.BusinessBinding(user, qa.SITE, task_id, lambda wanted: redis.hgetall(key) if wanted == task_id else {})
        tools.validate_binding(binding, lock_owner=True)
        blocked = other_connection_disable(expect_timeout=True)
        check('locked_enabled_account_blocks_concurrent_native_disable', blocked['state'] == 'lock_timeout'
              and frappe.db.get_value('User', user, 'enabled') == 1)
        frappe.db.rollback()

        # A establishes an old consistent snapshot; B commits the real disable.
        tools.validate_binding(binding)
        check('connection_a_initial_snapshot_enabled', frappe.db.get_value('User', user, 'enabled') == 1)
        disabled = other_connection_disable(expect_timeout=False)
        check('connection_b_disabled_new_user_and_committed', disabled['state'] == 'committed')
        stale = frappe.db.get_value('User', user, 'enabled')
        check('ordinary_repeatable_read_still_sees_stale_enabled', stale == 1)
        try:
            tools.validate_binding(binding, lock_owner=True)
        except frappe.PermissionError as error:
            evidence['current_read_refusal'] = {'type': type(error).__name__,
                'database_cause': type(error.__cause__).__name__ if error.__cause__ else None,
                'meaning': 'Disabled current row or snapshot-conflict locking read both fail closed; no automatic retry'}
            check('locking_current_read_rejects_actual_disabled_account_despite_snapshot', True)
        else:
            raise AssertionError('Current User row lock did not detect disabled account')
        calls = {'operation': 0, 'commit': 0}
        def operation():
            calls['operation'] += 1
            return {'readback': {}, 'selection': {}, 'transaction': 'pending_commit'}
        def commit():
            calls['commit'] += 1
            frappe.db.commit()
        ledger = transport.DurableWriteLedger(directory, {k: task[k] for k in ('site', 'owner', 'task_id', 'mode')},
            validate=lambda bound: tools.validate_binding(bound, lock_owner=True), commit=commit,
            rollback=frappe.db.rollback, outcome=tools.WriteOutcome)
        try:
            ledger(binding, 'must-not-write', 'a' * 64, operation)
        except frappe.PermissionError:
            check('real_ledger_rejects_disabled_actor_before_operation_and_commit', calls == {'operation': 0, 'commit': 0})
        else:
            raise AssertionError('Ledger admitted a disabled owner')
        frappe.db.rollback()
        frappe.destroy()
        frappe = qa.connect()
        frappe.db.sql('START TRANSACTION READ ONLY')
        check('new_connection_confirms_synthetic_user_remains_disabled', frappe.db.get_value('User', user, 'enabled') == 0)
        check('all_existing_business_records_and_teacher_user_unchanged', snapshot() == protected)
        evidence.update(status='passed', protected_records=len(protected), actor_disabled_at_end=True)
        redis.hset(key, 'status', 'complete')
        qa.private_json(output, evidence)
        print(json.dumps({'status': 'passed', 'run_id': run_id, 'passed': len(evidence['checks']),
                          'evidence_file': str(output), 'production_writes': False, 'business_writes': False}))
        return 0
    except BaseException as error:
        evidence.update(status='failed', failure={'type': type(error).__name__, 'message': str(error)})
        qa.private_json(output, evidence)
        if redis is not None:
            redis.hset(key, 'status', 'failed')
        print(json.dumps({'status': 'failed', 'run_id': run_id, 'passed': len(evidence['checks']),
                          'evidence_file': str(output), 'failure_type': type(error).__name__}), flush=True)
        raise
    finally:
        if getattr(frappe.local, 'site', None):
            frappe.db.rollback()  # releases A's row lock even on worker timeout
        for thread in threads:
            thread.join(timeout=8)
        if created:
            # Only this run's newly created fixture can be disabled as cleanup.
            # Never changes roles or re-enables any account, including on failure.
            assert user == 'business-mvcc-' + run_id + '@example.invalid'
            frappe.set_user('Administrator')
            if frappe.db.get_value('User', user, 'enabled', for_update=True):
                doc = frappe.get_doc('User', user)
                doc.enabled = 0
                doc.save()
                frappe.db.commit()
        if getattr(frappe.local, 'site', None):
            frappe.db.rollback()
            frappe.destroy()
        if redis is not None:
            redis.close()


if __name__ == '__main__':
    raise SystemExit(run())
