"""Reload this feature's zyd-owned services only when no conversation is active.

Run as the native bench service owner after the tested commit is fast-forwarded.
No privilege escalation, database schema change or global queue reset is used.
"""
import os
import signal
import subprocess
import sys
from pathlib import Path

import frappe

frappe.init(site='child.myyr.top', sites_path=str(Path.cwd() / 'sites'))
frappe.connect()
try:
    from tongjianyun.meal_chat import TaskStore, SESSION_RE, ACTIVE
    store = TaskStore()
    active = 0
    for raw in store.redis.scan_iter(match=store.prefix + '*', count=100):
        key = raw.decode() if isinstance(raw, bytes) else str(raw)
        task_id = key[len(store.prefix):]
        if SESSION_RE.fullmatch(task_id) and store.read(task_id).get('status') in ACTIVE:
            active += 1
    if active:
        raise SystemExit(f'Not reloading: {active} active conversations; wait for completion.')
    if '--check-only' in sys.argv:
        print('No active conversations; safe to deploy this batch.')
        raise SystemExit(0)
    units = ['frappe-native-web.service', 'frappe-native-meal-sse.service', 'frappe-native-worker-meal-chat.service']
    processes = []
    for unit in units:
        output = subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID', '-p', 'Restart', '-p', 'User'], text=True)
        props = dict(line.split('=', 1) for line in output.splitlines())
        pid = int(props['MainPID'])
        if props['User'] != 'zyd' or props['Restart'] != 'always' or pid <= 1 or Path(f'/proc/{pid}').stat().st_uid != os.getuid():
            raise SystemExit('Service identity/restart policy mismatch: ' + unit)
        processes.append((unit, pid))
    frappe.clear_cache()
    for unit, pid in processes:
        os.kill(pid, signal.SIGTERM)
        print('Requested graceful restart:', unit)
finally:
    frappe.db.rollback()
    frappe.destroy()
