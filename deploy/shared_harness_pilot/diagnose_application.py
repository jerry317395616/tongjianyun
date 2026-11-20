"""Read sanitized event/exception facts; never print record contents or credentials."""
import json
import os
from pathlib import Path
import traceback
from compression import zstd
import frappe

root = Path('/home/zyd/frappe/state/harness/runtime/sessions')
for file in sorted(root.rglob('*.jsonl.zstd'), key=lambda path: path.stat().st_mtime, reverse=True)[:3]:
    with zstd.open(file, 'rt') as stream:
        events = [json.loads(line) for line in stream.read().splitlines()]
    print(json.dumps({'preset': events[0].get('agentPreset'), 'events': [row['type'] for row in events][-35:],
        'reasons': [row['data'].get('reason', {}).get('kind') for row in events if row['type'] == 'turn/end'],
        'tools': [[tool['name'] for tool in row['data']['header'].get('tools', [])]
            for row in events if row['type'] == 'request/header']}))
    if events[0].get('agentPreset') == 'tongjianyun-business':
        for row in events:
            if row['type'] == 'tool/call':
                args = row['data']['arguments']
                args = json.loads(args) if isinstance(args, str) else args
                print(json.dumps({'tool': row['data']['name'], 'operation': args.get('operation'),
                    'arguments_type': type(args.get('arguments')).__name__}))
            if row['type'] == 'tool/result':
                for result in row['data']['message'].get('content', []):
                    if result.get('isError'):
                        print(json.dumps({'tool_error': [part.get('text', '')[:220]
                            for part in result.get('content', [])]}))
os.chdir('/home/zyd/frappe/native-bench')
frappe.init(site='child.myyr.top', sites_path='/home/zyd/frappe/native-bench/sites')
try:
    frappe.connect(set_admin_as_user=False)
    frappe.set_user('Administrator')
    from tongjianyun import harness_administrator_approvals as service
    frappe.conf[service.WRITE_ENABLE_KEY] = 1
    try:
        result = service.review_previews('d' * 64)
        print(json.dumps({'review_rows': len(result['items'])}))
    except Exception as error:
        print(json.dumps({'error_type': type(error).__name__,
            'locations': [{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                for frame in traceback.extract_tb(error.__traceback__)]}))
finally:
    frappe.db.rollback()
    frappe.destroy()
