"""No-model smoke test of the actual compiled filter in actual bwrap namespaces.

Run as an ordinary host user. This does NOT install or prove DynamicUser identity,
proxy authorization, complete kernel isolation, or real model/tool compatibility.
No secrets, production DB queries, or persistent files are used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import native_sandbox

PROBE = r'''
import ctypes, errno, json, os, pathlib, platform, socket, subprocess, threading
libc = ctypes.CDLL(None, use_errno=True)
status = dict(line.split(':', 1) for line in pathlib.Path('/proc/self/status').read_text().splitlines())
tests = {}
def expect_error(name, function, expected):
    ctypes.set_errno(0)
    value = function()
    found = ctypes.get_errno()
    tests[name] = {'passed': value == -1 and found == expected, 'errno': found}
expect_error('ptrace_denied', lambda: libc.ptrace(0, 0, None, None), errno.EPERM)
expect_error('unshare_denied', lambda: libc.unshare(0x10000000), errno.EPERM)
expect_error('mount_denied', lambda: libc.mount(None, b'/tmp', None, 0, None), errno.EPERM)
expect_error('setns_denied', lambda: libc.setns(-1, 0), errno.EPERM)
expect_error('syslog_denied', lambda: libc.klogctl(10, None, 0), errno.EPERM)
expect_error('sethostname_denied', lambda: libc.sethostname(b'probe', 5), errno.EPERM)
expect_error('setdomainname_denied', lambda: libc.setdomainname(b'probe', 5), errno.EPERM)
numbers = {'aarch64': {'clone3':435,'bpf':280,'keyctl':219,'perf_event_open':241,'io_uring_setup':425,'process_vm_readv':270},
           'x86_64': {'clone3':435,'bpf':321,'keyctl':250,'perf_event_open':298,'io_uring_setup':425,'process_vm_readv':310}}
if platform.machine() not in numbers:
    raise RuntimeError('diagnostic syscall map unavailable')
for name, number in numbers[platform.machine()].items():
    expect_error(name + '_filtered', lambda n=number: libc.syscall(n, 0, 0, 0, 0, 0, 0), errno.ENOSYS if name == 'clone3' else errno.EPERM)
try:
    socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 0)
    tests['netlink_denied'] = {'passed': False}
except OSError as exc:
    tests['netlink_denied'] = {'passed': exc.errno == errno.EPERM, 'errno': exc.errno}
for address in [('127.0.0.1',23316), ('172.18.112.42',22), ('169.254.169.254',80)]:
    sock = socket.socket()
    sock.settimeout(1)
    error = sock.connect_ex(address)
    sock.close()
    tests['network_' + address[0]] = {'passed': error in (errno.ENETUNREACH, errno.ECONNREFUSED), 'errno': error}
threads = []
thread = threading.Thread(target=lambda: threads.append(True)); thread.start(); thread.join()
tests['ordinary_thread_works'] = {'passed': threads == [True]}
tests['ordinary_subprocess_works'] = {'passed': subprocess.run(['/usr/bin/true']).returncode == 0}
tests['seccomp_loaded'] = {'passed': status['Seccomp'].strip() == '2'}
tests['no_new_privileges'] = {'passed': status['NoNewPrivs'].strip() == '1'}
tests['capabilities_empty'] = {'passed': all(int(status[key].strip(),16) == 0 for key in ('CapEff','CapPrm','CapInh','CapBnd','CapAmb'))}
tests['host_paths_hidden'] = {'passed': all(not pathlib.Path(p).exists() for p in ('/home/zyd/frappe','/root','/etc','/run/docker.sock','/run/user/1000','/usr/local'))}
tests['pid_namespace'] = {'passed': len([p for p in pathlib.Path('/proc').iterdir() if p.name.isdigit()]) <= 3}
tests['no_network_routes'] = {'passed': len(pathlib.Path('/proc/net/route').read_text().strip().splitlines()) == 1}
proc_mounts = [line.split() for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines() if line.split()[4] == '/proc']
tests['proc_read_only'] = {'passed': len(proc_mounts) == 1 and 'ro' in proc_mounts[0][5].split(',')}
print(json.dumps({'tests': tests, 'all_passed': all(test['passed'] for test in tests.values()), 'system_identity_verified':False,'real_codex_model_verified':False}))
'''


def main():
    if sys.platform != "linux" or os.geteuid() == 0:
        raise SystemExit("Run as an ordinary Linux user; this is not a root installation test")
    fd = native_sandbox.export_seccomp_fd()
    try:
        args = ["/usr/bin/bwrap", "--unshare-all", "--unshare-user", "--disable-userns",
                "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
                "--setenv", "PATH", "/usr/bin:/bin", "--ro-bind", "/usr/bin", "/usr/bin",
                "--ro-bind", "/usr/lib", "/usr/lib", "--symlink", "usr/bin", "/bin",
                "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                "--proc", "/proc", "--remount-ro", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                "--seccomp", str(fd), "--", "/usr/bin/python3", "-I", "-c", PROBE]
        # Match the outer system service's already-applied NoNewPrivileges flag.
        result = subprocess.run(["/usr/bin/setpriv", "--no-new-privs", *args],
                                close_fds=True, pass_fds=(fd,), capture_output=True,
                                text=True, timeout=30, env={"PATH": "/usr/bin:/bin"})
        if result.returncode:
            print(json.dumps({"all_passed": False, "code": result.returncode,
                              "error": result.stderr[:1500]}))
            return 1
        report = json.loads(result.stdout)
        report["host_uid"] = os.geteuid()
        report["outer_no_new_privileges"] = True
        report["filter_bytes"] = os.fstat(fd).st_size
        report["scope"] = "bwrap+libseccomp smoke only; no installation or model call"
        print(json.dumps(report, indent=2))
        return 0 if report["all_passed"] else 1
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
