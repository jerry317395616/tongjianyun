"""Installed Codex's local read-only display tool; deliberately not HTTP exposed."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--site', required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--view', required=True, choices=['students', 'class_students', 'meal_counts', 'recipe_week', 'recipe_nutrition',
                        'business_catalog', 'business_list', 'business_record', 'stock', 'ingredient_nutrition', 'classroom_day', 'weekly_orders'])
    parser.add_argument('--presentation', choices=['table', 'bars'])
    parser.add_argument('--components', nargs='+', choices=['stats', 'table', 'bars', 'notice', 'recipe_week'])
    parser.add_argument('--group')
    parser.add_argument('--day')
    parser.add_argument('--meal')
    parser.add_argument('--recipe')
    parser.add_argument('--garden-ratio', dest='garden_ratio', type=float)
    parser.add_argument('--standard-mode', dest='standard_mode', choices=['自动（按学生档案）', '手动估算'])
    parser.add_argument('--age-group', dest='age_group', choices=['4–6岁平均', '4岁', '5岁', '6岁'])
    parser.add_argument('--gender', choices=['男女平均', '男', '女'])
    parser.add_argument('--student-groups', dest='student_groups', nargs='+')
    for name in ('entity', 'record', 'keyword', 'period', 'start-date', 'end-date', 'status', 'company', 'warehouse', 'domain'):
        parser.add_argument('--' + name)
    parser.add_argument('--offset', type=int)
    args = parser.parse_args()
    sites = Path('/home/zyd/frappe/native-bench/sites').resolve()
    if Path(args.site).name != args.site or not (sites / args.site / 'site_config.json').is_file():
        parser.error('Invalid site')
    # Frappe's site log paths are relative to the sites directory even when
    # sites_path is absolute. The Codex command normally starts in the app repo.
    os.chdir(sites)
    import frappe
    frappe.init(site=args.site, sites_path=str(sites))
    frappe.connect()
    try:
        from tongjianyun.meal_views import publish_for_task
        requested = {k: v for k, v in vars(args).items() if k not in {'site', 'task'} and v is not None}
        print(json.dumps(publish_for_task(args.task, requested), ensure_ascii=False, default=str))
    except Exception as error:
        print(json.dumps({'displayed': False, 'error': str(error)[:400]}, ensure_ascii=False))
        raise SystemExit(1)
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == '__main__':
    main()
