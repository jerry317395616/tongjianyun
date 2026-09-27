"""Hash-pinned Excel-layout overlay; preserve unrelated production changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from release_nutrition_canvas import between, replace_once

PRODUCTION = Path('/home/zyd/frappe/native-bench/apps/tongjianyun')
CANDIDATE = Path('/home/zyd/frappe/remote-workspace/nutrition-excel-production-20260927')
SOURCE = Path('/home/zyd/frappe/remote-workspace/nutrition-excel-source-20260927')
BASELINES = {
    'tongjianyun/nutrition_canvas_sheet.py': None,
    'tongjianyun/meal_nutrition_view.py': '86a2283049a9ebf4ced83286f410c8b39347aad547918474a8f2926e991b02ba',
    'tongjianyun/meal_views.py': '371b72813298a689c6ca43c4ad8ae7a1ea3edb9140baa59fd58053c309648041',
    'tongjianyun/public/meal_scene/views.js': '61ce4ec542396dee533b9c553cc8f2df71b3b20d962609915b17d43cee99ab04',
    'tongjianyun/public/meal_scene/views.css': '0ee78075d12e89be48e10278d4bf649b3e71b5ae52cacbd04edf57c11c98180a',
    'tongjianyun/public/meal_scene/chat.js': '04be3e06154b11566c930cad9f2069489a28469963c26e1d2667347224499a2e',
    'tongjianyun/www/tongjianyun-meal-scene.html': '9c501dd4618eff8d18421a55ed51dbcab848b1c3c6648e6e2bd286162f860205',
}
VERSION = 'nutrition-excel-20260927-2'


def digest(content):
    return hashlib.sha256(content).hexdigest()


def build(relative, content):
    source = (SOURCE / relative).read_text(encoding='utf-8')
    if relative.endswith(('/nutrition_canvas_sheet.py', '/meal_nutrition_view.py')):
        return source.encode('utf-8')
    text = content.decode('utf-8')
    if relative.endswith('/meal_views.py'):
        text = replace_once(text, "'meal_register', 'nutrition_overview'}", "'meal_register', 'nutrition_overview', 'nutrition_sheet'}")
    elif relative.endswith('/views.js'):
        start, end = 'function renderNutritionOverview(block){', 'function safeDeskRoute(route){'
        text = replace_once(text, between(text, start, end), between(source, start, end))
        text = replace_once(text, 'renderers.nutrition_overview=renderNutritionOverview;',
                            'renderers.nutrition_overview=renderNutritionOverview;\nrenderers.nutrition_sheet=renderNutritionSheet;')
    elif relative.endswith('/views.css'):
        text = replace_once(text, '#view-status{', between(source, '.nutrition-sheet-tools{', '#view-status{') + '#view-status{')
    elif relative.endswith('/chat.js'):
        text = replace_once(text, './views.js?v=nutrition-canvas-20260927-1', './views.js?v=' + VERSION)
    elif relative.endswith('.html'):
        text = replace_once(text, 'views.css?v=nutrition-canvas-20260927-1', 'views.css?v=' + VERSION)
        text = replace_once(text, 'chat.js?v=nutrition-canvas-20260927-1', 'chat.js?v=' + VERSION)
    return text.encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True, choices=(PRODUCTION, CANDIDATE))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    target = args.target.resolve(strict=True)
    if target != args.target or SOURCE.resolve(strict=True) != SOURCE:
        raise RuntimeError('Unexpected target/source path')
    original, replacement = {}, {}
    for relative, expected in BASELINES.items():
        path = target / relative
        if not path.resolve().is_relative_to(target) or path.is_symlink():
            raise RuntimeError('Unexpected target file')
        original[relative] = path.read_bytes() if path.exists() else None
        actual = digest(original[relative]) if original[relative] is not None else None
        if actual != expected:
            raise RuntimeError('Concurrent change or different baseline: ' + relative)
        replacement[relative] = build(relative, original[relative])
    if args.apply:
        backup = target.parent / (target.name + '-nutrition-excel-backup-20260927')
        backup.mkdir(mode=0o700, exist_ok=False)
        for relative, content in original.items():
            if content is not None:
                path = backup / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        written = []
        try:
            for relative, content in replacement.items():
                path = target / relative
                if (path.read_bytes() if path.exists() else None) != original[relative]:
                    raise RuntimeError('Concurrent edit during release: ' + relative)
                temporary = path.with_name(path.name + '.nutrition-excel.tmp')
                with temporary.open('xb') as stream:
                    stream.write(content)
                os.replace(temporary, path)
                written.append(relative)
        except Exception:
            for relative in reversed(written):
                path = target / relative
                if original[relative] is None:
                    if path.read_bytes() == replacement[relative]:
                        path.unlink()  # only our newly created projection module
                else:
                    path.write_bytes(original[relative])
            raise
    print(json.dumps({'applied': args.apply, 'target': str(target), 'files': len(replacement),
                      'sha256': {name: digest(value) for name, value in replacement.items()},
                      'config_changed': False, 'schema_changed': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
