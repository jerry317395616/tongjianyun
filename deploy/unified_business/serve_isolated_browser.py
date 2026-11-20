"""Loopback-only browser QA harness; never serve or modify a production site.

prepare copies public assets and provisions synthetic browser credentials.
refresh-assets updates only public files and version evidence, never credentials
or database fixtures. seed-blueprint prepares one task-owned, unactivated v2
proposal for visible browser confirmation. serve pins the isolated site and blocks every non-allowlisted RPC (including
Codex execution/upload). verify prints non-secret readiness only. No workers,
schedulers, migrations, production sessions, proxies or debug server are used.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import urlopen


TASK = "tgy-blueprint-lifecycle-qa-20260925"
ROOT = Path("/home/zyd/frappe/remote-workspace") / TASK
SITES = ROOT / "sites"
SITE = "unified-business-acceptance.localhost"
SOURCE = Path("/home/zyd/frappe/remote-workspace/unified-business-20260925")
BENCH = Path("/home/zyd/frappe/native-bench")
PORT = 23380
ORIGIN = f"http://{SITE}:{PORT}"
ASSETS = SITES / "assets"
CREDENTIALS = ROOT / "browser-credentials.json"
STATE = ROOT / "browser-fixture.json"
ASSET_MARKER = ROOT / "browser-assets.json"
SERVER_STATE = ROOT / "browser-server.json"
BLUEPRINT_STATE = ROOT / "browser-blueprint-fixture.json"
DESK_STATE = ROOT / "browser-desk-readiness.json"
APPS = ("frappe", "erpnext", "education", "tongjianyun")
CRITICAL_ASSETS = ("meal_scene/views.js", "meal_scene/views.css", "meal_scene/chat.js",
                   "meal_scene/app.js", "meal_scene/state.js", "meal_scene/scene_bootstrap.js")
REQUIRED_RENDERERS = ("attendance_register:renderAttendance", "meal_register:renderMealRegister",
                      "business_blueprint:renderBlueprint", "stock_repair:renderStockRepair")

# This test surface deliberately does not run the host's privileged agent.
# Deny-by-default also covers alternative /api/v2/method and form cmd aliases.
READ_METHODS = {
    "frappe.auth.get_logged_user", "frappe.client.get", "frappe.client.get_list",
    "tongjianyun.scene_access.get_bootstrap",
    "tongjianyun.meal_chat.get_chat_access", "tongjianyun.meal_chat.get_conversation",
    "tongjianyun.meal_views.get_view", "tongjianyun.meal_scene.get_overview",
    "tongjianyun.meal_scene.get_recipe", "tongjianyun.classroom.get_overview",
    "tongjianyun.classroom.get_meals", "tongjianyun.classroom.get_health",
}
WRITE_METHODS = {
    "login", "logout", "tongjianyun.classroom.save_attendance",
    "tongjianyun.classroom.save_meal", "tongjianyun.classroom.save_meals",
}
BLUEPRINT_METHODS = {
    "tongjianyun.business_blueprints.activate",
    "frappe.desk.form.load.getdoctype", "frappe.desk.form.load.getdoc",
    "frappe.desk.form.load.get_docinfo", "frappe.desk.form.save.savedocs",
    "frappe.model.workflow.get_transitions", "frappe.model.utils.user_settings.get",
    "frappe.model.utils.user_settings.save",
}
DESK_READ_METHODS = {"frappe.translate.get_boot_translations",
    "frappe.core.doctype.session_default_settings.session_default_settings.get_session_default_values"}
AUDIT_PARAMETER_KEYS = {"cmd", "_", "csrf_token", "selection_json", "doctype", "with_parent", "cached_timestamp",
    "name", "doc", "action", "proposal_id", "revision", "user_settings", "lang", "v", "day", "meal",
    "student_group", "students", "group", "workspace", "expected_revision", "change_reason"}


def safe_target(path: Path) -> Path:
    assert path.is_absolute() and path.resolve().is_relative_to(ROOT), "Outside QA root"
    for parent in (path, *path.parents):
        if parent == ROOT.parent:
            break
        assert not parent.is_symlink(), "QA write target may not use symlinks"
    return path


def private_json(path, value):
    safe_target(path)
    # All script-generated files live below the guarded 0700 test root.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def guard(conf):
    assert conf.get("unified_business_acceptance") == 1
    assert conf.get("db_host") == "127.0.0.1" and int(conf.get("db_port", 0)) == 23316
    assert conf.get("db_name") == "tgy_blueprint_qa"
    assert conf.get("db_user", conf.get("db_name")) == "tgy_blueprint_qa"
    assert not conf.get("db_socket") and not conf.get("developer_mode")
    assert conf.get("pause_scheduler") == 1 and conf.get("disable_scheduler") == 1
    assert conf.get("mute_emails") == 1 and conf.get("disable_email_queue") == 1
    for key, db in (("redis_cache", "0"), ("redis_queue", "1"), ("redis_socketio", "2")):
        url = urlparse(conf.get(key) or "")
        assert url.scheme == "redis" and url.hostname == "127.0.0.1" and url.port == 23379
        assert url.path == "/" + db


def config_guard():
    assert ROOT.resolve(strict=True) == ROOT and SITES.resolve(strict=True) == SITES
    safe_target(SITES / SITE / "site_config.json")
    safe_target(SITES / "common_site_config.json")
    assert json.loads((ROOT / "isolation-marker.json").read_text())["owner"] == TASK
    config = {**json.loads((SITES / "common_site_config.json").read_text()),
              **json.loads((SITES / SITE / "site_config.json").read_text())}
    guard(config)
    assert SOURCE.resolve(strict=True) == SOURCE
    return config


def runtime():
    config_guard()
    for key in list(os.environ):
        if key.startswith(("FRAPPE_DB_", "FRAPPE_REDIS_")):
            os.environ.pop(key)
    os.environ["FRAPPE_BENCH_ROOT"] = str(ROOT)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SOURCE))
    os.chdir(SITES)
    import frappe
    import tongjianyun
    from tongjianyun.meal_view_tool import use_site_os_identity
    assert Path(tongjianyun.__file__).resolve().is_relative_to(SOURCE)
    assert Path(frappe.__file__).resolve().is_relative_to(BENCH / "apps/frappe")
    use_site_os_identity(SITES / SITE)
    os.umask(0o077)
    return frappe


def connect():
    frappe = runtime()
    frappe.init(site=SITE, sites_path=str(SITES))
    guard(frappe.conf)
    frappe.connect()
    frappe.set_user("Administrator")
    return frappe


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def public_source(app):
    assert app in APPS
    public = SOURCE / "tongjianyun/public" if app == "tongjianyun" else BENCH / f"apps/{app}/{app}/public"
    assert public.resolve(strict=True) == public and not public.is_symlink()
    return public


def source_version_evidence():
    public = public_source("tongjianyun")
    views = (public / "meal_scene/views.js").read_text()
    assert all(renderer in views for renderer in REQUIRED_RENDERERS), "Candidate lacks required business renderers"
    template = SOURCE / "tongjianyun/www/tongjianyun-meal-scene.html"
    assert template.resolve(strict=True).is_relative_to(SOURCE) and not template.is_symlink()
    return {"template_sha256": digest_file(template),
            "template_asset_urls": re.findall(r'/assets/tongjianyun/[^"\s>]+', template.read_text()),
            "chat_views_import": re.findall(r'\./views\.js\?v=[^\x27"\s]+', (public / "meal_scene/chat.js").read_text()),
            "renderers": list(REQUIRED_RENDERERS)}


def verify_asset_evidence():
    config_guard()
    marker = json.loads(safe_target(ASSET_MARKER).read_text())
    assert marker["owner"] == TASK and marker["state"] == "ready" and marker["evidence_version"] == 1
    assert marker["version"] == source_version_evidence(), "Candidate template or renderer version changed"
    for item in marker["files"]:
        relative = Path(item["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        origin = public_source(item["app"]) / relative
        assert not origin.is_symlink() and origin.resolve(strict=True).is_relative_to(public_source(item["app"]))
        target = safe_target(ASSETS / item["app"] / relative)
        assert digest_file(origin) == item["sha256"] == digest_file(target), "Source or copied public asset changed"
    critical = {item["path"]: item["sha256"] for item in marker["files"]
                if item["app"] == "tongjianyun" and item["path"] in CRITICAL_ASSETS}
    assert set(critical) == set(CRITICAL_ASSETS)
    return {"source_and_copy_match": True, "files_verified": len(marker["files"]),
            "critical_sha256": critical, **marker["version"]}


def copy_public_assets():
    config_guard()
    version = source_version_evidence()
    safe_target(ASSETS)
    if ASSETS.exists():
        assert ASSET_MARKER.exists() and json.loads(ASSET_MARKER.read_text())["owner"] == TASK
    else:
        ASSETS.mkdir(mode=0o700)
        private_json(ASSET_MARKER, {"owner": TASK, "state": "copying"})
    records = []
    for app in APPS:
        public = public_source(app)
        destination = safe_target(ASSETS / app)
        destination.mkdir(mode=0o700, exist_ok=True)
        for folder, directories, filenames in os.walk(public, followlinks=False):
            # Installed public/node_modules links point outside public. Bundles
            # already contain those dependencies; never follow these links.
            directories[:] = [name for name in directories if name not in {"node_modules", ".git"}
                              and not (Path(folder) / name).is_symlink()]
            relative = Path(folder).relative_to(public)
            target_dir = safe_target(destination / relative)
            target_dir.mkdir(mode=0o700, exist_ok=True)
            for name in filenames:
                origin = Path(folder) / name
                assert not origin.is_symlink() and origin.resolve().is_relative_to(public)
                target = safe_target(target_dir / name)
                shutil.copyfile(origin, target)
                target.chmod(0o600)
                origin_hash = digest_file(origin)
                assert digest_file(target) == origin_hash, "Asset copy changed during refresh"
                records.append({"app": app, "path": origin.relative_to(public).as_posix(), "sha256": origin_hash})
    for filename in ("assets.json", "assets-rtl.json"):
        # Public build indexes only; never read production site configuration.
        original = BENCH / "sites/assets" / filename
        manifest = json.loads(original.read_text())
        manifest = {key: value for key, value in manifest.items() if isinstance(value, str)
                    and any(value.startswith(f"/assets/{app}/") for app in APPS)}
        private_json(ASSETS / filename, manifest)
    private_json(ASSET_MARKER, {"owner": TASK, "state": "ready", "files_copied": len(records),
        "source": str(SOURCE), "apps": list(APPS), "evidence_version": 1,
        "version": version, "files": sorted(records, key=lambda row: (row["app"], row["path"]))})
    return verify_asset_evidence()


def refresh_assets():
    config_guard()
    # This path never initializes Frappe, connects to DB/Redis, enables the web,
    # seeds navigation, rotates credentials or edits any business fixture.
    preserved = (STATE, CREDENTIALS, SITES / SITE / "site_config.json", SITES / "common_site_config.json",
                 *[path for path in (BLUEPRINT_STATE, DESK_STATE) if path.exists()])
    before = {str(path): digest_file(safe_target(path)) for path in preserved}
    evidence = copy_public_assets()
    assert before == {str(path): digest_file(safe_target(path)) for path in preserved}
    return {"owner": TASK, "asset_only": True, "fixtures_and_credentials_unchanged": True,
            "assets": evidence}


def prepare_fixture():
    frappe = connect()
    try:
        if STATE.exists():
            state = json.loads(safe_target(STATE).read_text())
            secret = json.loads(safe_target(CREDENTIALS).read_text())
            assert state["owner"] == TASK and secret["owner"] == TASK
            assert state["manager"] == secret["manager"]["user"]
            assert state["teacher"] == secret["teacher"]["user"]
            assert set(frappe.get_roles(state["manager"])) >= {"System Manager", "Academics User"}
            assert not set(frappe.get_roles(state["teacher"])) & {"System Manager", "Education Manager", "Tongjianyun Business Operator"}
            assert frappe.db.get_value("User", state["manager"], "enabled")
            if state.get("navigation_version") != 2:
                seed_navigation(frappe, state)
                frappe.db.commit()
                private_json(STATE, state)
            return state
        assert not CREDENTIALS.exists(), "Orphan credentials require inspection; do not silently reset"
        report = json.loads((ROOT / "teacher-scope-lifecycle-9680e04d9f.json").read_text())
        assert report["isolated_site"] == SITE and report["status"] == "passed"
        assert report["fixtures_committed"] and not report["production_writes"]
        previous = report["retained_synthetic_records"]
        teacher, group = previous["teacher"], previous["assigned_group"]
        assert teacher.startswith("teacher-scope-") and teacher.endswith("@example.invalid")
        assert group.startswith("QA Teacher ")
        from frappe.utils import getdate, nowdate
        from frappe.utils.password import update_password
        from tongjianyun.attendance_scope import allowed_groups, is_manager
        from tongjianyun import classroom

        day = getdate(nowdate()) - timedelta(days=7)
        year = frappe.get_doc("Academic Year", frappe.db.get_value("Student Group", group, "academic_year"))
        while frappe.db.exists("Tongjianyun Daily Meal Confirmation", {"meal_date": str(day)}):
            day -= timedelta(days=1)
        assert day >= getdate(year.year_start_date)
        manager = "browser-manager-" + uuid.uuid4().hex[:10] + "@example.invalid"
        manager_password, teacher_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        frappe.get_doc({"doctype": "User", "email": manager, "first_name": "Synthetic Browser Manager",
            "enabled": 1, "user_type": "System User", "send_welcome_email": 0,
            "roles": [{"role": "System Manager"}, {"role": "Academics User"}]}).insert()
        update_password(manager, manager_password, logout_all_sessions=True)
        update_password(teacher, teacher_password, logout_all_sessions=True)
        frappe.set_user(teacher)
        assert not is_manager() and set(allowed_groups()) == {group}
        snapshot = classroom.get_overview(group, str(day), workspace="teacher")
        assert snapshot["attendance"]["counts"]["Unknown"] == 2
        assert snapshot["capabilities"]["attendance_write"]
        frappe.set_user(manager)
        assert is_manager() and manager != "Administrator"
        state = {"owner": TASK, "site": SITE, "origin": ORIGIN, "manager": manager, "teacher": teacher,
                 "group": group, "day": str(day), "meal": "lunch",
                 "credentials_file": str(CREDENTIALS), "production_writes": False,
                 "teacher_roles_unchanged": True, "codex_execution_blocked": True}
        seed_navigation(frappe, state)
        private_json(CREDENTIALS, {"owner": TASK, "manager": {"user": manager, "password": manager_password},
                                  "teacher": {"user": teacher, "password": teacher_password}})
        frappe.db.commit()
        private_json(STATE, state)
        return state
    finally:
        frappe.db.rollback()
        frappe.destroy()


def seed_navigation(frappe, state):
    from tongjianyun.meal_chat import TaskStore
    from tongjianyun.meal_views import publish_for_task
    task_id = str(uuid.uuid4())
    store = TaskStore()
    assert store.site == SITE
    store.update(task_id, owner=state["manager"], status="running", day=state["day"], meal=state["meal"],
                 message="隔离测试导航，未调用Codex", created=time.time(), heartbeat=time.time(), cancel_requested="0")
    store.emit(task_id, {"kind": "message", "item_id": "qa-navigation", "text": "合成验收导航。点击按钮读取真实测试数据；没有运行 Codex。"})
    try:
        for view in ("classroom_day", "meal_counts"):
            result = publish_for_task(task_id, {"view": view, "group": state["group"], "day": state["day"], "meal": state["meal"]})
            assert result["display_requested"]
        store.finish(task_id, "completed", "验收导航已准备；没有运行智能体或创建考勤/实际用餐记录。")
    except Exception:
        store.finish(task_id, "failed", "隔离导航准备失败；没有运行智能体。")
        raise
    history = store.user_key(state["manager"]) + ":history"
    # Unlink only the superseded, script-owned navigation fixture; retain its
    # task/events in Redis for inspection. Never touch another user's history.
    if state.get("navigation_task"):
        prior = store.read(state["navigation_task"])
        assert prior["owner"] == state["manager"] and prior["status"] == "completed"
        store.redis.lrem(history, 0, state["navigation_task"])
    store.redis.lpush(history, task_id)
    store.redis.expire(history, 14 * 24 * 3600)
    state.update(navigation_task=task_id, navigation_version=2)


def seed_blueprint():
    """Prepare one reviewed, task-bound proposal, never activate it for the UI."""
    frappe = connect()
    try:
        state = json.loads(safe_target(STATE).read_text())
        assert state["owner"] == TASK and state["site"] == SITE
        assert state["manager"] == "browser-manager-02e16a31d7@example.invalid"
        assert frappe.db.get_value("User", state["manager"], "enabled")
        assert "System Manager" in frappe.get_roles(state["manager"])
        from tongjianyun import business_blueprints as bp
        from tongjianyun.business_blueprints_v2 import row_name
        from tongjianyun.meal_chat import TaskStore
        credentials_before = digest_file(safe_target(CREDENTIALS))
        fixture_before = digest_file(safe_target(STATE))
        if BLUEPRINT_STATE.exists():
            fixture = blueprint_fixture()
            frappe.set_user(state["manager"])
            assert bp.revision(bp._load(fixture["proposal_id"])) == fixture["revision"]
            return {**fixture, "reused": True, "credentials_unchanged": True}
        run_id = uuid.uuid4().hex[:10]
        spec = bp.validate_spec({"version": 2, "key": "browser_estimate_" + run_id,
            "title": "隔离浏览器活动估算 " + run_id,
            "description": "合成浏览器验收：填写明细并复核；不采购、不付款、不扣库存。",
            "fields": [{"fieldname": "estimated_total", "label": "估算合计", "fieldtype": "Currency"}],
            "tables": [{"fieldname": "estimate_lines", "label": "估算明细", "reqd": 1, "fields": [
                {"fieldname": "item_label", "label": "项目", "fieldtype": "Data", "reqd": 1},
                {"fieldname": "quantity", "label": "数量", "fieldtype": "Float", "reqd": 1},
                {"fieldname": "unit_price", "label": "单价", "fieldtype": "Currency", "reqd": 1},
                {"fieldname": "line_amount", "label": "小计", "fieldtype": "Currency"}]}],
            "calculations": [{"op": "multiply", "table": "estimate_lines", "target": "line_amount",
                              "sources": ["quantity", "unit_price"]},
                             {"op": "sum", "table": "estimate_lines", "target": "estimated_total", "source": "line_amount"}],
            "workflow": {"template": "review"}})
        assert not frappe.db.exists("DocType", bp.doctype_name(spec))
        task_id, store = str(uuid.uuid4()), TaskStore()
        assert store.site == SITE
        store.update(task_id, owner=state["manager"], status="running", day=state["day"], meal=state["meal"],
                     message="隔离测试：新增活动估算业务（未调用 Codex）", created=time.time(), heartbeat=time.time(), cancel_requested="0")
        try:
            proposal = bp.propose_for_task(task_id, spec)
            assert proposal["display_requested"] and proposal["state"] == "proposed"
            assert not frappe.db.exists("DocType", proposal["doctype"])
            store.finish(task_id, "completed", "隔离验收方案已准备：请在左侧核对并决定启用；没有运行 Codex，也没有预先创建业务类型或记录。")
        except Exception:
            store.finish(task_id, "failed", "隔离方案准备失败，未运行 Codex。")
            raise
        history = store.user_key(state["manager"]) + ":history"
        store.redis.lpush(history, task_id)
        store.redis.expire(history, 14 * 24 * 3600)
        fixture = {"owner": TASK, "site": SITE, "manager": state["manager"], "run_id": run_id,
                   "task_id": task_id, "proposal_id": proposal["proposal_id"], "revision": proposal["revision"],
                   "doctype": proposal["doctype"], "title": spec["title"], "spec": spec,
                   "children": {t["fieldname"]: row_name(spec, t) for t in spec["tables"]},
                   "activation_performed": False, "codex_execution_performed": False, "production_writes": False}
        private_json(BLUEPRINT_STATE, fixture)
        assert credentials_before == digest_file(CREDENTIALS) and fixture_before == digest_file(STATE)
        return {**fixture, "reused": False, "credentials_unchanged": True}
    finally:
        frappe.db.rollback()
        frappe.destroy()


def blueprint_fixture():
    """Private script-owned allowlist, not request-controlled or a login bypass."""
    fixture = json.loads(safe_target(BLUEPRINT_STATE).read_text())
    assert fixture["owner"] == TASK and fixture["site"] == SITE
    assert fixture["manager"] == "browser-manager-02e16a31d7@example.invalid"
    assert re.fullmatch(r"[0-9a-f]{10}", fixture["run_id"])
    assert fixture["doctype"] == "Tongjianyun Advanced browser_estimate_" + fixture["run_id"]
    assert set(fixture["children"]) == {"estimate_lines"}
    expected_row = "TGY Extension Row " + hashlib.sha256(
        ("browser_estimate_" + fixture["run_id"] + ":estimate_lines").encode()).hexdigest()[:24]
    assert fixture["children"]["estimate_lines"] == expected_row
    assert re.fullmatch(r"[0-9a-f]{64}", fixture["revision"])
    assert isinstance(fixture["proposal_id"], str) and fixture["proposal_id"]
    return fixture


def inspect_desk():
    frappe = connect()
    try:
        frappe.db.sql("START TRANSACTION READ ONLY")
        return {"site": SITE, "setup_complete": frappe.is_setup_complete(),
            "installed": frappe.get_all("Installed Application", fields=["app_name", "is_setup_complete"]),
            "system": {key: frappe.db.get_single_value("System Settings", key) for key in
                       ("country", "time_zone", "currency", "language", "setup_complete")},
            "synthetic_companies": frappe.get_list("Company", filters={"name": ["like", "QA%"]},
                fields=["name", "country", "default_currency"], limit_page_length=0),
            "business_writes": False, "production_writes": False}
    finally:
        frappe.db.rollback()
        frappe.destroy()


def prepare_desk():
    """Complete only missing QA wizard markers; never rerun setup hooks."""
    frappe = connect()
    try:
        state = json.loads(safe_target(STATE).read_text())
        assert state["owner"] == TASK and state["site"] == SITE
        assert set(frappe.get_installed_apps()) == set(APPS)
        installed = {row.app_name: int(row.is_setup_complete or 0) for row in
                     frappe.get_all("Installed Application", fields=["app_name", "is_setup_complete"])}
        assert set(installed) == set(APPS) and all(flag in (0, 1) for flag in installed.values())
        companies = frappe.get_all("Company", fields=["name", "country", "default_currency"])
        assert companies and all(row.name.startswith("QA ") and row.country == "China" and row.default_currency == "CNY"
                                 for row in companies), "Only prepared synthetic companies may complete QA desk readiness"
        for company in companies:
            assert frappe.db.count("Account", {"company": company.name, "is_group": 0}) > 0
            assert frappe.db.count("Warehouse", {"company": company.name, "is_group": 0}) > 0
        before = {"installed": installed, "system_setup_complete": int(frappe.db.get_single_value("System Settings", "setup_complete") or 0)}
        if DESK_STATE.exists():
            original = json.loads(safe_target(DESK_STATE).read_text())
            assert original["owner"] == TASK and original["site"] == SITE
            assert original["after"] == before and frappe.is_setup_complete(), "Readiness changed; inspect instead of overwriting"
            return {**original, "idempotent_recheck": True}
        roles = {user: set(frappe.get_roles(user)) for user in (state["manager"], state["teacher"])}
        file_hashes = {path: digest_file(safe_target(path)) for path in (CREDENTIALS, STATE)}
        from frappe.desk.page.setup_wizard.setup_wizard import enable_setup_wizard_complete
        # Native is_setup_complete checks only these two installed-app flags.
        # The fixture already created its company/COA/warehouses. Do not invoke
        # setup_complete/disable_future_access, change users or send email.
        for app in ("frappe", "erpnext"):
            if not installed[app]:
                enable_setup_wizard_complete(app)
        assert frappe.is_setup_complete()
        if not before["system_setup_complete"]:
            frappe.db.set_single_value("System Settings", "setup_complete", 1)
        frappe.db.commit()
        frappe.clear_cache()
        after = {"installed": {row.app_name: int(row.is_setup_complete or 0) for row in
                 frappe.get_all("Installed Application", fields=["app_name", "is_setup_complete"])},
                 "system_setup_complete": int(frappe.db.get_single_value("System Settings", "setup_complete") or 0)}
        assert all(set(frappe.get_roles(user)) == original for user, original in roles.items())
        assert all(digest_file(path) == value for path, value in file_hashes.items())
        report = {"owner": TASK, "site": SITE, "before": before, "after": after,
            "native_setup_complete": frappe.is_setup_complete(), "full_wizard_run": False,
            "credentials_roles_and_business_fixture_unchanged": True, "production_writes": False}
        private_json(DESK_STATE, report)
        return report
    finally:
        frappe.db.rollback()
        frappe.destroy()


def desk_read_allowed(command, values, method):
    values = {key: value for key, value in values.items() if key not in {"cmd", "_", "csrf_token"}}
    if command == "frappe.translate.get_boot_translations":
        return (method in {"GET", "HEAD"} and set(values) <= {"lang", "v"}
                and all(isinstance(value, str) and len(value) <= 128 for value in values.values()))
    return method in {"GET", "HEAD", "POST"} and not values


def unique_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def native_blueprint_doc(value, fixture, *, read_only=False):
    """Only this new extension and its declared child table; no arbitrary flags."""
    doc = unique_json(value) if isinstance(value, str) else value
    if not isinstance(doc, dict) or doc.get("doctype") != fixture["doctype"]:
        return False
    standard = {"doctype", "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
                "__islocal", "__unsaved", "__last_sync_on", "__run_link_triggers", "__onload", "__unedited", "__checked"}
    ui_flags = ("__islocal", "__unsaved", "__run_link_triggers", "__unedited", "__checked")
    if any(doc.get(key) not in (None, False, True, 0, 1) for key in ui_flags):
        return False
    if set(doc) - standard - {"title", "estimated_total", "estimate_lines", "workflow_state", "amended_from"}:
        return False
    if read_only:
        # Native get_transitions reloads this exact type/name from DB before
        # checking read permission; just-saved browser rows may still carry the
        # old temporary parent ID. They are not a write request.
        if not isinstance(doc.get("name"), str) or not 1 <= len(doc["name"]) <= 140:
            return False
    else:
        if doc.get("docstatus", 0) not in (0, "0") or doc.get("workflow_state") not in (None, "", "扩展·草稿") or doc.get("amended_from"):
            return False
        if any(doc.get(key) not in (None, fixture["manager"]) for key in ("owner", "modified_by")):
            return False
    rows = doc.get("estimate_lines", [])
    if not isinstance(rows, list) or len(rows) > 500:
        return False
    for row in rows:
        if not isinstance(row, dict) or row.get("doctype") != fixture["children"]["estimate_lines"]:
            return False
        if set(row) - standard - {"parent", "parenttype", "parentfield", "item_label", "quantity", "unit_price", "line_amount"}:
            return False
        if any(row.get(key) not in (None, False, True, 0, 1) for key in ui_flags):
            return False
        if not read_only:
            if row.get("parenttype") not in (None, fixture["doctype"]) or row.get("parentfield") not in (None, "estimate_lines"):
                return False
            if row.get("parent") not in (None, doc.get("name")) or row.get("docstatus", 0) not in (0, "0"):
                return False
            if any(row.get(key) not in (None, fixture["manager"]) for key in ("owner", "modified_by")):
                return False
    return True


def blueprint_request_allowed(command, values, method):
    """Extra QA boundary; native session, CSRF and business checks still run."""
    try:
        fixture = blueprint_fixture()
        values = {key: value for key, value in values.items() if key not in {"cmd", "_", "csrf_token"}}
        if command == "tongjianyun.business_blueprints.activate":
            return (method == "POST" and set(values) == {"proposal_id", "revision"}
                    and values["proposal_id"] == fixture["proposal_id"] and values["revision"] == fixture["revision"])
        if command == "frappe.desk.form.save.savedocs":
            return (method == "POST" and set(values) == {"doc", "action"} and values["action"] == "Save"
                    and native_blueprint_doc(values["doc"], fixture))
        if method not in {"GET", "HEAD", "POST"}:
            return False
        if command == "frappe.desk.form.load.getdoctype":
            return (set(values) <= {"doctype", "with_parent", "cached_timestamp"}
                    and values.get("doctype") in {fixture["doctype"], *fixture["children"].values()})
        if command in {"frappe.desk.form.load.getdoc", "frappe.desk.form.load.get_docinfo"}:
            return (set(values) == {"doctype", "name"} and values["doctype"] == fixture["doctype"]
                    and isinstance(values["name"], str) and bool(values["name"]))
        if command == "frappe.model.workflow.get_transitions":
            return set(values) == {"doc"} and native_blueprint_doc(values["doc"], fixture, read_only=True)
        if command == "frappe.model.utils.user_settings.get":
            return set(values) == {"doctype"} and values["doctype"] == fixture["doctype"]
        if command == "frappe.model.utils.user_settings.save":
            settings = values.get("user_settings")
            settings = unique_json(settings) if isinstance(settings, str) else settings
            return (method == "POST" and set(values) == {"doctype", "user_settings"}
                    and values["doctype"] == fixture["doctype"] and isinstance(settings, dict))
    except (AssertionError, OSError, ValueError, KeyError, TypeError):
        return False
    return False


def enable_isolated_web():
    config_guard()
    path = safe_target(SITES / SITE / "site_config.json")
    config = json.loads(path.read_text())
    config.update(maintenance_mode=0, host_name=ORIGIN, unified_browser_acceptance=1,
                  developer_mode=0, pause_scheduler=1, disable_scheduler=1,
                  mute_emails=1, disable_email_queue=1)
    private_json(path, config)
    config_guard()


def reply(start_response, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode()
    start_response(status, [("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))), ("Cache-Control", "no-store"), ("X-Unified-Business-QA", "1")])
    return [body]


class QAFirewall:
    """A test-only WSGI request boundary, not a business authorization bypass."""
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        audit_context = {"method": environ.get("REQUEST_METHOD", "GET").upper(), "commands": [], "parameter_keys": []}
        conf = config_guard()  # Fail closed before Frappe connects for a request.
        assert conf.get("unified_browser_acceptance") == 1 and not conf.get("maintenance_mode")
        host = environ.get("HTTP_HOST", "")
        if host not in {f"{SITE}:{PORT}", f"127.0.0.1:{PORT}", f"localhost:{PORT}"}:
            return reply(start_response, "403 Forbidden", {"message": "QA host only"})
        if environ.get("HTTP_X_FRAPPE_SITE_NAME", SITE) != SITE:
            return reply(start_response, "403 Forbidden", {"message": "QA site is pinned"})
        path = unquote(unquote(environ.get("PATH_INFO", "")))
        method = environ.get("REQUEST_METHOD", "GET").upper()
        if path == "/__qa__/health" and method in {"GET", "HEAD"}:
            return reply(start_response, "200 OK", {"site": SITE, "port": PORT,
                "loopback_only": True, "codex_execution_blocked": True})
        query_values = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        if any(len(values) != 1 for values in query_values.values()):
            return self.block(start_response, audit_context)
        parameters = {key: values[0] for key, values in query_values.items()}
        commands = [parameters["cmd"]] if "cmd" in parameters else []
        rpc = None
        for prefix in ("/api/method/", "/api/v1/method/", "/api/v2/method/"):
            if path.startswith(prefix):
                rpc = path[len(prefix):].replace("/", ".")
                commands.append(rpc)
        # Frappe can parse JSON/form bodies even for GET. Inspect every declared
        # body before the framework sees it, not only conventional POST bodies.
        try:
            size = int(environ.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            return self.block(start_response, audit_context)
        if size < 0 or size > 1024 * 1024 or environ.get("HTTP_TRANSFER_ENCODING"):
            return self.block(start_response, audit_context)
        if method not in {"GET", "HEAD", "OPTIONS"} or size:
            content_type = environ.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
            native_empty_logout = (method == "POST" and size == 0 and not content_type
                                   and commands and all(command == "logout" for command in commands))
            if not native_empty_logout and content_type not in {"application/json", "application/x-www-form-urlencoded"}:
                return self.block(start_response, audit_context)
            body = environ["wsgi.input"].read(size)
            environ["wsgi.input"] = io.BytesIO(body)
            try:
                if native_empty_logout:
                    values = {}
                elif content_type == "application/json":
                    values = unique_json(body)
                else:
                    values = parse_qs(body.decode(), keep_blank_values=True)
                    if any(len(items) != 1 for items in values.values()):
                        return self.block(start_response, audit_context)
                    values = {key: items[0] for key, items in values.items()}
                if not isinstance(values, dict):
                    return self.block(start_response, audit_context)
                if any(key in parameters and parameters[key] != value for key, value in values.items()):
                    return self.block(start_response, audit_context)
                parameters.update(values)
                if "cmd" in values:
                    commands.append(values["cmd"])
            except (ValueError, UnicodeError):
                return self.block(start_response, audit_context)
        allowed = READ_METHODS if method in {"GET", "HEAD"} else WRITE_METHODS
        audit_context = {"method": method,
            "commands": [command if isinstance(command, str) and command in READ_METHODS | WRITE_METHODS | BLUEPRINT_METHODS | DESK_READ_METHODS else "unlisted-command" for command in commands],
            "parameter_keys": [key if key in AUDIT_PARAMETER_KEYS else "unlisted-key" for key in parameters],
            "unlisted_command_sha256": [hashlib.sha256(command.encode()).hexdigest() for command in commands
                if isinstance(command, str) and command not in READ_METHODS | WRITE_METHODS | BLUEPRINT_METHODS | DESK_READ_METHODS]}
        if commands:
            if any(not isinstance(command, str) for command in commands) or len(set(commands)) != 1:
                return self.block(start_response, audit_context)
            command = commands[0]
            if command in DESK_READ_METHODS:
                if not desk_read_allowed(command, parameters, method):
                    return self.block(start_response, audit_context)
            elif command in BLUEPRINT_METHODS:
                if not blueprint_request_allowed(command, parameters, method):
                    return self.block(start_response, audit_context)
            elif command not in allowed:
                return self.block(start_response, audit_context)
            if command == "logout" and (method != "POST" or set(parameters) - {"cmd", "_", "csrf_token"}):
                return self.block(start_response, audit_context)
            if command == "tongjianyun.scene_access.get_bootstrap":
                if set(parameters) - {"cmd", "_", "day", "meal", "group"}:
                    return self.block(start_response, audit_context)
                if ("day" in parameters and (not isinstance(parameters["day"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parameters["day"]))
                        or "meal" in parameters and parameters["meal"] not in {"breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner"}
                        or "group" in parameters and (not isinstance(parameters["group"], str) or not 1 <= len(parameters["group"]) <= 140)):
                    return self.block(start_response, audit_context)
            if command == "tongjianyun.meal_views.get_view":
                try:
                    selection = parameters.get("selection_json")
                    selection = unique_json(selection) if isinstance(selection, str) else selection
                    if isinstance(selection, dict) and selection.get("view") == "business_blueprint":
                        fixture = blueprint_fixture()
                        if selection.get("proposal_id") != fixture["proposal_id"]:
                            return self.block(start_response, audit_context)
                except (AssertionError, OSError, ValueError, KeyError, TypeError):
                    return self.block(start_response, audit_context)
        if path.startswith("/api/") and not rpc:
            # Generic resource and document-method routes remain outside this
            # scoped UI test, including after a blueprint fixture is prepared.
            return self.block(start_response, audit_context)
        if method not in {"GET", "HEAD", "OPTIONS"} and not commands:
            return self.block(start_response, audit_context)
        context = audit_context
        def audited_response(status, headers, exc_info=None):
            if context["commands"] and not set(context["commands"]) & {"login", "logout"}:
                print(json.dumps({"qa_rpc": context, "boundary": "native-application", "status": status}), flush=True)
            return start_response(status, headers, exc_info) if exc_info is not None else start_response(status, headers)
        return self.application(environ, audited_response)

    @staticmethod
    def block(start_response, audit_context):
        print(json.dumps({"qa_rpc": audit_context, "boundary": "qa-firewall", "status": "403 Forbidden"}), flush=True)
        return reply(start_response, "403 Forbidden", {"exc_type": "PermissionError",
            "message": "隔离验收已禁止智能体执行、上传及非本次验收接口；没有发送到 Codex。"})


def serve():
    conf = config_guard()
    assert conf.get("unified_browser_acceptance") == 1 and not conf.get("maintenance_mode")
    assert ASSETS.is_dir() and not ASSETS.is_symlink() and STATE.exists()
    verify_asset_evidence()
    frappe = runtime()
    import frappe.app
    from werkzeug.serving import WSGIRequestHandler, make_server

    class QuietHandler(WSGIRequestHandler):
        def log(self, kind, message, *args):
            # Never echo URLs, request parameters, cookies or credentials.
            pass

    frappe.app._site = SITE
    frappe.app._sites_path = str(SITES)
    app = frappe.app.application_with_statics()
    server = make_server("127.0.0.1", PORT, QAFirewall(app), threaded=False, request_handler=QuietHandler)
    state = {"owner": TASK, "pid": os.getpid(), "bind": "127.0.0.1", "port": PORT,
             "site": SITE, "running": True, "debugger": False, "reloader": False, "worker": False}
    private_json(SERVER_STATE, state)
    print(json.dumps(state), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        state["running"] = False
        private_json(SERVER_STATE, state)


def verify():
    conf = config_guard()
    state = json.loads(safe_target(STATE).read_text())
    assert state["owner"] == TASK
    assert CREDENTIALS.stat().st_mode & 0o777 == 0o600
    assert ASSETS.resolve() == ASSETS and not ASSETS.is_symlink()
    result = {**state, "assets_ready": json.loads(ASSET_MARKER.read_text())["state"] == "ready",
              "assets": verify_asset_evidence(), "maintenance_mode": conf.get("maintenance_mode"),
              "http_ready": False, "http_assets_match": False}
    try:
        with urlopen(f"http://127.0.0.1:{PORT}/__qa__/health", timeout=3) as response:
            health = json.load(response)
        assert health["site"] == SITE and health["codex_execution_blocked"]
        result["http_ready"] = True
        for path, expected in result["assets"]["critical_sha256"].items():
            with urlopen(f"http://127.0.0.1:{PORT}/assets/tongjianyun/{path}", timeout=3) as response:
                body = response.read(10 * 1024 * 1024 + 1)
            assert len(body) <= 10 * 1024 * 1024 and hashlib.sha256(body).hexdigest() == expected
        result["http_assets_match"] = True
    except OSError:
        pass
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "refresh-assets", "seed-blueprint", "inspect-desk", "prepare-desk", "serve", "verify"))
    args = parser.parse_args()
    if args.command == "prepare":
        evidence = copy_public_assets()
        state = prepare_fixture()
        enable_isolated_web()
        desk = prepare_desk()
        print(json.dumps({**state, "assets": evidence, "desk": desk, "http_started": False}, ensure_ascii=False), flush=True)
    elif args.command == "refresh-assets":
        print(json.dumps(refresh_assets(), ensure_ascii=False), flush=True)
    elif args.command == "seed-blueprint":
        print(json.dumps(seed_blueprint(), ensure_ascii=False), flush=True)
    elif args.command == "inspect-desk":
        print(json.dumps(inspect_desk(), ensure_ascii=False), flush=True)
    elif args.command == "prepare-desk":
        print(json.dumps(prepare_desk(), ensure_ascii=False), flush=True)
    elif args.command == "serve":
        serve()
    else:
        verify()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Do not forward arbitrary exception messages that might contain secrets.
        print(json.dumps({"failed": type(exc).__name__, "detail": "QA browser setup stopped; inspect guarded environment locally"}), flush=True)
        raise SystemExit(1) from None
