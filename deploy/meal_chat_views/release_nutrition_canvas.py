"""Release this canvas only, preserving the older production scene and dirty files.

Hash-pinned code-only overlay; no config, schema, role or service modification.
Run --check before --apply. Production must be idle before the separate reload.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

PRODUCTION = Path('/home/zyd/frappe/native-bench/apps/tongjianyun')
CANDIDATE = Path('/home/zyd/frappe/remote-workspace/nutrition-canvas-production-20260927')
SOURCE = Path('/home/zyd/frappe/remote-workspace/nutrition-canvas-20260927')
BASELINES = {
    'tongjianyun/meal_nutrition_view.py': '25b4139a047552b7d3168dac89acb023ce810767aa4b5fb3f1d3dece1697eaf8',
    'tongjianyun/frappe_project_views.py': 'c4ec57a70cc1cde8c3abbc292b1afd45ca5e7be74a00de1f3a83bceef3769659',
    'tongjianyun/meal_views.py': '9579f9ec7756fb2e3bf4404e8cd627b01a6811cd180edf75cd0b7c8a088825c6',
    'tongjianyun/public/meal_scene/views.js': '68a53260a6e41c0455cab4c9df2cfc24a35d0673fe4eb3728065da18d1858ef6',
    'tongjianyun/public/meal_scene/views.css': '89eafd729db9aa15440ac3b50a90ec28193a5f96dc6e5c6da11d2181c1211821',
    'tongjianyun/public/meal_scene/chat.js': '8f6aa00d6d736c5c0e932c4a0e495b11a93fc59b5e8315f481f25fc233c61a83',
    'tongjianyun/www/tongjianyun-meal-scene.html': '966d264662ed7a79a2b453791a3f4b805832c1444b9958cb4800cbaa0b10ea8a',
}
VERSION = 'nutrition-canvas-20260927-1'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Code anchor missing or ambiguous: ' + old[:80])
    return text.replace(old, new, 1)


def between(text, start, end):
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError('Source anchors missing or ambiguous')
    return text[text.index(start):text.index(end)]


def build(relative, original):
    source = (SOURCE / relative).read_text(encoding='utf-8')
    if relative in ('tongjianyun/meal_nutrition_view.py', 'tongjianyun/frappe_project_views.py'):
        return source.encode('utf-8')
    text = original.decode('utf-8')
    if relative.endswith('/meal_views.py'):
        text = replace_once(text, "{'attendance_register', 'meal_register'}", "{'attendance_register', 'meal_register', 'nutrition_overview'}")
    elif relative.endswith('/views.js'):
        anchor = "  const section=node(block.collapsed?'details':'section',undefined,block.collapsed?'view-section view-details':'view-section');"
        text = replace_once(text, anchor, anchor + "\n  if(block.detail_key==='nutrition-nutrients')section.id='nutrition-nutrients';")
        function = between(source, 'function renderNutritionOverview(block){', 'function safeDeskRoute(route){')
        text = replace_once(text, 'function safeDeskRoute(route){', function + 'function safeDeskRoute(route){')
        text = replace_once(text, 'export function buildComponents(data){', 'renderers.nutrition_overview=renderNutritionOverview;\nexport function buildComponents(data){')
    elif relative.endswith('/views.css'):
        styles = between(source, '\n.nutrition-assessment{', '\n#view-status{')
        text = replace_once(text, '#view-status{', styles + '#view-status{')
    elif relative.endswith('/chat.js'):
        text = replace_once(text, "./views.js?v=unified-business-20260925-6", './views.js?v=' + VERSION)
    elif relative.endswith('.html'):
        text = replace_once(text, 'views.css?v=unified-business-20260925-6', 'views.css?v=' + VERSION)
        text = replace_once(text, 'chat.js?v=unified-business-20260925-6', 'chat.js?v=' + VERSION)
    return text.encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True, choices=(PRODUCTION, CANDIDATE))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    target = args.target.resolve(strict=True)
    if target != args.target or SOURCE.resolve(strict=True) != SOURCE:
        raise RuntimeError('Unexpected path or symlink')
    original, replacement = {}, {}
    for relative, expected in BASELINES.items():
        path = target / relative
        if not path.resolve(strict=True).is_relative_to(target) or path.is_symlink():
            raise RuntimeError('Unexpected target file: ' + relative)
        original[relative] = path.read_bytes()
        if digest(original[relative]) != expected:
            raise RuntimeError('Concurrent change or different baseline: ' + relative)
        replacement[relative] = build(relative, original[relative])
    if args.apply:
        backup = target.parent / (target.name + '-nutrition-canvas-backup-20260927')
        backup.mkdir(mode=0o700, exist_ok=False)
        for relative, content in original.items():
            path = backup / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        written = []
        try:
            for relative, content in replacement.items():
                path = target / relative
                if path.read_bytes() != original[relative]:
                    raise RuntimeError('Concurrent edit during release: ' + relative)
                temporary = path.with_name(path.name + '.nutrition-release.tmp')
                with temporary.open('xb') as stream:
                    stream.write(content)
                os.replace(temporary, path)
                written.append(relative)
        except Exception:
            for relative in reversed(written):
                (target / relative).write_bytes(original[relative])
            raise
    print(json.dumps({'applied': args.apply, 'target': str(target), 'files': len(replacement),
                      'sha256': {name: digest(content) for name, content in replacement.items()},
                      'config_changed': False, 'schema_changed': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
