"""Loopback-only synthetic UI preview. No credentials, model, DB or export."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tongjianyun.nutrition_canvas_sheet import spreadsheet_component
from tongjianyun.tests.test_nutrition_canvas_sheet import synthetic_analysis


def main():
    analysis = synthetic_analysis()
    selection = {'view': 'recipe_nutrition', 'recipe': 'SYNTHETIC-RECIPE', 'day': '2026-09-24', 'meal': 'lunch', 'garden_ratio': 80}
    tools = {'type': 'nutrition_overview', 'mode': 'sheet', 'headline': '营养分析表', 'state': 'attention',
             'items': [], 'attention': [], 'unknown_count': 0, 'ingredient_count': len(analysis['ingredients']),
             'day_count': 5, 'selection': selection, 'can_export': False}
    for key, label, unit in [('energy', '热量', 'kcal'), ('protein', '蛋白质', 'g'), ('calcium', '钙', 'mg')]:
        value = analysis['nutrient_evaluations'][key]
        tools['items'].append({'label': label, 'unit': unit, 'value': value['actual'], 'target': value['garden_target'], 'status': value['status']})
    fixture = json.dumps({'version': 1, 'selection': selection, 'components': [tools,
        spreadsheet_component(analysis, analysis['nutrient_evaluations'], True)]}, ensure_ascii=False).encode()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def do_GET(self):
            if self.path != '/nutrition-sheet-preview.json':
                return super().do_GET()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(fixture)))
            self.end_headers()
            self.wfile.write(fixture)

    print('Synthetic preview: http://127.0.0.1:23403/deploy/meal_chat_views/nutrition-preview.html', flush=True)
    with ThreadingHTTPServer(('127.0.0.1', 23403), Handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
