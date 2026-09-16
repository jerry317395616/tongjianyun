"""Windows/Linux unattended recorder and resumable HTTPS uploader (stdlib only).

No AI, teacher names or face templates on the collection computer. FFmpeg must
already be installed. Never print configuration, camera URLs or API responses.
"""
import argparse
import base64
import csv
import hashlib
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
import urllib.request
import urllib.parse
import uuid

CHUNK = 256 * 1024
STOP = threading.Event()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("unexpected_redirect")


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    endpoint = urllib.parse.urlsplit(config["server"])
    camera = urllib.parse.urlsplit(config["rtsp_url"])
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.query or endpoint.fragment or endpoint.path not in ("", "/"):
        raise ValueError("Server must be an HTTPS origin")
    if camera.scheme != "rtsp" or not camera.hostname or not ipaddress.ip_address(camera.hostname).is_private:
        raise ValueError("Camera must use its literal LAN/VPN address")
    if not config.get("api_key") or not config.get("api_secret"):
        raise ValueError("Device credentials required")
    if not shutil.which(config["ffmpeg"]):
        raise ValueError("FFmpeg not found")
    probe = str(Path(config["ffmpeg"]).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    if not shutil.which(probe):
        raise ValueError("FFprobe must be installed beside FFmpeg")
    for key in ("api_key", "api_secret", "camera_id"):
        if any(c in config[key] for c in "\r\n"):
            raise ValueError("Invalid configuration")
    config["server"] = config["server"].rstrip("/")
    config["spool"] = str(Path(config["spool"]).resolve())
    config["segment_seconds"] = max(10, min(int(config.get("segment_seconds", 60)), 120))
    config["upload_interval"] = max(10, min(int(config.get("upload_interval", 60)), 300))
    config["max_spool_gb"] = max(1, min(int(config.get("max_spool_gb", 20)), 1000))
    return config


def call(config, method, payload):
    request = urllib.request.Request(config["server"] + "/api/method/tongjianyun.video_attendance.api." + method,
        data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json",
        "Authorization": "token " + config["api_key"] + ":" + config["api_secret"]})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=45) as response:
        body = response.read(2 * 1024**2)
    result = json.loads(body)
    if "message" not in result:
        raise RuntimeError("invalid_server_response")
    return result["message"]


