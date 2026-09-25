"""Fixed, task-scoped native runner. Installation/authorization is intentionally separate.

The system service is the identity boundary; bwrap is the mount/PID/network
boundary. Never invoke this through the existing administrator Codex wrapper.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import errno
try:
    import fcntl
except ImportError:  # Builders/tests also run on the Windows development host.
    fcntl = None
import os
from pathlib import Path
import stat
import subprocess
import uuid

INSTALL_ROOT = Path("/opt/tongjianyun-business-codex")
INPUT_ROOT = Path("/run/tongjianyun-business-codex/tasks")
MODEL = "deepseek-v4-pro"
PROC_ISOLATION_REVISION = "bwrap-ro-v2"
MAX_PROMPT_BYTES = 131072
DENIED_SYSCALLS = (
    "ptrace", "process_vm_readv", "process_vm_writev", "pidfd_getfd",
    "process_madvise", "unshare", "setns", "mount", "umount2", "pivot_root",
    "chroot", "open_tree", "move_mount", "fsopen", "fsconfig", "fsmount",
    "mount_setattr", "keyctl", "add_key", "request_key", "bpf",
    "perf_event_open", "io_uring_setup", "io_uring_enter", "io_uring_register",
    "userfaultfd", "kexec_load", "kexec_file_load", "reboot", "swapon",
    "swapoff", "init_module", "finit_module", "delete_module", "iopl", "ioperm",
    "quotactl", "lookup_dcookie", "handle_at", "open_by_handle_at",
    "syslog", "sethostname", "setdomainname",
)
NAMESPACE_CLONE_FLAGS = (0x00020000, 0x02000000, 0x04000000, 0x08000000,
                         0x10000000, 0x20000000, 0x40000000)


def validate_task_id(value: str) -> str:
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("task_id must be a canonical UUID")
    return value


def unit_name(task_id: str) -> str:
    return "tgy-business-codex-" + validate_task_id(task_id) + ".service"


def runtime_path(task_id: str) -> Path:
    return Path("/run") / ("tgy-business-" + validate_task_id(task_id))


def build_systemd_command(task_id: str) -> list[str]:
    """Trusted broker only: fixed properties, no caller command/env/path overrides.

    The broker must authenticate task ownership, prepare root-owned input files,
    bind/revoke the proxy token, and retain cancellation/result evidence itself.
    Constructing this argv is NOT evidence that system-level isolation is installed.
    """
    task_id = validate_task_id(task_id)
    source = INPUT_ROOT / task_id
    work = runtime_path(task_id)
    properties = (
        "Type=exec", "DynamicUser=yes", "UMask=0077",
        "RuntimeDirectory=" + work.name, "RuntimeDirectoryMode=0700",
        "RuntimeDirectoryPreserve=no", "PrivateTmp=yes", "PrivateDevices=yes",
        "PrivateNetwork=yes", "ProtectSystem=strict", "ProtectHome=yes",
        # systemd 255's tunables/logs/hostname /proc child mounts become locked
        # in a user namespace. Linux mount_too_revealing then refuses bwrap's
        # new PID namespace procfs. A 10-profile no-model test proved that all
        # three must move inside bwrap; ProtectProc=invisible remains compatible.
        # Keep the bootstrap DynamicUser, no caps/NNP and private network. The
        # final sandbox has its own read-only /proc and denies all three APIs.
        "ProtectKernelTunables=no", "ProtectKernelModules=yes",
        "ProtectKernelLogs=no", "ProtectControlGroups=yes",
        "ProtectClock=yes", "ProtectHostname=no", "ProtectProc=invisible",
        "NoNewPrivileges=yes", "RestrictSUIDSGID=yes", "LockPersonality=yes",
        "CapabilityBoundingSet=", "AmbientCapabilities=", "SupplementaryGroups=", "RemoveIPC=yes",
        "KillMode=control-group", "SendSIGKILL=yes", "TimeoutStopSec=15s",
        "TasksMax=128", "MemoryMax=2G", "CPUQuota=200%", "LimitNOFILE=256",
        "LimitCORE=0", "Restart=no", "CollectMode=inactive-or-failed",
        "WorkingDirectory=" + work.as_posix(),
        "LoadCredential=task-token:" + (source / "token").as_posix(),
        "LoadCredential=prompt:" + (source / "prompt.txt").as_posix(),
        "BindReadOnlyPaths=" + (source / "proxy.sock").as_posix() + ":" + (work / "proxy.sock").as_posix(),
    )
    argv = ["/usr/bin/systemd-run", "--quiet", "--pipe", "--wait", "--collect",
            "--unit=" + unit_name(task_id)]
    argv.extend("--property=" + p for p in properties)
    argv.extend(["/usr/bin/python3", "-I", (INSTALL_ROOT / "native_sandbox.py").as_posix(),
                 "--task-id", task_id])
    return argv


def require_root_owned_file(path: Path) -> None:
    """Reject symlinks and writable runtime/ancestor paths, not only the leaf."""
    for current in (path, *path.parents):
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError("runtime must be root-owned and immutable")
        if current == path and not stat.S_ISREG(info.st_mode):
            raise PermissionError("runtime file is not a regular file")


class _ArgCmp(ctypes.Structure):
    _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_int),
                ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]


def export_seccomp_fd() -> int:
    """Compile real native-architecture libseccomp BPF to a sealed anonymous fd."""
    if fcntl is None or not hasattr(os, "memfd_create"):
        raise RuntimeError("Linux memfd/seccomp are required; no unfiltered fallback")
    library = ctypes.util.find_library("seccomp")
    if not library:
        raise RuntimeError("libseccomp is required; no unfiltered fallback")
    lib = ctypes.CDLL(library, use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                          ctypes.c_int, ctypes.c_uint, ctypes.POINTER(_ArgCmp)]
    lib.seccomp_rule_add_array.restype = ctypes.c_int
    lib.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.seccomp_export_bpf.restype = ctypes.c_int
    context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW; deny rules below.
    if not context:
        raise RuntimeError("seccomp initialization failed")
    fd = -1
    try:
        def rule(name: str, error: int, comparisons=()):
            number = lib.seccomp_syscall_resolve_name(name.encode("ascii"))
            if number == -1:  # This syscall does not exist on this architecture.
                return
            items = (_ArgCmp * len(comparisons))(*comparisons)
            result = lib.seccomp_rule_add_array(context, 0x00050000 | error,
                                                number, len(items), items)
            if result < 0:
                raise RuntimeError("seccomp rule failed: " + name)
        for syscall in DENIED_SYSCALLS:
            rule(syscall, errno.EPERM)
        # Rust/glibc can retry ordinary clone; blanket EPERM breaks thread startup.
        rule("clone3", errno.ENOSYS)
        for flag in NAMESPACE_CLONE_FLAGS:
            rule("clone", errno.EPERM, (_ArgCmp(0, 7, flag, flag),))
        # Only filesystem Unix sockets and task-private IP loopback are needed.
        # libseccomp permits one comparison per argument within a rule. Split the
        # complement of {AF_UNIX=1, AF_INET=2, AF_INET6=10} into disjoint rules.
        for family in (0, 3, 4, 5, 6, 7, 8, 9):
            rule("socket", errno.EPERM, (_ArgCmp(0, 4, family, 0),))
        rule("socket", errno.EPERM, (_ArgCmp(0, 6, 10, 0),))
        fd = os.memfd_create("tgy-business-seccomp", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        if lib.seccomp_export_bpf(context, fd) != 0 or os.fstat(fd).st_size < 8:
            raise RuntimeError("seccomp export failed")
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK |
                    fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
        return fd
    except BaseException:
        if fd >= 0:
            os.close(fd)
        raise
    finally:
        lib.seccomp_release(context)


def build_bwrap_command(task_id: str, credential_dir: Path, filter_fd: int) -> list[str]:
    """There is no caller-controlled executable, environment or mount override."""
    task_id = validate_task_id(task_id)
    if not isinstance(filter_fd, int) or isinstance(filter_fd, bool) or filter_fd < 3:
        raise ValueError("invalid seccomp descriptor")
    work = runtime_path(task_id)
    expected_credentials = Path("/run/credentials") / unit_name(task_id)
    if credential_dir != expected_credentials:
        raise ValueError("unexpected system credential directory")
    argv = ["/usr/bin/bwrap", "--unshare-all", "--unshare-user", "--disable-userns",
            "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
            "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8",
            "--setenv", "HOME", "/work/home", "--setenv", "CODEX_HOME", "/work/codex-home",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--ro-bind", "/usr/bin", "/usr/bin", "--ro-bind", "/usr/lib", "/usr/lib",
            "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--proc", "/proc", "--remount-ro", "/proc",
            "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/work",
            "--dir", "/work/home", "--dir", "/work/codex-home", "--dir", "/bridge",
            "--ro-bind", INSTALL_ROOT.as_posix(), "/opt/business-codex",
            "--ro-bind", (work / "proxy.sock").as_posix(), "/bridge/proxy.sock",
            "--ro-bind", (credential_dir / "task-token").as_posix(), "/bridge/task-token",
            "--ro-bind", (credential_dir / "prompt").as_posix(), "/bridge/prompt.txt",
            "--chdir", "/work", "--seccomp", str(filter_fd), "--"]
    return argv + ["/usr/bin/python3", "-I", "/opt/business-codex/sandbox_entry.py"]


def run_task(task_id: str) -> int:
    task_id = validate_task_id(task_id)
    if not 61184 <= os.geteuid() <= 65519 or any(group != os.getegid() for group in os.getgroups()):
        raise PermissionError("a dedicated DynamicUser without supplementary groups is required")
    if Path(os.environ.get("RUNTIME_DIRECTORY", "")) != runtime_path(task_id):
        raise PermissionError("unexpected task runtime directory")
    for name in ("codex", "native_sandbox.py", "sandbox_entry.py", "business_tool.py"):
        require_root_owned_file(INSTALL_ROOT / name)
    work_info = runtime_path(task_id).stat()
    if work_info.st_uid != os.geteuid() or stat.S_IMODE(work_info.st_mode) != 0o700:
        raise PermissionError("private task runtime is required")
    if not stat.S_ISSOCK((runtime_path(task_id) / "proxy.sock").stat().st_mode):
        raise PermissionError("task proxy socket missing")
    credentials = Path(os.environ.get("CREDENTIALS_DIRECTORY", ""))
    fd = export_seccomp_fd()
    try:
        argv = build_bwrap_command(task_id, credentials, fd)
        return subprocess.run(argv, pass_fds=(fd,), close_fds=True,
                              env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, check=False).returncode
    finally:
        os.close(fd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    raise SystemExit(run_task(args.task_id))
