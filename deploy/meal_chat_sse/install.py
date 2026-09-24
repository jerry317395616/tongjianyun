"""Install the two isolated services and one SSE proxy location on Native Bench.

Run as root after deploying this app. Backs up each changed host configuration.
No migrations, DocTypes, or business records are touched.
"""
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

BENCH = Path('/home/zyd/frappe/native-bench')
SOURCE = Path(__file__).resolve().parent
LOCATION = '''        # meal-chat-sse: dedicated authenticated streaming endpoint
        location = /api/method/tongjianyun.meal_chat.stream_events {
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
            proxy_set_header X-Frappe-Site-Name $host;
            proxy_set_header Host $host;
            proxy_buffering off;
            proxy_cache off;
            gzip off;
            proxy_read_timeout 3600s;
            proxy_pass http://127.0.0.1:17810;
        }

'''


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root.')
    backup = BENCH / 'config' / 'backups' / ('meal-chat-sse-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True)
    config_path = BENCH / 'sites' / 'common_site_config.json'
    nginx_path = BENCH / 'config' / 'nginx.conf'
    for path in (config_path, nginx_path):
        shutil.copy2(path, backup / path.name)
    config = json.loads(config_path.read_text())
    config.setdefault('workers', {}).setdefault('meal_chat', {})['timeout'] = -1
    nginx = nginx_path.read_text()
    if '# meal-chat-sse:' not in nginx:
        anchor = '        location /socket.io {'
        if nginx.count(anchor) != 1:
            raise SystemExit('Expected proxy anchor not found; no changes applied.')
        nginx = nginx.replace(anchor, LOCATION + anchor)
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    nginx_path.write_text(nginx)
    try:
        subprocess.run(['/usr/sbin/nginx', '-t', '-c', str(nginx_path)], check=True)
    except Exception:
        shutil.copyfile(backup / config_path.name, config_path)
        shutil.copyfile(backup / nginx_path.name, nginx_path)
        raise
    services = ('frappe-native-meal-sse.service', 'frappe-native-worker-meal-chat.service')
    for name in services:
        target = Path('/etc/systemd/system') / name
        if target.exists():
            shutil.copy2(target, backup / name)
        shutil.copyfile(SOURCE / name, target)
        target.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', *services], check=True)
    subprocess.run(['systemctl', 'restart', *services], check=True)
    subprocess.run(['systemctl', 'restart', 'frappe-native-web.service'], check=True)
    subprocess.run(['systemctl', 'reload', 'frappe-native-proxy.service'], check=True)
    print('Installed meal chat SSE. Host configuration backup:', backup)


if __name__ == '__main__':
    main()
