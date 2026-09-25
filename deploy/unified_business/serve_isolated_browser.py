"""Loopback-only browser QA harness; never serve or modify a production site.

prepare copies public assets and provisions synthetic browser credentials.
refresh-assets updates only public files and version evidence, never credentials
or database fixtures. serve pins the isolated site and blocks every non-allowlisted RPC (including
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
APPS = ("frappe", "erpnext", "education", "tongjianyun")
CRITICAL_ASSETS = ("meal_scene/views.js", "meal_scene/views.css", "meal_scene/chat.js",
                   "meal_scene/app.js", "meal_scene/state.js")
REQUIRED_RENDERERS = ("attendance_register:renderAttendance", "meal_register:renderMealRegister",
                      "business_blueprint:renderBlueprint", "stock_repair:renderStockRepair")

# This test surface deliberately does not run the host's privileged agent.
# Deny-by-default also covers alternative /api/v2/method and form cmd aliases.
READ_METHODS = {
    "frappe.auth.get_logged_user", "frappe.client.get", "frappe.client.get_list",
    "tongjianyun.meal_chat.get_chat_access", "tongjianyun.meal_chat.get_conversation",
    "tongjianyun.meal_views.get_view", "tongjianyun.meal_scene.get_overview",
    "tongjianyun.meal_scene.get_recipe", "tongjianyun.classroom.get_overview",
    "tongjianyun.classroom.get_meals", "tongjianyun.classroom.get_health",
}
WRITE_METHODS = {
    "login", "logout", "tongjianyun.classroom.save_attendance",
    "tongjianyun.classroom.save_meal", "tongjianyun.classroom.save_meals",
}


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
    preserved = (STATE, CREDENTIALS, SITES / SITE / "site_config.json", SITES / "common_site_config.json")
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
        commands = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True).get("cmd", [])
        rpc = None
        for prefix in ("/api/method/", "/api/v2/method/"):
            if path.startswith(prefix):
                rpc = path[len(prefix):].replace("/", ".")
                commands.append(rpc)
        # Frappe can parse JSON/form bodies even for GET. Inspect every declared
        # body before the framework sees it, not only conventional POST bodies.
        try:
            size = int(environ.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            return self.block(start_response)
        if size < 0 or size > 1024 * 1024 or environ.get("HTTP_TRANSFER_ENCODING"):
            return self.block(start_response)
        if method not in {"GET", "HEAD", "OPTIONS"} or size:
            content_type = environ.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
            if content_type not in {"application/json", "application/x-www-form-urlencoded"}:
                return self.block(start_response)
            body = environ["wsgi.input"].read(size)
            environ["wsgi.input"] = io.BytesIO(body)
            try:
                values = json.loads(body) if content_type == "application/json" else parse_qs(body.decode())
                if not isinstance(values, dict):
                    return self.block(start_response)
                if "cmd" in values:
                    cmd = values["cmd"]
                    commands.extend(cmd if isinstance(cmd, list) else [cmd])
            except (ValueError, UnicodeError):
                return self.block(start_response)
        allowed = READ_METHODS if method in {"GET", "HEAD"} else WRITE_METHODS
        if commands and any(not isinstance(command, str) or command not in allowed for command in commands):
            return self.block(start_response)
        if path.startswith("/api/") and not rpc:
            # Resource writes/native method invocations are outside this limited
            # attendance/meal UI test. Never expose a generic privileged RPC.
            return self.block(start_response)
        if method not in {"GET", "HEAD", "OPTIONS"} and not commands:
            return self.block(start_response)
        return self.application(environ, start_response)

    @staticmethod
    def block(start_response):
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
    parser.add_argument("command", choices=("prepare", "refresh-assets", "serve", "verify"))
    args = parser.parse_args()
    if args.command == "prepare":
        evidence = copy_public_assets()
        state = prepare_fixture()
        enable_isolated_web()
        print(json.dumps({**state, "assets": evidence, "http_started": False}, ensure_ascii=False), flush=True)
    elif args.command == "refresh-assets":
        print(json.dumps(refresh_assets(), ensure_ascii=False), flush=True)
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
