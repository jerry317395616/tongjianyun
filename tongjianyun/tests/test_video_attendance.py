import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from tongjianyun.video_attendance.domain import validate_manifest, batch_id, consensus, validate_score, MAX_BYTES

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)


def manifest():
    return {"camera_id": "door-01", "clip_id": "clip-01", "sha256": "a" * 64, "size": 1024,
            "started_at": (NOW - timedelta(minutes=2)).isoformat(), "ended_at": (NOW - timedelta(minutes=1)).isoformat(),
            "clock_verified": True}


class ManifestTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_manifest(manifest(), NOW), manifest())

    def test_retry_id_stable(self):
        self.assertEqual(batch_id(manifest()), batch_id(manifest()))

    def test_camera_namespaced(self):
        self.assertNotEqual(batch_id(manifest()), batch_id(manifest() | {"camera_id": "door-02"}))

    def test_path_traversal(self):
        for key in ("camera_id", "clip_id"):
            with self.assertRaises(ValueError):
                validate_manifest(manifest() | {key: "../../etc"}, NOW)

    def test_requires_clock_check(self):
        for value in (False, "true", 1, None):
            with self.assertRaises(ValueError):
                validate_manifest(manifest() | {"clock_verified": value}, NOW)

    def test_naive_date(self):
        with self.assertRaises(ValueError):
            validate_manifest(manifest() | {"started_at": "2026-09-16T09:58:00"}, NOW)

    def test_future(self):
        with self.assertRaises(ValueError):
            validate_manifest(manifest() | {"ended_at": (NOW + timedelta(minutes=1)).isoformat()}, NOW)

    def test_retention_limit(self):
        with self.assertRaises(ValueError):
            validate_manifest(manifest(), NOW + timedelta(days=8))

    def test_size_limits(self):
        for size in (0, -1, MAX_BYTES + 1, True, "1024"):
            with self.assertRaises(ValueError):
                validate_manifest(manifest() | {"size": size}, NOW)

    def test_duration_limits(self):
        for end in (NOW - timedelta(minutes=2), NOW - timedelta(minutes=3), NOW + timedelta(minutes=2)):
            with self.assertRaises(ValueError):
                validate_manifest(manifest() | {"ended_at": end.isoformat()}, NOW)

    def test_checksum(self):
        with self.assertRaises(ValueError):
            validate_manifest(manifest() | {"sha256": "../a"}, NOW)

    def test_extraneous_fields_removed(self):
        self.assertNotIn("employee", validate_manifest(manifest() | {"employee": "fake"}, NOW))

    def test_bad_score(self):
        for value in (float("nan"), float("inf"), True, -0.1, 2):
            with self.assertRaises(ValueError):
                validate_score(value)


class ConsensusTests(unittest.TestCase):
    def rows(self):
        return [{"employee": "synthetic-id", "score": 0.7, "offset": i / 2} for i in range(4)]

    def test_consecutive(self):
        result = consensus(self.rows())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["offset"], 0)

    def test_unknown_breaks(self):
        rows = self.rows()
        rows[1]["employee"] = None
        self.assertEqual(consensus(rows), [])

    def test_gap_breaks(self):
        rows = self.rows()
        rows[1]["offset"] = 8
        self.assertEqual(consensus(rows), [])

    def test_identity_conflict(self):
        rows = self.rows()
        rows[1]["employee"] = "another-synthetic-id"
        self.assertEqual(consensus(rows), [])

    def test_single_frame_rejected(self):
        self.assertEqual(consensus(self.rows()[:1]), [])


class CollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2] / "deploy" / "video_attendance" / "collector.py"
        spec = importlib.util.spec_from_file_location("tjy_collector_test", path)
        cls.collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.collector)

    def test_never_guess_relative_timestamps(self):
        with self.assertRaises(ValueError):
            self.collector.manifest_for({}, Path("irrelevant"), 0, 60, True)

    def test_manifest_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "clip_1.mp4"
            path.write_bytes(b"synthetic-not-video")
            result = self.collector.manifest_for({"camera_id": "test"}, path, NOW.timestamp() - 60, NOW.timestamp(), True)
            self.assertEqual(result["size"], 19)
            self.assertEqual(result["started_at"], (NOW - timedelta(minutes=1)).isoformat())

    def test_schedule(self):
        c = {"weekdays": [0], "recording_windows": [["07:00", "18:00"]]}
        self.assertTrue(self.collector.in_schedule(c, datetime(2026, 9, 14, 8, 0)))
        self.assertFalse(self.collector.in_schedule(c, datetime(2026, 9, 14, 20, 0)))
        self.assertFalse(self.collector.in_schedule(c, datetime(2026, 9, 15, 8, 0)))

    def test_first_segment_uses_packet_clock(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "first.mp4"
            path.write_bytes(b"synthetic")
            probe = SimpleNamespace(returncode=0, stdout=json.dumps({"streams": [{"start_time": str(NOW.timestamp()-60)}]}))
            with patch.object(self.collector.subprocess, "run", return_value=probe):
                result = self.collector.manifest_for({"camera_id": "test", "ffmpeg": "/bin/ffmpeg"}, path, 0, NOW.timestamp(), True)
            self.assertEqual(result["started_at"], (NOW - timedelta(seconds=60)).isoformat())

    def test_queue_migration_and_retry_fairness(self):
        with tempfile.TemporaryDirectory() as folder:
            db = self.collector.connect(folder)
            db.execute("INSERT INTO clips(id,path,manifest,created,last_attempt) VALUES('failed','a','{}',1,100)")
            db.execute("INSERT INTO clips(id,path,manifest,created,last_attempt) VALUES('fresh','b','{}',2,0)")
            row = db.execute("SELECT id FROM clips WHERE acknowledged=0 ORDER BY last_attempt,created LIMIT 1").fetchone()
            self.assertEqual(row[0], "fresh")
            db.close()

    def test_audio_disabled_and_no_shell(self):
        command = self.collector.recorder_command({"ffmpeg": "ffmpeg", "rtsp_url": "rtsp://127.0.0.1/video", "segment_seconds": 60}, Path("session.json"))
        self.assertIn("-an", command)
        self.assertIn("-copyts", command)

    def test_receipt_checksum_required(self):
        from unittest.mock import patch
        with patch.object(self.collector, "call", return_value={"sealed": True, "sha256": "wrong"}):
            with self.assertRaises(RuntimeError):
                self.collector.upload({}, Path("not-opened"), manifest())

    def test_resume_upload(self):
        from unittest.mock import patch
        calls = []
        def fake(config, method, payload):
            calls.append((method, payload))
            return {"begin_upload": {"sealed": False, "batch": "test", "offset": 2},
                    "upload_chunk": {"offset": 5}, "seal_upload": {"sealed": True, "sha256": "a" * 64}}[method]
        with tempfile.TemporaryDirectory() as folder, patch.object(self.collector, "call", side_effect=fake):
            path = Path(folder) / "clip.mp4"
            path.write_bytes(b"12345")
            self.collector.upload({}, path, manifest() | {"size": 5})
        self.assertEqual(calls[1][1]["offset"], 2)


if __name__ == "__main__":
    unittest.main()
