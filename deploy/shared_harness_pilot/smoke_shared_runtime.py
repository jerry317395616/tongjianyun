"""Bounded candidate startup probe; no credential contents or runtime logs emitted."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

REPO = Path('/home/zyd/frappe/deepseek-harness')
DEPLOY = Path('/home/zyd/frappe/native-bench/apps/tongjianyun/deploy/shared_harness_pilot')

def main():
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='shared-runtime-probe-') as temporary:
        home = Path(temporary)
        profile = home/'profiles/web'
        modules = profile/'node_modules/@deepseek-ai'
        modules.mkdir(parents=True)
        dependencies = {}
        for name in ['tool-native-bench-source', 'tool-native-bench-frappe']:
            package = REPO/'packages/extensions'/name
            dependencies['@deepseek-ai/dsh-'+name] = 'link:'+str(package)
            (modules/('dsh-'+name)).symlink_to(package, target_is_directory=True)
        (profile/'package.json').write_text(json.dumps({'name':'shared-runtime-probe', 'private':True,
            'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app'],
                              'patchReload':'startup'}}, 'dependencies':dependencies}))
        examples = REPO/'apps/cli/config/examples'
        env = {'PATH':'/home/zyd/.local/bin:/usr/local/bin:/usr/bin:/bin', 'HOME':'/home/zyd',
               'DSH_HOME':str(home), 'DSH_AGENTS_HOME':str(home/'agents'),
               'DSH_EMPLOYEE_PRESET_ROOT':str(examples/'employee-readonly/presets'),
               'DSH_SHARED_PRESET_ROOT':str(examples/'employee-shared/presets'),
               'DSH_SHARED_PUBLIC_ORIGIN':'https://harness.myyr.top',
               'DSH_SHARED_IDENTITY_SOCKET':'/home/zyd/.config/ione-harness-shared/authority.sock',
               'DSH_SHARED_OWNERS_DIRECTORY':str(home/'owners'), 'DSH_TELEMETRY_DISABLED':'1'}
        command = ['/home/zyd/.local/bin/pnpm','dsh','web']
        for overlay in [examples/'employee-readonly/cordis.yml',examples/'employee-shared/cordis.yml',DEPLOY/'runtime.yml']:
            command += ['--patch',str(overlay)]
        command += ['--no-open','--host','127.0.0.1','--port','13093']
        # Logs may include a Host launch token: retain only transiently, never print them.
        with tempfile.TemporaryFile() as output:
            child = subprocess.Popen(command,cwd=REPO,env=env,stdout=output,stderr=output,start_new_session=True)
            result = {'passed':False,'stage':'startup','production_changed':False}
            try:
                deadline = time.monotonic()+45
                while time.monotonic()<deadline and child.poll() is None:
                    try:
                        req = urllib.request.Request('http://127.0.0.1:13093/employee/status',headers={'Host':'harness.myyr.top','Origin':'https://harness.myyr.top'})
                        try:
                            with urllib.request.urlopen(req,timeout=1) as response:
                                status = response.status
                        except urllib.error.HTTPError as error:
                            status = error.code
                        if status == 401:
                            result.update(passed=True,stage='employee_api_mounted',unauthenticated_status=status)
                            break
                    except (OSError,urllib.error.URLError): pass
                    time.sleep(.5)
                if result['passed']:
                    check = subprocess.run([sys.executable,'-B',str(DEPLOY/'accept_shared_http.py')],
                                           capture_output=True,timeout=55)
                    # The acceptance helper emits fixed stage labels only.
                    try: result['http_acceptance'] = json.loads(check.stdout)
                    except (ValueError,UnicodeError): result['http_acceptance'] = {'passed':False,'stage':'helper_failed'}
                    result['passed'] = check.returncode == 0
                if not result['passed']:
                    output.seek(0)
                    logs = output.read().decode(errors='replace')
                    # Only fixed diagnostic labels; no error lines or payloads.
                    result['diagnostics'] = [label for label,pattern in {
                        'missing_plugin':'Cannot find package', 'missing_module':'Cannot find module',
                        'activation_failure':'did not activate', 'invalid_configuration':'ZodError',
                        'port_conflict':'EADDRINUSE', 'credential_permissions':'readable beyond its owner',
                    }.items() if pattern in logs]
                    result['exit_code'] = child.poll()
            finally:
                if child.poll() is None:
                    os.killpg(child.pid,signal.SIGTERM)
                    try: child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid,signal.SIGKILL); child.wait()
            print(json.dumps(result))
            return 0 if result['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
