"""Provision a disposable, private Frappe lifecycle-test site on the QA server.

Run with the existing native-bench Python runtime. This script does not load any
production site config, copy a database, start a web server, or modify app source.
It intentionally retains evidence and data on failure. Repeated successful runs
validate and reuse the same, explicitly labelled test resources.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

SOURCE_BENCH = Path("/home/zyd/frappe/native-bench")
WORKSPACE = Path("/home/zyd/frappe/remote-workspace")
TASK = "tgy-blueprint-lifecycle-qa-20260925"
ROOT = WORKSPACE / TASK
SITES = ROOT / "sites"
SITE = "unified-business-acceptance.localhost"
DB_PORT = 23316
REDIS_PORT = 23379
DB_NAME = "tgy_blueprint_qa"
DB_CONTAINER = TASK + "-db"
REDIS_CONTAINER = TASK + "-redis"
APPS = ("frappe", "erpnext", "education", "tongjianyun")
MARKER = "codex.isolation.owner"
SECRETS_FILE = ROOT / "test-secrets.json"


def write_private_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def command(*args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if check and result.returncode:
        # Avoid forwarding generic Docker diagnostics which can contain env data.
        raise RuntimeError(f"Command failed ({result.returncode}): {args[0:2]}")
    return result


def validate_root():
    if WORKSPACE.resolve() != WORKSPACE or ROOT.resolve().parent != WORKSPACE:
        raise RuntimeError("Workspace path does not match the explicit QA scope")
    if ROOT.is_symlink() or SITES.is_symlink():
        raise RuntimeError("QA root/sites may not be symlinks")
    if str(SOURCE_BENCH) in str(ROOT):
        raise RuntimeError("QA scope overlaps production bench")
    existing = ROOT.exists()
    if existing:
        marker = ROOT / "isolation-marker.json"
        if not marker.exists() or json.loads(marker.read_text())["owner"] != TASK:
            raise RuntimeError("Existing QA path is not owned by this script")
    else:
        ROOT.mkdir(mode=0o700)
        write_private_json(ROOT / "isolation-marker.json", {"owner": TASK, "purpose": "synthetic lifecycle tests"})
    return existing


def inspect_container(name):
    result = command("docker", "inspect", name, check=False)
    if result.returncode:
        return None
    value = json.loads(result.stdout)[0]
    if value.get("Config", {}).get("Labels", {}).get(MARKER) != TASK:
        raise RuntimeError(f"Container name collision: {name}")
    for target, bindings in (value.get("HostConfig", {}).get("PortBindings") or {}).items():
        for binding in bindings:
            if binding["HostIp"] != "127.0.0.1":
                raise RuntimeError(f"Non-loopback port binding on QA container: {name}")
    return value


def assert_port_free(port):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def ensure_containers(secret):
    db = inspect_container(DB_CONTAINER)
    redis = inspect_container(REDIS_CONTAINER)
    if db is None:
        assert_port_free(DB_PORT)
        (ROOT / "dbdata").mkdir(mode=0o700, exist_ok=True)
        env_file = ROOT / "database.env"
        env_file.write_text("MARIADB_ROOT_PASSWORD=" + secret["db_root"] + "\nMARIADB_ROOT_HOST=%\n", encoding="utf-8")
        env_file.chmod(0o600)
        command("docker", "run", "-d", "--name", DB_CONTAINER,
                "--label", MARKER + "=" + TASK, "--memory", "2g", "--cpus", "2",
                "--publish", f"127.0.0.1:{DB_PORT}:3306", "--env-file", str(env_file),
                "--mount", f"type=bind,src={ROOT / 'dbdata'},dst=/var/lib/mysql",
                "mariadb:11.8", "--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci",
                "--skip-name-resolve", "--innodb-buffer-pool-size=256M")
    elif not db["State"]["Running"]:
        command("docker", "start", DB_CONTAINER)
    if redis is None:
        assert_port_free(REDIS_PORT)
        conf = ROOT / "redis.conf"
        conf.write_text("bind 0.0.0.0\nprotected-mode yes\nport 6379\nsave \"\"\nappendonly no\n"
                        "maxmemory 192mb\nmaxmemory-policy allkeys-lru\nrequirepass " + secret["redis"] + "\n",
                        encoding="utf-8")
        # Parent directory is 0700; readable in this one read-only file mount.
        conf.chmod(0o644)
        command("docker", "run", "-d", "--name", REDIS_CONTAINER,
                "--label", MARKER + "=" + TASK, "--memory", "256m", "--cpus", "1",
                "--publish", f"127.0.0.1:{REDIS_PORT}:6379",
                "--mount", f"type=bind,src={conf},dst=/usr/local/etc/redis/redis.conf,readonly",
                "redis:7-alpine", "redis-server", "/usr/local/etc/redis/redis.conf")
    elif not redis["State"]["Running"]:
        command("docker", "start", REDIS_CONTAINER)
    inspect_container(DB_CONTAINER)
    inspect_container(REDIS_CONTAINER)
    import pymysql
    import redis as redis_library
    for attempt in range(60):
        try:
            connection = pymysql.connect(host="127.0.0.1", port=DB_PORT, user="root", password=secret["db_root"], connect_timeout=2)
            connection.close()
            redis_library.Redis(host="127.0.0.1", port=REDIS_PORT, password=secret["redis"], socket_connect_timeout=2).ping()
            return
        except (pymysql.MySQLError, redis_library.RedisError, OSError):
            if attempt == 59:
                raise RuntimeError("Isolated database/cache did not become ready; retained for inspection") from None
            time.sleep(1)


def prepare_files(secret):
    for directory in (SITES, ROOT / "logs", ROOT / "config", ROOT / "apps"):
        directory.mkdir(mode=0o700, exist_ok=True)
    apps_file = SITES / "apps.txt"
    expected = "\n".join(APPS) + "\n"
    if apps_file.exists() and apps_file.read_text() != expected:
        raise RuntimeError("QA apps.txt differs; refusing overwrite")
    apps_file.write_text(expected, encoding="utf-8")
    redis_url = f"redis://:{secret['redis']}@127.0.0.1:{REDIS_PORT}"
    config = {
        "db_type": "mariadb", "db_host": "127.0.0.1", "db_port": DB_PORT,
        "redis_cache": redis_url + "/0", "redis_queue": redis_url + "/1", "redis_socketio": redis_url + "/2",
        "developer_mode": 0, "pause_scheduler": 1, "disable_scheduler": 1,
        "mute_emails": 1, "disable_email_queue": 1, "host_name": "http://" + SITE,
        "maintenance_mode": 1, "bench_id": TASK, "allow_tests": True,
    }
    common = SITES / "common_site_config.json"
    if common.exists() and json.loads(common.read_text()) != config:
        raise RuntimeError("QA common config differs; refusing overwrite")
    write_private_json(common, config)
    # Read-only source use. developer_mode stays disabled so custom DocTypes are not exported.
    for app in APPS:
        link = ROOT / "apps" / app
        source = SOURCE_BENCH / "apps" / app
        if not source.is_dir():
            raise RuntimeError(f"Required runtime app missing: {app}")
        if link.exists() and link.resolve() != source.resolve():
            raise RuntimeError(f"Unexpected app link: {app}")
        if not link.exists():
            link.symlink_to(source, target_is_directory=True)


def isolated_environment():
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("FRAPPE_"):
            del env[key]
    env["FRAPPE_BENCH_ROOT"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def install_site():
    validate_root()
    if Path.cwd().resolve() != SITES:
        raise RuntimeError("Install must run from the isolated sites directory")
    if os.environ.get("FRAPPE_BENCH_ROOT") != str(ROOT):
        raise RuntimeError("FRAPPE_BENCH_ROOT is not isolated")
    secret = json.loads(SECRETS_FILE.read_text())
    import frappe
    import frappe.database
    from frappe.installer import _new_site, install_app, update_site_config

    original_get_db = frappe.database.get_db
    def isolated_db_only(*args, **kwargs):
        if args or kwargs.get("socket") or kwargs.get("host") != "127.0.0.1" or int(kwargs.get("port") or 0) != DB_PORT:
            raise RuntimeError("Blocked connection outside the isolated test database")
        return original_get_db(*args, **kwargs)
    frappe.database.get_db = isolated_db_only

    config_exists = (SITES / SITE / "site_config.json").exists()
    if config_exists:
        frappe.init(SITE, sites_path=str(SITES))
        frappe.connect()
        if "frappe" not in frappe.get_installed_apps():
            raise RuntimeError("Partial bootstrap requires inspection; no database is dropped automatically")
    else:
        frappe.init(SITE, sites_path=str(SITES), new_site=True)
        _new_site(db_name=DB_NAME, site=SITE, db_root_username="root", db_root_password=secret["db_root"],
                  admin_password=secret["admin"], db_password=secret["db_user"], db_type="mariadb",
                  db_host="127.0.0.1", db_port=DB_PORT, db_user=DB_NAME,
                  mariadb_user_host_login_scope="%", install_apps=[], verbose=False)
    update_site_config("unified_business_acceptance", 1)
    frappe.set_user("Administrator")
    frappe.flags.mute_emails = True
    # Dependency order uses standard Frappe install hooks and schema lifecycle.
    for app in ("erpnext", "education", "tongjianyun"):
        install_app(app, verbose=False)
    frappe.db.set_single_value("System Settings", "enable_scheduler", 0)
    frappe.db.commit()
    report = {
        "ready": True, "site": SITE, "sites_path": str(SITES), "bench_root": str(ROOT),
        "db_host": "127.0.0.1", "db_port": DB_PORT, "db_name": DB_NAME, "redis_port": REDIS_PORT,
        "installed_apps": frappe.get_installed_apps(), "doctype_count": frappe.db.count("DocType"),
        "student_doctype": bool(frappe.db.exists("DocType", "Student")),
        "recipe_doctype": bool(frappe.db.exists("DocType", "Tongjianyun Recipe")),
        "production_data_copied": False, "web_server_started": False, "scheduler_enabled": False,
    }
    write_private_json(ROOT / "ready.json", report)
    frappe.destroy()
    print(json.dumps(report), flush=True)


def status():
    validate_root()
    info = json.loads((ROOT / "ready.json").read_text()) if (ROOT / "ready.json").exists() else {"ready": False}
    info["db_running"] = bool((inspect_container(DB_CONTAINER) or {}).get("State", {}).get("Running"))
    info["redis_running"] = bool((inspect_container(REDIS_CONTAINER) or {}).get("State", {}).get("Running"))
    print(json.dumps(info, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-child", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.install_child:
        install_site()
        return
    if args.status:
        status()
        return
    os.umask(0o077)
    validate_root()
    if SECRETS_FILE.exists():
        secret = json.loads(SECRETS_FILE.read_text())
    else:
        secret = {key: secrets.token_urlsafe(30) for key in ("db_root", "db_user", "redis", "admin")}
        write_private_json(SECRETS_FILE, secret)
    prepare_files(secret)
    ensure_containers(secret)
    print("Private QA database and cache ready; installing dependency schemas.", flush=True)
    log_path = ROOT / "install.log"
    with log_path.open("a", encoding="utf-8") as log:
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--install-child"],
                                   cwd=SITES, env=isolated_environment(), stdout=log, stderr=log)
    if completed.returncode:
        print(json.dumps({"ready": False, "exit_code": completed.returncode, "log": str(log_path),
                          "retained_root": str(ROOT), "production_site_untouched": True}), flush=True)
        raise SystemExit(completed.returncode)
    status()


if __name__ == "__main__":
    main()
