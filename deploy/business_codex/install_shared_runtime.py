"""Administrator-only install of one shared, hash-pinned native Codex runtime.

Does not grant sudo, change AppArmor, install a model/package, start a worker or
open teacher chat. The caller must separately verify dynamic task execution.
Input files are exact reviewed artifacts, not arbitrary package URLs/commands.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import uuid


SOURCE = Path('/home/zyd/frappe/remote-workspace/unified-business-20260925/deploy/business_codex')
BINARY = Path('/home/zyd/frappe/.codex-deepseek/runtime/node_modules/@openai/codex-linux-arm64/vendor/aarch64-unknown-linux-musl/bin/codex')
BINARY_SHA256 = '876fe6bb5f7af7d1e4eda629be0d8ba042f6f24a7bb07475f6a995849f50c068'
TARGET = Path('/opt/tongjianyun-business-codex')
INPUT = Path('/run/tongjianyun-business-codex/tasks')
FILES = ('native_sandbox.py', 'sandbox_entry.py', 'business_tool.py')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def real_path(path):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError('Source must be a real absolute path')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink source is forbidden')
    return path


def root_directory(path, mode):
    if path.exists():
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or path.is_symlink() or info.st_uid or info.st_mode & 0o022:
            raise ValueError('Unsafe existing runtime directory')
    else:
        path.mkdir(mode=mode)
    path.chmod(mode)


def install(expected_manifest):
    if os.geteuid() != 0:
        raise PermissionError('A system administrator must install the runtime')
    os.umask(0o077)
    source = real_path(SOURCE)
    manifest_path = real_path(source / 'runtime-manifest.json')
    if not manifest_path.is_file() or manifest_path.stat().st_size > 4096:
        raise ValueError('Invalid runtime manifest file')
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest:
        raise ValueError('Reviewed manifest changed')
    manifest = json.loads(manifest_bytes)
    if set(manifest) != set(FILES) or any(not isinstance(v, str) or len(v) != 64 for v in manifest.values()):
        raise ValueError('Invalid runtime manifest')
    for name, expected in manifest.items():
        if digest(real_path(source / name)) != expected:
            raise ValueError('Reviewed runtime changed: ' + name)
    if digest(real_path(BINARY)) != BINARY_SHA256:
        raise ValueError('Installed Codex version changed; review the new binary first')
    units = subprocess.run(['/usr/bin/systemctl', 'list-units', '--all', '--no-legend', '--plain',
                            'tgy-business-codex-*.service'], text=True, capture_output=True, check=True)
    if units.stdout.strip():
        raise RuntimeError('Business execution units still exist; do not replace a running runtime')
    real_path(TARGET.parent)
    if TARGET.parent.stat().st_uid or TARGET.parent.stat().st_mode & 0o022:
        raise ValueError('Runtime parent is not administrator controlled')
    root_directory(TARGET, 0o755)
    version = str(uuid.uuid4())
    archive = TARGET / ('previous-' + version)
    staging = TARGET / ('.staging-' + version)
    staging.mkdir(mode=0o700)
    installed = {}
    replacements = []
    for name, path, expected in [('codex', BINARY, BINARY_SHA256),
                                  *((name, source / name, manifest[name]) for name in FILES)]:
        target = TARGET / name
        if target.exists():
            info = target.lstat()
            if target.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_mode & 0o022:
                raise ValueError('Unsafe existing runtime file')
            if digest(target) == expected:
                installed[name] = expected
                continue
        temp = staging / name
        with path.open('rb') as src, temp.open('xb') as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        if digest(temp) != expected:
            raise ValueError('Source changed while copying; staged file retained for investigation')
        temp.chmod(0o755 if name == 'codex' else 0o644)
        replacements.append((name, target, temp))
        installed[name] = expected
    # No production starter is installed by this command. Before introducing a
    # concurrent starter it must share an installation lock/version protocol.
    # Recheck after staging so this manual QA install never touches live units.
    units = subprocess.run(['/usr/bin/systemctl', 'list-units', '--all', '--no-legend', '--plain',
                            'tgy-business-codex-*.service'], text=True, capture_output=True, check=True)
    if units.stdout.strip():
        raise RuntimeError('Business unit appeared during staging; files were not replaced')
    for name, target, temp in replacements:
        if target.exists():
            if not archive.exists():
                archive.mkdir(mode=0o700)
            os.link(target, archive / name)
    changed = []
    try:
        for name, target, temp in replacements:
            temp.replace(target)
            changed.append((name, target))
    except BaseException:
        # Preserve failed candidates and prior files rather than deleting them.
        for name, target in reversed(changed):
            target.replace(staging / ('failed-' + name))
            if (archive / name).exists():
                os.link(archive / name, target)
        raise
    root_directory(INPUT.parent, 0o700)
    root_directory(INPUT, 0o700)
    receipt = {'version': 1, 'codex': '0.156.1', 'same_existing_binary_sha256': BINARY_SHA256,
               'files': installed, 'production_chat_enabled': False, 'sudo_rules_changed': False,
               'apparmor_changed': False, 'previous_files': str(archive) if archive.exists() else None}
    receipt_path = TARGET / ('install-' + version + '.json')
    with receipt_path.open('x') as stream:
        json.dump(receipt, stream, sort_keys=True)
        stream.write('\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    install(args.manifest_sha256)
