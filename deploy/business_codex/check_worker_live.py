"""One real, non-root BusinessWorker attempt on existing synthetic QA data.

Default is prepare-only. --run consumes a durable execute-once marker before
creating its task. No automatic retries, production access, business writes,
account/role/session changes, service enable flags or direct admin runner.
Exercises the real task store -> site worker -> Unix daemon -> shared Codex ->
scoped tool -> public events. This is NOT HTTP/RQ/browser end-to-end evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'unified_business'))
import serve_isolated_browser as qa
sys.path.insert(0, str(HERE))
import check_live_codex as fixture

MARKER = qa.ROOT / 'business-worker-execute-once-20260925.json'
SOURCE_FILES = ('tongjianyun/business_agent_worker.py', 'tongjianyun/business_agent_tasks.py',
    'tongjianyun/business_agent_authority.py', 'tongjianyun/business_agent_events.py',
    'tongjianyun/business_agent_transport.py', 'tongjianyun/business_agent_tools.py',
    'tongjianyun/business_agent_service.py', 'tongjianyun/classroom.py',
    'tongjianyun/attendance_scope.py', 'tongjianyun/meal_chat_events.py',
    'deploy/business_codex/check_live_codex.py', 'deploy/unified_business/serve_isolated_browser.py',
    'deploy/business_codex/native_launcher.py', 'deploy/business_codex/check_worker_live.py')


def readonly_adapter(frappe):
    from tongjianyun.business_agent_authority import FreshFrappeChecks, FrappeBusinessAuthority
    def before():
        qa.config_guard()
        qa.guard(frappe.conf)
    fresh = FreshFrappeChecks(qa.SITE, str(qa.SITES), before_connect=before)
    def read(owner, callback):
        def guarded():
            frappe.db.sql('SET SESSION TRANSACTION READ ONLY')
            if frappe.db.sql('SELECT @@session.tx_read_only')[0][0] != 1:
                raise PermissionError('QA database must remain read-only')
            frappe.flags.read_only = True
            return callback()
        return fresh(owner, guarded)
    return FrappeBusinessAuthority(qa.SITE, run_check=read)


def reserve(value):
    qa.safe_target(MARKER)
    fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(json.dumps(value, sort_keys=True).encode())
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    fd = os.open(MARKER.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run(execute=False):
    if sys.flags.optimize or os.name != 'posix' or os.geteuid() == 0:
        raise PermissionError('Run as the existing site user, never root or optimized Python')
    qa.config_guard()
    frappe = qa.runtime()
    from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation
    from tongjianyun.business_agent_worker import BusinessWorker, UnixLauncherRuntime
    from tongjianyun.business_agent_transport import TaskProxy, private_directory
    from tongjianyun.business_agent_service import _model_key
    hashes = {name: qa.digest_file(qa.SOURCE / name) for name in SOURCE_FILES}
    runtime = UnixLauncherRuntime(site=qa.SITE, sites_path=str(qa.SITES))
    if runtime.ready() is not True:
        raise PermissionError('The authenticated installed QA launcher is not ready')
    adapter = readonly_adapter(frappe)
    def baseline():
        fixture.account_guard(frappe)
        return fixture.protected_digest(frappe)
    before = adapter.run_check(fixture.TEACHER, baseline)
    result = {'version':1, 'site':qa.SITE, 'worker_uid':os.geteuid(), 'source_sha256':hashes,
        'shared_launcher_ready':True, 'ordinary_teacher_verified':True,
        'production_access':False, 'database_session_read_only':True,
        'http_rq_browser_exercised':False, 'model_started':False, 'executed':False}
    if not execute:
        print(json.dumps({**result, 'prepare_passed':True, 'execute_once_marker_exists':MARKER.exists()}), flush=True)
        return
    task_id = str(uuid.uuid4())
    result.update(task_id=task_id, all_passed=False)
    reserve({'site':qa.SITE, 'task_id':task_id, 'source_sha256':hashes, 'automatic_retry_allowed':False})
    evidence = qa.safe_target(qa.ROOT / ('business-worker-live-' + task_id + '.json'))
    qa.private_json(evidence, result)
    proxies, calls = [], []
    store = identity = None
    def proxy_factory(directory, token, **kwargs):
        handler = kwargs['tool_handler']
        def tool(tool_name, arguments, call_id):
            data = handler(tool_name, arguments, call_id)
            calls.append({'tool':tool_name, 'group_matches':data.get('group') == fixture.GROUP,
                'day_matches':data.get('day') == fixture.DAY,
                'counts':data.get('counts') if tool_name == 'classroom_read' else None,
                'student_count':len(data.get('students',[])) if tool_name == 'classroom_read' else None})
            return data
        kwargs['tool_handler'] = tool
        proxy = TaskProxy(directory, token, max_model_calls=16, **kwargs)
        proxies.append(proxy)
        return proxy
    try:
        parent = qa.safe_target(qa.SITES / qa.SITE / 'private/business-codex')
        parent.mkdir(mode=0o700, exist_ok=True)
        private_directory(parent)
        directory = parent / 'tasks'
        directory.mkdir(mode=0o700, exist_ok=True)
        private_directory(directory)
        store = BusinessTaskStore(directory, qa.SITE, authorize=adapter,
            observe_execution=runtime.observe, seal_execution=runtime.seal_before_start,
            observe_queue=lambda job:QueueObservation(job,'present'))
        identity = TaskIdentity(qa.SITE, fixture.TEACHER, task_id)
        choice = {'view':'classroom_day','group':fixture.GROUP,'day':fixture.DAY,'meal':fixture.MEAL}
        scopes = adapter.view_scopes(identity, choice)
        created = store.create(fixture.TEACHER, task_id,
            '请实际查询本班这一天的出勤，告诉我可见学生人数和未登记人数，并显示左侧出勤视图。只查询，不修改数据。',
            {'day':fixture.DAY,'meal':fixture.MEAL,'selection':choice}, authority_scopes=scopes)
        if created['created'] is not True:
            raise RuntimeError('New QA task unexpectedly exists')
        ticket = store.take_dispatch(identity)
        store.acknowledge_dispatch(ticket)
        worker = BusinessWorker(store, runtime, model_key=_model_key, proxy_factory=proxy_factory,
            read_attendance=lambda claim,**args:adapter.read_attendance(store,claim,**args))
        result['executed'] = True
        qa.private_json(evidence,result)
        result['worker_result'] = worker.run(identity,store.job_id(identity))
        events = store.events(identity,limit=100)
        result['event_kinds'] = [event['kind'] for event in events]
        result['view_requested'] = any(event.get('kind') == 'view'
            and event.get('selection',{}).get('view') == 'classroom_day'
            and event.get('selection',{}).get('group') == fixture.GROUP
            and event.get('selection',{}).get('day') == fixture.DAY for event in events)
        result['public_answer_present'] = 'message' in result['event_kinds']
        result['scopes_registered'] = len(store.required_scopes(identity))
        result['tool_calls'] = calls
        result['model_calls'] = sum(proxy.model_calls for proxy in proxies)
        result['model_started'] = result['model_calls'] > 0
        result['final_status'] = store.task(identity)['status']
        observed = runtime.observe(identity, store._owned(identity)['claim_id'])
        result['launcher_exit_verified'] = (observed.state == 'exited' and observed.exit_code == 0
                                            and observed.lease_closed and observed.active_writes == 0)
        after = adapter.run_check(fixture.TEACHER,baseline)
        result['protected_business_digest_unchanged'] = before == after
        # A second delivery must not start a second model/proxy, even after success.
        count = len(proxies)
        repeated = worker.run(identity,store.job_id(identity))
        result['redelivery_did_not_execute'] = repeated.get('started') is False and len(proxies) == count
        result['all_passed'] = (result['final_status'] == 'completed' and result['view_requested']
            and result['public_answer_present'] and result['model_started']
            and any(call['tool']=='classroom_read' and call['student_count']==2
                    and call['group_matches'] and call['day_matches'] for call in calls)
            and result['protected_business_digest_unchanged'] and result['redelivery_did_not_execute']
            and result['launcher_exit_verified'])
    except BaseException as error:
        result['failure_type'] = type(error).__name__
        # Worker owns exact-unit cancellation/cleanup. Do not retry or manufacture
        # terminal proof here; unresolved state and original marker are preserved.
        raise
    finally:
        result['model_calls'] = sum(proxy.model_calls for proxy in proxies)
        result['model_started'] = result['model_calls'] > 0
        result['tool_calls'] = calls
        qa.private_json(evidence,result)
        print(json.dumps({'evidence':str(evidence),'task_id':task_id,
            'all_passed':result.get('all_passed',False),'model_calls':result['model_calls'],
            'failure_type':result.get('failure_type')}),flush=True)
    if not result['all_passed']:
        raise RuntimeError('Real business worker acceptance did not pass; do not automatically replay')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    args = parser.parse_args()
    try:
        run(args.run)
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__,
                          'detail':'Worker QA stopped; original task/evidence retained; no automatic retry'}),flush=True)
        raise SystemExit(1) from None
