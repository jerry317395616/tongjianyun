"""Install one shared live runtime. Private config stays outside Git; retain rollback."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

BASE=Path('/home/zyd/frappe')
DEPLOY=BASE/'native-bench/apps/tongjianyun/deploy/shared_harness_pilot'
REPO=BASE/'deepseek-harness'
UNITS=Path('/home/zyd/.config/systemd/user')

def run(*args): subprocess.run(args,check=True,stdout=subprocess.DEVNULL)
def write(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text); path.chmod(0o600)

def main():
    os.umask(0o077)
    # Unix identity socket rejects any group-writable parent; all services use zyd.
    BASE.chmod(BASE.stat().st_mode & ~0o020)
    config=BASE/'config/harness'; state=BASE/'state/harness'
    backup=BASE/'backups/harness'/time.strftime('%Y%m%d-%H%M%S')
    backup.mkdir(parents=True)
    for p in [config,state,BASE/'logs/harness']:
        p.mkdir(parents=True,exist_ok=True)
    targets=[]
    def override(service,content):
        path=UNITS/(service+'.service.d/90-shared-live.conf')
        if path.exists(): raise RuntimeError('live override already exists')
        write(path,content); targets.append(path)
    # Copy opaque credential files without inspecting their contents.
    for source,name in [('/home/zyd/deepseek-harness-config/qwen-credentials.yaml','model-credentials.yaml'),
                        ('/home/zyd/deepseek-harness-config/harness_sso_shared_secret','sso-secret')]:
        destination=config/name
        if destination.exists(): raise RuntimeError('credential destination exists')
        run('/bin/cp','--preserve=mode',source,str(destination))
        destination.chmod(0o600)
    identities=[]
    for account,service in [('admin','ione-harness-employee-admin'),('teacher-a','ione-harness-teacher-a'),('teacher-b','ione-harness-teacher-b')]:
        document=json.loads((Path('/home/zyd/.config/ione-harness-employees')/account/'refresh.json').read_text())
        directory=state/'identities'/account
        directory.mkdir(parents=True,exist_ok=True)
        document['assertion_file']=str(directory/'actor.assertion')
        target=config/(account+'.json');write(target,json.dumps(document,indent=2)); identities.append(str(target))
        override(service,'[Service]\nExecStart=\nExecStart='+str(BASE/'native-bench/env/bin/python')+' -B '+str(REPO/'packages/extensions/tool-native-bench-frappe/python/native_actor_refresh.py')+' --config '+str(target)+'\n')
    authority=json.loads(Path('/home/zyd/.config/ione-harness-shared/authority.json').read_text())
    authority.update(socket_path=str(state/'authority.sock'),secret_file=str(config/'sso-secret'),identity_configs=identities)
    write(config/'authority.json',json.dumps(authority,indent=2))
    override('ione-harness-shared-identity','[Service]\nExecStart=\nExecStart='+str(BASE/'native-bench/env/bin/python')+' -B '+str(REPO/'packages/extensions/tool-native-bench-frappe/python/shared_identity.py')+' --config '+str(config/'authority.json')+'\n')
    home=state/'runtime'; profile=home/'profiles/web'; modules=profile/'node_modules/@deepseek-ai'
    modules.mkdir(parents=True,exist_ok=True)
    deps={}
    for name in ['tool-native-bench-source','tool-native-bench-frappe']:
        package=REPO/'packages/extensions'/name
        deps['@deepseek-ai/dsh-'+name]='link:'+str(package)
        (modules/('dsh-'+name)).symlink_to(package,target_is_directory=True)
    write(profile/'package.json',json.dumps({'name':'shared-live','private':True,'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app'],'patchReload':'startup'}},'dependencies':deps}))
    runtime=(DEPLOY/'runtime.yml').read_text().replace('/home/zyd/deepseek-harness-config/qwen-credentials.yaml',str(config/'model-credentials.yaml'))
    write(config/'runtime.yml',runtime)
    unit=(DEPLOY/'runtime.conf').read_text().replace('/home/zyd/frappe/harness-shared-state',str(home)).replace('/home/zyd/.config/ione-harness-shared/authority.sock',str(state/'authority.sock')).replace('/home/zyd/.config/ione-harness-shared/owners',str(state/'owners')).replace(str(DEPLOY/'runtime.yml'),str(config/'runtime.yml'))
    override('ione-harness',unit)
    write(config/'nginx.conf',(DEPLOY/'shared-nginx.conf').read_text())
    run('/usr/sbin/nginx','-t','-c',str(config/'nginx.conf'),'-p',str(config)+'/')
    override('deepseek-harness-nginx',(DEPLOY/'live-nginx-unit.conf').read_text())
    # Snapshot only our override list; original service files/config are untouched.
    write(backup/'overrides.json',json.dumps([str(p) for p in targets],indent=2))
    for p in targets: shutil.copy2(p,config/(p.parent.name+'.conf'))
    run('systemctl','--user','daemon-reload')
    try:
        run('systemctl','--user','stop','deepseek-harness-nginx.service')
        for service in ['ione-harness-employee-admin','ione-harness-teacher-a','ione-harness-teacher-b','ione-harness-shared-identity','ione-harness']:
            run('systemctl','--user','restart',service+'.service')
        time.sleep(3)
        run('systemctl','--user','restart','deepseek-harness-nginx.service')
        for service in ['ione-harness','ione-harness-shared-identity','deepseek-harness-nginx']:
            run('systemctl','--user','is-active','--quiet',service+'.service')
    except Exception:
        for p in targets: p.unlink()
        run('systemctl','--user','daemon-reload')
        for service in ['ione-harness-employee-admin','ione-harness-teacher-a','ione-harness-teacher-b','ione-harness-shared-identity','ione-harness','deepseek-harness-nginx']:
            run('systemctl','--user','restart',service+'.service')
        raise
    print(json.dumps({'activated':True,'rollback_manifest':str(backup/'overrides.json')}))

if __name__=='__main__': main()
