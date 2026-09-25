"""Read-only review of a completed explicit-cancellation QA; never starts Codex.

systemd-run --wait may return zero for a successful administrator stop job.
The client exit code alone therefore proves neither cancellation nor natural
completion. Check PID-1 journal ordering, exact resource disappearance and the
retained stdout lifecycle instead. The original attempt report is never edited.
Only a new, private review report is written; no model/DB/key access is needed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid

import check_live_codex as live

STARTED = '39f53479d3a045ac8e11786248231fbf'
STOPPING = 'de5b426a63be47a7b6ac3eaac82e2f6f'
STOPPED = '9d1aaa27d60140bd96365438aad20286'
DEACTIVATED = '7ad2d189f7e94e70a38c781354912448'
LIFECYCLE = frozenset({STARTED, STOPPING, STOPPED, DEACTIVATED})


def _positive_decimal(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[0-9]{1,20}', value)) and int(value) > 0


def _journal_stop(journal, unit):
    """Do not use user message text, wall-clock ordering or mixed invocations."""
    if not isinstance(journal, (list, tuple)) or len(journal) > 64:
        return False, []
    records = [row for row in journal if type(row) is dict
        and row.get('_PID') == '1' and row.get('_UID') == '0' and row.get('_COMM') == 'systemd'
        and row.get('_EXE') in ('/usr/lib/systemd/systemd', '/lib/systemd/systemd')
        and row.get('_TRANSPORT') == 'journal' and row.get('_SYSTEMD_UNIT') == 'init.scope'
        and row.get('_SYSTEMD_CGROUP') == '/init.scope' and row.get('UNIT') == unit
        and isinstance(row.get('MESSAGE_ID'), str) and row['MESSAGE_ID'] in LIFECYCLE]
    if len(records) != 4 or {row['MESSAGE_ID'] for row in records} != LIFECYCLE:
        return False, records
    for field in ('_BOOT_ID', '_MACHINE_ID', 'INVOCATION_ID'):
        values = {row.get(field) for row in records if isinstance(row.get(field), str)}
        if len(values) != 1 or not all(re.fullmatch(r'[0-9a-f]{32}', value) for value in values) or any(
                not isinstance(row.get(field), str) or row[field] not in values for row in records):
            return False, records
    if not all(_positive_decimal(row.get('__MONOTONIC_TIMESTAMP')) for row in records):
        return False, records
    records.sort(key=lambda row: int(row['__MONOTONIC_TIMESTAMP']))
    if (len({int(row['__MONOTONIC_TIMESTAMP']) for row in records}) != 4
            or [row['MESSAGE_ID'] for row in records] != [STARTED, STOPPING, DEACTIVATED, STOPPED]):
        return False, records
    start, stop, _, done = records
    ordered = (start.get('JOB_TYPE') == 'start' and start.get('JOB_RESULT') == 'done'
        and _positive_decimal(start.get('JOB_ID')) and stop.get('JOB_TYPE') == 'stop'
        and _positive_decimal(stop.get('JOB_ID')) and done.get('JOB_TYPE') == 'stop'
        and done.get('JOB_RESULT') == 'done' and done.get('JOB_ID') == stop['JOB_ID'])
    return ordered, records


def assess(report, journal, *, unit_absent, pid_absent, cgroup_absent, inputs_absent):
    """Fixed facts only; journal entries must originate from trusted PID 1."""
    if type(report) is not dict:
        raise ValueError('Expected a private QA report')
    task = live.canonical(report.get('task_id'))
    unit = 'tgy-business-codex-' + task + '.service'
    ordered, records = _journal_stop(journal, unit)
    identity = report.get('cancel_trigger_identity')
    identity = identity if type(identity) is dict else {}
    cleanup = report.get('cleanup')
    cleanup = cleanup if type(cleanup) is dict else {}
    tools = report.get('tool_calls')
    tools_valid = type(tools) is list and all(type(row) is dict for row in tools)
    events = report.get('jsonl_events')
    events_valid = (type(events) is list and 0 < len(events) < live.MAX_EVENTS
                    and all(type(row) is dict for row in events))
    checks = {
        'exact_task_report': report.get('mode') == 'execute_once' and report.get('site') == live.qa.SITE
            and report.get('unit') == unit,
        'explicit_case': report.get('acceptance_case') == 'explicit-cancellation',
        'cancelled_not_completed': report.get('status') == 'cancelled',
        'trigger_while_live': report.get('explicit_cancellation_exercised') is True
            and report.get('cancel_trigger_process_unexited') is True,
        'reviewed_codex_identity': all(identity.get(key) is True for key in
            ('dynamic_uid', 'non_root_non_site_owner', 'capabilities_empty', 'binary_inode_matches_reviewed_runtime'))
            and identity.get('seccomp') == '2' and identity.get('no_new_privs') == '1'
            and type(identity.get('pid')) is int and identity['pid'] > 1
            and type(identity.get('uid')) is int and 61184 <= identity['uid'] <= 65519,
        'real_read_tool_returned': tools_valid and any(row.get('tool') == 'scene_bootstrap' and row.get('success') is True
                                                     for row in tools),
        'model_request_started': type(report.get('model_calls')) is int and report['model_calls'] > 0,
        # Missing/truncated output or a model terminal leaves the race ambiguous.
        'lifecycle_output_complete': events_valid and report.get('malformed_jsonl_events') == 0
            and type(report.get('malformed_jsonl_events')) is int,
        'no_normal_turn_completion': events_valid and not any(row.get('type') in {'turn.completed', 'turn.failed'}
                                                             for row in events),
        'client_exit_observed': type(report.get('process_exit_code')) is int,
        'pid1_ordered_stop_job': ordered,
        'unit_absent': unit_absent is True,
        'codex_pid_absent': pid_absent is True,
        'cgroup_absent': cgroup_absent is True,
        'input_and_runtime_absent': inputs_absent is True,
        'cleanup_complete': cleanup.get('unit') == unit and cleanup.get('unit_load_state') == 'not-found'
            and cleanup.get('errors') == [] and all(cleanup.get(key) is True for key in (
                'task_token_removed', 'task_input_directory_removed', 'dynamic_runtime_directory_removed', 'jsonl_readers_stopped')),
        'protected_business_unchanged': report.get('protected_business_digest_unchanged') is True,
        'no_business_or_production_writes': report.get('business_writes') is False
            and report.get('production_writes') is False,
    }
    return {'checks': checks, 'cancellation_verified': all(checks.values()),
            'task_status': report.get('status'), 'client_exit_code': report.get('process_exit_code'),
            'journal_events_inspected': len(records),
            'journal_stop_sequence': [{key: row.get(key) for key in
                ('MESSAGE_ID', '__MONOTONIC_TIMESTAMP', '_BOOT_ID', '_MACHINE_ID', 'INVOCATION_ID', 'JOB_ID')}
                for row in records] if ordered else []}


def _absent(path):
    # A broken leaf symlink is still a residual resource, never successful cleanup.
    return not path.exists() and not path.is_symlink()


def observe(report):
    task = live.canonical(report.get('task_id'))
    unit = 'tgy-business-codex-' + task + '.service'
    result = subprocess.run(['/usr/bin/journalctl', '--unit=' + unit, '--no-pager', '--output=json', '-n', '64'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=live.CHILD_ENV, check=True, timeout=15)
    if len(result.stdout) > 262144:
        raise ValueError('Unexpected journal evidence size')
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    pid = (report.get('cancel_trigger_identity') or {}).get('pid')
    if type(pid) is not int or pid <= 1:
        raise ValueError('Missing exact cancellation process identity')
    return assess(report, rows,
        unit_absent=live.unit_state(unit).get('LoadState') == 'not-found',
        pid_absent=_absent(Path('/proc') / str(pid)),
        cgroup_absent=_absent(Path('/sys/fs/cgroup/system.slice') / unit),
        inputs_absent=_absent(live.INPUT / task) and _absent(Path('/run') / ('tgy-business-' + task)))


def review(task):
    task = live.canonical(task)
    live.fixture_guard()
    report, raw, _ = live.read_root_json(live.qa.ROOT / ('live-codex-' + task + '.json'))
    if report.get('task_id') != task or report.get('site') != live.qa.SITE:
        raise PermissionError('Evidence identity mismatch')
    result = observe(report)
    if live.read_root_json(live.qa.ROOT / ('live-codex-' + task + '.json'))[1] != raw:
        raise PermissionError('Original evidence changed during review')
    import hashlib
    result.update(task_id=task, original_report_sha256=hashlib.sha256(raw).hexdigest(),
                  reviewer_sha256=live.qa.digest_file(Path(__file__)), model_executed=False,
                  original_report_modified=False)
    output = live.qa.safe_target(live.qa.ROOT / ('live-codex-cancel-review-' + task + '-' + uuid.uuid4().hex[:10] + '.json'))
    live.private_create(output, json.dumps(result, ensure_ascii=False, sort_keys=True).encode())
    return {**result, 'review_file': str(output)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task_id')
    args = parser.parse_args()
    try:
        result = review(args.task_id)
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result['cancellation_verified'] else 1)
    except Exception as error:
        print(json.dumps({'ok': False, 'error_type': type(error).__name__, 'details_redacted': True}))
        raise SystemExit(1)
