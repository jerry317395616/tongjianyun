"""Refresh only Frappe caches and gracefully reload this bench's web workers.

No migrations, installations, role changes, background-worker restarts or
business data writes. Run once after deploying the source files.
"""
import os
import signal
import subprocess
from pathlib import Path
import frappe

bench = Path.cwd().resolve()
assert bench.name == "native-bench" and (bench / "apps/tongjianyun/tongjianyun/classroom.py").is_file()
frappe.init(site=os.environ.get("CLASSROOM_TEST_SITE", "child.myyr.top"), sites_path=str(bench / "sites"))
frappe.connect()
try:
    frappe.set_user("Administrator")
    frappe.clear_cache()
    from frappe.website.utils import clear_website_cache
    clear_website_cache()
    print("Frappe and website caches refreshed; no schema migration")
finally:
    frappe.db.rollback()
    frappe.destroy()

processes = subprocess.check_output(["ps", "-C", "gunicorn", "-o", "pid=,ppid=,args="], text=True)
masters = []
for line in processes.splitlines():
    pid, ppid, command = line.strip().split(None, 2)
    if ppid == "1" and str(bench / "env/bin/gunicorn") in command and "--bind=127.0.0.1:17800" in command:
        masters.append(int(pid))
if len(masters) != 1:
    raise RuntimeError("Cannot uniquely identify this bench's web master; no process signalled")
os.kill(masters[0], signal.SIGHUP)
print("Graceful HUP sent to this bench's web master", masters[0])
