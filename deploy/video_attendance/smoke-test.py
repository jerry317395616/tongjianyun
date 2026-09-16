"""Explicit deployment smoke test: temporary uploader + synthetic (no-person) video.

Run with bench's Python, from bench root. Removes only its own namespaced test
records/files. Never enrolls an Employee or creates a teacher attendance record.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

import frappe
import requests

frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
frappe.connect()
frappe.set_user("Administrator")
from tongjianyun.video_attendance.setup import BATCH, DEVICE, EVENT, PROFILE
from tongjianyun.video_attendance.api import video_path
from tongjianyun.video_attendance.jobs import run_engine

stamp = secrets.token_hex(6)
user_name = "video-qa-" + stamp + "@example.invalid"
camera = "video-qa-" + stamp
created_batches = []
results = []
before = {d: frappe.db.count(d) for d in ("Employee Checkin", "Attendance", PROFILE)}
api_key, api_secret = secrets.token_hex(16), secrets.token_hex(24)
BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:17800"
if BASE_URL not in ("http://127.0.0.1:17800", "https://child.myyr.top"):
    raise ValueError("Smoke tests only target the configured site")


def call(method, args=None, authenticated=True):
    headers = {"Host": "child.myyr.top"}
    if authenticated:
        headers["Authorization"] = "token " + api_key + ":" + api_secret
    response = requests.post(BASE_URL + "/api/method/tongjianyun.video_attendance.api." + method,
                             json=args or {}, headers=headers, timeout=60)
    return response


def ok(name, condition):
    if not condition:
        raise AssertionError(name)
    results.append(name)


try:
    frappe.get_doc({"doctype": "User", "email": user_name, "first_name": "Synthetic Video QA",
                   "enabled": 1, "send_welcome_email": 0, "api_key": api_key, "api_secret": api_secret,
                   "user_type": "System User"}).insert(ignore_permissions=True)
    frappe.get_doc({"doctype": DEVICE, "camera_id": camera, "title": "合成视频临时测试设备",
                   "enabled": 1, "upload_user": user_name, "direction": "IN", "consent_scope_confirmed": 1}).insert(ignore_permissions=True)
    frappe.db.commit()
    ok("guest_denied", call("heartbeat", {"camera_id": camera}, False).status_code in (401, 403))
    r = call("heartbeat", {"camera_id": camera})
    ok("authenticated_heartbeat", r.status_code == 200 and "server_time" in r.json()["message"])
    ok("uploader_cannot_read_dashboard", call("overview").status_code in (401, 403))
    with tempfile.TemporaryDirectory(prefix="tjy-video-qa-") as directory:
        path = Path(directory) / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=10",
                        "-t", "4", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, timeout=30)
        raw = path.read_bytes()
        now = datetime.now(timezone.utc)
        value = {"camera_id": camera, "clip_id": "qa-" + stamp, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
                 "started_at": (now - timedelta(seconds=10)).isoformat(), "ended_at": (now - timedelta(seconds=6)).isoformat(), "clock_verified": True}
        r = call("begin_upload", {"manifest": value})
        ok("begin_upload", r.status_code == 200)
        name = r.json()["message"]["batch"]
        created_batches.append(name)
        half = len(raw) // 2
        r = call("upload_chunk", {"batch": name, "offset": 0, "data": base64.b64encode(raw[:half]).decode()})
        ok("first_chunk", r.status_code == 200 and r.json()["message"]["offset"] == half)
        r = call("begin_upload", {"manifest": value})
        ok("resume_offset", r.status_code == 200 and r.json()["message"]["offset"] == half)
        r = call("upload_chunk", {"batch": name, "offset": 0, "data": base64.b64encode(raw[:half]).decode()})
        ok("duplicate_chunk_not_appended", r.status_code == 200 and r.json()["message"]["offset"] == half)
        r = call("upload_chunk", {"batch": name, "offset": half, "data": base64.b64encode(raw[half:]).decode()})
        ok("second_chunk", r.status_code == 200 and r.json()["message"]["offset"] == len(raw))
        r = call("seal_upload", {"batch": name})
        ok("sha256_seal", r.status_code == 200 and r.json()["message"]["sha256"] == value["sha256"])
        ok("receipt_idempotent", call("begin_upload", {"manifest": value}).json()["message"]["sealed"])
        ok("manifest_conflict_denied", call("begin_upload", {"manifest": value | {"sha256": "0" * 64}}).status_code != 200)
        ok("uploader_video_download_denied", call("download_video", {"batch": name}).status_code in (401, 403))
        model_dir = Path(frappe.conf["tongjianyun_video_attendance"]["models_dir"])
        hashes = [hashlib.sha256((model_dir / file).read_bytes()).hexdigest()[:12] for file in
                  ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx")]
        version = "yunet-sface:" + ":".join(hashes)
        result = run_engine({"mode": "video", "input": str(path), "gallery": [{"employee": "SYNTHETIC-NOT-A-PERSON",
                            "feature": [1.0] + [0.0] * 127, "model_version": version}]})
        ok("real_decoder_and_models_no_false_face", result["candidates"] == [] and result["liveness_verified"] is False)
        # Verify FFmpeg wallclock segment timestamps using a synthetic source,
        # same muxer options as the installed collector (no camera credentials).
        csv_path = Path(directory) / "segments.csv"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-use_wallclock_as_timestamps", "1", "-copyts",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10", "-frames:v", "40", "-an", "-c:v", "libx264", "-fps_mode", "passthrough",
            "-g", "10", "-f", "segment", "-segment_time", "2", "-segment_list", str(csv_path), "-segment_list_type", "csv",
            "-reset_timestamps", "1", "-segment_format", "mp4", "-avoid_negative_ts", "disabled", str(Path(directory) / "segment-%03d.mp4")],
            check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import csv
        rows = list(csv.reader(csv_path.read_text().splitlines()))
        spec = importlib.util.spec_from_file_location("qa_collector", Path(__file__).with_name("collector.py"))
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        first = rows[0]
        parsed = collector.manifest_for({"camera_id": camera, "ffmpeg": "/usr/bin/ffmpeg"}, Path(directory) / first[0], float(first[1]), float(first[2]), True)
        ok("ffmpeg_absolute_capture_timestamps", datetime.fromisoformat(parsed["started_at"]).timestamp() > 1600000000)
    # Wait briefly for the real background worker; all input is synthetic.
    for _ in range(10):
        frappe.db.rollback()
        status = frappe.db.get_value(BATCH, name, "status")
        if status not in ("Queued", "Processing"):
            break
        time.sleep(1)
    ok("worker_processed_queue", status in ("Needs Setup", "No Match"))
    frappe.db.rollback()
    ok("no_employee_attendance_or_profile_created", before == {d: frappe.db.count(d) for d in before})
    print(json.dumps({"passed": len(results), "checks": results, "queue_status": status, "business_writes": 0}, ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.set_user("Administrator")
    for name in created_batches:
        for partial in (True, False):
            video_path(name, partial).unlink(missing_ok=True)
        for event in frappe.get_all(EVENT, filters={"batch": name}, pluck="name"):
            frappe.delete_doc(EVENT, event, ignore_permissions=True, force=True)
        frappe.delete_doc(BATCH, name, ignore_permissions=True, force=True)
    if frappe.db.exists(DEVICE, camera):
        frappe.delete_doc(DEVICE, camera, ignore_permissions=True, force=True)
    if frappe.db.exists("User", user_name):
        frappe.delete_doc("User", user_name, ignore_permissions=True, force=True)
    frappe.db.commit()
    frappe.destroy()
