"""Pure validation shared by upload, processing and tests. No Frappe dependency."""
import hashlib
import math
import re
from datetime import datetime, timezone

MAX_BYTES = 128 * 1024 * 1024
CHUNK_BYTES = 256 * 1024
MAX_SECONDS = 180


def instant(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp_requires_timezone")
    return result.astimezone(timezone.utc)


def validate_manifest(value, now=None):
    if not isinstance(value, dict):
        raise ValueError("invalid_manifest")
    for key in ("camera_id", "clip_id"):
        if not isinstance(value.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value[key]):
            raise ValueError("invalid_identifier")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("sha256", ""))):
        raise ValueError("invalid_checksum")
    size = value.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_BYTES:
        raise ValueError("invalid_size")
    start, end = instant(value.get("started_at")), instant(value.get("ended_at"))
    now = now or datetime.now(timezone.utc)
    if not 0 < (end - start).total_seconds() <= MAX_SECONDS:
        raise ValueError("invalid_duration")
    if (end - now).total_seconds() > 30 or (now - start).total_seconds() > 7 * 86400:
        raise ValueError("capture_time_out_of_window")
    if value.get("clock_verified") is not True:
        raise ValueError("collector_clock_not_verified")
    return {k: value[k] for k in ("camera_id", "clip_id", "sha256", "size")} | {
        "started_at": start.isoformat(), "ended_at": end.isoformat(), "clock_verified": True,
    }


def batch_id(manifest):
    return "TVB-" + hashlib.sha256((manifest["camera_id"] + ":" + manifest["clip_id"]).encode()).hexdigest()[:40]


def validate_score(value, low=0.0, high=1.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("invalid_score")
    return float(value)


def consensus(observations, min_frames=3, max_gap=2.5):
    """Keep consecutive same-identity observations; uncertainty breaks a run."""
    result, run = [], []
    def flush():
        if len(run) >= min_frames:
            result.append({"employee": run[0]["employee"], "offset": run[0]["offset"],
                           "score": min(x["score"] for x in run), "frames": len(run)})
    for row in observations:
        if not row.get("employee"):
            flush()
            run = []
            continue
        if run and (row["employee"] != run[-1]["employee"] or not 0 < row["offset"] - run[-1]["offset"] <= max_gap):
            flush()
            run = []
        run.append(row)
    flush()
    return result
