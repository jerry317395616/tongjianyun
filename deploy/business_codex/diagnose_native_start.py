"""Administrator-only, model-free diagnosis of the exact native outer sandbox.

Run manually as root. No Frappe import, database, model, API key or Codex execution.
Only one fresh UUID's synthetic inputs, socket and transient unit are created.
The installed runtime and all systemd/bwrap restrictions remain unchanged.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import subprocess
import sys
import uuid

INSTALL = Path('/opt/tongjianyun-business-codex')
INPUT = Path('/run/tongjianyun-business-codex/tasks')
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
MAX_ERROR = 4096

# Only this model-free diagnostic accepts these enumerated profiles. No caller
# can supply arbitrary systemd properties, command, mount, UID or environment.
# Historical v1 profiles are refused once the installed runtime carries the
# bwrap-ro-v2 fix; they must not be applied on top of the corrected baseline.
# Profile differences are temporary properties of a single disposable unit.
PROFILES = {
    'baseline': {},
    'protectproc-default': {'ProtectProc': 'default'},
    'tunables-off': {'ProtectKernelTunables': 'no'},
    'logs-off': {'ProtectKernelLogs': 'no'},
    'hostname-off': {'ProtectHostname': 'no'},
    'tunables-logs-off': {'ProtectKernelTunables': 'no', 'ProtectKernelLogs': 'no'},
    'tunables-hostname-off': {'ProtectKernelTunables': 'no', 'ProtectHostname': 'no'},
    'logs-hostname-off': {'ProtectKernelLogs': 'no', 'ProtectHostname': 'no'},
    'proc-overmounts-off': {'ProtectKernelTunables': 'no', 'ProtectKernelLogs': 'no', 'ProtectHostname': 'no'},
    'proc-overmounts-off-default': {'ProtectKernelTunables': 'no', 'ProtectKernelLogs': 'no', 'ProtectHostname': 'no', 'ProtectProc': 'default'},
}

# No credential content is read. This program runs only after the whole bwrap
# setup succeeds, and cannot issue model requests or connect to any service.
PROBE = r'''import json,os,stat
from pathlib import Path
s=Path('/proc/self/status').read_text()
fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in s.splitlines() if ':' in line}
print(json.dumps({'probe':'native_start_v1','uid':os.geteuid(),'gid':os.getegid(),
 'nnp':fields.get('NoNewPrivs'),'seccomp':fields.get('Seccomp'),'caps':fields.get('CapEff'),
 'proc_read_only':any(line.split()[4]=='/proc' and 'ro' in line.split()[5].split(',') for line in Path('/proc/self/mountinfo').read_text().splitlines()),
 'socket_mounted':stat.S_ISSOCK(Path('/bridge/proxy.sock').stat().st_mode),
 'synthetic_credentials_mounted':Path('/bridge/task-token').is_file() and Path('/bridge/prompt.txt').is_file(),
 'host_home_visible':Path('/home/zyd/frappe').exists()}))
'''

# This is fixed code, not a request-supplied command or alternative runner.
# Keep the same pre-bwrap identity/runtime guards as native.run_task.
CHILD = r'''import importlib.util,json,os,stat,subprocess,sys
from pathlib import Path
task_id=sys.argv[1]
path=Path('/opt/tongjianyun-business-codex/native_sandbox.py')
for p in (path,*path.parents):
 info=p.lstat()
 if stat.S_ISLNK(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
  raise PermissionError('untrusted installed runtime')
spec=importlib.util.spec_from_file_location('diagnostic_native',path)
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
native.validate_task_id(task_id)
if not 61184<=os.geteuid()<=65519 or any(g!=os.getegid() for g in os.getgroups()):
 raise PermissionError('dedicated DynamicUser required')
if Path(os.environ.get('RUNTIME_DIRECTORY',''))!=native.runtime_path(task_id):
 raise PermissionError('wrong runtime directory')
for name in ('codex','native_sandbox.py','sandbox_entry.py','business_tool.py'):
 native.require_root_owned_file(native.INSTALL_ROOT/name)
work=native.runtime_path(task_id);info=work.stat()
if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
 raise PermissionError('private task runtime required')
if not stat.S_ISSOCK((work/'proxy.sock').stat().st_mode):
 raise PermissionError('synthetic proxy socket missing')
proc_mounts=[]
for line in Path('/proc/self/mountinfo').read_text().splitlines():
 fields=line.split()
 if len(fields)>6 and (fields[4]=='/proc' or fields[4].startswith('/proc/')):
  proc_mounts.append({'mountpoint':fields[4],'options':fields[5]})
fd=native.export_seccomp_fd()
try:
 argv=native.build_bwrap_command(task_id,Path(os.environ.get('CREDENTIALS_DIRECTORY','')),fd)
 if argv[-3:]!=['/usr/bin/python3','-I','/opt/business-codex/sandbox_entry.py']:
  raise RuntimeError('unexpected bwrap entry')
 argv=argv[:-3]+['/usr/bin/python3','-I','-c',PROBE_LITERAL]
 result=subprocess.run(argv,pass_fds=(fd,),close_fds=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},capture_output=True,timeout=30)
 print(json.dumps({'stage':'bwrap','returncode':result.returncode,
  'outer_proc_mounts':proc_mounts[:64],
  'stdout':result.stdout[:4096].decode('utf-8','replace'),
  'stderr':result.stderr[:4096].decode('utf-8','replace'),
  'stderr_truncated':len(result.stderr)>4096}))
 raise SystemExit(result.returncode)
finally:
 os.close(fd)
'''.replace('PROBE_LITERAL', repr(PROBE))


def root_path(path, *, directory=False, private=False):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise PermissionError('Expected an exact administrator path')
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('Runtime must be root-owned and immutable')
    info = path.stat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise PermissionError('Wrong administrator path type')
    if private and stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError('Task parent must be root-only 0700')


def load_native():
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise PermissionError('Run this fixed diagnostic manually as administrator')
    root_path(INSTALL, directory=True)
    root_path(INPUT, directory=True, private=True)
    path = INSTALL / 'native_sandbox.py'
    root_path(path)
    spec = importlib.util.spec_from_file_location('diagnostic_native', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.INSTALL_ROOT != INSTALL or module.INPUT_ROOT != INPUT:
        raise PermissionError('Unexpected installed native paths')
    return module


def build_command(native, task_id, profile='baseline'):
    if profile not in PROFILES:
        raise ValueError('Unknown fixed diagnostic profile')
    if profile != 'baseline' and getattr(native, 'PROC_ISOLATION_REVISION', None) is not None:
        raise ValueError('Historical v1 matrix is not valid for the corrected runtime; use baseline')
    argv = native.build_systemd_command(task_id)
    original = ['/usr/bin/python3', '-I', (INSTALL / 'native_sandbox.py').as_posix(), '--task-id', task_id]
    if argv[-5:] != original:
        raise ValueError('Unexpected native systemd entry')
    for key, value in PROFILES[profile].items():
        expected = '--property=' + key + '=' + ('invisible' if key == 'ProtectProc' else 'yes')
        if argv.count(expected) != 1:
            raise ValueError('Unexpected native property to diagnose')
        argv[argv.index(expected)] = '--property=' + key + '=' + value
    return argv[:-5] + ['/usr/bin/python3', '-I', '-c', CHILD, task_id]


def error_class(value):
    text = value[:MAX_ERROR].lower()
    for name, patterns in (
        ('uid_map', ('uid_map', 'gid_map', 'uid map', 'gid map')),
        ('user_namespace', ('creating new namespace failed', 'user namespace', 'unshare')),
        ('mount', ('mount', 'remount', 'bind')),
        ('seccomp', ('seccomp', 'filter')),
        ('permission', ('permission denied', 'operation not permitted')),
        ('systemd_setup', ('failed at step', 'failed to start transient')),
    ):
        if any(pattern in text for pattern in patterns):
            return name
    return 'other' if text.strip() else 'none'


def private_file(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(content)


def cleanup(native, task_id, directory, listener, created):
    """No broad deletion; never touch an input directory we did not create."""
    if not created:
        return {'owned': False, 'unit_stopped': None, 'inputs_removed': False}
    if directory != INPUT / task_id or native.validate_task_id(task_id) != task_id:
        raise ValueError('Unexpected diagnostic cleanup target')
    stopped = False
    try:
        subprocess.run(['/usr/bin/systemctl', 'stop', native.unit_name(task_id)],
                       env=ENV, capture_output=True, timeout=25, check=False)
        result = subprocess.run(['/usr/bin/systemctl', 'show', native.unit_name(task_id),
                                 '--property=ActiveState', '--value'], env=ENV,
                                capture_output=True, timeout=10, check=False)
        stopped = result.stdout.strip() in (b'', b'inactive', b'failed')
    except Exception:
        pass
    finally:
        if listener is not None:
            listener.close()
        # Inputs are root-only and contain only our synthetic disposable data.
        # Token unlink happens even if stopping the unit needs administrator review.
        for name in ('token', 'prompt.txt', 'proxy.sock'):
            (directory / name).unlink(missing_ok=True)
    removed = False
    if stopped:
        directory.rmdir()  # Refuse unknown children; do not recursively delete.
        removed = True
    return {'owned': True, 'unit_stopped': stopped, 'inputs_removed': removed}


def run(profile='baseline', *, report_only=False):
    if profile not in PROFILES:
        raise ValueError('Unknown fixed diagnostic profile')
    native = load_native()  # Root refusal occurs before UUID/file/process activity.
    task_id = str(uuid.uuid4())
    command = build_command(native, task_id, profile)  # Reject obsolete profile before creating inputs.
    directory = INPUT / task_id
    listener, created = None, False
    report = {'diagnostic': 'native_start_v1', 'task_id': task_id,
              'profile': profile, 'temporary_property_changes': PROFILES[profile],
              'runtime_proc_revision': getattr(native, 'PROC_ISOLATION_REVISION', 'systemd-overmount-v1'),
              'model_called': False, 'database_accessed': False, 'runtime_modified': False}
    previous = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        directory.mkdir(mode=0o700)
        created = True
        root_path(directory, directory=True, private=True)
        private_file(directory / 'token', secrets.token_urlsafe(48).encode())
        private_file(directory / 'prompt.txt', b'Synthetic native startup diagnostic. No model is invoked.\n')
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(directory / 'proxy.sock'))
        os.chmod(directory / 'proxy.sock', 0o666)  # Private 0700 parent; identical read-only single-socket mount.
        listener.listen(1)  # No request handler, model credential or business callback exists.
        result = subprocess.run(command, env=ENV, capture_output=True,
                                timeout=45, check=False)
        report['process_returncode'] = result.returncode
        report['system_stderr'] = result.stderr[:MAX_ERROR].decode('utf-8', 'replace')
        report['system_stderr_truncated'] = len(result.stderr) > MAX_ERROR
        try:
            stage = json.loads(result.stdout[:16384])
            if type(stage) is not dict or set(stage) != {'stage', 'returncode', 'outer_proc_mounts', 'stdout', 'stderr', 'stderr_truncated'} or stage['stage'] != 'bwrap':
                raise ValueError('Unexpected diagnostic output')
            report['bwrap'] = stage
            report['error_class'] = error_class(stage['stderr'])
        except (ValueError, UnicodeError):
            report['error_class'] = error_class(report['system_stderr'])
            report['stage'] = 'before_bwrap_or_no_report'
    except (Exception, KeyboardInterrupt) as exc:
        report['error_class'] = type(exc).__name__  # No arbitrary exception text/trace.
    finally:
        report['cleanup'] = cleanup(native, task_id, directory, listener, created)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report_only:
        return report
    return 0 if report.get('process_returncode') == 0 and report['cleanup']['inputs_removed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument('--profile', choices=tuple(PROFILES), default='baseline')
    options.add_argument('--matrix', action='store_true', help='Run each fixed model-free profile once')
    args = parser.parse_args()
    if args.matrix:
        if getattr(load_native(), 'PROC_ISOLATION_REVISION', None) is not None:
            raise SystemExit('Historical v1 matrix refused for corrected runtime; run baseline without --matrix')
        outcomes = []
        for profile in PROFILES:
            report = run(profile, report_only=True)
            outcomes.append({'profile': profile, 'task_id': report['task_id'],
                             'returncode': report.get('process_returncode'),
                             'error_class': report.get('error_class'), 'cleanup': report['cleanup']})
            if not report['cleanup']['inputs_removed']:
                break  # Never accumulate live units or ambiguous cleanup.
        print(json.dumps({'matrix': outcomes}, ensure_ascii=False, indent=2))
        raise SystemExit(0 if len(outcomes) == len(PROFILES) and all(row['cleanup']['inputs_removed'] for row in outcomes) else 1)
    raise SystemExit(run(args.profile))
