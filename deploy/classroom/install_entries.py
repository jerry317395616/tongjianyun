"""Idempotent source-only navigation integration. Run from this app's checkout.

No DocTypes, Custom Fields, fixtures, site configuration or migrations are used.
"""
from pathlib import Path

APP = Path(__file__).resolve().parents[2]


def replace_once(path, old, new):
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f"Unexpected source revision: {path.relative_to(APP)}")
    path.write_text(text.replace(old, new, 1))
    print("Updated", path.relative_to(APP))


replace_once(
    APP / "tongjianyun/tongjianyun/page/tongjianyun_workbench/tongjianyun_workbench.js",
    '        this.page.add_inner_button("园区数字孪生", () => { window.location.href = "/tongjianyun-campus"; });',
    '        this.page.add_inner_button("园区数字孪生", () => { window.location.href = "/tongjianyun-campus"; });\n'
    '        this.page.add_inner_button("班级管理场景", () => { window.location.href = "/tongjianyun-classroom"; });',
)
replace_once(
    APP / "tongjianyun/public/js/student_group.js",
    '    add_student_import_button(frm)\n',
    '    add_student_import_button(frm)\n'
    '    if (!frm.is_new() && !frm.doc.disabled) {\n'
    '      frm.add_custom_button("班级管理场景", () => {\n'
    '        window.location.href = "/tongjianyun-classroom?class=" + encodeURIComponent(frm.doc.name)\n'
    '      })\n'
    '    }\n',
)
for relative in ["tongjianyun/hooks.py", "tongjianyun/public/js/page_cache_buster.js"]:
    path = APP / relative
    text = path.read_text()
    old, new = "20260919-director-teacher-attendance-1", "20260923-classroom-1"
    if old in text:
        path.write_text(text.replace(old, new))
        print("Updated", relative)

# Remove only the identical obsolete module created by this rollout; preserve any other edits.
legacy = APP / "tongjianyun/public/classroom/state.mjs"
current = APP / "tongjianyun/public/classroom/state.js"
if legacy.is_file() and current.is_file() and legacy.read_text() == current.read_text().split("\n", 1)[1]:
    legacy.unlink()
    print("Removed identical obsolete classroom state.mjs; modules now use .js MIME")
