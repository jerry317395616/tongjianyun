"""Isolated OpenCV CPU inference. Outputs candidates, NOT verified identities/liveness.

YuNet (MIT) and SFace (Apache-2.0) model weights are deployed separately.
No raw images, face crops or features are returned for unregistered bystanders.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

# Executed as a script in an isolated venv; import pure sibling without Frappe.
from domain import consensus


def analyze(config):
    cv2.setNumThreads(2)
    models = Path(config["models_dir"])
    detector_path = models / "face_detection_yunet_2023mar.onnx"
    recognizer_path = models / "face_recognition_sface_2021dec.onnx"
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (detector_path, recognizer_path)]
    version = "yunet-sface:" + ":".join(h[:12] for h in hashes)
    detector = cv2.FaceDetectorYN.create(str(detector_path), "", (640, 480), 0.9, 0.3, 100)
    recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")

    def feature(frame):
        h, w = frame.shape[:2]
        if w * h > 10_000_000:
            raise ValueError("image_too_large")
        scale = min(1.0, 1280 / max(w, h))
        if scale < 1:
            frame = cv2.resize(frame, (round(w * scale), round(h * scale)))
        detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = detector.detect(frame)
        if faces is None or len(faces) != 1:
            return None
        face = faces[0]
        if min(face[2:4]) < 60:
            return None
        aligned = recognizer.alignCrop(frame, face)
        if cv2.Laplacian(cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() < 40:
            return None
        result = recognizer.feature(aligned).reshape(-1)
        norm = np.linalg.norm(result)
        return result / norm if norm > 0 else None

    path = Path(config["input"]).resolve(strict=True)
    if config["mode"] == "enroll":
        frame = cv2.imread(str(path))
        embedding = feature(frame) if frame is not None else None
        return {"feature": embedding.tolist() if embedding is not None else None, "model_version": version}
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    fps, frames = capture.get(cv2.CAP_PROP_FPS), capture.get(cv2.CAP_PROP_FRAME_COUNT)
    width, height = capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    if not capture.isOpened() or not all(math.isfinite(v) for v in (fps, frames, width, height)) or not 1 <= fps <= 120 or not 0 < frames / fps <= 185 or width * height > 10_000_000:
        capture.release()
        raise ValueError("invalid_video")
    duration = frames / fps
    gallery = [g for g in config.get("gallery", []) if g["model_version"] == version]
    if not gallery:
        raise ValueError("no_compatible_templates")
    threshold = float(config["threshold"])
    margin = float(config["margin"])
    if not 0 < threshold <= 1 or not 0 < margin < 1:
        raise ValueError("invalid_threshold")
    observations = []
    try:
        # Sequential decoding avoids expensive seeks and skips inference on most frames.
        step = max(1, round(fps / 2))
        for index in range(min(int(frames), 22200)):
            ok, frame = capture.read()
            if not ok:
                break
            if index % step:
                continue
            offset = index / fps
            row = {"offset": offset, "employee": None}
            embedding = feature(frame)
            if embedding is not None:
                scores = sorted(((float(np.dot(embedding, np.asarray(g["feature"], dtype=np.float32))), g["employee"]) for g in gallery), reverse=True)
                best, employee = scores[0]
                runner = scores[1][0] if len(scores) > 1 else -1
                if best >= threshold and best - runner >= margin:
                    row.update(employee=employee, score=best)
            observations.append(row)
    finally:
        capture.release()
    return {"duration": duration, "model_version": version, "candidates": consensus(observations, min_frames=4),
            "liveness_verified": False, "mode": "review-only"}


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.read(2 * 1024**2))
        print(json.dumps(analyze(request), allow_nan=False))
    except Exception:
        print('{"error":"analysis_failed"}', file=sys.stderr)
        sys.exit(1)
