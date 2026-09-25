"""Local CLI acceptance probe, never an HTTP method or generic mutation tool.

Run only through the authorized native Codex as root from /home/zyd/frappe.
Writes only generated temporary code and one uniquely marked unassigned test ToDo.
The ToDo is committed, edited, read back, then deleted through the original ORM.
Frappe may retain normal deletion/version audit metadata for the test record.
"""
import json
import os
from pathlib import Path
import runpy
import tempfile
import uuid

import frappe

ROOT = Path('/home/zyd/frappe')
SITE = 'child.myyr.top'
REPORT = ROOT / '.codex-deepseek' / 'admin-access-verification.json'


def code_probe(parent):
    with tempfile.TemporaryDirectory(prefix='.codex-admin-check-', dir=parent) as directory:
        target = Path(directory) / 'probe.py'
        target.write_text('RESULT = "created"\n', encoding='utf-8')
        assert runpy.run_path(str(target))['RESULT'] == 'created'
        target.write_text('RESULT = "updated"\n', encoding='utf-8')
        assert runpy.run_path(str(target))['RESULT'] == 'updated'
    assert not Path(directory).exists()
    return {'created': True, 'edited_and_executed': True, 'cleaned': True}


def main():
    if os.geteuid() != 0 or Path.cwd().resolve() != ROOT:
        raise RuntimeError('Run from /home/zyd/frappe using the native Codex admin executor.')
    result = {'uid': os.getuid(), 'euid': os.geteuid(), 'cwd': str(Path.cwd()), 'site': SITE}
    result['codex_home'] = os.environ.get('CODEX_HOME')
    assert result['codex_home'] == str(ROOT / '.codex-deepseek' / 'admin-home')
    result['same_mount_namespace_as_host'] = os.readlink('/proc/self/ns/mnt') == os.readlink('/proc/1/ns/mnt')
    result['apparmor_profile'] = Path('/proc/self/attr/current').read_text().strip()
    result['effective_capabilities'] = next(line.split(':', 1)[1].strip() for line in
                                          Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:'))
    result['project_code'] = code_probe(ROOT)
    result['root_only_filesystem'] = code_probe('/root')
    # Directories only; never dump credentials or business records in this report.
    paths = [p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith('.')]
    paths += [p for p in (ROOT / 'native-bench' / 'apps').iterdir() if p.is_dir()]
    result['project_directory_count'] = len(paths)
    result['unwritable_project_directories'] = [str(p) for p in paths if not os.access(p, os.R_OK | os.W_OK | os.X_OK)]
    assert not result['unwritable_project_directories']
    sites = ROOT / 'native-bench' / 'sites'
    os.chdir(sites)
    frappe.init(site=SITE, sites_path=str(sites))
    frappe.connect()
    record_name = None
    marker = 'Codex admin access verification ' + str(uuid.uuid4())
    try:
        frappe.set_user('Administrator')
        result['business_actor'] = frappe.session.user
        result['installed_apps'] = frappe.get_installed_apps()
        record = frappe.get_doc({'doctype': 'ToDo', 'description': marker, 'status': 'Open', 'priority': 'Low'})
        record.insert()
        record_name = record.name
        frappe.db.commit()
        fresh = frappe.get_doc('ToDo', record_name)
        fresh.check_permission('read')
        assert fresh.description == marker
        result['data_insert_committed'] = True
        fresh.description = marker + ' updated'
        fresh.save()
        frappe.db.commit()
        assert frappe.get_doc('ToDo', record_name).description == marker + ' updated'
        result['data_update_committed_and_reread'] = True
    finally:
        frappe.db.rollback()
        try:
            if record_name and frappe.db.exists('ToDo', record_name):
                check = frappe.get_doc('ToDo', record_name)
                if check.description not in {marker, marker + ' updated'} or check.owner != 'Administrator':
                    raise RuntimeError('Test record changed unexpectedly; no cleanup attempted.')
                frappe.delete_doc('ToDo', record_name)
                frappe.db.commit()
            result['test_todo_removed'] = not record_name or not frappe.db.exists('ToDo', record_name)
        finally:
            frappe.db.rollback()
            frappe.destroy()
    assert result['test_todo_removed']
    result['passed'] = True
    if REPORT.is_symlink():
        raise RuntimeError('Refusing to overwrite a symlink report.')
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    owner = ROOT.stat()
    os.chown(REPORT, owner.st_uid, owner.st_gid)
    REPORT.chmod(0o600)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
