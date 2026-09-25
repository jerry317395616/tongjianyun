"""Reviewed, QA-only root launcher installation. Default: read-only preflight.

Never installs/replaces the Codex binary, starts a model, provisions a user,
changes production configuration, enables a service at boot, or edits AppArmor.
Only --install creates the exact daemon/config/unit below. Start is a separate
explicit administrator operation after --check-config. Existing different files
are refused, not overwritten. The source SHA must be provided by the reviewer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid
from urllib.parse import urlparse

SOURCE = Path('/home/zyd/frappe/remote-workspace/unified-business-20260925/deploy/business_codex/native_launcher.py')
QA_ROOT = Path('/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925')
SITE = 'unified-business-acceptance.localhost'
SITES = QA_ROOT / 'sites'
INSTALL = Path('/opt/tongjianyun-business-codex')
CONFIG = Path('/etc/tongjianyun-business-codex/launcher.json')
RUN = Path('/run/tongjianyun-business-codex')
STATE = Path('/var/lib/tongjianyun-business-codex/launcher')
SERVICE = 'tgy-business-codex-qa-launcher.service'
UNIT = Path('/etc/systemd/system') / SERVICE
PHASE = 'not_started'
HASHES = {
    'codex': '876fe6bb5f7af7d1e4eda629be0d8ba042f6f24a7bb07475f6a995849f50c068',
    'native_sandbox.py': 'e5763a25c2b9af6dd436ceae0a5297952be7de4e3ba993702f6872e1fe82ecd2',
    'sandbox_entry.py': 'e82d6407604d95041e3334621a8a15e110a8c5868e8f76b44cab96809efb846e',
    'business_tool.py': '3937600d96416f4923928f04cbf32ad6828d7a5fde475b0058ed134e96ed0382',
}
UNIT_BYTES = b'''[Unit]
Description=Tongjianyun isolated QA business Codex launcher (QA site only)
After=local-fs.target

[Service]
Type=simple
User=root
Group=root
UMask=0077
WorkingDirectory=/opt/tongjianyun-business-codex
ExecStartPre=/usr/bin/python3 -I -B /opt/tongjianyun-business-codex/native_launcher.py --check-config
ExecStart=/usr/bin/python3 -I -B /opt/tongjianyun-business-codex/native_launcher.py --serve
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PATH=/usr/bin:/bin
NoNewPrivileges=yes
LimitCORE=0
Restart=no
TimeoutStopSec=60
KillMode=control-group
StandardOutput=journal
StandardError=journal
'''


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()


def real(path):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise PermissionError('Exact non-symlink path required')
    for part in (path, *path.parents):
        if stat.S_ISLNK(part.lstat().st_mode):
            raise PermissionError('Symlink ancestor refused')
    return path


def root_path(path, *, directory=False):
    real(path)
    for part in (path, *path.parents):
        info = part.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('Administrator-controlled path required')
    info = path.lstat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise PermissionError('Unexpected root path type')
    return path


def read_regular(path, maximum=1024 * 1024):
    real(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise PermissionError('Invalid bounded source/config file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise PermissionError('Source grew during read')
        return data
    finally:
        os.close(fd)


def qa_identity():
    """Check the exact existing QA config without connecting or printing secrets."""
    marker = json.loads(read_regular(QA_ROOT / 'isolation-marker.json'))
    if marker.get('owner') != QA_ROOT.name:
        raise PermissionError('Wrong QA owner')
    conf = {**json.loads(read_regular(SITES / 'common_site_config.json')),
            **json.loads(read_regular(SITES / SITE / 'site_config.json'))}
    validate_qa_config(conf)
    info = real(SITES / SITE).stat()
    import pwd
    user = pwd.getpwnam('zyd')
    if (info.st_uid, info.st_gid) != (user.pw_uid, user.pw_gid) or not 1 <= user.pw_uid < 61184:
        raise PermissionError('Unexpected QA site OS identity')
    return user.pw_uid, user.pw_gid


def validate_qa_config(conf):
    expected = {'unified_business_acceptance': 1, 'db_host': '127.0.0.1',
                'db_name': 'tgy_blueprint_qa', 'pause_scheduler': 1,
                'disable_scheduler': 1, 'mute_emails': 1, 'disable_email_queue': 1}
    if (any(conf.get(k) != v for k, v in expected.items())
            or int(conf.get('db_port', 0)) != 23316 or conf.get('developer_mode')
            or conf.get('db_socket') or conf.get('db_user', conf['db_name']) != conf['db_name']):
        raise PermissionError('Not the isolated QA configuration')
    for key, database in (('redis_cache','0'),('redis_queue','1'),('redis_socketio','2')):
        url = urlparse(conf.get(key) or '')
        if (url.scheme != 'redis' or url.hostname != '127.0.0.1' or url.port != 23379
                or url.path != '/' + database or url.query or url.fragment):
            raise PermissionError('Not the isolated QA Redis endpoint')
    # Authentication embedded in the existing QA URL is allowed but never
    # returned, copied into launcher config, logged or modified by this script.


def refuse_live_units():
    result = subprocess.run(['/usr/bin/systemctl', 'list-units', '--all', '--no-legend', '--plain',
                             'tgy-business-codex-*.service'], check=True, capture_output=True, text=True,
                            timeout=10)
    # Includes the launcher itself: manual updates require it stopped first.
    # A stopped installed unit may still be listed; allow only its inactive/dead row.
    for line in result.stdout.splitlines():
        words = line.split()
        if len(words) < 4 or words[:4] != [SERVICE, 'loaded', 'inactive', 'dead']:
            raise RuntimeError('Existing execution/launcher unit prevents installation')
    if (RUN / 'control.sock').exists():
        raise RuntimeError('Control socket exists; inspect the old launcher first')


def exact_existing(path, data, mode):
    if not path.exists() and not path.is_symlink():
        return False
    root_path(path)
    info = path.stat()
    if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != mode or read_regular(path) != data:
        raise PermissionError('Existing install file differs; manual review required')
    return True


def root_directory(path, mode, *, permit_mode_transition=False):
    root_path(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        root_path(path, directory=True)
        old_mode = stat.S_IMODE(path.stat().st_mode)
        if old_mode != mode:
            if not permit_mode_transition or path != RUN or old_mode != 0o700 or mode != 0o711:
                raise PermissionError('Unexpected existing directory mode')
            path.chmod(mode)  # Only allow traversal to the authenticated 0660 socket.
    else:
        path.mkdir(mode=mode)
    if stat.S_IMODE(path.stat().st_mode) != mode:
        # umask 077 can remove the two intended traverse bits on first creation.
        path.chmod(mode)


def preflight_directories():
    """Read existing ancestors/modes; do not make paths or a lock on dry run."""
    planned = ((CONFIG.parent, 0o700), (RUN, 0o711), (RUN / 'tasks', 0o700),
               (STATE.parent, 0o700), (STATE, 0o700))
    missing = []
    for path, mode in planned:
        if path.exists() or path.is_symlink():
            root_path(path, directory=True)
            current = stat.S_IMODE(path.stat().st_mode)
            if current != mode and not (path == RUN and current == 0o700 and mode == 0o711):
                raise PermissionError('Existing deployment directory needs manual review')
        else:
            parent = path.parent
            while not parent.exists() and not parent.is_symlink():
                parent = parent.parent
            root_path(parent, directory=True)
            missing.append(str(path))
    root_path(UNIT.parent, directory=True)
    lock_path = STATE / 'daemon.lock'
    if lock_path.exists() or lock_path.is_symlink():
        root_path(lock_path)
        import fcntl
        fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if info.st_nlink != 1 or info.st_mode & 0o077:
                raise PermissionError('Unsafe existing daemon lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
    return missing


def create_exact(path, data, mode):
    root_path(path.parent, directory=True)
    if exact_existing(path, data, mode):
        return False
    temporary = path.parent / ('.qa-launcher-stage-' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(data)
            stream.flush()
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)
    # Atomic no-overwrite publication. An interrupted staging write leaves no
    # final half-file; retain its private staging file for administrator review.
    os.link(temporary, path, follow_symlinks=False)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
        temporary.unlink()  # Only the exact staging file just created here.
        os.fsync(directory)
    finally:
        os.close(directory)
    return True


def install(expected_sha, *, apply=False):
    global PHASE
    PHASE = 'administrator_identity'
    if os.name != 'posix' or os.geteuid() != 0:
        raise PermissionError('Explicit Linux administrator execution required')
    if not isinstance(expected_sha, str) or not re.fullmatch('[a-f0-9]{64}', expected_sha):
        raise ValueError('Reviewed launcher SHA-256 required')
    os.umask(0o077)
    PHASE = 'candidate_source'
    source = read_regular(SOURCE)
    if hashlib.sha256(source).hexdigest() != expected_sha:
        raise PermissionError('Reviewed launcher source changed')
    compile(source, str(SOURCE), 'exec')  # Syntax only. Do not import writable code as root.
    PHASE = 'installed_shared_runtime'
    root_path(INSTALL, directory=True)
    for name, expected in HASHES.items():
        with root_path(INSTALL / name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise PermissionError('Existing shared runtime differs from the reviewed version')
    PHASE = 'isolated_qa_identity'
    uid, gid = qa_identity()
    config = json_bytes({'version': 1, 'control_gid': gid,
        'sites': {SITE: {'sites_path': str(SITES), 'uid': uid, 'gid': gid}}, 'runtime_sha256': HASHES})
    artifacts = ((INSTALL / 'native_launcher.py', source, 0o644), (CONFIG, config, 0o600), (UNIT, UNIT_BYTES, 0o644))
    PHASE = 'existing_install_files'
    for path, data, mode in artifacts:
        exact_existing(path, data, mode)
    PHASE = 'existing_execution_units'
    refuse_live_units()
    PHASE = 'deployment_directories'
    missing = preflight_directories()
    result = {'site': SITE, 'launcher_sha256': expected_sha, 'shared_runtime_sha256': HASHES,
              'production_chat_enabled': False, 'model_started': False,
              'service_started': False, 'service_enabled_at_boot': False, 'installed': False,
              'directories_to_create': missing}
    if not apply:
        return {**result, 'preflight_passed': True}
    # Serialize with an existing daemon without touching its task records.
    PHASE = 'install_directories_and_lock'
    root_directory(STATE.parent, 0o700)
    root_directory(STATE, 0o700)
    import fcntl
    lock = os.open(STATE / 'daemon.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_nlink != 1 or info.st_mode & 0o077:
            raise PermissionError('Unsafe daemon lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        refuse_live_units()
        root_directory(CONFIG.parent, 0o700)
        root_directory(RUN, 0o711, permit_mode_transition=True)
        root_directory(RUN / 'tasks', 0o700)
        PHASE = 'publish_reviewed_files'
        created = [str(path) for path, data, mode in artifacts if create_exact(path, data, mode)]
        PHASE = 'verify_installed_configuration'
        subprocess.run(['/usr/bin/python3', '-I', '-B', str(INSTALL / 'native_launcher.py'), '--check-config'],
                       check=True, capture_output=True, timeout=30)
        subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], check=True, capture_output=True, timeout=20)
        return {**result, 'installed': True, 'created': created, 'configuration_verified': True}
    finally:
        os.close(lock)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher-sha256', required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.launcher_sha256, apply=args.install), sort_keys=True))
    except Exception as error:
        print(json.dumps({'ok': False, 'error_type': type(error).__name__,
                          'phase': PHASE,
                          'detail': 'QA launcher setup stopped; no automatic overwrite or retry'}))
        raise SystemExit(1) from None