def connect(spool):
    db = sqlite3.connect(str(Path(spool) / "queue.sqlite"), timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS clips (id TEXT PRIMARY KEY, path TEXT NOT NULL, manifest TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL)")
    if "last_attempt" not in {row[1] for row in db.execute("PRAGMA table_info(clips)")}:
        db.execute("ALTER TABLE clips ADD COLUMN last_attempt REAL NOT NULL DEFAULT 0")
    db.commit()
    return db


def manifest_for(config, path, start, end, clock_ok):
    # -copyts + wallclock input must retain epoch timestamps in segment CSV.
    # Never substitute upload time or guess time from filenames.
    if start == 0 and end > 1600000000:
        # FFmpeg's first segment CSV starts at zero even with -copyts. Recover
        # the original packet timeline from the closed MP4, never from wall time.
        binary = str(Path(config["ffmpeg"]).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
        probe = subprocess.run([binary, "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "v:0",
            "-show_entries", "stream=start_time", "-of", "json", str(path)], capture_output=True, text=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if probe.returncode:
            raise ValueError("stream_wallclock_unavailable")
        start = float(json.loads(probe.stdout)["streams"][0]["start_time"])
    if not 1600000000 < start < end or end - start > 180:
        raise ValueError("stream_wallclock_unavailable")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"camera_id": config["camera_id"], "clip_id": path.stem.replace("-", "_"),
        "sha256": digest, "size": path.stat().st_size,
        "started_at": datetime.fromtimestamp(start, timezone.utc).isoformat(),
        "ended_at": datetime.fromtimestamp(end, timezone.utc).isoformat(), "clock_verified": bool(clock_ok)}


def discover(config, db):
    for session in Path(config["spool"]).glob("session-*.json"):
        meta = json.loads(session.read_text(encoding="utf-8"))
        csv_path = session.with_suffix(".csv")
        if not csv_path.exists():
            continue
        with csv_path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.reader(stream))
        for row in rows:
            if len(row) != 3:
                continue
            # Ignore incomplete lines and any path escaping the dedicated spool.
            path = (Path(config["spool"]) / Path(row[0]).name).resolve()
            if path.parent != Path(config["spool"]).resolve() or not path.exists():
                continue
            if db.execute("SELECT 1 FROM clips WHERE id=?", (path.stem,)).fetchone():
                continue
            try:
                manifest = manifest_for(config, path, float(row[1]), float(row[2]), meta["clock_ok"])
            except (ValueError, OSError):
                logging.warning("片段时间不可验证或未完整，保留本地待处理")
                continue
            db.execute("INSERT OR IGNORE INTO clips(id,path,manifest,created) VALUES(?,?,?,?)",
                       (path.stem, str(path), json.dumps(manifest), time.time()))
        db.commit()


def upload(config, path, manifest):
    receipt = call(config, "begin_upload", {"manifest": manifest})
    if receipt.get("sealed"):
        if receipt.get("sha256") != manifest["sha256"]:
            raise RuntimeError("receipt_mismatch")
        return
    offset = int(receipt["offset"])
    with path.open("rb") as stream:
        retries = 0
        while offset < manifest["size"]:
            if not 0 <= offset <= manifest["size"]:
                raise RuntimeError("invalid_server_offset")
            stream.seek(offset)
            chunk = stream.read(CHUNK)
            response = call(config, "upload_chunk", {"batch": receipt["batch"], "offset": offset,
                                                    "data": base64.b64encode(chunk).decode()})
            next_offset = int(response["offset"])
            retries = retries + 1 if next_offset <= offset else 0
            if retries > 3:
                raise RuntimeError("upload_not_progressing")
            offset = next_offset
    done = call(config, "seal_upload", {"batch": receipt["batch"]})
    if not done.get("sealed") or done.get("sha256") != manifest["sha256"]:
        raise RuntimeError("receipt_mismatch")


def in_schedule(config, now=None):
    # Installation UI must confirm local Windows time zone. This is a collection
    # schedule, not a rule for calculating employee attendance.
    now = now or datetime.now()
    if now.weekday() not in config.get("weekdays", [0, 1, 2, 3, 4]):
        return False
    minute = now.strftime("%H:%M")
    return any(start <= minute < end for start, end in config.get("recording_windows", [["06:30", "19:30"]]))


def recorder_command(config, session):
    return [config["ffmpeg"], "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
        "-rw_timeout", "15000000", "-use_wallclock_as_timestamps", "1", "-copyts", "-i", config["rtsp_url"],
        "-map", "0:v:0", "-an", "-c:v", "copy", "-f", "segment", "-segment_time", str(config["segment_seconds"]), "-segment_atclocktime", "1",
        "-segment_list", str(session.with_suffix(".csv")), "-segment_list_type", "csv", "-reset_timestamps", "1",
        "-segment_format", "mp4", "-segment_format_options", "movflags=+faststart", "-avoid_negative_ts", "disabled",
        str(session.parent / (session.stem + "-%06d.mp4"))]


def stop_recorder(process):
    if not process or process.poll() is not None:
        return
    try:
        process.stdin.write(b"q\n")
        process.stdin.flush()
        process.wait(timeout=20)
    except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    # Only finalized CSV-listed segments are eligible; interrupted tail stays local.


def uploader(config, state):
    db = connect(config["spool"])
    while not STOP.is_set():
        try:
            discover(config, db)
            pending = db.execute("SELECT COUNT(*) FROM clips WHERE acknowledged=0").fetchone()[0]
            begin = time.time()
            health = call(config, "heartbeat", {"camera_id": config["camera_id"], "health": "upload_error" if state.get("upload_failed") else state["health"],
                "pending": pending, "disk_free_mb": shutil.disk_usage(config["spool"]).free // 1024**2})
            finish = time.time()
            server = datetime.fromisoformat(health["server_time"]).timestamp()
            clock_ok = finish - begin < 10 and abs(server - (begin + finish) / 2) < 5
            state.update(clock_ok=clock_ok, last_contact=finish)
            if not clock_ok:
                state["health"] = "clock_error"
            failed = False
            for clip_id, filename, payload in db.execute("SELECT id,path,manifest FROM clips WHERE acknowledged=0 ORDER BY last_attempt,created LIMIT 10").fetchall():
                manifest = json.loads(payload)
                db.execute("UPDATE clips SET last_attempt=? WHERE id=?", (time.time(), clip_id))
                db.commit()
                if not manifest["clock_verified"]:
                    failed = True
                    continue
                try:
                    upload(config, Path(filename), manifest)
                    db.execute("UPDATE clips SET acknowledged=1 WHERE id=?", (clip_id,))
                    db.commit()
                except Exception:
                    # One expired/corrupt clip must not block all later arrivals.
                    failed = True
                    logging.warning("一个片段待重试或人工处理，继续处理其他片段；未删除原片段")
            state["upload_failed"] = failed
            # Receipt must match before local deletion. Short fixed cache; disk-full
            # never deletes unacknowledged videos behind the operator's back.
            cutoff = time.time() - 86400
            for clip_id, filename in db.execute("SELECT id,path FROM clips WHERE acknowledged=1 AND created<?", (cutoff,)).fetchall():
                Path(filename).unlink(missing_ok=True)
            status = {"health": state["health"], "pending": pending, "clock_ok": clock_ok,
                      "last_contact": datetime.now(timezone.utc).isoformat()}
            temp = Path(config["spool"]) / "status.tmp"
            temp.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
            temp.replace(Path(config["spool"]) / "status.json")
        except Exception:
            state["health"] = "upload_error"
            state["upload_failed"] = True
            logging.warning("上传或心跳失败，将自动重试；凭据与接口响应不写入日志")
        STOP.wait(config["upload_interval"])
    db.close()


def run(config):
    spool = Path(config["spool"])
    spool.mkdir(parents=True, exist_ok=True)
    # Single instance lock across Task Scheduler/manual starts; released on crash.
    lock = (spool / "collector.lock").open("a+b")
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    handler = RotatingFileHandler(spool / "collector.log", maxBytes=512000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(message)s")
    state = {"health": "camera_offline", "clock_ok": False, "last_contact": 0}
    worker = threading.Thread(target=uploader, args=(config, state), daemon=True)
    worker.start()
    process = None
    try:
        while not STOP.wait(5):
            used = sum(p.stat().st_size for p in spool.glob("*.mp4"))
            enough = used < config["max_spool_gb"] * 1024**3 and shutil.disk_usage(spool).free > 1024**3
            if not in_schedule(config) or not enough:
                stop_recorder(process)
                process = None
                state["health"] = "outside_schedule" if enough else "disk_full"
                continue
            if process and process.poll() is None:
                # Keep recording during WAN outage if clock was checked before start.
                state["health"] = "recording"
                continue
            if not state["clock_ok"] or time.time() - state["last_contact"] > 300:
                state["health"] = "clock_error"
                continue
            session = spool / ("session-" + uuid.uuid4().hex + ".json")
            session.write_text(json.dumps({"clock_ok": True, "created": time.time()}), encoding="utf-8")
            # FFmpeg may log credentials in errors: deliberately suppress its output.
            # OS administrators can inspect argv; restrict access to this machine.
            process = subprocess.Popen(recorder_command(config, session), stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            state["health"] = "recording"
    finally:
        STOP.set()
        stop_recorder(process)
        worker.join(timeout=50)
        lock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
        if args.check:
            print("Configuration valid; secrets omitted. Network/camera not tested.")
        else:
            run(cfg)
    except KeyboardInterrupt:
        STOP.set()
    except Exception:
        print("Collector stopped. Check configuration, disk permissions and private logs; no credentials displayed.", file=__import__("sys").stderr)
        raise SystemExit(1)
